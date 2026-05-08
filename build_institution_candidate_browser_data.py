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
            {field_select}
        FROM author_year ay
        LEFT JOIN read_parquet('{_pq(author_details)}') ad
          ON ay.AuthorID = ad.authorid
        LEFT JOIN read_parquet('{_pq(authors)}') sa
          ON ay.AuthorID = sa.authorid
        LEFT JOIN read_parquet('{_pq(fields)}') f
          ON ay.AuthorID = f.AuthorID;
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

            fp = {
                code: clean_number(float(prob))
                for code, prob in probs.items()
                if prob is not None and abs(float(prob)) >= 0.0005
            }
            if fp:
                out["fp"] = fp
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
        },
        "defaults": {
            "university_key": "stanford",
            "year": 1985,
            "field": "ECON",
            "min_works": 5,
            "min_field_probability": 0.5,
            "min_school_papers": 1,
        },
        "universities": SCHOOLS,
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
