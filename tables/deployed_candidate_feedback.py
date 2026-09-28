"""
Registration file for `deployed_candidate_feedback_scoped`.
Satellite table, RBAC-scoped via join to deployed_candidates.
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidate_feedback_scoped",
    description="""
Table: deployed_candidate_feedback_scoped
(RBAC-scoped via join to deployed_candidates internally.)

PURPOSE: client-provided performance feedback for a deployed candidate
-- one row per candidate (not one per review cycle, based on the
schema having no date/cycle column of its own beyond feedback_updated_at).

Columns:
- id (int, PK), deployed_candidate_id (int) -- JOIN KEY, same pattern:
  JOIN deployed_candidates_masked_scoped ON
  deployed_candidate_id = deployed_candidates_masked_scoped.id
- client_rating (decimal) -- numeric rating. Exact scale (e.g. 0-5)
  not yet confirmed against real data (this snapshot has no populated
  rows to check) -- do not assume a specific scale when phrasing an
  answer; report the raw number and let the person interpret it, or
  ask if the scale genuinely matters to the question.
- client_feedback (text) -- free-form feedback text.
- improvement_areas (text) -- comma-separated list (same convention as
  account_managers elsewhere: multiple values in one text column).
- feedback_updated_at, feedback_updated_by

Notes for writing SQL:
- Always use table name `deployed_candidate_feedback_scoped`.
- This is candidate performance/HR-adjacent content -- present ratings
  and feedback text plainly and factually; don't editorialize or add
  interpretation beyond what the data says.
- Never write SELECT *.
""".strip(),
    examples=(
        Example(
            question="What is the average client rating for my candidates?",
            sql=(
                "SELECT AVG(fb.client_rating) AS avg_rating, COUNT(*) AS rated_count "
                "FROM deployed_candidate_feedback_scoped fb "
                "JOIN deployed_candidates_masked_scoped dc ON fb.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 AND fb.client_rating IS NOT NULL"
            ),
        ),
        Example(
            question="Show me feedback for candidates at Accenture",
            sql=(
                "SELECT dc.candidate_name, fb.client_rating, fb.client_feedback "
                "FROM deployed_candidate_feedback_scoped fb "
                "JOIN deployed_candidates_masked_scoped dc ON fb.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 AND dc.client = 'Accenture'"
            ),
        ),
    ),
)