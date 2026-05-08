#!/usr/bin/env python3
"""Build static department-browser data for the classifier explorer site."""
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
OUT = ROOT / "tools" / "classifier_explorer" / "departments.json"

SCHOOL_IDS = {
    "Stanford": "I97018004",
    "UC Berkeley": "I95457486",
    "UC Davis": "I84218800",
    "UCLA": "I161318765",
}

AUDIT_DEPARTMENTS = [
    {
        "key": "ucb-eecs-1985",
        "university": "UC Berkeley",
        "department": "Electrical Engineering and Computer Science",
        "year": 1985,
        "target_field": "COMP_ENGG",
        "target_label": "Computer Science or Engineering",
    },
    {
        "key": "stanford-cs-1985",
        "university": "Stanford",
        "department": "Computer Science",
        "year": 1985,
        "target_field": "COMP",
        "target_label": "Computer Science",
    },
    {
        "key": "ucla-cs-1985",
        "university": "UCLA",
        "department": "Computer Science",
        "year": 1985,
        "target_field": "COMP",
        "target_label": "Computer Science",
    },
    {
        "key": "ucb-econ-1985",
        "university": "UC Berkeley",
        "department": "Economics",
        "year": 1985,
        "target_field": "ECON",
        "target_label": "Economics",
    },
    {
        "key": "stanford-soc-1985",
        "university": "Stanford",
        "department": "Sociology",
        "year": 1985,
        "target_field": "SOCI",
        "target_label": "Sociology",
    },
    {
        "key": "ucd-ece-1985",
        "university": "UC Davis",
        "department": "Electrical and Computer Engineering",
        "year": 1985,
        "target_field": "COMP_ENGG",
        "target_label": "Computer Science or Engineering",
    },
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


def field_prob_case(alias: str = "f") -> str:
    return """
        CASE d.target_field
            WHEN 'COMP' THEN {alias}.field_prob_COMP
            WHEN 'ENGG' THEN {alias}.field_prob_ENGG
            WHEN 'COMP_ENGG' THEN coalesce({alias}.field_prob_COMP, 0) + coalesce({alias}.field_prob_ENGG, 0)
            WHEN 'ECON' THEN {alias}.field_prob_ECON
            WHEN 'SOCI' THEN {alias}.field_prob_SOCI
            WHEN 'MATH' THEN {alias}.field_prob_MATH
            WHEN 'PHYS' THEN {alias}.field_prob_PHYS
            ELSE NULL
        END
    """.format(alias=alias)


def build_data(args: argparse.Namespace) -> dict[str, Any]:
    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute("SET preserve_insertion_order=false")

    imputed = args.openalex_root / "data" / "imputed" / "paper_author_edu_imputed_1940_2000.parquet"
    authors = args.openalex_root / "data" / "sciscinet" / "sciscinet_authors.parquet"
    author_details = args.openalex_root / "data" / "sciscinet" / "sciscinet_author_details.parquet"
    fields = ROOT / "data" / "intermediate" / "scinet" / "author_preds" / "author_field_career.parquet"
    audit_status = ROOT / "data" / "intermediate" / "faculty_rosters" / "department_audit_research_person_status.csv"
    audit_summary = ROOT / "data" / "intermediate" / "faculty_rosters" / "department_audit_slice_summary.csv"
    matches = ROOT / "data" / "intermediate" / "faculty_rosters" / "bleemer_openalex_matches_full.csv"

    dept_values = ",\n".join(
        "('{key}', '{university}', '{department}', {year}, '{institution_id}', "
        "'{target_field}', '{target_label}')".format(
            key=d["key"].replace("'", "''"),
            university=d["university"].replace("'", "''"),
            department=d["department"].replace("'", "''"),
            year=d["year"],
            institution_id=SCHOOL_IDS[d["university"]],
            target_field=d["target_field"],
            target_label=d["target_label"].replace("'", "''"),
        )
        for d in AUDIT_DEPARTMENTS
    )

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE depts AS
        SELECT *
        FROM (VALUES
            {dept_values}
        ) AS t(
            dept_key,
            university,
            department,
            audit_year,
            institution_id,
            target_field,
            target_label
        );

        CREATE OR REPLACE TEMP TABLE audit_summary AS
        SELECT *
        FROM read_csv_auto('{_pq(audit_summary)}');

        CREATE OR REPLACE TEMP TABLE audit_status AS
        SELECT
            *,
            coalesce(nullif(automatic_author_id, ''),
                     nullif(api_openalex_id, ''),
                     nullif(local_author_id, '')) AS matched_author_id
        FROM read_csv_auto('{_pq(audit_status)}');

        CREATE OR REPLACE TEMP TABLE audit_roster AS
        SELECT
            d.dept_key,
            a.bleemer_person_cluster_id,
            a.bleemer_name,
            a.audit_position_label,
            CAST(a.audit_is_ladder AS BOOLEAN) AS audit_is_ladder,
            a.is_research_role,
            a.cluster_departments,
            a.area,
            a.gen_area,
            a.bleemer_min_year,
            a.bleemer_max_year,
            a.audit_status,
            a.found_in_openalex_after_hard_search,
            a.hard_search_source,
            a.matched_author_id,
            coalesce(nullif(a.automatic_display_name, ''),
                     nullif(a.api_display_name, ''),
                     nullif(a.local_display_name, '')) AS matched_display_name,
            a.automatic_tier,
            a.audit_note
        FROM depts d
        JOIN audit_status a
          ON d.university = a.university
         AND d.department = a.audit_department
         AND d.audit_year = a.audit_year;

        CREATE OR REPLACE TEMP TABLE dept_author_map AS
        SELECT
            dept_key,
            matched_author_id AS AuthorID,
            string_agg(DISTINCT bleemer_name, ' | ' ORDER BY bleemer_name)
                AS bleemer_names,
            string_agg(DISTINCT audit_position_label, ' | ' ORDER BY audit_position_label)
                AS bleemer_positions
        FROM audit_roster
        WHERE matched_author_id IS NOT NULL
          AND matched_author_id != ''
        GROUP BY dept_key, matched_author_id;

        CREATE OR REPLACE TEMP TABLE university_roster_map AS
        SELECT
            d.dept_key,
            m.author_id AS AuthorID,
            string_agg(DISTINCT m.bleemer_name, ' | ' ORDER BY m.bleemer_name)
                AS university_bleemer_names,
            string_agg(DISTINCT m.department, ' | ' ORDER BY m.department)
                AS university_bleemer_departments,
            string_agg(DISTINCT m.position_label, ' | ' ORDER BY m.position_label)
                AS university_bleemer_positions
        FROM depts d
        JOIN read_csv_auto('{_pq(matches)}') m
          ON d.university = m.university
         AND d.audit_year BETWEEN CAST(m.bleemer_min_year AS INTEGER)
                              AND CAST(m.bleemer_max_year AS INTEGER)
        GROUP BY d.dept_key, m.author_id;

        CREATE OR REPLACE TEMP TABLE author_year_inst AS
        SELECT
            d.dept_key,
            i.AuthorID,
            count(DISTINCT i.PaperID) AS papers_at_school_year,
            sum(CASE WHEN i.imputed = 0 THEN 1 ELSE 0 END) AS raw_rows_at_school_year,
            min(i.imputed) AS min_imputed_at_school_year
        FROM depts d
        JOIN read_parquet('{_pq(imputed)}') i
          ON i.InstitutionID = d.institution_id
         AND CAST(i.year AS INTEGER) = d.audit_year
        GROUP BY d.dept_key, i.AuthorID;

        CREATE OR REPLACE TEMP TABLE openalex_rows AS
        SELECT
            d.dept_key,
            a.AuthorID,
            coalesce(sa.display_name, ad.display_name, a.AuthorID) AS display_name,
            a.papers_at_school_year,
            a.raw_rows_at_school_year,
            a.min_imputed_at_school_year,
            coalesce(f.n_papers, 0) AS n_papers,
            f.year_first,
            f.year_last,
            f.field_top1,
            f.field_top2,
            f.field_top3,
            f.field_p1,
            f.field_p2,
            f.field_p3,
            {field_prob_case("f")} AS target_field_prob,
            f.field_prob_COMP,
            f.field_prob_ENGG,
            f.field_prob_ECON,
            f.field_prob_SOCI,
            f.field_prob_MATH,
            f.field_prob_PHYS,
            CASE
                WHEN dm.AuthorID IS NOT NULL THEN 'department_roster'
                WHEN um.AuthorID IS NOT NULL THEN 'other_bleemer_roster'
                ELSE 'not_in_bleemer'
            END AS bleemer_status,
            dm.bleemer_names AS department_bleemer_names,
            dm.bleemer_positions AS department_bleemer_positions,
            um.university_bleemer_names,
            um.university_bleemer_departments,
            um.university_bleemer_positions
        FROM depts d
        JOIN author_year_inst a USING (dept_key)
        LEFT JOIN read_parquet('{_pq(authors)}') sa
          ON a.AuthorID = sa.authorid
        LEFT JOIN read_parquet('{_pq(author_details)}') ad
          ON a.AuthorID = ad.authorid
        LEFT JOIN read_parquet('{_pq(fields)}') f
          ON a.AuthorID = f.AuthorID
        LEFT JOIN dept_author_map dm
          ON a.dept_key = dm.dept_key
         AND a.AuthorID = dm.AuthorID
        LEFT JOIN university_roster_map um
          ON a.dept_key = um.dept_key
         AND a.AuthorID = um.AuthorID;
    """)

    summary_rows = con.execute("""
        SELECT
            d.dept_key,
            d.university,
            d.department,
            d.audit_year,
            d.institution_id,
            d.target_field,
            d.target_label,
            s.clusters,
            s.matched,
            s.unmatched,
            s.match_share,
            count(o.AuthorID) AS openalex_author_count,
            sum(CASE
                WHEN o.n_papers >= 5
                 AND coalesce(o.target_field_prob, 0) >= 0.5
                THEN 1 ELSE 0 END
            ) AS default_openalex_count,
            sum(CASE
                WHEN o.n_papers >= 5
                 AND coalesce(o.target_field_prob, 0) >= 0.5
                 AND o.bleemer_status = 'department_roster'
                THEN 1 ELSE 0 END
            ) AS default_matched_department_count,
            sum(CASE
                WHEN o.n_papers >= 5
                 AND coalesce(o.target_field_prob, 0) >= 0.5
                 AND o.bleemer_status = 'other_bleemer_roster'
                THEN 1 ELSE 0 END
            ) AS default_other_roster_count
        FROM depts d
        LEFT JOIN audit_summary s
          ON d.university = s.university
         AND d.department = s.department
         AND d.audit_year = s.audit_year
        LEFT JOIN openalex_rows o USING (dept_key)
        GROUP BY
            d.dept_key, d.university, d.department, d.audit_year,
            d.institution_id, d.target_field, d.target_label,
            s.clusters, s.matched, s.unmatched, s.match_share
        ORDER BY
            CASE d.dept_key
                WHEN 'ucb-eecs-1985' THEN 1
                WHEN 'stanford-cs-1985' THEN 2
                WHEN 'ucla-cs-1985' THEN 3
                WHEN 'ucb-econ-1985' THEN 4
                WHEN 'stanford-soc-1985' THEN 5
                ELSE 6
            END
    """).fetchall()
    summary_cols = [d[0] for d in con.description]

    roster_rows = con.execute("""
        SELECT *
        FROM audit_roster
        ORDER BY
            dept_key,
            is_research_role DESC,
            audit_is_ladder DESC,
            lower(bleemer_name)
    """).fetchall()
    roster_cols = [d[0] for d in con.description]

    oa_rows = con.execute("""
        SELECT *
        FROM openalex_rows
        ORDER BY
            dept_key,
            CASE bleemer_status
                WHEN 'department_roster' THEN 1
                WHEN 'other_bleemer_roster' THEN 2
                ELSE 3
            END,
            target_field_prob DESC NULLS LAST,
            n_papers DESC,
            lower(display_name)
    """).fetchall()
    oa_cols = [d[0] for d in con.description]

    def dicts(rows: list[tuple[Any, ...]], cols: list[str]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            item = dict(zip(cols, row))
            for k, v in list(item.items()):
                if isinstance(v, bool):
                    item[k] = bool(v)
            out.append(item)
        return out

    departments = []
    for row in dicts(summary_rows, summary_cols):
        key = row["dept_key"]
        row["bleemer_roster"] = [
            r for r in dicts(roster_rows, roster_cols) if r["dept_key"] == key
        ]
        row["openalex_authors"] = [
            r for r in dicts(oa_rows, oa_cols) if r["dept_key"] == key
        ]
        departments.append(row)

    return {
        "built_from": {
            "imputed_affiliations": "paper_author_edu_imputed_1940_2000.parquet",
            "author_fields": "author_field_career.parquet",
            "bleemer_audit": "department_audit_research_person_status.csv",
        },
        "defaults": {
            "min_papers": 5,
            "field_probability": 0.5,
        },
        "departments": departments,
    }


def main() -> None:
    args = parse_args()
    data = build_data(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=True, separators=(",", ":")))
    print(f"Wrote {args.output}")
    print(
        "Departments: "
        + ", ".join(d["dept_key"] for d in data["departments"])
    )


if __name__ == "__main__":
    main()
