"""
followup_suggester.py
------------------------
Structured, clickable follow-up suggestions -- this REPLACES the
current always-empty pass-through (_extract_followup_suggestion() in
llm.py, which was deliberately left as "return answer, None" pending
exactly this kind of real implementation).

Zero LLM calls, by design -- built from three cheap, deterministic
signals instead:
  1. ENTITY -- if the question just asked named a specific client
     (e.g. "candidates at NTT"), every follow-up below stays anchored
     to that SAME client. A recruiter who just asked about NTT wants
     "Active vs Inactive at NTT?" next, not a generic "my candidates"
     question that drops the context they just gave you.
  2. ROLE (scope_type) -- when no client was named, a scoped
     account-manager/recruiter/BU login's natural next question is
     about THEIR OWN candidates ("how many of MY candidates..."); an
     unrestricted/admin login can meaningfully ask company-wide
     comparison questions ("break this down by recruiter/client/BU").
  3. TOPIC of the question that was just asked -- a rolloff question
     invites different follow-ups than a margin question or a
     headcount question.

*** TWO HONESTY CONSTRAINTS THIS MODULE ENFORCES ***

1. Never suggest a follow-up this schema can't actually answer. No
   "awaiting feedback" or "interview" suggestions anywhere below --
   those columns don't exist in candidates_masked_scoped (same gap
   already flagged for metrics_builder.py's KPI card and the roll-off
   subscription discussion). A suggestion chip that leads to a wrong
   or refused answer is worse than no suggestion.

2. Never suggest a margin/client-rate/pay-rate follow-up to a scoped
   login that can't view those columns (per
   access_guard.RESTRICTED_COLUMNS_*). They'd just get refused by
   check_restricted_columns() if they clicked it -- a suggestion
   should always be something that will actually work if clicked.
"""

import re

_MARGIN_RE = re.compile(r"\bmargin\b|client.?rate", re.IGNORECASE)
_ROLLOFF_RE = re.compile(r"\broll(?:s|ing|ed)?[\s\-]?off\b", re.IGNORECASE)
_HEADCOUNT_RE = re.compile(r"\bhow many candidates\b|\btotal candidates\b|\bcandidate count\b", re.IGNORECASE)
_RECRUITER_RE = re.compile(r"\brecruiter\b", re.IGNORECASE)
_CLIENT_ENTITY_RE = re.compile(
    r"(?:for|at|with|client)\s+([A-Z][a-zA-Z0-9&.\-]*(?:\s+[A-Z][a-zA-Z0-9&.\-]*)*)"
)


def _extract_client(question: str) -> str | None:
    m = _CLIENT_ENTITY_RE.search(question)
    return m.group(1).strip() if m else None


def _pay_or_safe_alt(client: str, is_scoped: bool, can_view_restricted: bool) -> str:
    """
    A pay-rate follow-up is only ever safe to suggest if the login can
    actually view it -- otherwise swap in a different client-anchored
    suggestion that will actually work if clicked (constraint #2).
    """
    if not is_scoped or can_view_restricted:
        return f"What's the average pay rate at {client}?"
    return f"Show candidates ending soon at {client}"


def build_followups(
    question: str,
    scope_type: str,
    can_view_restricted: bool,
    answer_summary: str = "",  # accepted for compatibility with callers that
                                # pass it; not currently used as a signal here
    limit: int = 3,
) -> list[str]:
    """
    Returns up to `limit` follow-up question strings, tailored to
    `scope_type` ("unrestricted" | "account_manager" | "recruiter" |
    "bu") and the topic of `question` (the one that was just asked and
    answered). If `question` named a specific client, every suggestion
    below stays anchored to that same client rather than drifting to a
    generic "my candidates" phrasing.
    """
    is_scoped = scope_type != "unrestricted"
    client = _extract_client(question)
    suggestions: list[str] = []

    if _MARGIN_RE.search(question):
        # Only offer margin follow-ups to a login that can actually
        # view margin at all -- otherwise offer NOTHING for this topic
        # rather than a suggestion guaranteed to be refused.
        if not is_scoped or can_view_restricted:
            if client:
                suggestions.append(f"Which recruiter has the most candidates at {client}?")
                suggestions.append(f"What's the average pay rate at {client}?")
            else:
                suggestions.append("Break this down by business unit")
                suggestions.append("Which clients have the lowest margin?")

    elif _ROLLOFF_RE.search(question):
        if client:
            suggestions.append(f"How many candidates are rolling off at {client} in the next 60 days?")
            suggestions.append(f"How many are Active vs Inactive at {client}?")
        elif is_scoped:
            suggestions.append("Show my roll-offs in the next 60 days")
            suggestions.append("How many of my candidates are currently active?")
        else:
            suggestions.append("Break this down by business unit")
            suggestions.append("Show only the unexpected roll-offs")

    elif _RECRUITER_RE.search(question):
        if client:
            suggestions.append(f"How many are Active vs Inactive at {client}?")
            suggestions.append(f"Compare recruiters' candidate counts at {client}")
        else:
            suggestions.append("Compare this with last month")
            if not is_scoped:
                suggestions.append("Show this recruiter's Active vs Inactive split")

    elif _HEADCOUNT_RE.search(question):
        if client:
            # Stay anchored to the SAME client for every follow-up here --
            # this is what a recruiter/AM who just asked about one client
            # actually asks next: count -> Active/Inactive split -> avg pay.
            suggestions.append(f"How many are Active vs Inactive at {client}?")
            suggestions.append(_pay_or_safe_alt(client, is_scoped, can_view_restricted))
            if not is_scoped:
                suggestions.append(f"Break down {client} by recruiter")
        elif is_scoped:
            suggestions.append("How many of my candidates are Active vs Inactive?")
            suggestions.append("Show my candidates rolling off in the next 30 days")
        else:
            suggestions.append("Break this down by recruiter")
            suggestions.append("Break this down by client")

    # Entity-aware addition, if a client was mentioned and isn't
    # already covered by a topic-specific suggestion above (e.g. a
    # topic branch above matched but didn't fire the client path for
    # some reason, or fewer than `limit` suggestions were produced)
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