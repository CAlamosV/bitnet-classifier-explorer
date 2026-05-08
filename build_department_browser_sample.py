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
OAFC_ROOT = OPENALEX_ROOT / "code" / "field_classification"
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
        "target_field": "COMP",
        "target_label": "Computer Science",
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
        "key": "stanford-econ-1985",
        "university": "Stanford",
        "department": "Economics",
        "year": 1985,
        "target_field": "ECON",
        "target_label": "Economics",
    },
    {
        "key": "ucd-econ-1985",
        "university": "UC Davis",
        "department": "Economics",
        "year": 1985,
        "target_field": "ECON",
        "target_label": "Economics",
    },
    {
        "key": "ucla-econ-1985",
        "university": "UCLA",
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
        "target_field": "ENGG",
        "target_label": "Engineering",
    },
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
    affiliations = args.openalex_root / "data" / "sciscinet" / "sciscinet_affiliations.parquet"
    fields = ROOT / "data" / "intermediate" / "scinet" / "author_preds" / "author_field_career.parquet"
    paper_text = args.oafc_root / "data" / "intermediate" / "scinet" / "oafc_text_full.parquet"
    field_preds = args.oafc_root / "data" / "intermediate" / "scinet" / "preds_e5_v1v2" / "preds_*.parquet"
    subfield_preds = args.oafc_root / "data" / "intermediate" / "scinet" / "preds_subfield_v1" / "preds_*.parquet"
    audit_status = ROOT / "data" / "intermediate" / "faculty_rosters" / "department_audit_research_person_status.csv"
    audit_summary = ROOT / "data" / "intermediate" / "faculty_rosters" / "department_audit_slice_summary.csv"
    matches = ROOT / "data" / "intermediate" / "faculty_rosters" / "bleemer_openalex_matches_full.csv"
    raw_roster = ROOT / "data" / "raw" / "faculty_rosters" / "bleemer_faculty_panel.parquet"
    cluster_map = ROOT / "data" / "intermediate" / "faculty_rosters" / "bleemer_person_cluster_map_1940_2000.parquet"

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
            coalesce(p.dept_years, 0) AS years_in_selected_department,
            p.dept_min_year AS selected_department_min_year,
            p.dept_max_year AS selected_department_max_year,
            coalesce(nullif(a.automatic_display_name, ''),
                     nullif(a.api_display_name, ''),
                     nullif(a.local_display_name, '')) AS matched_display_name,
            a.automatic_tier,
            a.audit_note
        FROM depts d
        JOIN audit_status a
          ON d.university = a.university
         AND d.department = a.audit_department
         AND d.audit_year = a.audit_year
        LEFT JOIN (
            SELECT
                p.university,
                cm.bleemer_person_cluster_id,
                p.department,
                COUNT(DISTINCT p.year) AS dept_years,
                MIN(p.year) AS dept_min_year,
                MAX(p.year) AS dept_max_year
            FROM read_parquet('{_pq(raw_roster)}') p
            JOIN read_parquet('{_pq(cluster_map)}') cm
              ON p.faculty_uid = cm.faculty_uid
            GROUP BY p.university, cm.bleemer_person_cluster_id, p.department
        ) p
          ON a.university = p.university
         AND a.bleemer_person_cluster_id = p.bleemer_person_cluster_id
         AND a.audit_department = p.department;

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

        CREATE OR REPLACE TEMP TABLE same_dept_other_year_map AS
        SELECT
            d.dept_key,
            m.author_id AS AuthorID,
            string_agg(DISTINCT m.bleemer_name, ' | ' ORDER BY m.bleemer_name)
                AS same_department_names,
            string_agg(DISTINCT m.position_label, ' | ' ORDER BY m.position_label)
                AS same_department_positions,
            string_agg(
                DISTINCT CAST(m.bleemer_min_year AS VARCHAR) || '-' ||
                         CAST(m.bleemer_max_year AS VARCHAR),
                ' | ' ORDER BY CAST(m.bleemer_min_year AS VARCHAR) || '-' ||
                             CAST(m.bleemer_max_year AS VARCHAR)
            ) AS same_department_year_ranges,
            MIN(CAST(m.bleemer_min_year AS INTEGER)) AS same_department_min_year,
            MAX(CAST(m.bleemer_max_year AS INTEGER)) AS same_department_max_year
        FROM depts d
        JOIN read_csv_auto('{_pq(matches)}') m
          ON d.university = m.university
         AND (
                m.department = d.department
             OR contains(m.department, d.department)
             OR contains(d.department, m.department)
         )
         AND NOT d.audit_year BETWEEN CAST(m.bleemer_min_year AS INTEGER)
                                  AND CAST(m.bleemer_max_year AS INTEGER)
        GROUP BY d.dept_key, m.author_id;

        CREATE OR REPLACE TEMP TABLE university_roster_map AS
        SELECT
            d.dept_key,
            m.author_id AS AuthorID,
            string_agg(DISTINCT m.bleemer_name, ' | ' ORDER BY m.bleemer_name)
                AS university_bleemer_names,
            string_agg(DISTINCT m.department, ' | ' ORDER BY m.department)
                AS university_bleemer_departments,
            string_agg(DISTINCT m.university, ' | ' ORDER BY m.university)
                AS university_bleemer_universities,
            string_agg(
                DISTINCT m.university || ' - ' || m.department,
                ' | ' ORDER BY m.university || ' - ' || m.department
            ) AS university_bleemer_locations,
            string_agg(DISTINCT m.position_label, ' | ' ORDER BY m.position_label)
                AS university_bleemer_positions
        FROM depts d
        JOIN read_csv_auto('{_pq(matches)}') m
          ON d.audit_year BETWEEN CAST(m.bleemer_min_year AS INTEGER)
                              AND CAST(m.bleemer_max_year AS INTEGER)
         AND NOT (
                d.university = m.university
            AND (
                   m.department = d.department
                OR contains(m.department, d.department)
                OR contains(d.department, m.department)
            )
         )
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
            ad.works_count AS openalex_works_count,
            ad.cited_by_count AS openalex_cited_by_count,
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
                WHEN sd.AuthorID IS NOT NULL THEN 'same_department_other_year'
                WHEN um.AuthorID IS NOT NULL THEN 'other_bleemer_roster'
                ELSE 'not_in_bleemer'
            END AS bleemer_status,
            dm.bleemer_names AS department_bleemer_names,
            dm.bleemer_positions AS department_bleemer_positions,
            sd.same_department_names,
            sd.same_department_positions,
            sd.same_department_year_ranges,
            sd.same_department_min_year,
            sd.same_department_max_year,
            um.university_bleemer_names,
            um.university_bleemer_departments,
            um.university_bleemer_universities,
            um.university_bleemer_locations,
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
        LEFT JOIN same_dept_other_year_map sd
          ON a.dept_key = sd.dept_key
         AND a.AuthorID = sd.AuthorID
        LEFT JOIN university_roster_map um
          ON a.dept_key = um.dept_key
         AND a.AuthorID = um.AuthorID;

        CREATE OR REPLACE TEMP TABLE selected_dept_authors AS
        SELECT DISTINCT dept_key, AuthorID
        FROM openalex_rows
        UNION
        SELECT DISTINCT dept_key, matched_author_id AS AuthorID
        FROM audit_roster
        WHERE matched_author_id IS NOT NULL
          AND matched_author_id != '';

        CREATE OR REPLACE TEMP TABLE selected_authors AS
        SELECT DISTINCT AuthorID
        FROM selected_dept_authors;

        CREATE OR REPLACE TEMP TABLE author_profiles AS
        SELECT
            a.AuthorID,
            coalesce(sa.display_name, ad.display_name, a.AuthorID) AS display_name,
            ad.works_count AS openalex_works_count,
            ad.cited_by_count AS openalex_cited_by_count,
            sa.productivity AS sciscinet_productivity,
            sa.h_index AS sciscinet_h_index,
            coalesce(f.n_papers, 0) AS n_papers,
            f.year_first,
            f.year_last,
            f.field_top1,
            f.field_top2,
            f.field_top3,
            f.field_p1,
            f.field_p2,
            f.field_p3,
            f.field_prob_COMP,
            f.field_prob_ENGG,
            f.field_prob_ECON,
            f.field_prob_SOCI,
            f.field_prob_MATH,
            f.field_prob_PHYS
        FROM selected_authors a
        LEFT JOIN read_parquet('{_pq(authors)}') sa
          ON a.AuthorID = sa.authorid
        LEFT JOIN read_parquet('{_pq(author_details)}') ad
          ON a.AuthorID = ad.authorid
        LEFT JOIN read_parquet('{_pq(fields)}') f
          ON a.AuthorID = f.AuthorID;

        CREATE OR REPLACE TEMP TABLE selected_author_papers AS
        SELECT
            i.AuthorID,
            i.PaperID,
            MIN(CAST(i.year AS INTEGER)) AS year
        FROM read_parquet('{_pq(imputed)}') i
        JOIN selected_authors a USING (AuthorID)
        GROUP BY i.AuthorID, i.PaperID;

        CREATE OR REPLACE TEMP TABLE selected_author_paper_institutions AS
        SELECT
            i.AuthorID,
            i.PaperID,
            string_agg(
                DISTINCT coalesce(aff.display_name, i.InstitutionID),
                ' | ' ORDER BY coalesce(aff.display_name, i.InstitutionID)
            ) AS assigned_institutions,
            string_agg(
                DISTINCT i.InstitutionID,
                ' | ' ORDER BY i.InstitutionID
            ) AS assigned_institution_ids
        FROM read_parquet('{_pq(imputed)}') i
        JOIN selected_author_papers sap
          ON i.AuthorID = sap.AuthorID
         AND i.PaperID = sap.PaperID
        LEFT JOIN read_parquet('{_pq(affiliations)}') aff
          ON i.InstitutionID = aff.institution_id
        GROUP BY i.AuthorID, i.PaperID;

        CREATE OR REPLACE TEMP TABLE career_inst_counts AS
        WITH counts AS (
            SELECT
                i.AuthorID,
                i.InstitutionID,
                coalesce(aff.display_name, i.InstitutionID) AS institution_name,
                COUNT(DISTINCT i.PaperID) AS n_papers,
                MIN(CAST(i.year AS INTEGER)) AS year_first,
                MAX(CAST(i.year AS INTEGER)) AS year_last
            FROM read_parquet('{_pq(imputed)}') i
            JOIN selected_authors a USING (AuthorID)
            LEFT JOIN read_parquet('{_pq(affiliations)}') aff
              ON i.InstitutionID = aff.institution_id
            GROUP BY i.AuthorID, i.InstitutionID, institution_name
        )
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY AuthorID
                    ORDER BY n_papers DESC, institution_name
                ) AS rn
            FROM counts
        )
        WHERE rn <= 8;

        CREATE OR REPLACE TEMP TABLE author_subfield_long AS
        SELECT sap.AuthorID, p.subfield_top1 AS subfield_code, CAST(p.sp1 AS DOUBLE) AS mass
        FROM selected_author_papers sap
        JOIN read_parquet('{_pq(subfield_preds)}') p ON sap.PaperID = p.paper_id
        WHERE p.subfield_top1 IS NOT NULL AND p.sp1 IS NOT NULL AND p.sp1 > 0
        UNION ALL
        SELECT sap.AuthorID, p.subfield_top2 AS subfield_code, CAST(p.sp2 AS DOUBLE) AS mass
        FROM selected_author_papers sap
        JOIN read_parquet('{_pq(subfield_preds)}') p ON sap.PaperID = p.paper_id
        WHERE p.subfield_top2 IS NOT NULL AND p.sp2 IS NOT NULL AND p.sp2 > 0
        UNION ALL
        SELECT sap.AuthorID, p.subfield_top3 AS subfield_code, CAST(p.sp3 AS DOUBLE) AS mass
        FROM selected_author_papers sap
        JOIN read_parquet('{_pq(subfield_preds)}') p ON sap.PaperID = p.paper_id
        WHERE p.subfield_top3 IS NOT NULL AND p.sp3 IS NOT NULL AND p.sp3 > 0
        UNION ALL
        SELECT sap.AuthorID, p.subfield_top4 AS subfield_code, CAST(p.sp4 AS DOUBLE) AS mass
        FROM selected_author_papers sap
        JOIN read_parquet('{_pq(subfield_preds)}') p ON sap.PaperID = p.paper_id
        WHERE p.subfield_top4 IS NOT NULL AND p.sp4 IS NOT NULL AND p.sp4 > 0
        UNION ALL
        SELECT sap.AuthorID, p.subfield_top5 AS subfield_code, CAST(p.sp5 AS DOUBLE) AS mass
        FROM selected_author_papers sap
        JOIN read_parquet('{_pq(subfield_preds)}') p ON sap.PaperID = p.paper_id
        WHERE p.subfield_top5 IS NOT NULL AND p.sp5 IS NOT NULL AND p.sp5 > 0;

        CREATE OR REPLACE TEMP TABLE author_subfield_top AS
        WITH mass AS (
            SELECT AuthorID, subfield_code, SUM(mass) AS mass
            FROM author_subfield_long
            GROUP BY AuthorID, subfield_code
        ),
        denom AS (
            SELECT AuthorID, SUM(mass) AS total_mass
            FROM mass
            GROUP BY AuthorID
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
            JOIN denom d USING (AuthorID)
            WHERE d.total_mass > 0
        )
        SELECT
            AuthorID,
            MAX(CASE WHEN rn = 1 THEN subfield_code END) AS subfield_top1,
            MAX(CASE WHEN rn = 2 THEN subfield_code END) AS subfield_top2,
            MAX(CASE WHEN rn = 3 THEN subfield_code END) AS subfield_top3,
            MAX(CASE WHEN rn = 1 THEN prob END) AS sp1,
            MAX(CASE WHEN rn = 2 THEN prob END) AS sp2,
            MAX(CASE WHEN rn = 3 THEN prob END) AS sp3
        FROM ranked
        WHERE rn <= 3
        GROUP BY AuthorID;

        CREATE OR REPLACE TEMP TABLE recent_publications AS
        WITH dept_papers AS (
            SELECT
                s.dept_key,
                d.audit_year,
                sap.AuthorID,
                sap.PaperID,
                sap.year,
                fp.field_top1,
                fp.p1 AS field_p1,
                fp.field_top2,
                fp.p2 AS field_p2
            FROM selected_dept_authors s
            JOIN depts d USING (dept_key)
            JOIN selected_author_papers sap USING (AuthorID)
            JOIN read_parquet('{_pq(field_preds)}') fp
              ON sap.PaperID = fp.paper_id
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY dept_key, AuthorID
                    ORDER BY abs(year - audit_year), year DESC, PaperID
                ) AS rn
            FROM dept_papers
        )
        SELECT
            r.dept_key,
            r.AuthorID,
            r.PaperID,
            r.year,
            coalesce(t.title, '') AS title,
            r.field_top1,
            r.field_p1,
            r.field_top2,
            r.field_p2,
            sp.subfield_top1,
            sp.sp1,
            sp.subfield_top2,
            sp.sp2,
            pi.assigned_institutions,
            pi.assigned_institution_ids,
            r.rn
        FROM ranked r
        LEFT JOIN read_parquet('{_pq(paper_text)}') t
          ON r.PaperID = t.paper_id
        LEFT JOIN read_parquet('{_pq(subfield_preds)}') sp
          ON r.PaperID = sp.paper_id
        LEFT JOIN selected_author_paper_institutions pi
          ON r.AuthorID = pi.AuthorID
         AND r.PaperID = pi.PaperID
        WHERE r.rn <= 5;
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
                WHEN coalesce(o.openalex_works_count, 0) >= 5
                 AND coalesce(o.target_field_prob, 0) >= 0.5
                THEN 1 ELSE 0 END
            ) AS default_openalex_count,
            sum(CASE
                WHEN coalesce(o.openalex_works_count, 0) >= 5
                 AND coalesce(o.target_field_prob, 0) >= 0.5
                 AND o.bleemer_status = 'department_roster'
                THEN 1 ELSE 0 END
            ) AS default_matched_department_count,
            sum(CASE
                WHEN coalesce(o.openalex_works_count, 0) >= 5
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
                WHEN 'stanford-econ-1985' THEN 5
                WHEN 'ucd-econ-1985' THEN 6
                WHEN 'ucla-econ-1985' THEN 7
                WHEN 'stanford-soc-1985' THEN 8
                ELSE 9
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
            openalex_works_count DESC NULLS LAST,
            lower(display_name)
    """).fetchall()
    oa_cols = [d[0] for d in con.description]

    profile_rows = con.execute("""
        SELECT *
        FROM author_profiles
    """).fetchall()
    profile_cols = [d[0] for d in con.description]

    inst_rows = con.execute("""
        SELECT AuthorID, InstitutionID, institution_name, n_papers, year_first, year_last
        FROM career_inst_counts
        ORDER BY AuthorID, n_papers DESC, institution_name
    """).fetchall()
    inst_cols = [d[0] for d in con.description]

    subfield_rows = con.execute("""
        SELECT *
        FROM author_subfield_top
    """).fetchall()
    subfield_cols = [d[0] for d in con.description]

    recent_rows = con.execute("""
        SELECT *
        FROM recent_publications
        ORDER BY dept_key, AuthorID, rn
    """).fetchall()
    recent_cols = [d[0] for d in con.description]

    def dicts(rows: list[tuple[Any, ...]], cols: list[str]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            item = dict(zip(cols, row))
            for k, v in list(item.items()):
                if isinstance(v, bool):
                    item[k] = bool(v)
            out.append(item)
        return out

    roster_items = dicts(roster_rows, roster_cols)
    oa_items = dicts(oa_rows, oa_cols)
    profile_items = dicts(profile_rows, profile_cols)
    inst_items = dicts(inst_rows, inst_cols)
    subfield_items = dicts(subfield_rows, subfield_cols)
    recent_items = dicts(recent_rows, recent_cols)

    inst_by_author: dict[str, list[dict[str, Any]]] = {}
    for item in inst_items:
        inst_by_author.setdefault(item["AuthorID"], []).append({
            "institution_id": item["InstitutionID"],
            "name": item["institution_name"],
            "n_papers": item["n_papers"],
            "year_first": item["year_first"],
            "year_last": item["year_last"],
        })

    subfield_by_author = {
        item["AuthorID"]: {
            "subfield_top1": item["subfield_top1"],
            "subfield_top2": item["subfield_top2"],
            "subfield_top3": item["subfield_top3"],
            "sp1": item["sp1"],
            "sp2": item["sp2"],
            "sp3": item["sp3"],
        }
        for item in subfield_items
    }

    profile_by_author = {item["AuthorID"]: item for item in profile_items}

    def enriched_profile(author_id: str | None) -> dict[str, Any] | None:
        if not author_id:
            return None
        base = profile_by_author.get(author_id)
        if not base:
            return None
        out = dict(base)
        out.update(subfield_by_author.get(author_id, {}))
        out["career_institutions"] = inst_by_author.get(author_id, [])
        return out

    recent_by_dept_author: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in recent_items:
        recent_by_dept_author.setdefault((item["dept_key"], item["AuthorID"]), []).append({
            "paper_id": item["PaperID"],
            "year": item["year"],
            "title": item["title"],
            "field_top1": item["field_top1"],
            "field_p1": item["field_p1"],
            "field_top2": item["field_top2"],
            "field_p2": item["field_p2"],
            "subfield_top1": item["subfield_top1"],
            "sp1": item["sp1"],
            "subfield_top2": item["subfield_top2"],
            "sp2": item["sp2"],
            "assigned_institutions": item["assigned_institutions"],
            "assigned_institution_ids": item["assigned_institution_ids"],
        })

    roster_by_dept: dict[str, list[dict[str, Any]]] = {}
    for item in roster_items:
        profile = enriched_profile(item.get("matched_author_id"))
        if profile:
            profile = dict(profile)
            profile["recent_publications"] = recent_by_dept_author.get(
                (item["dept_key"], item["matched_author_id"]), []
            )
            item["openalex_profile"] = profile
        else:
            item["openalex_profile"] = None
        roster_by_dept.setdefault(item["dept_key"], []).append(item)

    oa_by_dept: dict[str, list[dict[str, Any]]] = {}
    for item in oa_items:
        item.update(subfield_by_author.get(item["AuthorID"], {}))
        item["career_institutions"] = inst_by_author.get(item["AuthorID"], [])
        item["recent_publications"] = recent_by_dept_author.get(
            (item["dept_key"], item["AuthorID"]), []
        )
        oa_by_dept.setdefault(item["dept_key"], []).append(item)

    departments = []
    for row in dicts(summary_rows, summary_cols):
        key = row["dept_key"]
        row["bleemer_roster"] = roster_by_dept.get(key, [])
        row["openalex_authors"] = oa_by_dept.get(key, [])
        departments.append(row)

    return {
        "built_from": {
            "imputed_affiliations": "paper_author_edu_imputed_1940_2000.parquet",
            "author_fields": "author_field_career.parquet",
            "faculty_roster_audit": "department_audit_research_person_status.csv",
            "paper_field_predictions": "preds_e5_v1v2/preds_*.parquet",
            "paper_subfield_predictions": "preds_subfield_v1/preds_*.parquet",
        },
        "defaults": {
            "min_papers": 5,
            "field_probability": 0.5,
            "min_roster_department_years": 1,
        },
        "departments": departments,
    }


def main() -> None:
    args = parse_args()
    data = build_data(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dept_dir = args.output.parent / "departments"
    dept_dir.mkdir(parents=True, exist_ok=True)

    metadata_departments = []
    for dept in data["departments"]:
        key = dept["dept_key"]
        file_name = f"{key}.json"
        dept_payload = {
            "built_from": data["built_from"],
            "defaults": data["defaults"],
            "department": dept,
        }
        (dept_dir / file_name).write_text(
            json.dumps(dept_payload, ensure_ascii=True, separators=(",", ":"))
        )
        meta = dict(dept)
        meta.pop("openalex_authors", None)
        meta["data_file"] = f"departments/{file_name}"
        metadata_departments.append(meta)

    metadata = dict(data)
    metadata["departments"] = metadata_departments
    args.output.write_text(json.dumps(metadata, ensure_ascii=True, separators=(",", ":")))
    print(f"Wrote {args.output}")
    print(f"Wrote per-department data to {dept_dir}")
    print(
        "Departments: "
        + ", ".join(d["dept_key"] for d in data["departments"])
    )


if __name__ == "__main__":
    main()
