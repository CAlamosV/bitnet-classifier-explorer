#!/usr/bin/env python3
"""Build OpenAlex-only university-year-field candidate browser data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[2]
OPENALEX_ROOT = Path(
    "/Users/alamos/US Inequality Dropbox/US Inequality Team Folder/OpenAlex"
)
OAFC_ROOT = (
    OPENALEX_ROOT / "code" / "field_classification"
)
OUT = ROOT / "tools" / "classifier_explorer" / "institution_candidates.json"
TAXONOMY = ROOT / "tools" / "classifier_explorer" / "taxonomy.json"

SCHOOLS = [
    {"key": "stanford", "name": "Stanford", "institution_id": "I97018004"},
    {"key": "ucb", "name": "UC Berkeley", "institution_id": "I95457486"},
    {"key": "ucd", "name": "UC Davis", "institution_id": "I84218800"},
    {"key": "ucla", "name": "UCLA", "institution_id": "I161318765"},
]


def _pq(path: Path | str) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openalex-root", type=Path, default=OPENALEX_ROOT)
    parser.add_argument("--oafc-root", type=Path, default=OAFC_ROOT)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory", default="8GB")
    return parser.parse_args()


def clean_number(value: Any, digits: int = 4) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, digits)
    return value


def set_if_present(out: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "":
        return
    if isinstance(value, float):
        out[key] = clean_number(value)
    else:
        out[key] = value


def school_values_sql() -> str:
    return ",\n".join(
        "('{key}', '{name}', '{institution_id}')".format(**school)
        for school in SCHOOLS
    )


def build_data(args: argparse.Namespace) -> None:
    taxonomy = json.loads(TAXONOMY.read_text())
    field_codes = list(taxonomy["fields"].keys())
    field_select = ",\n            ".join(
        f"f.field_prob_{code}" for code in field_codes
    )

    imputed = args.openalex_root / "data" / "imputed" / "paper_author_edu_imputed_1940_2000.parquet"
    authors = args.openalex_root / "data" / "sciscinet" / "sciscinet_authors.parquet"
    author_details = args.openalex_root / "data" / "sciscinet" / "sciscinet_author_details.parquet"
    fields = ROOT / "data" / "intermediate" / "scinet" / "author_preds" / "author_field_career.parquet"
    institution_types = args.openalex_root / "data" / "institution_types.parquet"
    paper_text = args.oafc_root / "data" / "intermediate" / "scinet" / "oafc_text_full.parquet"
    paper_fields = args.oafc_root / "data" / "intermediate" / "scinet" / "preds_e5_v1v2" / "preds_*.parquet"
    paper_subfields = args.oafc_root / "data" / "intermediate" / "scinet" / "preds_subfield_v1" / "preds_*.parquet"

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE schools AS
        SELECT *
        FROM (VALUES
            {school_values_sql()}
        ) AS t(university_key, university, institution_id);

        CREATE OR REPLACE TEMP TABLE all_institutions AS
        SELECT
            i.InstitutionID AS institution_id,
            COALESCE(MAX(t.InstitutionName), i.InstitutionID) AS name,
            MAX(t.type) AS type,
            MAX(t.country_code) AS country_code,
            COUNT(DISTINCT i.AuthorID) AS author_count,
            COUNT(DISTINCT i.AuthorID || ':' || CAST(i.year AS VARCHAR)) AS author_year_count,
            MIN(CAST(i.year AS INTEGER)) AS year_min,
            MAX(CAST(i.year AS INTEGER)) AS year_max
        FROM read_parquet('{_pq(imputed)}') i
        LEFT JOIN read_parquet('{_pq(institution_types)}') t
          ON i.InstitutionID = t.InstitutionID
        GROUP BY i.InstitutionID;

        CREATE OR REPLACE TEMP TABLE author_year AS
        SELECT
            s.university_key,
            s.university,
            s.institution_id,
            CAST(i.year AS INTEGER) AS year,
            i.AuthorID,
            COUNT(DISTINCT i.PaperID) AS school_papers,
            COUNT(*) FILTER (WHERE i.imputed = 0) AS raw_affiliation_rows,
            MIN(i.imputed) AS min_imputed
        FROM read_parquet('{_pq(imputed)}') i
        JOIN schools s
          ON i.InstitutionID = s.institution_id
        GROUP BY 1, 2, 3, 4, 5;

        CREATE OR REPLACE TEMP TABLE candidate_authors AS
        SELECT DISTINCT AuthorID
        FROM author_year;

        CREATE OR REPLACE TEMP TABLE candidate_edges AS
        SELECT DISTINCT i.AuthorID, i.PaperID AS paper_id
        FROM read_parquet('{_pq(imputed)}') i
        JOIN candidate_authors ca
          ON i.AuthorID = ca.AuthorID;

        CREATE OR REPLACE TEMP TABLE sub_preds AS
        SELECT
            paper_id,
            subfield_top1, subfield_top2, subfield_top3, subfield_top4, subfield_top5,
            CAST(sp1 AS DOUBLE) AS sp1,
            CAST(sp2 AS DOUBLE) AS sp2,
            CAST(sp3 AS DOUBLE) AS sp3,
            CAST(sp4 AS DOUBLE) AS sp4,
            CAST(sp5 AS DOUBLE) AS sp5
        FROM read_parquet('{_pq(paper_subfields)}');

        CREATE OR REPLACE TEMP TABLE sub_long AS
        SELECT ce.AuthorID, subfield_top1 AS subfield_code, sp1 AS prob
        FROM candidate_edges ce JOIN sub_preds sp ON ce.paper_id = sp.paper_id
        WHERE subfield_top1 IS NOT NULL AND sp1 IS NOT NULL AND sp1 > 0
        UNION ALL
        SELECT ce.AuthorID, subfield_top2 AS subfield_code, sp2 AS prob
        FROM candidate_edges ce JOIN sub_preds sp ON ce.paper_id = sp.paper_id
        WHERE subfield_top2 IS NOT NULL AND sp2 IS NOT NULL AND sp2 > 0
        UNION ALL
        SELECT ce.AuthorID, subfield_top3 AS subfield_code, sp3 AS prob
        FROM candidate_edges ce JOIN sub_preds sp ON ce.paper_id = sp.paper_id
        WHERE subfield_top3 IS NOT NULL AND sp3 IS NOT NULL AND sp3 > 0
        UNION ALL
        SELECT ce.AuthorID, subfield_top4 AS subfield_code, sp4 AS prob
        FROM candidate_edges ce JOIN sub_preds sp ON ce.paper_id = sp.paper_id
        WHERE subfield_top4 IS NOT NULL AND sp4 IS NOT NULL AND sp4 > 0
        UNION ALL
        SELECT ce.AuthorID, subfield_top5 AS subfield_code, sp5 AS prob
        FROM candidate_edges ce JOIN sub_preds sp ON ce.paper_id = sp.paper_id
        WHERE subfield_top5 IS NOT NULL AND sp5 IS NOT NULL AND sp5 > 0;

        CREATE OR REPLACE TEMP TABLE author_subfields AS
        WITH mass AS (
            SELECT AuthorID, subfield_code, SUM(prob) AS mass
            FROM sub_long
            GROUP BY 1, 2
        ),
        denom AS (
            SELECT AuthorID, SUM(mass) AS total_mass
            FROM mass
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                m.AuthorID,
                m.subfield_code,
                m.mass / NULLIF(d.total_mass, 0) AS prob,
                ROW_NUMBER() OVER (
                    PARTITION BY m.AuthorID
                    ORDER BY m.mass / NULLIF(d.total_mass, 0) DESC, m.subfield_code
                ) AS rn
            FROM mass m
            JOIN denom d ON m.AuthorID = d.AuthorID
            WHERE d.total_mass > 0
        )
        SELECT
            AuthorID,
            MAX(subfield_code) FILTER (WHERE rn = 1) AS subfield_top1,
            MAX(subfield_code) FILTER (WHERE rn = 2) AS subfield_top2,
            MAX(subfield_code) FILTER (WHERE rn = 3) AS subfield_top3,
            MAX(subfield_code) FILTER (WHERE rn = 4) AS subfield_top4,
            MAX(subfield_code) FILTER (WHERE rn = 5) AS subfield_top5,
            MAX(prob) FILTER (WHERE rn = 1) AS sub_p1,
            MAX(prob) FILTER (WHERE rn = 2) AS sub_p2,
            MAX(prob) FILTER (WHERE rn = 3) AS sub_p3,
            MAX(prob) FILTER (WHERE rn = 4) AS sub_p4,
            MAX(prob) FILTER (WHERE rn = 5) AS sub_p5
        FROM ranked
        WHERE rn <= 5
        GROUP BY AuthorID;

        CREATE OR REPLACE TEMP TABLE selected_work_base AS
        SELECT
            ay.university_key,
            ay.university,
            ay.institution_id,
            ay.year,
            ay.AuthorID,
            i.PaperID AS paper_id,
            MIN(i.imputed) AS min_imputed,
            COUNT(*) FILTER (WHERE i.imputed = 0) AS raw_rows
        FROM author_year ay
        JOIN read_parquet('{_pq(imputed)}') i
          ON ay.institution_id = i.InstitutionID
         AND ay.year = CAST(i.year AS INTEGER)
         AND ay.AuthorID = i.AuthorID
        GROUP BY 1, 2, 3, 4, 5, 6;

        CREATE OR REPLACE TEMP TABLE selected_papers AS
        SELECT DISTINCT paper_id
        FROM selected_work_base;

        CREATE OR REPLACE TEMP TABLE selected_work_titles AS
        SELECT p.paper_id, ANY_VALUE(t.title) AS title
        FROM selected_papers p
        LEFT JOIN read_parquet('{_pq(paper_text)}') t
          ON p.paper_id = t.paper_id
        GROUP BY p.paper_id;

        CREATE OR REPLACE TEMP TABLE selected_work_fields AS
        SELECT p.paper_id, f.field_top1, CAST(f.p1 AS DOUBLE) AS p1
        FROM selected_papers p
        LEFT JOIN read_parquet('{_pq(paper_fields)}') f
          ON p.paper_id = f.paper_id;

        CREATE OR REPLACE TEMP TABLE selected_work_subfields AS
        SELECT p.paper_id, s.subfield_top1, CAST(s.sp1 AS DOUBLE) AS sp1
        FROM selected_papers p
        LEFT JOIN sub_preds s
          ON p.paper_id = s.paper_id;

        CREATE OR REPLACE TEMP TABLE selected_works AS
        WITH ranked AS (
            SELECT
                b.*,
                t.title,
                f.field_top1,
                f.p1,
                s.subfield_top1,
                s.sp1,
                ROW_NUMBER() OVER (
                    PARTITION BY b.university_key, b.year, b.AuthorID
                    ORDER BY b.min_imputed ASC, b.paper_id
                ) AS rn
            FROM selected_work_base b
            LEFT JOIN selected_work_titles t ON b.paper_id = t.paper_id
            LEFT JOIN selected_work_fields f ON b.paper_id = f.paper_id
            LEFT JOIN selected_work_subfields s ON b.paper_id = s.paper_id
        )
        SELECT *
        FROM ranked
        WHERE rn <= 5;

        CREATE OR REPLACE TEMP TABLE candidate_rows AS
        SELECT
            ay.university_key,
            ay.university,
            ay.institution_id,
            ay.year,
            ay.AuthorID,
            coalesce(ad.display_name, sa.display_name, ay.AuthorID) AS display_name,
            ad.works_count AS openalex_works_count,
            ad.cited_by_count AS openalex_cited_by_count,
            sa.h_index AS sciscinet_h_index,
            coalesce(f.n_papers, 0) AS classifier_sample_pubs,
            f.year_first,
            f.year_last,
            ay.school_papers,
            ay.raw_affiliation_rows,
            ay.min_imputed,
            f.field_top1,
            f.field_top2,
            f.field_top3,
            f.field_p1,
            f.field_p2,
            f.field_p3,
            sf.subfield_top1,
            sf.subfield_top2,
            sf.subfield_top3,
            sf.subfield_top4,
            sf.subfield_top5,
            sf.sub_p1,
            sf.sub_p2,
            sf.sub_p3,
            sf.sub_p4,
            sf.sub_p5,
            {field_select}
        FROM author_year ay
        LEFT JOIN read_parquet('{_pq(author_details)}') ad
          ON ay.AuthorID = ad.authorid
        LEFT JOIN read_parquet('{_pq(authors)}') sa
          ON ay.AuthorID = sa.authorid
        LEFT JOIN read_parquet('{_pq(fields)}') f
          ON ay.AuthorID = f.AuthorID
        LEFT JOIN author_subfields sf
          ON ay.AuthorID = sf.AuthorID;
    """)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_dir = args.output.parent / "institution_candidates"
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = con.execute("""
        SELECT
            university_key,
            university,
            institution_id,
            year,
            COUNT(*) AS author_count,
            COUNT(*) FILTER (WHERE raw_affiliation_rows > 0) AS raw_author_count
        FROM candidate_rows
        GROUP BY 1, 2, 3, 4
        ORDER BY university_key, year
    """).fetchall()
    count_cols = [d[0] for d in con.description]

    institution_rows = con.execute("""
        SELECT
            institution_id,
            name,
            type,
            country_code,
            author_count,
            author_year_count,
            year_min,
            year_max
        FROM all_institutions
        ORDER BY author_count DESC, lower(name)
    """).fetchall()
    institution_cols = [d[0] for d in con.description]
    institutions = [dict(zip(institution_cols, row)) for row in institution_rows]

    data_files = []
    years = set()
    for row in counts:
        meta = dict(zip(count_cols, row))
        years.add(meta["year"])
        file_name = f"{meta['university_key']}-{meta['year']}.json"
        print(f"Writing {file_name}: {meta['author_count']} authors")
        rows = con.execute("""
            SELECT *
            FROM candidate_rows
            WHERE university_key = ?
              AND year = ?
            ORDER BY
                school_papers DESC,
                openalex_works_count DESC NULLS LAST,
                lower(display_name)
        """, [meta["university_key"], meta["year"]]).fetchall()
        cols = [d[0] for d in con.description]
        prob_start = cols.index(f"field_prob_{field_codes[0]}")

        work_rows = con.execute("""
            SELECT
                AuthorID,
                paper_id,
                year,
                title,
                field_top1,
                p1,
                subfield_top1,
                sp1,
                raw_rows
            FROM selected_works
            WHERE university_key = ?
              AND year = ?
            ORDER BY AuthorID, rn
        """, [meta["university_key"], meta["year"]]).fetchall()
        work_cols = [d[0] for d in con.description]
        works_by_author: dict[str, list[dict[str, Any]]] = {}
        for work_row in work_rows:
            work = dict(zip(work_cols, work_row))
            item: dict[str, Any] = {
                "p": work["paper_id"],
                "y": int(work["year"]) if work["year"] is not None else None,
            }
            set_if_present(item, "t", work["title"])
            set_if_present(item, "f", work["field_top1"])
            set_if_present(item, "fp", work["p1"])
            set_if_present(item, "s", work["subfield_top1"])
            set_if_present(item, "sp", work["sp1"])
            raw = int(work["raw_rows"] or 0)
            if raw:
                item["raw"] = raw
            works_by_author.setdefault(work["AuthorID"], []).append(item)

        authors_out = []
        for values in rows:
            item = dict(zip(cols[:prob_start], values[:prob_start]))
            probs = dict(zip(field_codes, values[prob_start:]))
            out: dict[str, Any] = {
                "a": item["AuthorID"],
                "n": item["display_name"],
                "yp": int(item["school_papers"] or 0),
            }
            set_if_present(out, "w", item["openalex_works_count"])
            set_if_present(out, "c", item["openalex_cited_by_count"])
            set_if_present(out, "h", item["sciscinet_h_index"])
            set_if_present(out, "sp", item["classifier_sample_pubs"])
            set_if_present(out, "yf", item["year_first"])
            set_if_present(out, "yl", item["year_last"])
            raw_rows = int(item["raw_affiliation_rows"] or 0)
            if raw_rows:
                out["raw"] = raw_rows
            out["imp"] = int(item["min_imputed"] or 0)

            top_fields = []
            for i in range(1, 4):
                code = item.get(f"field_top{i}")
                prob = item.get(f"field_p{i}")
                if code and prob is not None:
                    top_fields.append([code, clean_number(float(prob))])
            if top_fields:
                out["tf"] = top_fields

            top_subfields = []
            for i in range(1, 6):
                code = item.get(f"subfield_top{i}")
                prob = item.get(f"sub_p{i}")
                if code and prob is not None:
                    top_subfields.append([code, clean_number(float(prob))])
            if top_subfields:
                out["ts"] = top_subfields

            fp = {
                code: clean_number(float(prob))
                for code, prob in probs.items()
                if prob is not None and abs(float(prob)) >= 0.0005
            }
            if fp:
                out["fp"] = fp
            works = works_by_author.get(item["AuthorID"])
            if works:
                out["wk"] = works
            authors_out.append(out)

        payload = {
            "university_key": meta["university_key"],
            "university": meta["university"],
            "institution_id": meta["institution_id"],
            "year": meta["year"],
            "authors": authors_out,
        }
        (out_dir / file_name).write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        )
        data_files.append({
            **meta,
            "data_file": f"institution_candidates/{file_name}",
        })

    metadata = {
        "built_from": {
            "imputed_affiliations": "paper_author_edu_imputed_1940_2000.parquet",
            "author_details": "sciscinet_author_details.parquet",
            "author_fields": "author_field_career.parquet",
            "paper_fields": "preds_e5_v1v2/preds_*.parquet",
            "paper_subfields": "preds_subfield_v1/preds_*.parquet",
            "paper_titles": "oafc_text_full.parquet",
        },
        "defaults": {
            "university_key": "stanford",
            "institution_id": "I97018004",
            "year": 1985,
            "field": "ECON",
            "min_works": 5,
            "min_field_probability": 0.5,
            "min_school_papers": 1,
        },
        "universities": SCHOOLS,
        "institutions": institutions,
        "years": sorted(years),
        "fields": field_codes,
        "school_years": data_files,
    }
    args.output.write_text(json.dumps(metadata, ensure_ascii=True, separators=(",", ":")))
    print(f"Wrote {args.output}")
    print(f"Wrote per-school-year data to {out_dir}")


def main() -> None:
    args = parse_args()
    build_data(args)


if __name__ == "__main__":
    main()
