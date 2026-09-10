"""
chart_builder.py

Decides whether a query result is worth rendering as a chart, and if so,
builds a plain-JSON chart spec for the frontend to draw. This runs AFTER
db.run_query() returns real rows (Step 6c in the pipeline, right after
execution and before/alongside phrase_answer) -- it is pure Python logic
over columns/rows already in hand. It makes ZERO additional LLM calls and
NEVER changes the existing text answer; it only adds an optional
`chart` key alongside it.

Design goals (see project handoff for the bug classes this guards against):
  1. Never chart a single scalar value -- only genuine multi-row comparisons.
  2. Never blend rows across incompatible units. This project has multiple
     verified bugs from averaging/summing pay_rate_numeric or margin across
     different pay_rate_currency / pay_rate_payment_basis combinations. A
     chart is just as capable of lying about this as a sentence is -- if
     the result mixes currencies/bases, either facet by them or refuse to
     chart at all, never plot them on one shared axis.
  3. Carry data-quality caveats (e.g. non-recruiter process codes like
     'PTR'/'TBD' appearing in a recruiter breakdown) through to the chart
     the same way the text answer already surfaces them, so a chart never
     looks "cleaner" or more authoritative than the prose it sits next to.
  4. Cap category counts so a chart never becomes an unreadable wall of bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


MAX_BAR_CATEGORIES = 15
MIN_ROWS_TO_CHART = 2

# Column-name signals used to decide chart shape. Matched case-insensitively
# against the columns actually returned by the query (not guessed from the
# question text) -- so this only ever reacts to real result shape.
DATE_LIKE_COLUMN_HINTS = (
    "month", "quarter", "date", "year", "period", "week",
)
CURRENCY_OR_BASIS_COLUMNS = (
    "pay_rate_currency", "client_rate_currency", "pay_rate_payment_basis",
    "client_rate_payment_basis",
)
KNOWN_NON_RECRUITER_CODES = {
    "pt", "ptr", "tbd", "na", "vendor change", "vendor consolidation",
    "redeployement", "redeployment",
}
RECRUITER_COLUMN_NAMES = {"recruiter_name", "recruiter"}


@dataclass
class ChartSpec:
    chart_type: str  # "bar" | "line"
    title: str
    x_label: str
    y_label: str
    categories: list
    series: list  # list of {"name": str, "data": [numbers]}
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.chart_type,
            "title": self.title,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "categories": self.categories,
            "series": self.series,
            "caveats": self.caveats,
        }


def _is_numeric(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float, Decimal))


def _is_date_like(value: Any) -> bool:
    return isinstance(value, (date, datetime))


def _col_index(columns: list[str], name: str) -> Optional[int]:
    lname = name.lower()
    for i, c in enumerate(columns):
        if c.lower() == lname:
            return i
    return None


def _find_date_like_column(columns: list[str]) -> Optional[int]:
    for i, c in enumerate(columns):
        lc = c.lower()
        if any(hint in lc for hint in DATE_LIKE_COLUMN_HINTS):
            return i
    return None


def _find_numeric_columns(columns: list[str], rows: list[tuple]) -> list[int]:
    numeric_idxs = []
    for i in range(len(columns)):
        if all(_is_numeric(row[i]) for row in rows if row[i] is not None):
            # at least one non-null numeric value must exist
            if any(_is_numeric(row[i]) for row in rows):
                numeric_idxs.append(i)
    return numeric_idxs


def _find_category_column(columns: list[str], rows: list[tuple], exclude: set[int]) -> Optional[int]:
    """First non-numeric, non-excluded column with a distinct value per row
    (or at least mostly distinct) -- the thing a bar chart's x-axis needs."""
    for i in range(len(columns)):
        if i in exclude:
            continue
        values = [row[i] for row in rows]
        if all(_is_numeric(v) or v is None for v in values):
            continue
        if len(set(values)) >= max(2, len(values) // 2):
            return i
    return None


def _mixed_units_present(columns: list[str], rows: list[tuple]) -> list[str]:
    """Returns which currency/basis columns actually vary across rows (the
    real trigger for the blending bug) -- an empty list means it's safe to
    plot a single shared numeric axis."""
    problems = []
    for cname in CURRENCY_OR_BASIS_COLUMNS:
        idx = _col_index(columns, cname)
        if idx is None:
            continue
        distinct = {row[idx] for row in rows if row[idx] is not None}
        if len(distinct) > 1:
            problems.append(cname)
    return problems


def _recruiter_caveat(columns: list[str], rows: list[tuple], category_idx: int) -> list[str]:
    cname = columns[category_idx].lower()
    if cname not in RECRUITER_COLUMN_NAMES:
        return []
    values = {str(row[category_idx]).strip().lower() for row in rows if row[category_idx]}
    contaminated = values & KNOWN_NON_RECRUITER_CODES
    if contaminated:
        return [
            "Note: this breakdown includes non-recruiter process codes "
            f"({', '.join(sorted(contaminated))}) alongside real recruiter names -- "
            "these represent real candidate counts, but are not tied to an individual recruiter."
        ]
    return []


def build_chart_spec(question: str, columns: list[str], rows: list[tuple]) -> Optional[dict]:
    """
    Main entry point. Returns a chart spec dict, or None if this result
    isn't (or shouldn't be) charted. Never raises -- any uncertainty about
    shape should just mean "no chart," never a broken chart.

    `question` is accepted for future use (e.g. picking a chart title) but
    deliberately NOT used to make any chartability/safety decision -- those
    decisions come only from the real columns/rows already returned by the
    database, per this project's core design philosophy of never trusting
    the AI-authored question text over verified query results.
    """
    if not rows or len(rows) < MIN_ROWS_TO_CHART or not columns:
        return None

    try:
        numeric_idxs = _find_numeric_columns(columns, rows)
        if not numeric_idxs:
            return None

        mixed = _mixed_units_present(columns, rows)
        if mixed:
            # Refuse to chart rather than silently blend incompatible units.
            # (Faceting by currency/basis is a reasonable future enhancement,
            # but the safe default -- matching this project's track record --
            # is "don't guess," same as the text-answer rules already do.)
            return None

        date_idx = _find_date_like_column(columns)
        if date_idx is not None:
            metric_idxs = [i for i in numeric_idxs if i != date_idx]
            if not metric_idxs:
                return None
            metric_idx = metric_idxs[0]

            pairs = [(row[date_idx], row[metric_idx]) for row in rows
                     if row[date_idx] is not None and row[metric_idx] is not None]
            if len(pairs) < MIN_ROWS_TO_CHART:
                return None
            pairs.sort(key=lambda p: str(p[0]))

            return ChartSpec(
                chart_type="line",
                title=columns[metric_idx].replace("_", " ").title(),
                x_label=columns[date_idx].replace("_", " ").title(),
                y_label=columns[metric_idx].replace("_", " ").title(),
                categories=[str(p[0]) for p in pairs],
                series=[{"name": columns[metric_idx].replace("_", " ").title(),
                         "data": [float(p[1]) for p in pairs]}],
            ).to_dict()

        category_idx = _find_category_column(columns, rows, exclude=set(numeric_idxs))
        if category_idx is None:
            return None
        metric_idx = numeric_idxs[0]

        pairs = [(row[category_idx], row[metric_idx]) for row in rows
                 if row[category_idx] is not None and row[metric_idx] is not None]
        if len(pairs) < MIN_ROWS_TO_CHART:
            return None

        pairs.sort(key=lambda p: p[1], reverse=True)
        truncated = len(pairs) > MAX_BAR_CATEGORIES
        pairs = pairs[:MAX_BAR_CATEGORIES]

        caveats = _recruiter_caveat(columns, rows, category_idx)
        if truncated:
            caveats.append(
                f"Showing the top {MAX_BAR_CATEGORIES} of {len(rows)} categories by value."
            )

        return ChartSpec(
            chart_type="bar",
            title=columns[metric_idx].replace("_", " ").title(),
            x_label=columns[category_idx].replace("_", " ").title(),
            y_label=columns[metric_idx].replace("_", " ").title(),
            categories=[str(p[0]) for p in pairs],
            series=[{"name": columns[metric_idx].replace("_", " ").title(),
                     "data": [float(p[1]) for p in pairs]}],
            caveats=caveats,
        ).to_dict()

    except Exception:
        # Charting is a pure bonus feature -- any unexpected shape should
        # degrade to "no chart," never break the underlying text answer.
        return None