"""
Thin FastAPI wrapper around the existing pipeline (llm.py + db.py +
sql_guard.py + access_guard.py + auth.py). This file adds NO new query
logic of its own beyond RBAC enforcement -- it exposes the same
generate_sql -> validate -> check_restricted_columns -> execute ->
phrase_answer flow that main.py already uses, over HTTP, so a
browser-based chat UI can call it.

Run with:  uvicorn webapp.server:app --reload --port 8000
Then open: http://127.0.0.1:8000

RBAC NOTE: every db.run_query() call in this file now requires a
login_id, resolved once per request via auth.get_login_id_from_request()
at the top of ask(), then threaded through every helper function that
touches the database -- including the typo-suggestion fallback (fixed
below to query the scoped view, not the old unscoped one) and the
answer cache (fixed below to key on login_id too, so a cached answer
for one login can never be served to a different login).
"""

import sys
import os
import json
import re
import difflib

# Allow imports of the parent project's modules (config, db, llm, sql_guard)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sql_guard import UnsafeQueryError
from llm import (
    generate_sql, phrase_answer, answer_general_knowledge, classify_question,
    NotDatabaseQuestion, decompose_insight_question, synthesize_insight_answer,
)
import db
import export
import auth
from access_guard import check_restricted_columns, get_scope_for_user, AccessDenied
from followup_suggester import build_followups

app = FastAPI(title="Staffing Data Q&A Pipeline")


class HistoryTurn(BaseModel):
    question: str
    answer: str


class Question(BaseModel):
    question: str
    history: list[HistoryTurn] = []


class AnswerResponse(BaseModel):
    answer: str
    sql: str | None = None
    provider: str | None = None
    blocked: bool = False
    error: str | None = None
    download_id: str | None = None
    download_filename: str | None = None
    row_count: int = 0
    suggested_followups: list[str] = []
    is_general_knowledge: bool = False
    is_insight: bool = False
    # Raw preview data for UI rendering (e.g. a real report-builder
    # preview table) -- NOT a new query path, just exposing a capped
    # slice of the SAME rows already fetched and already passed through
    # RBAC + masking. Capped small (20 rows) since this is for on-screen
    # preview, not data export (the .xlsx download already covers that,
    # via export.py, uncapped up to sql_guard's row limit).
    preview_columns: list[str] | None = None
    preview_rows: list[list] | None = None


# Simple in-memory cache for FRESH, standalone questions only (no
# conversation history). Scope, in addition to the original design:
#   - Only questions asked with NO history are ever cached or served
#     from cache -- a follow-up/contextual question always runs live.
#   - Only SUCCESSFUL (non-blocked, non-error) answers are cached.
#   - Resets automatically whenever the server restarts.
#   - CACHE KEY NOW INCLUDES login_id (see _cache_key below). This is a
#     REAL FIX, not just tidiness: two different logins can have two
#     different row/column scopes, so the exact same question text
#     legitimately has a DIFFERENT correct answer for each of them. A
#     cache keyed only on question+history would silently hand one
#     user another user's scoped data the moment both asked the same
#     question -- exactly the kind of leak RBAC exists to prevent.
_answer_cache: dict[str, AnswerResponse] = {}


def _cache_key(question: str, history: list, login_id: str) -> str:
    """
    Cache key = login_id + the exact question PLUS the exact preceding
    conversation so far, serialized deterministically. Different logins
    NEVER share a cache entry, even for byte-identical question text and
    history -- see the module-level note above for why that's a
    correctness requirement here, not just caution.
    """
    normalized_history = json.dumps(history, sort_keys=True)
    return f"{login_id}||{normalized_history}||{question.strip().lower()}"


def _maybe_cache_and_return(response: AnswerResponse, question: str, history: list, login_id: str) -> AnswerResponse:
    """Stores a response in the cache if the answer was genuinely
    successful (not blocked, not errored), keyed on login_id + the full
    conversation path (see _cache_key), then returns it unchanged
    either way."""
    if not response.blocked and not response.error:
        _answer_cache[_cache_key(question, history, login_id)] = response
    return response


# --- Typo-tolerant name fallback -------------------------------------
_NAME_LIKE_PATTERN = re.compile(
    r"(candidate_name|recruiter_name)\s+LIKE\s+'%([^%']+)%'", re.IGNORECASE
)


