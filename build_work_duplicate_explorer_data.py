#!/usr/bin/env python3
"""Build sample JSON files for the work-dedup explorer tab.

Designed to run on Sherlock where the 125 ``year_*/papers_with_titles.parquet``
files (~22 GB total) and the global crosswalk live. Outputs three small
JSON files (typically <30 MB combined) suitable for static-site hosting:

- ``work_duplicates_stats.json``      : headline tier and size histograms
- ``work_duplicates.json``            : ~1500 clusters stratified by best-tier
                                        and cluster-size, with full member
                                        metadata (paperid, title, doi,
                                        doctype, year, cited_by_count,
                                        is_canonical) and per-pair tier edges
- ``work_duplicates_tier_examples.json``: ~4 example clusters per tier for
                                          the overview page

Heavy lifting is DuckDB throughout; pandas is not imported.

Algorithm:
  1. Load the global crosswalk and canonical-papers tables.
  2. For each year's ``candidate_pairs_features.parquet``, join (left, right)
     to the global crosswalk to get a ``(cluster_id, merge_signal)`` row.
  3. Per cluster: pick the lowest-priority tier across its pairs.
  4. Compute stats (cluster_size_hist, by_tier_pairs, by_tier_clusters).
  5. Stratify-sample clusters by (best_tier, size_bucket).
  6. For sampled clusters, look up member titles by unioning all 125
     ``papers_with_titles.parquet`` and filtering to the member paperid set.
  7. Emit JSONs.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

import duckdb


# Tier priority -- lower number is stronger evidence; cluster's "best_tier"
# is the lowest-priority tier among its accepted pairs. Mirrors the rule
# ordering inside ``07_tier_rules.py``.
#
# We collapse step 07's T4a / T4b split (based on per-pair block_size) into
# a single ``T4_same_title`` class -- the explorer doesn't reapply step 07's
# block_size cutoff or frontmatter blocklist, so cluster-level "best tier"
# is computed on the candidate-side normalised signal name. The overview
# page documents the T4a vs T4b distinction at the rule level.
TIER_PRIORITY = {
    "T0_same_doi": 0,
    "T1_same_pmid": 1,
    "T2_same_pmcid": 2,
    "T3_same_mag": 3,
    "T7_cross_year_same_doi": 4,
    "T6_doi_suffix_variant": 5,
    "T4_same_title": 6,
    "T5_shared_author_fuzzy_title": 7,
    "T9_cross_year_shared_author": 8,
}


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-cleaning",
        type=Path,
        default=Path("/scratch/users/alamos/bitnet/data/intermediate/work_cleaning"),
        help="Directory containing global/ and year_*/ outputs.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Where to write the JSON files (default: alongside this script).",
    )
    p.add_argument("--max-clusters", type=int, default=1500,
                   help="Total clusters to sample for the explorer.")
    p.add_argument("--examples-per-tier", type=int, default=4)
    p.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", 8)))
    p.add_argument("--memory", default=os.environ.get("MEMORY", "64GB"))
    p.add_argument(
        "--temp-dir",
        type=Path,
        default=Path(os.environ.get("TMP", "/tmp/duckdb_work_dup_explorer")),
    )
    return p.parse_args()


def discover_year_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for d in sorted(root.glob("year_*")):
        if not d.is_dir():
            continue
        try:
            int(d.name.removeprefix("year_"))
        except ValueError:
            continue
        out.append(d)
    return out


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.temp_dir.mkdir(parents=True, exist_ok=True)

    crosswalk_path = args.out_cleaning / "global" / "crosswalk.parquet"
    canonical_path = args.out_cleaning / "global" / "canonical_papers.parquet"
    if not crosswalk_path.exists():
        raise FileNotFoundError(crosswalk_path)
    if not canonical_path.exists():
        raise FileNotFoundError(canonical_path)

    year_dirs = discover_year_dirs(args.out_cleaning)
    if not year_dirs:
        raise SystemExit(f"No year_*/ subdirectories under {args.out_cleaning}")
    print(f"[work-dup-explorer] {len(year_dirs)} year-slices "
          f"({year_dirs[0].name} ... {year_dirs[-1].name})", flush=True)

    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute(f"SET temp_directory='{args.temp_dir}'")
    con.execute("SET preserve_insertion_order=false")

    # tier priority lookup
    con.execute("CREATE TEMP TABLE tier_pri(tier VARCHAR, pri INTEGER)")
    con.executemany(
        "INSERT INTO tier_pri VALUES (?, ?)",
        list(TIER_PRIORITY.items()),
    )

    print("[1/8] load global crosswalk", flush=True)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE crosswalk AS
        SELECT paperid, canonical_paperid, cluster_id, cluster_size, is_canonical
        FROM read_parquet('{_pq(crosswalk_path)}')
    """)
    n_pids_in_clusters = con.execute("SELECT COUNT(*) FROM crosswalk").fetchone()[0]
    n_clusters_total = con.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM crosswalk"
    ).fetchone()[0]
    print(f"  {n_pids_in_clusters:,} paperids in clusters; "
          f"{n_clusters_total:,} clusters", flush=True)

    print("[2/8] load canonical metadata", flush=True)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE canonical AS
        SELECT * FROM read_parquet('{_pq(canonical_path)}')
    """)

    print("[3/8] stream per-year tier-signal sources -> pair_clusters",
          flush=True)
    # Memory-friendly: stream per-year files one at a time, project to
    # (cluster_id, signal_clean, left_paperid, right_paperid), and APPEND
    # into a single growing temp table. Avoids the 30 GB temp-spill blowup
    # of a 125-way UNION ALL on 1 cpu / 3 GB.
    #
    # We aggregate four sources per year:
    #   - candidate_pairs_features.parquet   (T0 / T1 / T2 / T3 / T4)
    #   - extra_candidate_pairs.parquet      (T5 / T6, from step 04)
    #   - t7_candidate_pairs.parquet         (T7, from step 05)
    #   - t9_cross_year_shared_author_pairs.parquet (T9, from step 06)
    #
    # Step 02 emits signal names with a 'W-' prefix to mark "work tier";
    # step 07 strips the prefix and may split T4 -> T4a/T4b based on
    # per-pair block_size + frontmatter check. The explorer does NOT
    # re-apply step 07's block_size or frontmatter rules: cluster-level
    # "best tier" is computed on the candidate-side normalised signal.
    # In the small fraction of cases where a candidate pair was rejected
    # by step 07 but its endpoints were transitively merged via another
    # accepted pair, the explorer's tier label is therefore an upper
    # bound on the strongest acceptance signal.
    SIGNAL_CASE = """
        CASE
            WHEN merge_signal = 'W-T0_same_doi'             THEN 'T0_same_doi'
            WHEN merge_signal = 'W-T1_same_pmid'            THEN 'T1_same_pmid'
            WHEN merge_signal = 'W-T2_same_pmcid'           THEN 'T2_same_pmcid'
            WHEN merge_signal = 'W-T3_same_mag'             THEN 'T3_same_mag'
            WHEN merge_signal = 'W-T4_same_title'           THEN 'T4_same_title'
            WHEN merge_signal = 'W-T5_shared_author_fuzzy_title'
                                                            THEN 'T5_shared_author_fuzzy_title'
            WHEN merge_signal = 'W-T6_doi_suffix_variant'   THEN 'T6_doi_suffix_variant'
            WHEN merge_signal = 'W-T7_cross_year_same_doi'  THEN 'T7_cross_year_same_doi'
            WHEN merge_signal = 'W-T9_cross_year_shared_author'
                                                            THEN 'T9_cross_year_shared_author'
            ELSE merge_signal
        END
    """

    con.execute("""
        CREATE OR REPLACE TEMP TABLE pair_clusters (
            cluster_id    VARCHAR,
            merge_signal  VARCHAR,
            left_paperid  VARCHAR,
            right_paperid VARCHAR
        )
    """)
    n_pair_rows = 0
    SOURCE_FILES = [
        "candidate_pairs_features.parquet",
        "extra_candidate_pairs.parquet",
        "t7_candidate_pairs.parquet",
        "t9_cross_year_shared_author_pairs.parquet",
    ]
    src_count = {s: 0 for s in SOURCE_FILES}
    print(f"  streaming {len(year_dirs)} years x {len(SOURCE_FILES)} sources",
          flush=True)
    for i, d in enumerate(year_dirs):
        for src in SOURCE_FILES:
            f = d / src
            if not f.exists():
                continue
            try:
                con.execute(f"""
                    INSERT INTO pair_clusters
                    SELECT
                        cw_l.cluster_id,
                        {SIGNAL_CASE} AS merge_signal,
                        f.left_paperid,
                        f.right_paperid
                    FROM read_parquet('{_pq(f)}') f
                    JOIN crosswalk cw_l ON cw_l.paperid = f.left_paperid
                    JOIN crosswalk cw_r ON cw_r.paperid = f.right_paperid
                    WHERE cw_l.cluster_id = cw_r.cluster_id
                """)
                src_count[src] += 1
            except Exception as e:
                print(f"    [{d.name}/{src}] failed: {e}", flush=True)
        n_year = con.execute(
            "SELECT COUNT(*) FROM pair_clusters"
        ).fetchone()[0]
        added = n_year - n_pair_rows
        n_pair_rows = n_year
        if (i + 1) % 25 == 0 or i == len(year_dirs) - 1:
            print(f"    [{i+1:3d}/{len(year_dirs)}] {d.name}: +{added:,} rows "
                  f"(running total: {n_pair_rows:,})", flush=True)
    print(f"  {n_pair_rows:,} total (cluster, pair, tier) rows", flush=True)
    for s, c in src_count.items():
        print(f"    {s}: {c} years", flush=True)

    print("[4/8] cluster best-tier (lowest priority across all pairs)",
          flush=True)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE cluster_best_tier AS
        SELECT pc.cluster_id,
               min_by(pc.merge_signal, tp.pri) AS best_tier
        FROM pair_clusters pc
        JOIN tier_pri tp ON tp.tier = pc.merge_signal
        GROUP BY pc.cluster_id
    """)
    n_with_tier = con.execute(
        "SELECT COUNT(*) FROM cluster_best_tier"
    ).fetchone()[0]
    print(f"  {n_with_tier:,} clusters have at least one tier-tagged pair",
          flush=True)

    by_tier_pairs = dict(con.execute("""
        SELECT merge_signal, COUNT(*) FROM pair_clusters
        GROUP BY merge_signal ORDER BY COUNT(*) DESC
    """).fetchall())
    by_tier_clusters = dict(con.execute("""
        SELECT best_tier, COUNT(*) FROM cluster_best_tier
        GROUP BY best_tier ORDER BY COUNT(*) DESC
    """).fetchall())
    cluster_size_hist = dict(con.execute("""
        SELECT cluster_size, COUNT(DISTINCT cluster_id)
        FROM crosswalk GROUP BY cluster_size ORDER BY cluster_size
    """).fetchall())
    canonical_year_hist = dict(con.execute("""
        SELECT
            CASE
                WHEN canonical_year < 1950 THEN 'pre-1950'
                WHEN canonical_year < 1980 THEN '1950-1979'
                WHEN canonical_year < 2000 THEN '1980-1999'
                WHEN canonical_year < 2010 THEN '2000-2009'
                WHEN canonical_year IS NULL THEN 'unknown'
                ELSE '2010-'
            END AS bucket,
            COUNT(*)
        FROM canonical
        GROUP BY bucket ORDER BY bucket
    """).fetchall())

    headline = {
        "n_pairs": int(n_pair_rows),
        "n_clusters": int(n_clusters_total),
        "n_member_ids": int(n_pids_in_clusters),
        "excess_ids_collapsed": int(n_pids_in_clusters - n_clusters_total),
        "by_tier_pairs": {k: int(v) for k, v in by_tier_pairs.items()},
        "by_tier_clusters": {k: int(v) for k, v in by_tier_clusters.items()},
        "cluster_size_hist": {int(k): int(v) for k, v in cluster_size_hist.items()},
        "canonical_year_hist": {k: int(v) for k, v in canonical_year_hist.items()},
    }
    (args.out_dir / "work_duplicates_stats.json").write_text(
        json.dumps(headline, indent=2))
    print(f"  wrote {args.out_dir / 'work_duplicates_stats.json'}", flush=True)

    print("[5/8] stratified sample of clusters + per-tier examples", flush=True)
    n_tiers = max(1, len(by_tier_clusters))
    per_tier = max(1, args.max_clusters // n_tiers)
    # Stratified sample: per_tier random clusters per best_tier.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sampled_clusters AS
        WITH ranked AS (
            SELECT
                cw.cluster_id,
                MAX(cw.cluster_size) AS cluster_size,
                cbt.best_tier,
                row_number() OVER (
                    PARTITION BY cbt.best_tier
                    ORDER BY hash(cw.cluster_id || cbt.best_tier)
                ) AS rn
            FROM crosswalk cw
            JOIN cluster_best_tier cbt USING(cluster_id)
            GROUP BY cw.cluster_id, cbt.best_tier
        )
        SELECT cluster_id, cluster_size, best_tier
        FROM ranked WHERE rn <= {int(per_tier)}
    """)
    n_sampled = con.execute(
        "SELECT COUNT(*) FROM sampled_clusters").fetchone()[0]

    # Tier-example clusters (largest few per tier; for the overview page).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE example_clusters AS
        WITH ranked AS (
            SELECT
                cw.cluster_id,
                MAX(cw.cluster_size) AS cluster_size,
                cbt.best_tier,
                row_number() OVER (
                    PARTITION BY cbt.best_tier
                    ORDER BY MAX(cw.cluster_size) DESC,
                             hash(cw.cluster_id || cbt.best_tier)
                ) AS rn
            FROM crosswalk cw
            JOIN cluster_best_tier cbt USING(cluster_id)
            GROUP BY cw.cluster_id, cbt.best_tier
        )
        SELECT cluster_id, cluster_size, best_tier
        FROM ranked WHERE rn <= {int(args.examples_per_tier)}
    """)
    n_ex = con.execute(
        "SELECT COUNT(*) FROM example_clusters").fetchone()[0]
    print(f"  {n_sampled:,} sampled (<= {per_tier}/tier) + "
          f"{n_ex:,} examples (<= {args.examples_per_tier}/tier)", flush=True)

    print("[6/8] union per-year title metadata for sample + example members",
          flush=True)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE all_membership AS
        SELECT cluster_id FROM sampled_clusters
        UNION
        SELECT cluster_id FROM example_clusters
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE all_members AS
        SELECT cw.cluster_id, cw.cluster_size, cbt.best_tier,
               cw.paperid, cw.canonical_paperid, cw.is_canonical
        FROM crosswalk cw
        JOIN all_membership am ON am.cluster_id = cw.cluster_id
        JOIN cluster_best_tier cbt ON cbt.cluster_id = cw.cluster_id
    """)
    n_am = con.execute("SELECT COUNT(*) FROM all_members").fetchone()[0]
    print(f"  {n_am:,} member rows to enrich", flush=True)

    # Stream per-year title files: open one at a time, filter by paperid IN
    # all_members (~5-10k paperids), append to titles_lookup. Same memory
    # discipline as step 3.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE titles_lookup (
            paperid VARCHAR, title VARCHAR, doi VARCHAR, doi_norm VARCHAR,
            doctype VARCHAR, cited_by_count BIGINT, year INTEGER
        )
    """)
    title_files = []
    for d in year_dirs:
        f = d / "papers_with_titles.parquet"
        if f.exists():
            title_files.append((d.name, f))
    print(f"  streaming {len(title_files)} per-year title files for lookup",
          flush=True)
    n_t = 0
    for i, (name, f) in enumerate(title_files):
        con.execute(f"""
            INSERT INTO titles_lookup
            SELECT paperid, title, doi, doi_norm, doctype,
                   cited_by_count, year
            FROM read_parquet('{_pq(f)}')
            WHERE paperid IN (SELECT paperid FROM all_members)
        """)
        n_t_new = con.execute(
            "SELECT COUNT(*) FROM titles_lookup"
        ).fetchone()[0]
        if (i + 1) % 25 == 0 or i == len(title_files) - 1:
            print(f"    [{i+1:3d}/{len(title_files)}] {name}: "
                  f"running total {n_t_new:,}", flush=True)
        n_t = n_t_new
    print(f"  {n_t:,} title rows fetched", flush=True)

    print("[7/8] assemble cluster records (sampled set)", flush=True)
    members_full = con.execute("""
        SELECT
            am.cluster_id, am.cluster_size, am.best_tier,
            am.paperid, am.canonical_paperid, am.is_canonical,
            t.title, t.doi, t.doi_norm, t.doctype, t.cited_by_count, t.year
        FROM all_members am
        JOIN sampled_clusters sc ON sc.cluster_id = am.cluster_id
        LEFT JOIN titles_lookup t USING(paperid)
        ORDER BY am.cluster_id,
                 am.is_canonical DESC,
                 coalesce(t.cited_by_count, 0) DESC,
                 am.paperid
    """).fetchall()

    edges = con.execute("""
        SELECT pc.cluster_id, pc.left_paperid, pc.right_paperid,
               pc.merge_signal
        FROM pair_clusters pc
        JOIN sampled_clusters sc ON sc.cluster_id = pc.cluster_id
    """).fetchall()

    cluster_records: dict[str, dict] = {}
    for cid, sz, bt, pid, cpid, is_can, title, doi, doi_norm, doctype, cites, yr in members_full:
        c = cluster_records.setdefault(cid, {
            "cluster_id": cid,
            "size": int(sz) if sz is not None else 0,
            "best_tier": bt,
            "members": [],
            "edges": [],
        })
        c["members"].append({
            "paperid": pid,
            "canonical_paperid": cpid,
            "is_canonical": bool(is_can),
            "title": title,
            "doi": doi,
            "doctype": doctype,
            "cited_by_count": int(cites) if cites is not None else None,
            "year": int(yr) if yr is not None else None,
        })
    for cid, l, r, t in edges:
        c = cluster_records.get(cid)
        if c is None:
            continue
        c["edges"].append({"left": l, "right": r, "tier": t})

    out = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "tier_priority": TIER_PRIORITY,
        "headline": headline,
        "clusters": list(cluster_records.values()),
    }
    (args.out_dir / "work_duplicates.json").write_text(json.dumps(out, indent=1))
    print(f"  wrote {args.out_dir / 'work_duplicates.json'} "
          f"({len(cluster_records):,} clusters)", flush=True)

    print("[8/8] tier-example clusters for the overview page", flush=True)
    ex_rows = con.execute("""
        SELECT
            am.cluster_id, am.cluster_size, am.best_tier,
            am.paperid, am.is_canonical,
            t.title, t.doi, t.doctype, t.cited_by_count, t.year
        FROM all_members am
        JOIN example_clusters ec ON ec.cluster_id = am.cluster_id
        LEFT JOIN titles_lookup t USING(paperid)
        ORDER BY am.best_tier, am.cluster_id,
                 am.is_canonical DESC,
                 coalesce(t.cited_by_count, 0) DESC,
                 am.paperid
    """).fetchall()
    tier_examples: dict[str, list] = defaultdict(list)
    cluster_acc: dict[tuple[str, str], dict] = {}
    for cid, sz, bt, pid, is_can, title, doi, doctype, cites, yr in ex_rows:
        key = (bt, cid)
        c = cluster_acc.get(key)
        if c is None:
            c = {
                "cluster_id": cid,
                "size": int(sz) if sz is not None else 0,
                "members": [],
            }
            cluster_acc[key] = c
            tier_examples[bt].append(c)
        if len(c["members"]) >= 6:
            continue
        c["members"].append({
            "paperid": pid,
            "is_canonical": bool(is_can),
            "title": title,
            "doi": doi,
            "doctype": doctype,
            "cited_by_count": int(cites) if cites is not None else None,
            "year": int(yr) if yr is not None else None,
        })

    (args.out_dir / "work_duplicates_tier_examples.json").write_text(
        json.dumps(dict(tier_examples), indent=2))
    print(f"  wrote {args.out_dir / 'work_duplicates_tier_examples.json'}",
          flush=True)


if __name__ == "__main__":
    main()
