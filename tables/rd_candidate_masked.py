"""
Placeholder for the `rd_candidate` table (907 rows, the separate bench/
redeployment pool identified earlier). Not wired up yet -- no masked view
has been built for it, so this stays disabled.

TO ACTIVATE THIS TABLE LATER:
  1. Create the masked view in MySQL, e.g. `rd_candidate_masked`.
  2. Fill in the real column list/description below (copy the pattern
     from candidates_masked.py).
  3. Flip enabled=True.
That's it -- no other file needs to change. The table will automatically
show up in the LLM's schema context and the safety allow-list.
"""

from tables.base import TableSpec

TABLE = TableSpec(
    name="rd_candidate_masked",
    description="""
Table: rd_candidate_masked
(PLACEHOLDER -- real schema/masking not yet defined. Do not enable until
 filled in.)
""".strip(),
    enabled=False,  # <-- flip to True once the view + description above are real
)
