#!/usr/bin/env python3
"""Build duplicates.json for the static dedup explorer.

Reads `accepted_pairs.parquet` from the global duplicate classifier, builds
clusters via union-find, joins each member to display_name / works_count /
year_first / year_last / last_known_institution / merge_tier, then samples
clusters stratified by (a) cluster size and (b) merge tier so the explorer
covers the spectrum of cases.

Also writes:
- `duplicates_stats.json`: headline numbers used by duplicates_overview.html.
- `duplicates_tier_examples.json`: 3 example clusters per tier for the overview
  page (so the methodology page can show the kinds of pairs each tier catches).
"""
from __future__ import annotations

import argparse
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
    p.add_argument("--max-clusters", type=int, default=1500,
                   help="Cap on clusters in the browseable JSON.")
    p.add_argument("--examples-per-tier", type=int, default=3)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=repo / "tools" / "classifier_explorer",
    )
    p.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", 6)))
    p.add_argument("--memory", default=os.environ.get("MEMORY", "16GB"))
    return p.parse_args()


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}; SET memory_limit='{args.memory}'")

    print("[1/6] reading accepted pairs", flush=True)
    pairs = con.execute(f"""
        SELECT
            left_authorid, right_authorid, merge_tier,
            shared_papers, shared_coauthors, shared_institutions,
            bucket_size, name_token_count
        FROM read_parquet('{_pq(args.accepted)}')
    """).fetchall()
    print(f"  {len(pairs):,} accepted pairs", flush=True)

    print("[2/6] union-find clusters", flush=True)
    uf = UnionFind()
    for l, r, *_ in pairs:
        uf.union(str(l), str(r))
    cluster_of: dict[str, str] = {a: uf.find(a) for a in uf.parent}
    n_clusters = len(set(cluster_of.values()))
    print(f"  {n_clusters:,} clusters / {len(cluster_of):,} member IDs", flush=True)

    # Per-cluster aggregates.
    members_by_cluster: dict[str, list[str]] = defaultdict(list)
    for aid, root in cluster_of.items():
        members_by_cluster[root].append(aid)

    # Best tier and best evidence per cluster (priority of strongest signal).
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
    tier_for_cluster: dict[str, str] = {}
    edges_for_cluster: dict[str, list] = defaultdict(list)
    for l, r, tier, sp, sc, si, bs, ntok in pairs:
        root = uf.find(str(l))
        edges_for_cluster[root].append((str(l), str(r), tier, sp, sc, si, bs, ntok))
        prev = tier_for_cluster.get(root)
        if prev is None or TIER_PRIORITY.get(tier, 99) < TIER_PRIORITY.get(prev, 99):
            tier_for_cluster[root] = tier

    print("[3/6] per-author profile lookup", flush=True)
    member_ids = list(cluster_of.keys())
    con.execute("CREATE TEMP TABLE cluster_authors(authorid VARCHAR)")
    con.executemany("INSERT INTO cluster_authors VALUES (?)", [(a,) for a in member_ids])
    profiles = con.execute(f"""
        SELECT DISTINCT
            cf.left_authorid AS authorid,
            cf.left_name AS display_name,
            cf.left_works_count AS works_count,
            cf.left_year_first AS imp_year_first,
            cf.left_year_last AS imp_year_last,
            cf.left_last_known_institution AS last_known_institution
        FROM read_parquet('{_pq(args.features)}') cf
        WHERE cf.left_authorid IN (SELECT authorid FROM cluster_authors)
        UNION
        SELECT DISTINCT
            cf.right_authorid AS authorid,
            cf.right_name AS display_name,
            cf.right_works_count AS works_count,
            cf.right_year_first AS imp_year_first,
            cf.right_year_last AS imp_year_last,
            cf.right_last_known_institution AS last_known_institution
        FROM read_parquet('{_pq(args.features)}') cf
        WHERE cf.right_authorid IN (SELECT authorid FROM cluster_authors)
    """).fetchdf()

    oay = con.execute(f"""
        SELECT authorid, oa_year_first, oa_year_last
        FROM read_parquet('{_pq(args.oa_years)}')
        WHERE authorid IN (SELECT authorid FROM cluster_authors)
    """).fetchdf()

    profiles = profiles.drop_duplicates(subset="authorid", keep="first").set_index("authorid")
    oay = oay.drop_duplicates(subset="authorid", keep="first").set_index("authorid")
    print(f"  {len(profiles):,} unique member profiles", flush=True)

    print("[4/6] cluster-level stats", flush=True)
    headline = {
        "n_pairs": len(pairs),
        "n_clusters": n_clusters,
        "n_member_ids": len(cluster_of),
        "excess_ids_collapsed": len(cluster_of) - n_clusters,
    }
    by_tier_pairs: dict[str, int] = defaultdict(int)
    by_tier_clusters: dict[str, int] = defaultdict(int)
    cluster_size_hist: dict[int, int] = defaultdict(int)
    for _, _, tier, *_ in pairs:
        by_tier_pairs[tier] += 1
    for root, members in members_by_cluster.items():
        by_tier_clusters[tier_for_cluster.get(root, "?")] += 1
        cluster_size_hist[len(members)] += 1
    headline["by_tier_pairs"] = dict(sorted(by_tier_pairs.items(), key=lambda x: -x[1]))
    headline["by_tier_clusters"] = dict(sorted(by_tier_clusters.items(), key=lambda x: -x[1]))
    headline["cluster_size_hist"] = dict(sorted(cluster_size_hist.items()))

    print("[5/6] sampling clusters for the explorer", flush=True)

    def lookup(aid: str) -> dict:
        prof = profiles.loc[aid] if aid in profiles.index else None
        oa = oay.loc[aid] if aid in oay.index else None
        out = {
            "authorid": aid,
            "display_name": (prof.display_name if prof is not None else None),
            "works_count": int(prof.works_count) if prof is not None and prof.works_count is not None else None,
            "imp_year_first": int(prof.imp_year_first) if prof is not None and prof.imp_year_first is not None else None,
            "imp_year_last": int(prof.imp_year_last) if prof is not None and prof.imp_year_last is not None else None,
            "last_known_institution": (prof.last_known_institution if prof is not None else None),
            "oa_year_first": int(oa.oa_year_first) if oa is not None and oa.oa_year_first is not None else None,
            "oa_year_last": int(oa.oa_year_last) if oa is not None and oa.oa_year_last is not None else None,
        }
        return out

    # Stratified sample: per tier, pick max(N) clusters with that tier as the
    # cluster's best (lowest-priority-number) tier, ordered by hash so it's
    # deterministic. Then concatenate.
    per_tier_cap = max(1, args.max_clusters // max(1, len(by_tier_clusters)))
    sample_roots: list[str] = []
    for tier in by_tier_clusters:
        roots_in_tier = [
            r for r, t in tier_for_cluster.items() if t == tier
        ]
        roots_in_tier.sort(key=lambda r: hash((r, "shuffle")))
        sample_roots.extend(roots_in_tier[:per_tier_cap])
    sample_roots = sample_roots[: args.max_clusters]

    cluster_records = []
    for root in sample_roots:
        members = sorted(members_by_cluster[root])
        member_records = [lookup(a) for a in members]
        # Canonical = author with the most works (None counts as 0).
        member_records.sort(
            key=lambda d: (-(d.get("works_count") or 0), d["authorid"])
        )
        # Edges within this cluster
        edges = [
            {
                "left": l, "right": r, "tier": t,
                "shared_papers": sp, "shared_coauthors": sc,
                "shared_institutions": si, "bucket_size": bs,
                "name_token_count": ntok,
            }
            for l, r, t, sp, sc, si, bs, ntok in edges_for_cluster[root]
        ]
        cluster_records.append({
            "cluster_id": root,
            "size": len(members),
            "best_tier": tier_for_cluster.get(root),
            "members": member_records,
            "edges": edges,
        })

    # Tier example clusters (for the methodology page)
    tier_examples = {}
    for tier in by_tier_clusters:
        roots_in_tier = [r for r, t in tier_for_cluster.items() if t == tier]
        roots_in_tier.sort(key=lambda r: (
            -len(members_by_cluster[r]), hash((r, "ex"))
        ))
        examples = []
        for root in roots_in_tier[: args.examples_per_tier]:
            members = sorted(members_by_cluster[root])
            recs = [lookup(a) for a in members]
            recs.sort(key=lambda d: (-(d.get("works_count") or 0), d["authorid"]))
            examples.append({
                "cluster_id": root,
                "size": len(members),
                "members": recs[:5],  # cap to first 5 for compactness
            })
        tier_examples[tier] = examples

    print("[6/6] writing JSON", flush=True)
    out = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "headline": headline,
        "tier_priority": TIER_PRIORITY,
        "clusters": cluster_records,
    }
    (args.out_dir / "duplicates.json").write_text(json.dumps(out, indent=1))
    (args.out_dir / "duplicates_stats.json").write_text(json.dumps(headline, indent=2))
    (args.out_dir / "duplicates_tier_examples.json").write_text(
        json.dumps(tier_examples, indent=2)
    )
    print(f"  wrote {args.out_dir / 'duplicates.json'} "
          f"({len(cluster_records):,} clusters)", flush=True)
    print(f"  wrote {args.out_dir / 'duplicates_stats.json'}", flush=True)
    print(f"  wrote {args.out_dir / 'duplicates_tier_examples.json'}", flush=True)


if __name__ == "__main__":
    main()