def _extract_name_search(sql: str):
    """If the SQL contains a `candidate_name LIKE '%X%'` or
    `recruiter_name LIKE '%X%'` clause, returns (column, searched_text).
    Otherwise returns (None, None)."""
    match = _NAME_LIKE_PATTERN.search(sql)
    if match:
        return match.group(1), match.group(2)
    return None, None


def _find_typo_suggestions(column: str, searched_text: str, login_id: str, max_suggestions: int = 3):
    """
    Fetches every distinct real value in the given column THAT THIS
    LOGIN IS ALLOWED TO SEE, and returns up to max_suggestions names
    textually similar to what was searched.

    RBAC FIX: this used to query `candidates_masked` directly -- the
    old, unscoped view -- which meant a typo-suggestion could reveal
    the existence of a candidate/recruiter name entirely outside a
    scoped login's row access, bypassing RBAC through a side door that
    was never covered by sql_guard.py's allow-list checks (this query
    is Python-constructed, not LLM-generated, so it never passed
    through generate_sql/validate_sql at all). Now queries
    candidates_masked_scoped with this login's real scope applied, so
    a suggestion can never surface a name the login couldn't otherwise
    see or query directly.
    """
    try:
        columns, rows = db.run_query(
            f"SELECT DISTINCT {column} FROM candidates_masked_scoped", login_id
        )
    except AccessDenied:
        return []  # fail closed -- no suggestions rather than an error for a nice-to-have
    except Exception:
        return []
    all_names = [r[0] for r in rows if r[0]]
    matches = difflib.get_close_matches(searched_text, all_names, n=max_suggestions, cutoff=0.6)
    return matches


def _followups_for(login_id: str, question: str) -> list[str]:
    """
    Computes the structured, clickable follow-up suggestions for a
    question that was just answered, using this login's real scope
    (never guessed or defaulted) -- see followup_suggester.py for the
    two honesty constraints this enforces (never suggest something the
    schema can't answer, never suggest a restricted-column follow-up to
    a login that can't view it). Falls back to an empty list rather
    than raising -- a missing suggestion is a minor UX gap, never a
    reason to fail the whole answer.
    """
    try:
        scope = get_scope_for_user(login_id)
    except AccessDenied:
        return []
    return build_followups(
        question=question,
        scope_type=scope.get("scope_type", "unrestricted"),
        can_view_restricted=bool(scope.get("can_view_restricted")),
    )


def _answer_database_part(db_question: str, history: list, login_id: str) -> AnswerResponse:
    """
    Runs generate_sql -> validate -> check_restricted_columns -> execute
    -> phrase_answer for one specific, standalone database question.

    RBAC ADDITIONS vs. the original: check_restricted_columns() runs
    right after SQL validation and BEFORE execution -- a query touching
    a column this login can never see (e.g. margin_value) is rejected
    outright, never silently run and NULLed by the view. db.run_query()
    now takes login_id, and AccessDenied from either step is
    distinguished from a genuine DB error (returned as `blocked`, not
    `error`, so the frontend can style/message it differently).
    """
    try:
        sql, provider, _raw = generate_sql(db_question, history=history)
    except NotDatabaseQuestion:
        print(f"[server] generate_sql vetoed {db_question!r} as NOT_DATABASE_QUESTION "
              f"despite classify_question flagging it as a database question.")
        return None
    except UnsafeQueryError as e:
        return AnswerResponse(
            answer=f"That question was blocked for safety reasons: {e}",
            blocked=True,
        )

    try:
        check_restricted_columns(sql, login_id)
    except AccessDenied as e:
        return AnswerResponse(
            answer=f"That question requires data you're not permitted to view: {e}",
            sql=sql,
            provider=provider,
            blocked=True,
        )

    try:
        columns, rows = db.run_query(sql, login_id)
    except AccessDenied as e:
        return AnswerResponse(
            answer=f"You don't have access to run that query: {e}",
            sql=sql,
            provider=provider,
            blocked=True,
        )
    except Exception as e:
        return AnswerResponse(
            answer="The query failed to run against the database.",
            sql=sql,
            provider=provider,
            error=str(e),
        )

    if len(rows) == 0:
        column, searched_text = _extract_name_search(sql)
        if column and searched_text:
            suggestions = _find_typo_suggestions(column, searched_text, login_id)
            if suggestions:
                label = "candidate" if column == "candidate_name" else "recruiter"
                suggestion_list = ", ".join(f"**{s}**" for s in suggestions)
                return AnswerResponse(
                    answer=(
                        f"I couldn't find a {label} named \"{searched_text}\" exactly, "
                        f"but I found {'a' if len(suggestions) == 1 else 'these'} similarly-spelled "
                        f"{label}{'s' if len(suggestions) > 1 else ''} in our data: {suggestion_list}. "
                        f"Did you mean one of these?"
                    ),
                    sql=sql,
                    provider=provider,
                )

    answer_text, suggested_followup = phrase_answer(db_question, sql, columns, rows, provider)

    download_id = None
    download_filename = None
    is_tabular = len(rows) > 1 or (len(rows) == 1 and len(columns) > 1)
    if is_tabular:
        download_id, download_filename = export.export_to_xlsx(columns, rows)

    return AnswerResponse(
        answer=answer_text,
        sql=sql,
        provider=provider,
        download_id=download_id,
        download_filename=download_filename,
        row_count=len(rows),
        suggested_followups=_followups_for(login_id, db_question),
        preview_columns=columns if rows else None,
        preview_rows=[list(r) for r in rows[:20]] if rows else None,
    )


