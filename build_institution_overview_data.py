#!/usr/bin/env python3
"""Build static data for institution concentration charts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
OPENALEX_ROOT = Path(
    "/Users/alamos/US Inequality Dropbox/US Inequality Team Folder/OpenAlex"
)
OUT = ROOT / "tools" / "classifier_explorer" / "institution_overview_1980.json"
CANDIDATES = ROOT / "tools" / "classifier_explorer" / "institution_candidates.json"


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openalex-root", type=Path, default=OPENALEX_ROOT)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--candidate-metadata", type=Path, default=CANDIDATES)
    parser.add_argument("--year", type=int, default=1980)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory", default="8GB")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    imputed = (
        args.openalex_root
        / "data"
        / "imputed"
        / "paper_author_edu_imputed_1940_2000.parquet"
    )
    institution_types = args.openalex_root / "data" / "institution_types.parquet"
    candidate_metadata = json.loads(args.candidate_metadata.read_text())
    selected = candidate_metadata["universities"]
    values_sql = ",\n".join(
        "('{key}', '{name}', '{institution_id}')".format(**row)
        for row in selected
    )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE selected_institutions AS
        SELECT *
        FROM (VALUES
            {values_sql}
        ) AS t(university_key, display_name, institution_id);

        CREATE OR REPLACE TEMP TABLE institution_counts AS
        SELECT
            s.university_key,
            s.display_name,
            s.institution_id,
            COALESCE(MAX(t.InstitutionName), s.display_name, s.institution_id) AS institution_name,
            MAX(t.country_code) AS country_code,
            COUNT(DISTINCT i.AuthorID) AS author_count,
            COUNT(DISTINCT i.PaperID) AS paper_count,
            COUNT(*) FILTER (WHERE i.imputed = 0) AS raw_rows,
            COUNT(i.PaperID) AS affiliation_rows
        FROM selected_institutions s
        LEFT JOIN read_parquet('{_pq(imputed)}') i
          ON i.InstitutionID = s.institution_id
         AND i.year = {args.year}
        LEFT JOIN read_parquet('{_pq(institution_types)}') t
          ON s.institution_id = t.InstitutionID
        GROUP BY s.university_key, s.display_name, s.institution_id;

        CREATE OR REPLACE TEMP TABLE ranked AS
        SELECT
            university_key,
            display_name,
            institution_id,
            institution_name,
            country_code,
            COALESCE(author_count, 0) AS author_count,
            COALESCE(paper_count, 0) AS paper_count,
            COALESCE(raw_rows, 0) AS raw_rows,
            COALESCE(affiliation_rows, 0) AS affiliation_rows,
            ROW_NUMBER() OVER (
                ORDER BY COALESCE(author_count, 0) DESC, lower(display_name), institution_id
            ) AS rank,
            SUM(COALESCE(author_count, 0)) OVER () AS total_author_institution_placements
        FROM institution_counts;
    """)

    stats_row = con.execute(f"""
        SELECT
            {args.year} AS year,
            COUNT(*) AS total_institutions,
            COUNT(*) FILTER (WHERE author_count >= 100) AS institutions_with_100_plus_authors,
            SUM(author_count) AS total_author_institution_placements,
            (SELECT COUNT(DISTINCT i.AuthorID)
             FROM read_parquet('{_pq(imputed)}') i
             JOIN selected_institutions s ON i.InstitutionID = s.institution_id
             WHERE i.year = {args.year}) AS total_unique_authors,
            AVG(author_count) AS mean_authors_per_institution,
            MEDIAN(author_count) AS median_authors_per_institution,
            MAX(author_count) AS max_authors_per_institution,
            SUM(author_count) FILTER (WHERE rank <= 5)
                / SUM(author_count)::DOUBLE AS top_5_share,
            SUM(author_count) FILTER (WHERE rank <= 10)
                / SUM(author_count)::DOUBLE AS top_10_share,
            SUM(author_count) FILTER (WHERE rank <= 25)
                / SUM(author_count)::DOUBLE AS top_25_share,
            SUM(author_count) FILTER (WHERE rank <= 100)
                / SUM(author_count)::DOUBLE AS top_100_share
        FROM ranked
    """).fetchone()
    stat_cols = [d[0] for d in con.description]
    stats = dict(zip(stat_cols, stats_row))

    histogram = con.execute("""
        WITH bins AS (
            SELECT
                CASE
                    WHEN author_count = 1 THEN '1'
                    WHEN author_count BETWEEN 2 AND 4 THEN '2-4'
                    WHEN author_count BETWEEN 5 AND 9 THEN '5-9'
                    WHEN author_count BETWEEN 10 AND 24 THEN '10-24'
                    WHEN author_count BETWEEN 25 AND 49 THEN '25-49'
                    WHEN author_count BETWEEN 50 AND 99 THEN '50-99'
                    WHEN author_count BETWEEN 100 AND 249 THEN '100-249'
                    WHEN author_count BETWEEN 250 AND 499 THEN '250-499'
                    WHEN author_count BETWEEN 500 AND 999 THEN '500-999'
                    WHEN author_count BETWEEN 1000 AND 1999 THEN '1000-1999'
                    ELSE '2000+'
                END AS bin,
                CASE
                    WHEN author_count = 1 THEN 1
                    WHEN author_count BETWEEN 2 AND 4 THEN 2
                    WHEN author_count BETWEEN 5 AND 9 THEN 3
                    WHEN author_count BETWEEN 10 AND 24 THEN 4
                    WHEN author_count BETWEEN 25 AND 49 THEN 5
                    WHEN author_count BETWEEN 50 AND 99 THEN 6
                    WHEN author_count BETWEEN 100 AND 249 THEN 7
                    WHEN author_count BETWEEN 250 AND 499 THEN 8
                    WHEN author_count BETWEEN 500 AND 999 THEN 9
                    WHEN author_count BETWEEN 1000 AND 1999 THEN 10
                    ELSE 11
                END AS ord,
                author_count
            FROM institution_counts
        )
        SELECT
            bin,
            COUNT(*) AS institution_count,
            SUM(author_count) AS author_institution_placements
        FROM bins
        GROUP BY bin, ord
        ORDER BY ord
    """).fetchall()
    hist_cols = [d[0] for d in con.description]

    cumulative = con.execute("""
        SELECT
            rank,
            university_key,
            display_name,
            institution_id,
            institution_name,
            country_code,
            author_count,
            SUM(author_count) OVER (
                ORDER BY rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS cumulative_author_institution_placements,
            SUM(author_count) OVER (
                ORDER BY rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) / total_author_institution_placements::DOUBLE AS cumulative_share
        FROM ranked
        ORDER BY rank
    """).fetchall()
    cum_cols = [d[0] for d in con.description]

    top = con.execute("""
        SELECT
            rank,
            university_key,
            display_name,
            institution_id,
            institution_name,
            country_code,
            author_count
        FROM ranked
        WHERE rank <= 20
        ORDER BY rank
    """).fetchall()
    top_cols = [d[0] for d in con.description]

    out = {
        "year": args.year,
        "scope": "institutions exported in the Institution candidates browser",
        "selected_institutions": selected,
        "stats": stats,
        "histogram": [dict(zip(hist_cols, row)) for row in histogram],
        "institutions": [dict(zip(cum_cols, row)) for row in cumulative],
        "cumulative": [dict(zip(cum_cols, row)) for row in cumulative],
        "top_institutions": [dict(zip(top_cols, row)) for row in top],
        "notes": {
            "unit": "Distinct authors per institution in the imputed education-affiliation file.",
            "counting": (
                "An author attached to two institutions in the same year counts "
                "once for each institution."
            ),
        },
    }
    args.output.write_text(json.dumps(out, ensure_ascii=True, separators=(",", ":")))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
