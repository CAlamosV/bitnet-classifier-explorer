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
EXPOSURE = ROOT / "data" / "intermediate" / "exposure" / "bitnet" / "institution_field_year_exposure.parquet"
EXPOSURE_MANIFEST = EXPOSURE.with_suffix(EXPOSURE.suffix + ".manifest.json")


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openalex-root", type=Path, default=OPENALEX_ROOT)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--candidate-metadata", type=Path, default=CANDIDATES)
    parser.add_argument("--exposure-frame", type=Path, default=EXPOSURE)
    parser.add_argument("--exposure-manifest", type=Path, default=EXPOSURE_MANIFEST)
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
    manifest = json.loads(args.exposure_manifest.read_text())
    diagnostics = manifest.get("diagnostics", {})
    min_pubs = int(diagnostics.get("min_pubs", 2000))
    pre_start = int(diagnostics.get("pre_start", 1970))
    pre_end = int(diagnostics.get("pre_end", 1979))
    network = str(diagnostics.get("network", "bitnet"))

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE selected_institutions AS
        WITH frame_fields AS (
            SELECT DISTINCT
                institution_id,
                field,
                w_if_pre,
                connect_year
            FROM read_parquet('{_pq(args.exposure_frame)}')
        ),
        frame AS (
            SELECT
                institution_id,
                SUM(COALESCE(w_if_pre, 0))::BIGINT AS pre_period_papers,
                MIN(connect_year) FILTER (WHERE connect_year IS NOT NULL) AS connect_year
            FROM frame_fields
            GROUP BY institution_id
        )
        SELECT
            f.institution_id AS university_key,
            COALESCE(t.InstitutionName, f.institution_id) AS display_name,
            f.institution_id,
            f.pre_period_papers,
            f.connect_year
        FROM frame f
        LEFT JOIN read_parquet('{_pq(institution_types)}') t
          ON f.institution_id = t.InstitutionID;

        CREATE OR REPLACE TEMP TABLE institution_counts AS
        SELECT
            s.university_key,
            s.display_name,
            s.institution_id,
            s.pre_period_papers,
            s.connect_year,
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
        GROUP BY
            s.university_key,
            s.display_name,
            s.institution_id,
            s.pre_period_papers,
            s.connect_year;

        CREATE OR REPLACE TEMP TABLE ranked AS
        SELECT
            university_key,
            display_name,
            institution_id,
            pre_period_papers,
            connect_year,
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
            COUNT(*) FILTER (WHERE author_count > 0) AS institutions_with_authors,
            COUNT(*) FILTER (WHERE pre_period_papers >= {min_pubs}) AS institutions_passing_pub_threshold,
            COUNT(*) FILTER (WHERE pre_period_papers < {min_pubs} AND connect_year IS NOT NULL)
                AS connected_below_pub_threshold,
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
            pre_period_papers,
            connect_year,
            author_count,
            paper_count,
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
            pre_period_papers,
            connect_year,
            author_count,
            paper_count
        FROM ranked
        WHERE rank <= 20
        ORDER BY rank
    """).fetchall()
    top_cols = [d[0] for d in con.description]

    out = {
        "year": args.year,
        "scope": "BitNet event-study exposure frame",
        "frame": {
            "network": network,
            "min_pubs": min_pubs,
            "pre_start": pre_start,
            "pre_end": pre_end,
            "source": str(args.exposure_frame.relative_to(ROOT)),
            "definition": (
                f"institutions with at least {min_pubs:,} distinct pre-period "
                f"papers in {pre_start}-{pre_end}, plus BitNet-connected "
                "institutions with any pre-period output"
            ),
        },
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
            "denominator": (
                "The cumulative chart sums to 100% over the event-study frame, "
                "not only over the institutions exported for browsing."
            ),
        },
    }
    args.output.write_text(json.dumps(out, ensure_ascii=True, separators=(",", ":")))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
