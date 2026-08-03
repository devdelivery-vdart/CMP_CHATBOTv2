"""
Thin FastAPI wrapper around the existing pipeline (llm.py + db.py +
sql_guard.py). This file adds NO new logic of its own -- it just exposes
the same generate_sql -> validate -> execute -> phrase_answer flow that
main.py already uses, over HTTP, so a browser-based chat UI can call it.

Run with:  uvicorn webapp.server:app --reload --port 8000
Then open: http://127.0.0.1:8000
"""

import sys
import os
import json
import re
import difflib

# Allow imports of the parent project's modules (config, db, llm, sql_guard)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
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
    suggested_followup: str | None = None
    is_general_knowledge: bool = False
    is_insight: bool = False


# Simple in-memory cache for FRESH, standalone questions only (no
# conversation history). This is intentionally narrow in scope:
#   - Only questions asked with NO history are ever cached or served
#     from cache -- a follow-up/contextual question always runs live,
#     so a cached answer can never be wrong due to missing context.
#   - Only SUCCESSFUL (non-blocked, non-error) answers are cached --
#     a transient failure is never "stuck" as a cached result.
#   - Resets automatically whenever the server restarts (plain
#     in-memory dict, no persistence) -- if the underlying data
#     changes, just restart the server to clear stale cached answers.
# Practical use: rehearsing a fixed set of demo questions once, then
# asking the exact same questions again live returns instantly, with
# no AI/database latency at all on the repeat.
_answer_cache: dict[str, AnswerResponse] = {}


def _cache_key(question: str, history: list) -> str:
    """
    Cache key = the exact question PLUS the exact preceding conversation
    so far, serialized deterministically. This means caching now works
    for an ENTIRE rehearsed multi-question conversation, not just a
    single first message with no history -- if you rehearse a full
    script once and then replay the SAME sequence of questions in the
    SAME order live, every step matches its rehearsed counterpart and
    returns instantly.
    The tradeoff, by design: this only matches if the conversation SO
    FAR is character-for-character identical to something seen before --
    any deviation (different wording, different order, an improvised
    question) means that step (and anything after it, since its history
    differs from that point on) is never served from cache, and runs
    live instead. This is intentional -- it guarantees a cached answer
    can never be served for a genuinely different conversational
    context.
    """
    normalized_history = json.dumps(history, sort_keys=True)
    return f"{normalized_history}||{question.strip().lower()}"


def _maybe_cache_and_return(response: AnswerResponse, question: str, history: list) -> AnswerResponse:
    """Stores a response in the cache if the answer was genuinely
    successful (not blocked, not errored) -- keyed on the full
    conversation path (see _cache_key), then returns it unchanged
    either way."""
    if not response.blocked and not response.error:
        _answer_cache[_cache_key(question, history)] = response
    return response


# --- Typo-tolerant name fallback -------------------------------------
# LIKE '%name%' (already built into the schema notes) handles missing
# words, extra spaces, and partial names -- but NOT genuine spelling
# mistakes (wrong/transposed letters). This adds a real, deterministic
# fallback using Python's built-in difflib: if a candidate_name or
# recruiter_name search returns zero rows, compare the searched term
# against every real name in that column and suggest close matches --
# never silently guesses, same principle as the existing disambiguation
# behavior for genuine duplicate-name matches.

_NAME_LIKE_PATTERN = re.compile(
    r"(candidate_name|recruiter_name)\s+LIKE\s+'%([^%']+)%'", re.IGNORECASE
)


def _extract_name_search(sql: str):
    """If the SQL contains a `candidate_name LIKE '%X%'` or
    `recruiter_name LIKE '%X%'` clause, returns (column, searched_text).
    Otherwise returns (None, None). Deliberately simple/conservative --
    only fires for this one well-defined, common pattern."""
    match = _NAME_LIKE_PATTERN.search(sql)
    if match:
        return match.group(1), match.group(2)
    return None, None