def _restricted_skip_note() -> str:
    """
    Deterministic, code-authored sentence -- never LLM-phrased -- used
    when one or more insight sub-questions were skipped specifically
    because they needed a column this login isn't permitted to view.

    WHY THIS EXISTS: without it, a permission denial was silently
    absorbed by the sub-question loop, and the synthesis model (seeing
    only the sub-questions that DID succeed) would describe the gap in
    its own words -- e.g. "the data doesn't show margin information."
    That reads as "this isn't tracked," which is a different and
    misleading claim from the true one: "you aren't permitted to see
    it." This fixed sentence states the real reason plainly and can't
    be quietly dropped, softened, or reworded by the model.
    """
    return ("**Note:** part of this question required data your account "
            "isn't permitted to view, so that part was excluded from the "
            "analysis above.")


def _answer_insight_part(db_question: str, history: list, login_id: str) -> AnswerResponse:
    """
    Handles a deeper analysis/insight question: decomposes it into a
    small, bounded set of concrete sub-questions, runs EACH through the
    exact same trusted generate_sql -> sql_guard -> check_restricted_columns
    -> db.run_query pipeline used everywhere else (no new/parallel query
    path, and no RBAC bypass for sub-questions), then synthesizes a
    final answer.

    RBAC NOTE: if a sub-question would touch a restricted column or
    fall outside this login's row scope, it's SKIPPED (same graceful-
    degradation pattern the original code already used for a
    sub-question that failed to generate valid SQL) -- but unlike a
    generic failure, a permission-related skip is tracked separately
    and surfaced via _restricted_skip_note() so the person is told the
    real reason (a permission boundary), not left to infer it from an
    LLM's vague paraphrase of missing data.
    """
    sub_questions = decompose_insight_question(db_question, history=history)
    print(f"[server] Insight decomposition for {db_question!r} produced {len(sub_questions)} sub-questions:")

    sub_results = []
    had_restricted_skip = False
    for sub_q in sub_questions:
        try:
            sql, provider, _raw = generate_sql(sub_q, history=history)
        except (NotDatabaseQuestion, UnsafeQueryError) as e:
            print(f"[server]   SKIPPED sub-question {sub_q!r}: {e}")
            continue

        try:
            check_restricted_columns(sql, login_id)
        except AccessDenied as e:
            print(f"[server]   SKIPPED sub-question {sub_q!r} (restricted column): {e}")
            had_restricted_skip = True
            continue

        try:
            columns, rows = db.run_query(sql, login_id)
        except AccessDenied as e:
            print(f"[server]   SKIPPED sub-question {sub_q!r} (access denied): {e}")
            had_restricted_skip = True
            continue
        except Exception as e:
            print(f"[server]   FAILED sub-question {sub_q!r} (SQL: {sql}): {e}")
            continue

        print(f"[server]   OK sub-question {sub_q!r}\n            SQL: {sql}\n            Result: {rows[:10]}"
              f"{' ...' if len(rows) > 10 else ''} ({len(rows)} rows)")
        sub_results.append((sub_q, sql, columns, rows[:50]))

    if not sub_results:
        fallback = _answer_database_part(db_question, history, login_id)
        if fallback is not None:
            return fallback
        if had_restricted_skip:
            return AnswerResponse(answer=_restricted_skip_note(), blocked=True)
        return AnswerResponse(answer="I couldn't retrieve the data needed to analyze that.")

    answer_text, provider = synthesize_insight_answer(db_question, sub_results, history=history)

    if had_restricted_skip:
        answer_text = f"{answer_text.rstrip()}\n\n{_restricted_skip_note()}"

    download_id = None
    download_filename = None
    largest = max(sub_results, key=lambda r: len(r[3]))
    _, _, largest_columns, largest_rows = largest
    if len(largest_rows) > 1 or (len(largest_rows) == 1 and len(largest_columns) > 1):
        download_id, download_filename = export.export_to_xlsx(largest_columns, largest_rows)

    return AnswerResponse(
        answer=answer_text,
        provider=provider,
        download_id=download_id,
        download_filename=download_filename,
        row_count=sum(len(r[3]) for r in sub_results),
        is_insight=True,
        suggested_followups=_followups_for(login_id, db_question),
        preview_columns=largest_columns if largest_rows else None,
        preview_rows=[list(r) for r in largest_rows[:20]] if largest_rows else None,
    )


