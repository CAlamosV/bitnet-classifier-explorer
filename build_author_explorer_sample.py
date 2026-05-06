#!/usr/bin/env python3
"""Build authors.json for the static classifier explorer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    repo = Path(__file__).resolve().parent.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=Path("/scratch/users/alamos/oafc/data/author_preds/author_eval_sample.parquet"))
    parser.add_argument("--labels", type=Path, default=Path("/scratch/users/alamos/oafc/data/author_preds/author_eval_labels.parquet"))
    parser.add_argument("--field-by-weight", type=Path, default=Path("/scratch/users/alamos/oafc/data/author_preds/author_field_career_by_weight.parquet"))
    parser.add_argument("--subfield-by-weight", type=Path, default=Path("/scratch/users/alamos/oafc/data/author_preds/author_subfield_career_by_weight.parquet"))
    parser.add_argument("--weight", default="uniform")
    parser.add_argument("--max-authors", type=int, default=1200)
    parser.add_argument("--out", type=Path, default=repo / "tools" / "classifier_explorer" / "authors.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    con = duckdb.connect()
    labels_join = ""
    labels_select = """
        NULL AS llm_field, NULL AS llm_field_alt, NULL AS llm_field_conf,
        NULL AS llm_secondary_field,
        NULL AS llm_subfield, NULL AS llm_subfield_alt, NULL AS llm_secondary_subfield,
        NULL AS llm_subfield_conf,
        NULL AS llm_interdisciplinary
    """
    if args.labels.exists():
        labels_join = f"LEFT JOIN read_parquet('{_pq(args.labels)}') l ON sm.AuthorID = l.AuthorID"
        labels_select = """
            l.llm_field, l.llm_field_alt, l.llm_field_conf, l.llm_secondary_field,
            l.llm_subfield, l.llm_subfield_alt, l.llm_secondary_subfield, l.llm_subfield_conf,
            l.llm_interdisciplinary
        """
    df = con.execute(f"""
        SELECT
            sm.AuthorID, sm.AuthorName, sm.paper_bucket, sm.sample_source,
            sm.top_institutions, sm.top_journals, sm.papers_json,
            f.n_papers, f.year_first, f.year_last,
            f.field_top1, f.field_top2, f.field_top3,
            f.field_p1, f.field_p2, f.field_p3,
            s.subfield_top1, s.subfield_top2, s.subfield_top3, s.subfield_top4, s.subfield_top5,
            s.sp1, s.sp2, s.sp3, s.sp4, s.sp5,
            {labels_select}
        FROM read_parquet('{_pq(args.sample)}') sm
        JOIN read_parquet('{_pq(args.field_by_weight)}') f
          ON sm.AuthorID = f.AuthorID AND f.weight_scheme = '{args.weight}'
        LEFT JOIN read_parquet('{_pq(args.subfield_by_weight)}') s
          ON sm.AuthorID = s.AuthorID
         AND s.weight_scheme = CASE
             WHEN '{args.weight}' = 'p1' THEN 'sp1'
             WHEN '{args.weight}' = 'p1_inv_n_authors' THEN 'sp1_inv_n_authors'
             ELSE '{args.weight}'
         END
        {labels_join}
        ORDER BY HASH(sm.AuthorID)
        LIMIT {args.max_authors}
    """).fetchdf()

    records = []
    for row in df.itertuples(index=False):
        d = row._asdict()
        d["papers"] = json.loads(d.pop("papers_json") or "[]")
        for key, val in list(d.items()):
            if isinstance(val, list):
                continue
            if pd.isna(val):
                d[key] = None
            elif hasattr(val, "item"):
                d[key] = val.item()
        records.append(d)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, ensure_ascii=True, separators=(",", ":")))
    print(f"[author-explorer] wrote {len(records):,} authors to {args.out}")


if __name__ == "__main__":
    main()