def _find_typo_suggestions(column: str, searched_text: str, max_suggestions: int = 3):
    """Fetches every distinct real value in the given column and returns
    up to max_suggestions names that are textually SIMILAR (via
    difflib's standard similarity ratio) to what was searched -- this is
    what catches genuine typos (e.g. 'Adapla' -> 'Adapala'), which a
    plain LIKE '%...%' cannot do since it requires an exact substring."""
    try:
        columns, rows = db.run_query(f"SELECT DISTINCT {column} FROM candidates_masked")
    except Exception:
        return []
    all_names = [r[0] for r in rows if r[0]]
    matches = difflib.get_close_matches(searched_text, all_names, n=max_suggestions, cutoff=0.6)
    return matches


def _answer_database_part(db_question: str, history: list) -> AnswerResponse:
    """Runs the existing, unchanged generate_sql -> validate -> execute ->
    phrase_answer pipeline for one specific, standalone database
    question. Exactly the same logic as before -- just factored out so
    it can be called for either a whole message or just the database
    half of a compound one."""
    try:
        sql, provider, _raw = generate_sql(db_question, history=history)
    except NotDatabaseQuestion:
        # The classifier thought there was a database part, but the SQL
        # generator itself disagrees (e.g. the question needs analysis/
        # recommendation, not a single fact) -- treat as if there wasn't
        # one at this level. Logged so this path is never silently
        # invisible -- the caller (ask()) uses this signal to retry via
        # the insight pipeline before giving up entirely.
        print(f"[server] generate_sql vetoed {db_question!r} as NOT_DATABASE_QUESTION "
              f"despite classify_question flagging it as a database question.")
        return None
    except UnsafeQueryError as e:
        return AnswerResponse(
            answer=f"That question was blocked for safety reasons: {e}",
            blocked=True,
        )

    try:
        columns, rows = db.run_query(sql)
    except Exception as e:
        return AnswerResponse(
            answer="The query failed to run against the database.",
            sql=sql,
            provider=provider,
            error=str(e),
        )

    # TYPO-TOLERANCE FALLBACK: if this was a candidate/recruiter name
    # search and it genuinely found nothing, check whether the searched
    # text is a close typo of a REAL name in the data -- catches actual
    # spelling mistakes that a plain LIKE '%...%' cannot (e.g. "Adapla"
    # vs the real "Adapala"). Never silently substitutes a guess --
    # only ever suggests and asks, same as the existing disambiguation
    # behavior for genuine duplicate names.
    if len(rows) == 0:
        column, searched_text = _extract_name_search(sql)
        if column and searched_text:
            suggestions = _find_typo_suggestions(column, searched_text)
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
        suggested_followup=suggested_followup,
    )


def _answer_insight_part(db_question: str, history: list) -> AnswerResponse:
    """
    Handles a deeper analysis/insight question: decomposes it into a
    small, bounded set of concrete sub-questions, runs EACH through the
    exact same trusted generate_sql -> sql_guard -> db.run_query
    pipeline used everywhere else (no new/parallel query path), then
    synthesizes a final answer that keeps data-grounded findings
    strictly separate from any general (non-data) suggestions.

    If every sub-question fails to produce a usable query (rare), falls
    back to the plain single-query pipeline on the original question
    rather than returning nothing.
    """
    sub_questions = decompose_insight_question(db_question, history=history)
    print(f"[server] Insight decomposition for {db_question!r} produced {len(sub_questions)} sub-questions:")

    sub_results = []
    any_blocked = False
    for sub_q in sub_questions:
        try:
            sql, provider, _raw = generate_sql(sub_q, history=history)
        except (NotDatabaseQuestion, UnsafeQueryError) as e:
            print(f"[server]   SKIPPED sub-question {sub_q!r}: {e}")
            continue  # skip this sub-question, keep going with the others
        try:
            columns, rows = db.run_query(sql)
        except Exception as e:
            print(f"[server]   FAILED sub-question {sub_q!r} (SQL: {sql}): {e}")
            continue  # skip a sub-question whose query failed to execute
        print(f"[server]   OK sub-question {sub_q!r}\n            SQL: {sql}\n            Result: {rows[:10]}"
              f"{' ...' if len(rows) > 10 else ''} ({len(rows)} rows)")
        sub_results.append((sub_q, sql, columns, rows[:50]))  # cap rows per sub-result

    if not sub_results:
        # Every sub-question failed -- degrade gracefully to a plain
        # single-query attempt on the original question rather than
        # returning nothing.
        fallback = _answer_database_part(db_question, history)
        return fallback if fallback is not None else AnswerResponse(
            answer="I couldn't retrieve the data needed to analyze that.",
        )

    answer_text, provider = synthesize_insight_answer(db_question, sub_results, history=history)

    # Offer a download of the combined sub-question results as separate
    # sheets would be ideal, but for a first version we keep this simple:
    # export the largest/most detailed sub-result table, since that's
    # usually the most useful one to take away.
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
    )