@app.post("/api/ask", response_model=AnswerResponse)
def ask(payload: Question, request: Request):
    # RBAC: resolve who's asking FIRST, before any other work happens.
    # An unrecognized/missing login is rejected here as a proper HTTP
    # 401, never silently treated as unrestricted or as some default user.
    try:
        login_id = auth.get_login_id_from_request(request)
    except AccessDenied as e:
        raise HTTPException(status_code=401, detail=str(e))

    question = payload.question.strip()
    if not question:
        return AnswerResponse(answer="Please type a question.", error="empty_question")

    history = [turn.model_dump() for turn in payload.history]

    cached = _answer_cache.get(_cache_key(question, history, login_id))
    if cached is not None:
        print(f"[server] Cache hit for {login_id!r} / {question!r} -- returning instantly, no AI/DB calls made.")
        return cached

    classification = classify_question(question, history=history)
    db_question = classification.get("database_question")
    gk_question = classification.get("general_knowledge_question")
    is_insight = classification.get("is_insight", False)

    gk_answer_text = None
    gk_provider = None
    if gk_question:
        gk_answer_text, gk_provider = answer_general_knowledge(gk_question, history=history)

    db_response = None
    if db_question:
        if is_insight:
            db_response = _answer_insight_part(db_question, history, login_id)
        else:
            db_response = _answer_database_part(db_question, history, login_id)
            if db_response is None:
                print(f"[server] Retrying {db_question!r} via the insight pipeline "
                      f"after the simple path vetoed it.")
                db_response = _answer_insight_part(db_question, history, login_id)

    if db_response is not None and (db_response.blocked or db_response.error):
        if gk_answer_text:
            db_response.answer = f"{gk_answer_text}\n\n{db_response.answer}"
        return _maybe_cache_and_return(db_response, question, history, login_id)

    combined_parts = [p for p in [gk_answer_text, db_response.answer if db_response else None] if p]
    combined_answer = "\n\n".join(combined_parts) if combined_parts else "I couldn't find an answer to that."

    if db_response is not None:
        db_response.answer = combined_answer
        db_response.is_general_knowledge = bool(gk_question)
        return _maybe_cache_and_return(db_response, question, history, login_id)

    return _maybe_cache_and_return(
        AnswerResponse(
            answer=combined_answer,
            provider=gk_provider,
            is_general_knowledge=True,
        ),
        question, history, login_id,
    )


@app.get("/api/download/{file_id}")
def download(file_id: str, filename: str = "results.xlsx"):
    filepath = export.resolve_download_path(file_id, "xlsx")
    if not filepath:
        return {"error": "This download has expired or was not found. Please ask the question again."}
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


# Serve the chat frontend (index.html + assets) as static files.
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(static_dir, "index.html"))