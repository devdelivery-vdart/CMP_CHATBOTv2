"""
Every queryable table/view in the system is registered here as a small
TableSpec object. To add a new masked view later (e.g. rd_candidate_masked,
jobs_masked, etc.), you do NOT touch sql_guard.py, config.py, or llm.py --
you just drop a new file in this `tables/` folder (see candidates_masked.py
for the pattern) and it's automatically picked up.

This is what makes the system "pluggable": the allow-list of safe tables,
and the schema text shown to the LLM, are both generated dynamically from
whatever TableSpecs are registered -- never hardcoded elsewhere.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Example:
    """One few-shot example: a real question paired with its correct SQL.
    These meaningfully improve accuracy on similar future questions --
    more so than schema description alone -- especially for resolving
    known ambiguities (e.g. which column/join is the "correct" one)."""
    question: str
    sql: str


@dataclass(frozen=True)
class TableSpec:
    name: str                         # exact table/view name in the database
    description: str                  # plain-English schema description for the LLM
    enabled: bool = True              # set False to temporarily disable a table
    examples: tuple[Example, ...] = field(default_factory=tuple)  # few-shot examples
