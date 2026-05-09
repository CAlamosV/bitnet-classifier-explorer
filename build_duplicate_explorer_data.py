#!/usr/bin/env python3
"""Build duplicates.json for the static dedup explorer.

Heavy lifting in DuckDB:
  1. Read accepted_pairs as one table.
  2. Union-find via DuckDB label-propagation (tens of millions of edges fast).
  3. Cluster-level aggregates (size, best-tier).
  4. Stratified sample of clusters by best_tier.
  5. Profile lookup ONLY for sampled-cluster members (small).
  6. Emit JSON.

Outputs:
- duplicates.json            — sampled clusters + members + edges (browseable)
- duplicates_stats.json      — headline tier and size histograms
- duplicates_tier_examples.json — small per-tier example clusters for the
                                  overview page.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

import duckdb


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    repo = Path(__file__).resolve().parent.parent.parent
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--accepted",
        type=Path,
        default=repo / "data/intermediate/author_cleaning/duplicate_global/accepted_pairs.parquet",
    )
    p.add_argument(
        "--features",
        type=Path,
        default=repo / "data/intermediate/author_cleaning/duplicate_global/candidate_pairs_features.parquet",
    )
    p.add_argument(
        "--oa-years",
        type=Path,
        default=repo / "data/intermediate/author_cleaning/duplicate_global/author_oa_years.parquet",
    )
    p.add_argument("--max-clusters", type=int, default=1500)
    p.add_argument("--examples-per-tier", type=int, default=4)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=repo / "tools" / "classifier_explorer",
    )
    p.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", 6)))
    p.add_argument("--memory", default=os.environ.get("MEMORY", "16GB"))
    p.add_argument(
        "--temp-dir",
        type=Path,
        default=Path(os.environ.get("TMP", "/tmp/duckdb_dup_explorer")),
    )
    return p.parse_args()


# Lower number = stronger evidence; cluster's "best_tier" is min priority.
TIER_PRIORITY = {
    "T0_same_orcid": 0,
    "T1_shared_paper": 1,
    "T2_shared_coauthor": 2,
    "T2b_two_shared_coauthors_common_surname_ok": 3,
    "T3_two_shared_institutions": 4,
    "T3_shared_institution_small_bucket": 5,
    "T4_non_latin_small_bucket": 6,
    "T5_singleton_pair_rare_name": 7,
    "T7a_three_token_small_bucket": 8,
    "T7b_two_token_tiny_bucket": 9,
    "T6_tiny_stub_absorption": 10,
}


def install_tier_priority(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE tier_pri(tier VARCHAR, pri INTEGER)")
    con.executemany("INSERT INTO tier_pri VALUES (?, ?)",
                    list(TIER_PRIORITY.items()))


def build_clusters(con: duckdb.DuckDBPyConnection) -> None:
    """Connected components via DuckDB label propagation."""
    con.execute("""
        CREATE OR REPLACE TEMP TABLE undirected AS
        SELECT left_authorid AS a, right_authorid AS b FROM accepted
        UNION ALL
        SELECT right_authorid AS a, left_authorid AS b FROM accepted
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE node_label AS
        SELECT a AS authorid, a AS label
        FROM (SELECT DISTINCT a FROM undirected)
    """)
    for it in range(1, 50):
        con.execute("""
            CREATE OR REPLACE TEMP TABLE node_label_next AS
            SELECT authorid, MIN(cand) AS label
            FROM (
                SELECT authorid, label AS cand FROM node_label
                UNION ALL
                SELECT u.a AS authorid, nl.label AS cand
                FROM undirected u
                JOIN node_label nl ON nl.authorid = u.b
            )
            GROUP BY authorid
        """)
        changed = con.execute("""
            SELECT COUNT(*) FROM node_label nl JOIN node_label_next nn USING(authorid)
            WHERE nl.label <> nn.label
        """).fetchone()[0]
        con.execute("DROP TABLE node_label")
        con.execute("ALTER TABLE node_label_next RENAME TO node_label")
        print(f"  iter {it}: {changed:,} updated", flush=True)
        if changed == 0:
            break


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.temp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}; SET memory_limit='{args.memory}'")
    con.execute(f"SET temp_directory='{args.temp_dir}'")
    con.execute("SET preserve_insertion_order=false")

    install_tier_priority(con)

    print("[1/6] read accepted pairs", flush=True)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE accepted AS
        SELECT
            left_authorid, right_authorid, merge_tier,
            shared_papers, shared_coauthors, shared_institutions,
            bucket_size, name_token_count
        FROM read_parquet('{_pq(args.accepted)}')
    """)
    n_pairs = con.execute("SELECT COUNT(*) FROM accepted").fetchone()[0]
    print(f"  {n_pairs:,} pairs", flush=True)

    print("[2/6] compute clusters (DuckDB label-prop)", flush=True)
    build_clusters(con)

    print("[3/6] cluster-level aggregates", flush=True)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE pair_with_cluster AS
        SELECT a.*, nl.label AS cluster_id
        FROM accepted a JOIN node_label nl ON nl.authorid = a.left_authorid
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE cluster_size AS
        SELECT label AS cluster_id, COUNT(*) AS size
        FROM node_label GROUP BY label
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE cluster_best_tier AS
        SELECT pwc.cluster_id, min_by(pwc.merge_tier, tp.pri) AS best_tier
        FROM pair_with_cluster pwc
        JOIN tier_pri tp ON tp.tier = pwc.merge_tier
        GROUP BY pwc.cluster_id
    """)
    n_clusters = con.execute("SELECT COUNT(*) FROM cluster_size").fetchone()[0]
    n_member_ids = con.execute("SELECT COUNT(*) FROM node_label").fetchone()[0]
    print(f"  {n_clusters:,} clusters / {n_member_ids:,} member IDs", flush=True)

    by_tier_pairs = dict(con.execute("""
        SELECT merge_tier, COUNT(*) FROM accepted GROUP BY 1 ORDER BY 2 DESC
    """).fetchall())
    by_tier_clusters = dict(con.execute("""
        SELECT best_tier, COUNT(*) FROM cluster_best_tier GROUP BY 1 ORDER BY 2 DESC
    """).fetchall())
    cluster_size_hist = dict(con.execute("""
        SELECT size, COUNT(*) FROM cluster_size GROUP BY 1 ORDER BY 1
    """).fetchall())

    headline = {
        "n_pairs": n_pairs,
        "n_clusters": n_clusters,
        "n_member_ids": n_member_ids,
        "excess_ids_collapsed": n_member_ids - n_clusters,
        "by_tier_pairs": {k: int(v) for k, v in by_tier_pairs.items()},
        "by_tier_clusters": {k: int(v) for k, v in by_tier_clusters.items()},
        "cluster_size_hist": {int(k): int(v) for k, v in cluster_size_hist.items()},
    }

    print("[4/6] stratified-by-tier sample of clusters", flush=True)
    n_tiers = max(1, len(by_tier_clusters))
    per_tier = max(1, args.max_clusters // n_tiers)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sampled_clusters AS
        WITH ranked AS (
            SELECT cs.cluster_id, cs.size, cbt.best_tier,
                   row_number() OVER (PARTITION BY cbt.best_tier
                                      ORDER BY hash(cs.cluster_id)) AS rn
            FROM cluster_size cs
            JOIN cluster_best_tier cbt USING(cluster_id)
        )
        SELECT cluster_id, size, best_tier
        FROM ranked WHERE rn <= {per_tier}
    """)
    n_sampled = con.execute("SELECT COUNT(*) FROM sampled_clusters").fetchone()[0]
    print(f"  {n_sampled:,} sampled clusters", flush=True)

    print("[5/6] member profiles for sampled clusters", flush=True)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE sample_members AS
        SELECT sc.cluster_id, sc.size, sc.best_tier, nl.authorid
        FROM sampled_clusters sc
        JOIN node_label nl ON nl.label = sc.cluster_id
    """)
    n_members = con.execute("SELECT COUNT(*) FROM sample_members").fetchone()[0]
    print(f"  {n_members:,} members in sampled clusters", flush=True)

    # Profile lookup: pull display_name / works_count / years / institution
    # for these AuthorIDs from the features parquet (each AuthorID appears as
    # left or right in some pair).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE prof_left AS
        SELECT DISTINCT
            cf.left_authorid AS authorid,
            cf.left_name AS display_name,
            cf.left_works_count AS works_count,
            cf.left_year_first AS imp_year_first,
            cf.left_year_last AS imp_year_last,
            cf.left_last_known_institution AS last_known_institution
        FROM read_parquet('{_pq(args.features)}') cf
        SEMI JOIN sample_members sm ON sm.authorid = cf.left_authorid
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE prof_right AS
        SELECT DISTINCT
            cf.right_authorid AS authorid,
            cf.right_name AS display_name,
            cf.right_works_count AS works_count,
            cf.right_year_first AS imp_year_first,
            cf.right_year_last AS imp_year_last,
            cf.right_last_known_institution AS last_known_institution
        FROM read_parquet('{_pq(args.features)}') cf
        SEMI JOIN sample_members sm ON sm.authorid = cf.right_authorid
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE profiles AS
        SELECT * FROM prof_left
        UNION
        SELECT * FROM prof_right
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE profiles_uniq AS
        SELECT authorid,
               first(display_name) AS display_name,
               max(works_count) AS works_count,
               min(imp_year_first) AS imp_year_first,
               max(imp_year_last) AS imp_year_last,
               first(last_known_institution) AS last_known_institution
        FROM profiles
        WHERE display_name IS NOT NULL
        GROUP BY authorid
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE oa_years AS
        SELECT authorid, oa_year_first, oa_year_last
        FROM read_parquet('{_pq(args.oa_years)}')
        SEMI JOIN sample_members sm ON sm.authorid = oa_years.authorid
    """ if False else f"""
        CREATE OR REPLACE TEMP TABLE oa_years AS
        SELECT oay.authorid, oay.oa_year_first, oay.oa_year_last
        FROM read_parquet('{_pq(args.oa_years)}') oay
        SEMI JOIN sample_members sm ON sm.authorid = oay.authorid
    """)

    members_full = con.execute("""
        SELECT
            sm.cluster_id, sm.size, sm.best_tier, sm.authorid,
            p.display_name, p.works_count, p.imp_year_first, p.imp_year_last,
            p.last_known_institution,
            o.oa_year_first, o.oa_year_last
        FROM sample_members sm
        LEFT JOIN profiles_uniq p USING(authorid)
        LEFT JOIN oa_years o USING(authorid)
        ORDER BY sm.cluster_id, coalesce(p.works_count, 0) DESC, sm.authorid
    """).fetchall()

    edges = con.execute("""
        SELECT pwc.cluster_id, pwc.left_authorid, pwc.right_authorid,
               pwc.merge_tier, pwc.shared_papers, pwc.shared_coauthors,
               pwc.shared_institutions, pwc.bucket_size, pwc.name_token_count
        FROM pair_with_cluster pwc
        SEMI JOIN sampled_clusters sc ON sc.cluster_id = pwc.cluster_id
    """).fetchall()

    print("[6/6] write JSON", flush=True)
    cluster_records: dict[str, dict] = {}
    for cid, sz, bt, aid, name, w, iyf, iyl, inst, oyf, oyl in members_full:
        c = cluster_records.setdefault(cid, {
            "cluster_id": cid, "size": int(sz), "best_tier": bt,
            "members": [], "edges": [],
        })
        c["members"].append({
            "authorid": aid, "display_name": name,
            "works_count": int(w) if w is not None else None,
            "imp_year_first": int(iyf) if iyf is not None else None,
            "imp_year_last":  int(iyl) if iyl is not None else None,
            "last_known_institution": inst,
            "oa_year_first": int(oyf) if oyf is not None else None,
            "oa_year_last":  int(oyl) if oyl is not None else None,
        })
    for cid, l, r, t, sp, sc, si, bs, ntok in edges:
        c = cluster_records.get(cid)
        if c is None:
            continue
        c["edges"].append({
            "left": l, "right": r, "tier": t,
            "shared_papers": int(sp) if sp is not None else 0,
            "shared_coauthors": int(sc) if sc is not None else 0,
            "shared_institutions": int(si) if si is not None else 0,
            "bucket_size": int(bs) if bs is not None else None,
            "name_token_count": int(ntok) if ntok is not None else None,
        })

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "headline": headline,
        "tier_priority": TIER_PRIORITY,
        "clusters": list(cluster_records.values()),
    }
    (args.out_dir / "duplicates.json").write_text(json.dumps(out, indent=1))
    (args.out_dir / "duplicates_stats.json").write_text(json.dumps(headline, indent=2))

    # Tier examples: 4 clusters per tier with ≤5 members each
    tier_examples: dict[str, list] = {}
    for tier in by_tier_clusters:
        ex_rows = con.execute(f"""
            WITH t AS (
                SELECT cs.cluster_id, cs.size,
                       row_number() OVER (ORDER BY cs.size DESC, hash(cs.cluster_id)) AS rn
                FROM cluster_size cs JOIN cluster_best_tier cbt USING(cluster_id)
                WHERE cbt.best_tier = '{tier}'
            )
            SELECT cluster_id, size FROM t WHERE rn <= {args.examples_per_tier}
        """).fetchall()
        ex_clusters = []
        for cid, sz in ex_rows:
            mems = con.execute(f"""
                SELECT nl.authorid, p.display_name, p.works_count,
                       o.oa_year_first, o.oa_year_last,
                       p.last_known_institution
                FROM node_label nl
                LEFT JOIN profiles_uniq p ON p.authorid = nl.authorid
                LEFT JOIN oa_years o ON o.authorid = nl.authorid
                WHERE nl.label = '{cid}'
                ORDER BY coalesce(p.works_count, 0) DESC LIMIT 5
            """).fetchall()
            ex_clusters.append({
                "cluster_id": cid, "size": int(sz),
                "members": [
                    {
                        "authorid": a, "display_name": n,
                        "works_count": int(w) if w is not None else None,
                        "oa_year_first": int(yf) if yf is not None else None,
                        "oa_year_last":  int(yl) if yl is not None else None,
                        "last_known_institution": inst,
                    }
                    for a, n, w, yf, yl, inst in mems
                ],
            })
        tier_examples[tier] = ex_clusters
    (args.out_dir / "duplicates_tier_examples.json").write_text(
        json.dumps(tier_examples, indent=2))

    print(f"  wrote {args.out_dir / 'duplicates.json'} "
          f"({len(cluster_records):,} clusters)", flush=True)
    print(f"  wrote {args.out_dir / 'duplicates_stats.json'}", flush=True)
    print(f"  wrote {args.out_dir / 'duplicates_tier_examples.json'}", flush=True)


if __name__ == "__main__":
    main()
