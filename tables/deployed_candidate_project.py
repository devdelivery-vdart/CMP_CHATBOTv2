"""
Registration file for `deployed_candidate_project_scoped`.
Satellite table, RBAC-scoped via join to deployed_candidates.
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidate_project_scoped",
    description="""
Table: deployed_candidate_project_scoped
(RBAC-scoped via join to deployed_candidates internally.)

PURPOSE: project/tech-stack detail collected from the candidate,
tracked through a submission-form workflow (sent -> completed).

Columns:
- id (int, PK), deployed_candidate_id (int) -- JOIN KEY:
  JOIN deployed_candidates_masked_scoped ON
  deployed_candidate_id = deployed_candidates_masked_scoped.id
- project_tech_stack, project_overview, project_goals,
  project_role_responsibility, key_achievement (text) -- free-form
  content describing the candidate's actual project work.
- project_experience_rating (int) -- exact scale not yet confirmed
  against real data (no populated rows in this snapshot) -- report the
  raw number rather than assuming what it's out of.
- project_info_status (text) -- one of: 'pending', 'submitted',
  'completed'. Filter on this exact set of values for "how many
  candidates have/haven't submitted their project info" questions.
- project_info_submitted_at, project_form_sent_at,
  project_form_completed_at, project_form_reminder_count,
  project_form_last_reminder_at -- form-workflow timestamps/counters.
- project_updated_at, project_updated_by

Notes for writing SQL:
- Always use table name `deployed_candidate_project_scoped`.
- Never write SELECT *.
""".strip(),
    examples=(
        Example(
            question="How many candidates haven't submitted their project info yet?",
            sql=(
                "SELECT COUNT(*) FROM deployed_candidate_project_scoped "
                "WHERE project_info_status != 'completed'"
            ),
        ),
        Example(
            question="Show me the tech stack for candidates working on Java projects",
            sql=(
                "SELECT dc.candidate_name, pj.project_tech_stack "
                "FROM deployed_candidate_project_scoped pj "
                "JOIN deployed_candidates_masked_scoped dc ON pj.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 AND pj.project_tech_stack LIKE '%Java%'"
            ),
        ),
    ),
)