@app.post("/api/ask", response_model=AnswerResponse)
def ask(payload: Question):
    question = payload.question.strip()
    if not question:
        return AnswerResponse(answer="Please type a question.", error="empty_question")

    history = [turn.model_dump() for turn in payload.history]

    # CACHE CHECK: keyed on the exact question PLUS the exact
    # conversation so far -- works at ANY point in a rehearsed,
    # scripted conversation replayed in the same order, not just the
    # very first message. Any deviation in wording, order, or an
    # improvised question simply misses the cache and runs live.
    cached = _answer_cache.get(_cache_key(question, history))
    if cached is not None:
        print(f"[server] Cache hit for {question!r} (at this point in the conversation) "
              f"-- returning instantly, no AI/DB calls made.")
        return cached

    # Step 1: classify the message -- it may be entirely a database
    # question, entirely general knowledge, or a mix of both. Each part
    # (if present) is answered through its own dedicated, independent
    # pipeline below -- this is what prevents a compound question (e.g.
    # "what is Accenture, and how many candidates do we have with them")
    # from ever producing a fabricated database number, since the
    # database part always goes through the real, unchanged
    # generate_sql -> execute pipeline on its own.
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
            db_response = _answer_insight_part(db_question, history)
        else:
            db_response = _answer_database_part(db_question, history)
            if db_response is None:
                # The simple single-query path just vetoed this question
                # as NOT_DATABASE_QUESTION -- that's itself a signal it
                # likely needed deeper analysis (a single SQL query
                # genuinely can't express "how do I reduce X"), even
                # though the classifier didn't flag it as insight. Retry
                # via the insight pipeline before giving up entirely,
                # rather than dead-ending on a misclassification.
                print(f"[server] Retrying {db_question!r} via the insight pipeline "
                      f"after the simple path vetoed it.")
                db_response = _answer_insight_part(db_question, history)

    # If the DB part turned out blocked/errored, surface that clearly --
    # don't silently swallow it just because a general-knowledge part
    # also succeeded.
    if db_response is not None and (db_response.blocked or db_response.error):
        if gk_answer_text:
            db_response.answer = f"{gk_answer_text}\n\n{db_response.answer}"
        return _maybe_cache_and_return(db_response, question, history)

    # Combine whichever parts actually ran into one final answer.
    combined_parts = [p for p in [gk_answer_text, db_response.answer if db_response else None] if p]
    combined_answer = "\n\n".join(combined_parts) if combined_parts else "I couldn't find an answer to that."

    if db_response is not None:
        db_response.answer = combined_answer
        db_response.is_general_knowledge = bool(gk_question)
        return _maybe_cache_and_return(db_response, question, history)

    # Pure general-knowledge message, no database part at all.
    return _maybe_cache_and_return(
        AnswerResponse(
            answer=combined_answer,
            provider=gk_provider,
            is_general_knowledge=True,
        ),
        question, history,
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