"""
followup_suggester.py
------------------------
Structured, clickable follow-up suggestions -- this REPLACES the
current always-empty pass-through (_extract_followup_suggestion() in
llm.py, which was deliberately left as "return answer, None" pending
exactly this kind of real implementation).

Zero LLM calls, by design -- built from two cheap, deterministic
signals instead:
  1. ROLE (scope_type) -- a scoped account-manager/recruiter/BU login's
     natural next question is about THEIR OWN candidates ("how many of
     MY candidates..."); an unrestricted/admin login can meaningfully
     ask company-wide comparison questions ("break this down by
     recruiter/client/BU").
  2. TOPIC of the question that was just asked -- a rolloff question
     invites different follow-ups than a margin question or a
     headcount question.

*** TWO HONESTY CONSTRAINTS THIS MODULE ENFORCES ***

1. Never suggest a follow-up this schema can't actually answer. No
   "awaiting feedback" or "interview" suggestions anywhere below --
   those columns don't exist in candidates_masked_scoped (same gap
   already flagged for metrics_builder.py's KPI card and the roll-off
   subscription discussion). A suggestion chip that leads to a wrong
   or refused answer is worse than no suggestion.

2. Never suggest a margin/client-rate follow-up to a scoped login that
   can't view those columns (per access_guard.RESTRICTED_COLUMNS_*).
   They'd just get refused by check_restricted_columns() if they
   clicked it -- a suggestion should always be something that will
   actually work if clicked.
"""

import re

_MARGIN_RE = re.compile(r"\bmargin\b|client.?rate", re.IGNORECASE)
_ROLLOFF_RE = re.compile(r"\broll.?off", re.IGNORECASE)
_HEADCOUNT_RE = re.compile(r"\bhow many candidates\b|\btotal candidates\b|\bcandidate count\b", re.IGNORECASE)
_RECRUITER_RE = re.compile(r"\brecruiter\b", re.IGNORECASE)
_CLIENT_ENTITY_RE = re.compile(
    r"(?:for|at|with|client)\s+([A-Z][a-zA-Z0-9&.\-]*(?:\s+[A-Z][a-zA-Z0-9&.\-]*)*)"
)


def _extract_client(question: str) -> str | None:
    m = _CLIENT_ENTITY_RE.search(question)
    return m.group(1).strip() if m else None


def build_followups(
    question: str,
    scope_type: str,
    can_view_restricted: bool,
    limit: int = 3,
) -> list[str]:
    """
    Returns up to `limit` follow-up question strings, tailored to
    `scope_type` ("unrestricted" | "account_manager" | "recruiter" |
    "bu") and the topic of `question` (the one that was just asked and
    answered).
    """
    is_scoped = scope_type != "unrestricted"
    client = _extract_client(question)
    suggestions: list[str] = []

    if _MARGIN_RE.search(question):
        # Only offer margin follow-ups to a login that can actually
        # view margin at all -- otherwise offer NOTHING for this topic
        # rather than a suggestion guaranteed to be refused.
        if not is_scoped or can_view_restricted:
            suggestions.append("Break this down by business unit")
            if client:
                suggestions.append(f"Which recruiter has the most candidates at {client}?")
            else:
                suggestions.append("Which clients have the lowest margin?")

    elif _ROLLOFF_RE.search(question):
        if is_scoped:
            suggestions.append("Show my roll-offs in the next 60 days")
            suggestions.append("How many of my candidates are currently active?")
        else:
            suggestions.append("Break this down by business unit")
            suggestions.append("Show only the unexpected roll-offs")

    elif _RECRUITER_RE.search(question):
        suggestions.append("Compare this with last month")
        if not is_scoped:
            suggestions.append("Show this recruiter's Active vs Inactive split")

    elif _HEADCOUNT_RE.search(question):
        if client:
            suggestions.append(f"How many candidates were submitted at {client} this month?")
        if is_scoped:
            suggestions.append("How many of my candidates are Active vs Inactive?")
            suggestions.append("Show my candidates rolling off in the next 30 days")
        else:
            suggestions.append("Break this down by recruiter")
            suggestions.append("Break this down by client")

    # Entity-aware addition, if a client was mentioned and isn't
    # already covered by a topic-specific suggestion above
    if client and not any(client in s for s in suggestions):
        suggestions.append(f"Show candidates ending soon at {client}")

    # Generic role-based fallback if nothing topic-specific matched at all
    if not suggestions:
        if is_scoped:
            suggestions = [
                "How many of my candidates are Active right now?",
                "Show my candidates rolling off in the next 30 days",
            ]
        else:
            suggestions = [
                "Break this down by recruiter",
                "Break this down by client",
            ]

    return suggestions[:limit]