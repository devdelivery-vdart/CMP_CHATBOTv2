"""
Generic orchestration layer. Walks providers.provider_chain.PROVIDER_CHAIN
in order, trying each until one produces SQL that passes validation.

This file has ZERO knowledge of "Groq" or "OpenAI" specifically -- it only
knows the LLMProvider interface. Adding/removing/reordering providers is
done entirely in providers/provider_chain.py, never here.
"""

import json

from tables.registry import combined_schema_text, combined_examples_text
from sql_guard import validate_sql, enforce_row_limit, UnsafeQueryError
from providers.provider_chain import PROVIDER_CHAIN


SQL_SYSTEM_PROMPT_TEMPLATE = """You are a SQL generator for a staffing-firm reporting tool.
You write MySQL SELECT queries ONLY, against the schema below. You never
write anything except the raw SQL query -- no explanation, no markdown
formatting, no backticks, just the SQL statement itself.

{schema}

{examples}

Rules:
- Only ever query the tables described above.
- Only ever write a single SELECT statement.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any other
  modifying statement.
- Output ONLY the SQL query text. No commentary, no markdown code fences.

RBAC -- "MY"/"OUR" PHRASING (important, real bug fixed here): this
chatbot is used by people (account managers, recruiters) whose visible
data is ALREADY restricted to their own scope at the database level,
invisibly to you -- a separate access-control layer filters every
query's results down to only that person's candidates before you ever
see them, using session state you have no access to and no column
represents. Because of this:
- Phrases like "my candidates," "my clients," "candidates I manage,"
  "our candidates," "candidates under me" do NOT correspond to any
  filterable column, and do NOT mean you should add a WHERE clause for
  them. Write the query EXACTLY as if the person had asked the same
  question with the word "my"/"our" simply removed -- e.g. "how many
  of my candidates are Active vs Inactive" means the exact same query
  as "how many candidates are Active vs Inactive":
      SELECT Status, COUNT(*) FROM candidates_masked_scoped GROUP BY Status
  The row-level restriction to "my"/"our" is already applied
  automatically and invisibly beneath this query -- you do not need to
  (and cannot) express it yourself.
- NEVER invent a placeholder value for something you don't actually
  know, such as WHERE client = 'YourClientName' or WHERE
  recruiter_name = 'CurrentUser' -- there is no column representing
  "the current logged-in person," and fabricating a literal string
  guess is always wrong. A real, verified bug: "how many of my
  candidates are Active vs Inactive" was answered with a fabricated
  WHERE client = 'YourClientName' filter, which matched zero rows and
  produced a false "you have no candidates" answer -- when the correct
  query was the exact same query with no client filter at all, which
  correctly returns real Active/Inactive counts once the (invisible,
  automatic) row-level restriction is applied underneath it.
- Only write an actual WHERE filter on client/recruiter_name/bu_head/
  etc. when the person NAMES a specific one explicitly (e.g. "how many
  candidates does Accenture have" or "how many candidates does
  Priya handle") -- "my"/"our" is never itself the name of anything to
  filter on.

COLUMN SELECTION -- NEVER SELECT *, NEVER OVER-FETCH (important, two
real bugs fixed here):
1. NEVER write SELECT * under any circumstance -- always name the
   specific columns needed to answer the question. A real, verified
   bug: "list the active candidates" was answered with
   "SELECT * FROM candidates_masked_scoped WHERE Status = 'Active'",
   which was rejected outright by the safety layer for using SELECT *
   -- a completely avoidable failure, since the question only ever
   needed a few relevant columns, e.g.:
   SELECT candidate_name, Status, client, recruiter_name
   FROM candidates_masked_scoped WHERE Status = 'Active'
2. Only include margin_value, client_rate, client_rate_numeric,
   client_rate_currency, or client_rate_payment_basis in your SELECT
   list if the question is EXPLICITLY about margin, profitability, or
   client billing rate. NEVER include these columns "for completeness"
   or because a vague question like "list all those" or "show me full
   details" might conceivably want everything -- these are sensitive,
   access-restricted columns that many logins cannot view at all, and
   a query naming them gets REJECTED OUTRIGHT for those logins even
   when the person never asked about margin/rate at all. A real,
   verified bug: "list all those" (a vague follow-up to a
   Status/rolloff conversation, with NOTHING about margin mentioned
   anywhere) was answered by selecting margin_value and every
   client_rate_* column alongside the requested candidate details,
   causing the ENTIRE question to be blocked as a permission violation
   -- when the correct query needed only candidate_name, Status,
   end_date, etc., with no rate/margin columns involved at all.
3. When a follow-up is vague about WHICH columns to show (e.g. "list
   them", "list all those", "show details"), infer the relevant
   columns from the CONVERSATION CONTEXT of what was just discussed
   (e.g. if the prior exchange was about Active/Inactive status, show
   candidate_name + Status + a couple of identifying columns like
   client/recruiter_name) -- never default to trying to show every
   column that exists in the schema just because the request itself is
   unspecific.

PERCENTAGES AND COMPARISONS -- COMPUTE IN SQL, NOT LATER IN PROSE:
whenever a query GROUPs candidates into 2 or more categories (by
Status, by recruiter, by client, by BU, etc.), ALSO add a
percentage-of-total column to that SAME query using a window function
-- this is far more reliable than estimating a percentage afterward
from a text summary, and costs nothing extra (it's still one query,
one LLM call). Example:

  SELECT status, COUNT(*) AS candidate_count,
         ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
  FROM deployed_candidates_masked_scoped
  GROUP BY status

`SUM(COUNT(*)) OVER ()` computes the true total across every group
actually returned by this exact query -- it automatically respects
whatever WHERE filter and row-level RBAC scope is already applied, so
the percentage is always honest and never needs a second query, a
subquery against a different table, or a guessed denominator.
- Add this percentage column for any GROUP BY producing 2+ category
  rows -- UNLESS the question is a single flat count with nothing to
  compare against (e.g. "how many candidates total" -- skip it there,
  a lone number has no "of what" to be a percentage of).
- For a direct comparison between named entities (e.g. "compare
  Accenture and Wipro"), compute each one's share of their combined
  total the same way, still within this one query -- never as a
  separate follow-up query.
- If MariaDB in this environment doesn't support the OVER() window
  function for some reason, use `ROUND(COUNT(*) * 100.0 / (SELECT
  COUNT(*) FROM <same table/view> <same WHERE clause if any>), 2)`
  instead -- but always mirror the exact same WHERE filter in the
  subquery's denominator as the main query uses, never a plain
  unfiltered table count when the main query itself is filtered.

ROUTING: if the question has NOTHING to do with this staffing database
(the schema above) -- e.g. general knowledge questions like "what type
of company is Accenture", "what does SOW stand for", "who is the CEO of
X", small talk, or anything else this schema plainly cannot answer --
do NOT attempt to write SQL for it. Instead, output EXACTLY this and
nothing else: NOT_DATABASE_QUESTION
Only use this if the question is clearly unrelated to querying this
database -- if there's a reasonable way to answer it from the schema
above, write the SQL query as normal instead.

CONVERSATION CONTEXT: you may be shown a few of the most recent prior
questions and answers from this same conversation, followed by a new
question. Use that history ONLY to understand what the new question is
actually asking -- e.g. if the new question is just "Yes", "What about
by client instead?", or "And the total?", look at the immediately
preceding question/answer to figure out the real, complete intent.
Regardless of how much history is shown, you must still write exactly
ONE fresh, complete, self-contained SQL query that fully answers the
new question on its own -- never write a query that only makes sense
combined with a previous one, and never reference results from a prior
answer as if they were already in a table.
If a plain affirmation like "Yes" follows a vague or open-ended prior
question (one that offered more than one possible thing), pick the
single most likely, most specific interpretation and write ONE query
for that -- never attempt to cover multiple different interpretations
by writing more than one SQL statement.

CARRYING FORWARD AN IMPLIED FILTER (important, real bug fixed here):
if the recent conversation was clearly about a SPECIFIC entity (a
particular client, recruiter, or BU -- e.g. the last 1-2 exchanges were
about "Accenture"), and the new question does NOT explicitly repeat
that entity's name but also does not clearly ask about something
broader/different, ASSUME the new question is still scoped to that same
entity -- do not silently widen the query to the whole database.
Example: if the immediately preceding question was "How many candidates
do we have with Accenture?" (answer: 107), and the new question is
"give number of active and inactive candidates" (with no client
mentioned), the correct query is:
SELECT Status, COUNT(*) FROM candidates_masked WHERE client = 'Accenture' GROUP BY Status
NOT a global breakdown across the whole database -- that would silently
answer a different, broader question than what was actually being
discussed. Only drop the implied filter if the new question clearly
signals a broader scope, e.g. "across the whole database", "overall",
"in total for everyone", "regardless of client"."""

ANSWER_SYSTEM_PROMPT = """You are a helpful analyst reporting results from a
staffing database to a non-technical user. You will be given the original
question, the SQL query that was run, and the raw result rows. Write a
short, clear, plain-English answer using those results. Do not invent any
numbers that aren't in the provided results. If the result set is empty,
say so plainly rather than guessing.

FORMATTING: your response is rendered as Markdown, so use real Markdown
syntax, not plain dashes or commas, to make answers easy to scan:
- For any breakdown/grouping result with TWO OR MORE columns worth of
  data per row (e.g. a recruiter name AND its candidate count; a client
  AND a status AND a count) -- use a proper Markdown TABLE, not a
  bullet list. Format it EXACTLY like this, with a header row and a
  separator row of dashes:

  | Recruiter | Candidates |
  |---|---|
  | Saravanan Rajendran | 24 |
  | Elavenil Elambharathi | 16 |

  Use column headers that clearly describe what each column is. Every
  row must have the same number of columns as the header.
- For a simple list of just ONE column of items with no accompanying
  number/value (e.g. a plain list of names), a bullet list ("- item")
  is fine instead of a table.
- Use **bold** for key numbers or names worth drawing attention to,
  including inside table cells if helpful.
- Keep a short lead-in sentence before a table or list, not just the
  table alone.
- For a single-number answer, plain sentence form is fine -- no need to
  force a table or list for one fact.
- If a result set has many rows, you do not need to render all of them
  in the table -- showing the top 15-20 in the table with a note that
  more are available (and downloadable) is fine.

COMPLETENESS -- never silently omit a row from an UNTRUNCATED result
set. If note_if_truncated says nothing was cut off, every row you were
given must appear in your table/breakdown -- including a row whose
category looks unusual, blank, NULL, or like a small residual group
(e.g. a blank/NULL Status value must still get its own labeled row,
e.g. "Unspecified" or "(blank)", never be dropped silently). Dropping a
row is just as misleading as inventing one: it quietly changes the
true total/denominator without telling the person. This matters
especially for the percentage rule below -- a percentage is only
honest when every row making up the whole has actually been shown, so
never compute one against a breakdown you've secretly left a row out
of.

If the results represent a breakdown/grouping (e.g. counts per recruiter,
per client), do NOT state an overall "total" number unless the query
itself explicitly computed one (e.g. a separate COUNT(*) with no GROUP
BY, or a SUM of a column). Never add up the counts shown to you and
present that as "the total" -- the rows you've been given may be a
truncated preview of a larger result set, so a sum you calculate
yourself could be wrong. If the person's question asked for both a
breakdown AND a total, and the query only provided one of those two
things, answer with what the query actually shows and note that the
other part (e.g. "the exact overall total") would need a follow-up
question to calculate precisely, rather than guessing or mislabeling a
group count as a total.

PERCENTAGES AND COMPARISONS -- prefer a value the SQL query already
computed for you. If a column in the results is clearly a percentage
or ratio the query itself calculated (e.g. named something like
pct_of_total, percentage, ratio -- per the SQL-generation instructions
that now add this automatically for category breakdowns), just report
that value plainly and correctly attributed to its row -- do NOT
recompute or second-guess it yourself, and do not perform your own
separate division when one is already sitting in the data.

Only if NO such column exists, but a percentage would still clearly
help answer the question, may you compute one yourself -- and only
under the same strict discipline as everything else in this prompt:
- Only state a percentage when BOTH the part and the whole are
  literally present, complete, and untruncated in the results you were
  given -- e.g. a Status breakdown whose rows cover EVERY status value
  actually returned (per the COMPLETENESS rule above -- if the results
  contain 3 distinct status groups, all 3 must be shown, not just the
  2 you find most relevant), with note_if_truncated confirming nothing
  was cut off. Once that condition is met, COMPUTE the percentage --
  this is not optional caution once completeness is satisfied. Sum ALL
  the rows shown to get the whole (e.g. 1,579 + 18 + 2,044 = 3,641),
  then divide the specific part being discussed by that whole. Example:
  "35 Active out of 42 total (about 83%)." Do not withhold a percentage
  out of general caution once every row is genuinely in front of you --
  the completeness rule above exists precisely so you CAN trust the sum
  of what you were given as the true whole.
- NEVER compute a percentage against a denominator that isn't itself
  present in this result set -- do not assume, guess, or recall a
  "total" from a different question or from conversation history.
  If the whole you'd need to divide by isn't in the data in front of
  you, skip the percentage and state the raw number(s) plainly instead.
- NEVER compute a percentage if note_if_truncated says any rows were
  omitted -- a partial preview cannot give you an honest denominator,
  for the exact same reason you never self-calculate a truncated total
  above.
- For a COMPARISON between two or more named entities/values in the
  SAME result set (e.g. two clients' candidate counts, two recruiters'
  breakdowns), you may state the relative difference using ONLY the
  numbers shown (e.g. "Accenture has roughly 2x as many candidates as
  Wipro") -- never pull a number from a different question or from
  history to make the comparison.
- Always show your work: state the raw numbers a percentage or
  comparison came from in the same sentence as the computed figure, so
  it's auditable at a glance, never a bare percentage with its inputs
  hidden.
- If none of the above conditions are safely met, that's fine -- just
  answer with the plain numbers and skip the percentage/comparison
  rather than forcing one that isn't honestly computable.

NAME DISAMBIGUATION: if the SQL query filtered a person's name using
LIKE (a partial/fuzzy match, e.g. WHERE recruiter_name LIKE '%X%') --
you can tell this happened by looking at the SQL provided -- check how
many DISTINCT values for that name column came back in the results:
- ZERO rows: say plainly that no recruiter matching that name was
  found, and suggest checking the spelling.
- Results show exactly ONE distinct name for that column: answer
  normally using those results, but explicitly state the FULL matched
  name in your answer (e.g. "Selvakumar M has 10 candidates..."), even
  if the person only typed a shorter or partial version -- this makes
  it transparent which exact record was used.
- Results show MORE THAN ONE distinct name for that column (e.g. both
  "Selvakumar M" and "Selvakumar J" matched): do NOT combine their
  counts, do NOT guess which one was meant, and do NOT just pick the
  first one. Instead, list the distinct names you found and ask the
  person which one they meant, e.g. "I found more than one match:
  **Selvakumar M** and **Selvakumar J**. Which one did you mean?" --
  then wait for their answer rather than providing any candidate count
  in this response.

Do NOT confuse "the number of distinct categories/groups in the
breakdown" (e.g. 193 different recruiters) with "the total count across
all rows" (e.g. 1,121 total candidates) -- these are different numbers
and must never be swapped or substituted for each other.

Do NOT end your answer with a follow-up question or offer to check
something else -- follow-up suggestions are now handled separately, as
structured clickable options (see followup_suggester.py), not as a
sentence you write. Simply answer the question and stop."""


def _clean_sql_text(text: str) -> str:
    """Strips markdown code fences if a model adds them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


MAX_HISTORY_TURNS = 4  # how many prior Q&A pairs to include as context


def _format_history(history):
    """Formats a list of {"question": ..., "answer": ...} dicts (most
    recent last) into a text block for the model. Keeps only the last
    MAX_HISTORY_TURNS to bound prompt size/cost."""
    if not history:
        return ""
    trimmed = history[-MAX_HISTORY_TURNS:]
    lines = ["Recent conversation history (most recent last):"]
    for turn in trimmed:
        q = turn.get("question", "").strip()
        a = turn.get("answer", "").strip()
        if q:
            lines.append(f'Q: "{q}"')
        if a:
            lines.append(f'A: "{a}"')
    return "\n".join(lines)


ROUTING_SENTINEL = "NOT_DATABASE_QUESTION"


class NotDatabaseQuestion(Exception):
    """
    Raised when a provider determines a question has nothing to do with
    the staffing database (e.g. general knowledge). This is a SUCCESSFUL
    classification, not a failure -- it is deliberately NOT retried on
    the next provider in the chain, and it is caught by the caller
    (webapp/server.py) to route to a separate general-knowledge answer
    path instead. Critically: no SQL is ever generated, validated, or
    executed for a question that takes this path -- the database
    (masked or otherwise) is never touched for these questions at all.
    """
    def __init__(self, question: str):
        self.question = question
        super().__init__(f"Not a database question: {question!r}")


def generate_sql(question: str, history=None):
    """
    Tries each configured provider in order (see PROVIDER_CHAIN) until one
    returns SQL that passes our safety validation. `history` is an optional
    list of {"question": ..., "answer": ...} dicts from earlier in this
    same conversation -- used only to resolve ambiguous follow-ups like
    "Yes" or "what about by client instead", never to skip writing a
    fresh, complete query. Returns
    (row_limited_sql, provider_name_used, raw_model_output).
    Raises NotDatabaseQuestion if the question isn't about this database
    at all (see ROUTING_SENTINEL) -- callers should catch this
    separately from UnsafeQueryError and route to a general-knowledge
    answer instead.
    Raises UnsafeQueryError if every configured provider fails to
    produce a safe, valid database query.
    """
    system_prompt = SQL_SYSTEM_PROMPT_TEMPLATE.format(
        schema=combined_schema_text(),
        examples=combined_examples_text(),
    )

    history_block = _format_history(history)
    user_message = (
        f"{history_block}\n\nNew question: \"{question}\"" if history_block else question
    )

    errors = []

    for provider in PROVIDER_CHAIN:
        if not provider.is_configured():
            errors.append(f"{provider.name}: not configured (missing API key)")
            continue
        try:
            raw_sql = _clean_sql_text(provider.generate_sql(system_prompt, user_message))
            if raw_sql.strip().upper() == ROUTING_SENTINEL:
                # This is a successful classification, not an error --
                # propagate immediately, do not try the next provider,
                # do not treat it like a failed SQL attempt.
                raise NotDatabaseQuestion(question)
            validated = validate_sql(raw_sql)
            limited = enforce_row_limit(validated)
            return limited, provider.name, raw_sql
        except NotDatabaseQuestion:
            raise
        except Exception as e:
            print(f"[llm] {provider.name} failed ({e}); trying next provider...")
            errors.append(f"{provider.name}: {e}")

    raise UnsafeQueryError(
        "Every configured provider failed to produce a safe query.\n"
        + "\n".join(errors)
    )


def _extract_followup_suggestion(answer_text: str):
    """
    Pass-through: follow-up suggestions are no longer written into the
    answer text at all (see ANSWER_SYSTEM_PROMPT -- that instruction
    was removed once followup_suggester.py became the real
    implementation) and are no longer parsed out of anything here
    either. Real suggestions are computed deterministically in
    webapp/server.py via followup_suggester.build_followups(), using
    the login's scope_type -- something this function has no access to
    and shouldn't need. Kept as a no-op so phrase_answer's call site
    doesn't need to change shape again if this evolves further.
    """
    return answer_text.rstrip(), None


GENERAL_KNOWLEDGE_SYSTEM_PROMPT = """You are a helpful assistant embedded
inside a staffing-data business chatbot used by staffing/recruiting
professionals. The person just asked something that has nothing to do
with querying the internal staffing database.

FIRST, decide if this question is actually in scope for a professional
staffing-business tool:
- IN SCOPE: general knowledge that's genuinely relevant to understanding
  the staffing business context -- e.g. "what type of company is
  Accenture" (a client), "what does SOW mean", "what's a C2C contract",
  industry/staffing terminology, facts about client/vendor companies,
  or brief relevant small talk in a professional context.
- OUT OF SCOPE: anything clearly unrelated to work/staffing business --
  e.g. jokes, poems, creative writing, unrelated trivia (sports,
  celebrities, entertainment), personal life advice, coding help,
  requests to write code/essays/stories, or generic assistant tasks
  that have nothing to do with staffing or this business.

If OUT OF SCOPE: politely decline in ONE short sentence, explain this
tool is meant for staffing-data questions and related business
knowledge, and stop there -- do not attempt the request (e.g. do not
actually tell the joke/write the poem/answer the trivia).

If IN SCOPE: answer it directly and concisely, the way a knowledgeable
general-purpose assistant would.

Rules for in-scope answers:
- Make it clear this is general knowledge, not verified internal data --
  naturally distinguish it, e.g. "That's outside our database, but..."
  or similar, so it's never confused with a database-verified fact.
- Keep answers concise and factual. If you're not confident or don't
  know, say so honestly rather than guessing.
- If recent conversation history is provided below, use it to resolve
  references like "their" or "that company" in the new question.
- This is a knowledge question, not a database question -- do not
  mention SQL, queries, or databases in your answer except to note (if
  relevant) that this particular question isn't something the internal
  data covers.
"""


def answer_general_knowledge(question: str, history=None):
    """
    Answers a question that generate_sql determined has nothing to do
    with the staffing database (see NotDatabaseQuestion). No SQL is
    generated or run for this path -- it never touches db.py, sql_guard,
    or the masked view at all. Returns (answer_text, provider_name_used).
    """
    history_block = _format_history(history)
    user_message = (
        f"{history_block}\n\nNew question: \"{question}\"" if history_block else question
    )

    for provider in PROVIDER_CHAIN:
        if not provider.is_configured():
            continue
        try:
            answer = provider.generate_answer(GENERAL_KNOWLEDGE_SYSTEM_PROMPT, user_message)
            return answer.strip(), provider.name
        except Exception as e:
            print(f"[llm] {provider.name} failed general-knowledge answer ({e}); trying next...")

    return "I couldn't generate an answer right now -- all providers failed.", None


CLASSIFY_SYSTEM_PROMPT_TEMPLATE = """You will be given a person's message, which
may be ENTIRELY about the internal staffing database, ENTIRELY general
knowledge unrelated to it, or a MIX of both in one message (e.g. "What
type of company is Accenture, and how many candidates do we have with
them?" mixes a general-knowledge part about Accenture with a database
part about candidate counts).

Here is what this specific database actually contains -- use this to
correctly recognize when a question maps to real, available data here,
even if the question's wording alone might sound like a generic/general
topic:

{schema}

IMPORTANT: a question can SOUND like generic small talk or a general
topic while actually being fully answerable from the schema above --
e.g. "What is the average hourly pay rate?" sounds like it could be a
generic salary-survey question, but this database has real pay_rate
data, so it MUST be classified as a database_question, not general
knowledge. When in doubt, check: does a column or combination of
columns above plausibly answer this? If yes, it's a database question.

Decompose the message into up to two separate, complete, standalone
sub-questions. Output STRICT JSON only -- no markdown fences, no
commentary, nothing else -- in EXACTLY this shape:
{{"database_question": "<text or null>", "general_knowledge_question": "<text or null>", "is_insight": true or false}}

The "is_insight" field: set it to true ONLY if database_question is a
deeper analysis/diagnosis/recommendation-style request that a single
simple query cannot fully answer -- e.g. "how would I reduce unexpected
rolloffs at LTIMindtree", "why is X happening", "what should we do
about Y", "how is our recruiter workload distributed" (asking for
interpretation of a pattern, not just raw numbers). Set it to FALSE for
a direct, simple fact/count/breakdown question -- e.g. "how many
candidates does X have", "average pay rate", "list clients with more
than 10 candidates" -- even if it involves a GROUP BY or multiple
columns. When database_question is null, is_insight must be false.

CRITICAL RULE -- DO NOT MISROUTE THESE TO general_knowledge_question:
any question of the form "how do I fix/reduce/solve/improve <a metric
this database tracks>" (rolloffs, roll-offs, margins, workload,
turnover, pay rates, client relationships, etc.) is ALWAYS a
database_question with is_insight=true -- REGARDLESS of the exact
wording used. All of these mean the exact same thing and must ALL be
classified as database_question + is_insight=true:
- "How can I fix the rolloff problem at HCL?"
- "How do I fix or reduce these roll offs?" (referring back to a client
  discussed earlier in history)
- "How do I reduce roll offs in HCL?"
- "What should we do about our margins at Cognizant?"
Do NOT classify any of these as general_knowledge_question just because
they contain words like "fix"/"solve"/"problem" that might sound like
generic advice-seeking -- they are specifically about THIS business's
data and belong in database_question, never general knowledge. Generic,
truly unrelated advice-seeking (e.g. "how do I fix my sleep schedule",
"how do I solve a relationship problem") is the only kind that should
ever go to general_knowledge_question (where it will then correctly be
declined as out of scope) -- never a business-metric improvement
question about data this schema tracks.

CONTRAST -- these are SIMPLE fact questions, is_insight=FALSE, even
though they mention rolloffs/a client, because they only ask for a
plain count/breakdown, not a fix/reduce/improve/diagnose:
- "How many roll offs does HCL have?" -- a plain count, is_insight=false
  (and NOTE: no word "unexpected" appears, so this means the plain
  rolloff definition, end_date <= CURDATE(), not the unexpected one --
  see the end_date column notes above for this exact distinction).
- "How many unexpected rolloffs does LTIMindtree have?" -- still just a
  plain count (of the unexpected definition specifically, since that
  word IS present), is_insight=false.
- "Give a candidate who is a Cloud engineer with skills X, Y, Z handled
  by [person]" -- a SIMPLE, direct lookup with multiple filter
  criteria, is_insight=FALSE. Listing several required
  skills/attributes does NOT make something an analysis/insight
  question -- it's still just a filtered search, answerable with ONE
  query combining all the criteria with AND/OR (see the schema's
  vendor_contact_person notes for the exact correct pattern). A real,
  verified bug: this exact question type was incorrectly routed through
  the insight/decomposition pipeline, which then broke it into several
  separate flawed sub-questions instead of one direct search.
Only set is_insight=true when the question asks HOW to change/improve
the number, WHY it's happening, or asks for interpretation of a pattern
-- not when it just asks WHAT the number/breakdown currently is, and
not just because a question has MANY filter criteria in it.

CRITICAL -- DO NOT DECLINE HISTORICAL/TIME-COMPARISON QUESTIONS: a
question like "how does this compare to last quarter/last month/N
months ago", "which clients grew or shrank over the last 6 months", or
"how many did we have 3 months ago" is a REAL, ANSWERABLE
database_question (is_insight=true) -- it can be approximated using
start_date/end_date (see the schema's point-in-time comparison notes
above). Do NOT classify these as general_knowledge_question and do NOT
let them get declined as "I can't provide historical comparisons" --
that is a real, confirmed bug. These belong in database_question.

CRITICAL -- A PARTIAL LIMITATION IS NEVER A REASON TO DECLINE THE WHOLE
QUESTION: if a question is genuinely about staffing metrics this
schema covers (candidates, recruiters, clients, rates, regions, dates,
skills, status, margins) but some SPECIFIC detail it also asks about
isn't tracked in this data (e.g. "rates that haven't been reviewed" --
no review-date field exists), this is STILL a database_question, is_insight can still be true, NEVER general_knowledge_question and NEVER
declined as out-of-scope. The correct handling is to answer what IS
available and honestly note the specific untracked detail -- a real,
confirmed regression happened from over-applying this: a legitimate
question like "are our rates competitive by region" (fully answerable
from pay_rate_numeric, client_rate_numeric, project_country) was
wrongly declined as "out of scope" as if it were an off-topic request
like a joke. Reserve general_knowledge_question / out-of-scope decline
ONLY for messages that are not about this business's staffing data at
all (jokes, unrelated trivia, personal tasks) -- never for a real
staffing-metric question just because one detail of it isn't tracked.

Rules:
- If the message is ENTIRELY a database question (about candidates,
  recruiters, clients, BUs, rates, dates, status, skills, etc.), set
  general_knowledge_question to null and put the full question (or a
  clean restatement of it) in database_question.
- If the message is ENTIRELY general knowledge (facts, definitions,
  companies, unrelated topics -- nothing this database could answer),
  set database_question to null.
- If it's a MIX, extract BOTH parts as separate, complete, standalone
  questions -- each one must make sense fully on its own.
- Use any provided conversation history to resolve references like
  "they", "them", or "it" into the actual entity (e.g. a company name)
  mentioned earlier, for either part.
  IMPORTANT: resolve such a pronoun to the SINGLE entity from the MOST
  RECENT relevant exchange only -- never blend it with other, older
  entities that were mentioned earlier in the conversation for an
  unrelated question. For example, if the conversation mentioned
  "HCL" and "Cognizant" in earlier unrelated exchanges, and the most
  recent exchange was specifically about "Accenture", then "what type
  of company is it" means Accenture ONLY -- do not also mention HCL or
  Cognizant just because they appeared somewhere earlier in the
  history.
- Preserve names/entities exactly as the person means them.
- SHORT FOLLOW-UPS: if the message is short and ambiguous on its own --
  e.g. "Yes", "Sure", "the second one", "sidd, vinay, oliver", a bare
  name, or similar -- do NOT treat it as unclassifiable. Look at the
  immediately preceding question/answer in the history: if it ended
  with a suggested follow-up or a clarifying question (e.g. "Would you
  like me to check X?", "Which one did you mean?"), resolve this short
  message as the person's answer to THAT, and produce the FULL,
  complete resulting question in database_question and/or
  general_knowledge_question as appropriate -- never leave both fields
  null just because the raw message alone looks like a fragment. A
  short reply almost always means "yes, do the thing you just offered"
  or "here is the specific value you asked me to clarify" -- resolve it
  into a complete question using that context rather than giving up.
- If, after using all available history, you genuinely cannot determine
  what a message means (rare), default to treating the ENTIRE raw
  message as database_question rather than returning both fields null
  -- an attempt that might not perfectly match intent is better than no
  attempt at all.
- Output ONLY the JSON object. No code fences, no explanation, nothing
  before or after it."""


def classify_question(question: str, history=None) -> dict:
    """
    Splits a message into {"database_question": ..., "general_knowledge_question": ...,
    "is_insight": bool} (either question key can be None). This lets a
    single compound message (e.g. "what is Accenture, and how many
    candidates do we have with them") be answered by running EACH part
    through its own dedicated, independent pipeline -- rather than
    forcing one model call to somehow answer both at once, which is
    what caused a fabricated database number in earlier testing.
    "is_insight" flags whether database_question needs deeper
    multi-query analysis (see answer_insight_question) rather than a
    single simple query.

    On any parsing/provider failure, falls back to treating the whole
    message as a single, non-insight database_question (matches the
    simpler, previous single-path behavior) so a classification hiccup
    never means the person gets no answer at all.
    """
    system_prompt = CLASSIFY_SYSTEM_PROMPT_TEMPLATE.format(schema=combined_schema_text())

    history_block = _format_history(history)
    user_message = (
        f"{history_block}\n\nNew message: \"{question}\"" if history_block else question
    )

    for provider in PROVIDER_CHAIN:
        if not provider.is_configured():
            continue
        try:
            raw = provider.generate_answer(system_prompt, user_message)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = [l for l in cleaned.split("\n") if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()
            parsed = json.loads(cleaned)
            db_q = parsed.get("database_question")
            gk_q = parsed.get("general_knowledge_question")
            is_insight = bool(parsed.get("is_insight", False))
            # Normalize the JSON string "null"/empty-string cases some
            # models produce instead of a real null.
            db_q = db_q if db_q and db_q.strip().lower() != "null" else None
            gk_q = gk_q if gk_q and gk_q.strip().lower() != "null" else None
            if db_q is None:
                is_insight = False  # can't be an insight question with no DB part
            if db_q is None and gk_q is None:
                # The model returned valid JSON but couldn't classify
                # either part -- this used to mean the person got a
                # flat "I couldn't find an answer to that" with no
                # attempt made at all. Instead, default to treating the
                # whole raw message as a database question (the most
                # common real intent in this app) rather than giving up
                # silently.
                print(f"[llm] Classifier returned both fields null for {question!r}; "
                      f"falling back to treating it as a database question.")
                return {"database_question": question, "general_knowledge_question": None, "is_insight": False}
            return {"database_question": db_q, "general_knowledge_question": gk_q, "is_insight": is_insight}
        except Exception as e:
            print(f"[llm] {provider.name} failed to classify ({e}); trying next...")

    # Fallback: treat the whole thing as a database question, same as
    # the original single-path behavior, rather than failing entirely.
    return {"database_question": question, "general_knowledge_question": None, "is_insight": False}


def phrase_answer(question: str, sql: str, columns, rows, provider_name: str):
    """
    Asks the same provider that generated the SQL to phrase a plain-English
    answer from the results. Falls back through the remaining chain if that
    specific provider call fails for some reason.
    Returns (display_answer_text, suggested_followup_question_or_None).
    """
    # Truncate for size, but ALWAYS keep the last row. Summary/rollup rows
    # (e.g. GROUP BY ... WITH ROLLUP grand totals) conventionally appear
    # last -- a naive rows[:50] slice would silently drop exactly the row
    # a "what's the total" question needs.
    if len(rows) > 50:
        shown_rows = list(rows[:49]) + [rows[-1]]
        truncation_note = (
            f"Rows 1-49 of {len(rows)} total result rows are shown above, "
            f"PLUS the final row (row {len(rows)}) shown in full since "
            f"summary/rollup total rows conventionally appear last. Rows "
            f"50 through {len(rows) - 1} are omitted from this preview, but "
            f"were still used correctly by the database to compute any "
            f"aggregate/rollup values."
        )
    else:
        shown_rows = rows
        truncation_note = "All result rows are shown above (none truncated)."

    result_preview = {
        "columns": columns,
        "rows": shown_rows,
        "note_if_truncated": truncation_note,
    }
    user_content = (
        f"Question: {question}\n\nSQL run: {sql}\n\nResults: {result_preview}\n\n"
        f"IMPORTANT: any row/group count mentioned in 'note_if_truncated' "
        f"describes how many ROWS/GROUPS this query returned (e.g. how many "
        f"distinct recruiters, clients, etc.) -- this is NEVER the same thing "
        f"as a business total like 'total candidates'. If the "
        f"question asks for a total count of candidates/items, that total must "
        f"come from an actual COUNT/SUM value in the 'rows' data itself, not "
        f"from the number of rows/groups returned."
    )

    # Try the provider that succeeded at SQL generation first, then walk
    # the rest of the chain as a fallback for the phrasing step too.
    ordered = sorted(PROVIDER_CHAIN, key=lambda p: p.name != provider_name)

    for provider in ordered:
        if not provider.is_configured():
            continue
        try:
            raw_answer = provider.generate_answer(ANSWER_SYSTEM_PROMPT, user_content)
            return _extract_followup_suggestion(raw_answer)
        except Exception as e:
            print(f"[llm] {provider.name} failed to phrase answer ({e}); trying next...")

    fallback_text = (
        f"(Could not generate a natural-language summary -- all providers failed.)\n"
        f"Raw result -- columns: {columns}, rows: {rows[:20]}"
    )
    return fallback_text, None


MAX_INSIGHT_SUB_QUESTIONS = 4  # bounded, so this never runs away in cost/latency

DECOMPOSE_INSIGHT_SYSTEM_PROMPT_TEMPLATE = """You help analyze a deeper
staffing-business question by breaking it into a SMALL, bounded set of
concrete, standalone sub-questions -- each one answerable by a single
SQL query against the schema below.

{schema}

Given the person's insight/analysis question, output a JSON array of
2 to {max_n} short, concrete, standalone sub-questions that would help
answer it thoroughly using ONLY this schema's real data. Each
sub-question must be something a single SQL query could answer (a
count, an average, a breakdown, a comparison) -- not another vague
analysis question.

Example: for "How would I reduce unexpected rolloffs at LTIMindtree?",
good sub-questions include things like:
["What is the total count of LTIMindtree's unexpected rolloffs?",
 "What is LTIMindtree's total candidate count?",
 "What is the company-wide total count of unexpected rolloffs across all clients?",
 "What is the breakdown of LTIMindtree's unexpected rolloffs by recruiter?"]

Rules:
- IMPORTANT: if the original question is about a count/total of
  something (e.g. rolloffs, candidates, margins) at a specific
  entity (a client, BU, recruiter), your FIRST sub-question MUST be a
  direct, simple "what is the total count of X" question that a single
  COUNT/SUM query can answer exactly -- this ensures a real, literal
  total number exists for later use, rather than requiring anyone to
  add up a breakdown table themselves. Breakdown-style sub-questions
  (by recruiter, by month, etc.) should come AFTER this direct total
  question, not replace it.
- IMPORTANT: if the original question invites any percentage or
  comparison (see the synthesis prompt's narrow exception for exactly
  what's allowed there), make sure your sub-questions produce BOTH raw
  numbers such a comparison would need as separate, simple counts (e.g.
  "entity's count" AND "entity's total", or "entity A's count" AND
  "entity B's count") -- never a single sub-question asking for a
  pre-computed rate (see the rule immediately below for why).
- CRITICAL -- NEVER ask for a pre-computed "rate", "ratio", or
  "percentage compared to average" as a single sub-question (e.g. NEVER
  generate something like "what is X's rate compared to the
  company-wide average" as ONE sub-question). A real, verified bug
  happened from exactly this pattern: asking for a comparative rate in
  one shot produced a badly wrong number (an actual case: stated
  company-wide rate was off by more than 2x from the true value).
  Instead, ALWAYS decompose a rate/comparison need into SEPARATE,
  simple raw-count sub-questions (e.g. "entity's count", "entity's
  total", "company-wide count", "company-wide total") -- each trivially
  answerable by one COUNT/SUM query -- and let the synthesis step do
  the final simple division itself using the raw numbers it receives.
- Output ONLY a JSON array of strings. No markdown fences, no
  commentary, nothing else.
- Every sub-question must be answerable from the schema above -- do not
  invent sub-questions needing data this schema doesn't have.
- Keep each sub-question specific and standalone (no pronouns needing
  outside context).
- 2 to {max_n} sub-questions -- prefer fewer, more targeted ones over
  padding the list."""

INSIGHT_SYNTHESIS_SYSTEM_PROMPT = """You are a staffing-business analyst.
You will be given an original question the person asked, and a set of
sub-questions that were each answered with REAL, verified data retrieved
from the database (shown as sub-question + actual result rows).

Write a short synthesis of what the actual retrieved numbers show,
directly relevant to the original question. EVERY number or fact you
state MUST come from the provided sub-question results -- never state
a number that isn't in them. If the retrieved data is incomplete or
doesn't fully cover the question, say so honestly rather than filling
gaps with guesses. Use a Markdown table if presenting a breakdown with
2+ columns (same formatting rules as any other data answer).

Do NOT include general staffing-industry advice, best-practice
suggestions, or recommendations of any kind -- answer ONLY with what
the retrieved data shows, and stop there. Stay strictly on the data in
front of you; do not editorialize or advise beyond it.

CRITICAL -- ENTITY NAME ACCURACY: if conversation history is
provided and it discussed a DIFFERENT client/recruiter/BU than the
one this question is actually about, do NOT let that earlier name
bleed into your findings. Always name the SAME client/entity that
the CURRENT original question and CURRENT sub-question results are
actually about -- double check the entity name in your opening
sentence matches the one in the question, not one from earlier in
the conversation. A real, verified example of this exact bug: a
synthesis about LTIMindtree incorrectly opened with "HCL has 223
candidates with LTIMindtree" -- mixing in a client name (HCL) from
a few turns earlier in the conversation. Never do this -- name only
the entity the current question and data are actually about.

CRITICAL -- NO NUMBER BLEEDING FROM HISTORY EITHER: this same rule
applies to NUMBERS, not just names. Every single number you state
must come from the CURRENT sub-question results provided to you in
THIS call -- never reuse or reference a number from an earlier
question/answer in the conversation history, even if it seems
topically related or similar. A real, verified example of this
bug: a synthesis about pay rates by region stated an average pay
rate of "2250000.00" that was not present anywhere in the current
result set at all -- it had been discussed many turns earlier in
the conversation for a completely different question, and
incorrectly resurfaced here as if it were part of the current
findings. Treat conversation history as useful ONLY for
understanding entities/context/intent -- NEVER as a source of
numbers to restate in a new answer.

RECRUITER/NAME DATA QUALITY: if a recruiter breakdown includes
known non-recruiter process codes (e.g. 'PT', 'PTR', 'TBD', 'NA',
'Vendor Change') as if they were real people, especially if one of
them has a notably high count, explicitly call this out as a data
quality caveat (e.g. "note: a large share of this is tagged under
the process code 'PTR' rather than an actual recruiter, which may
need investigating before drawing conclusions about individual
recruiter performance") rather than silently presenting it in the
table as if it were an ordinary recruiter.

CRITICAL -- NO SELF-CALCULATED NUMBERS OF ANY KIND: do not calculate
ANY number yourself from the raw data you were given -- this
includes not just percentages/ratios/averages, but also overall
totals or summary counts (e.g. do NOT write an opening sentence like
"there are a total of 36 X" by mentally adding up rows from a
breakdown table). You are unreliable at this kind of mental
arithmetic and it produces wrong numbers that look confident -- a
real, verified example of this exact bug: a synthesis stated "a
total of 36" for something a direct query later confirmed was
actually 45. A second real example: a synthesis stated a
company-wide rate of 0.7058 when the true value (computable from the
provided raw counts) was 0.3167 -- more than double the truth.
Only state ANY summary/total number if it EXACTLY matches a single
value that was ALREADY computed and returned directly by one of the
sub-question SQL results (i.e. you can see that literal number
sitting in the data, not derived by summing rows yourself). If you
want to state an overall total and no sub-question result already
contains one, either omit that summary sentence entirely and just
present the breakdown table, or explicitly say a specific follow-up
query could calculate the precise total -- never estimate or add it
up yourself.

NARROW EXCEPTION -- simple, auditable single division ONLY, but USE IT
WHEREVER IT APPLIES: a bare count is harder to interpret than a count
with its percentage/comparison alongside it, so whenever the
sub-question results genuinely give you exactly two raw numbers that
form one obvious ratio or comparison (e.g. "15 unexpected rolloffs" and
"41 total candidates" for the same entity; or two entities' counts
side by side), you SHOULD compute and state that one single division or
comparison, not just "may" -- but you MUST show both raw input numbers
explicitly in the same sentence as the computed figure (e.g. "15 of
Cognizant's 41 candidates (about 36.6%) had unexpected rolloffs"),
never state a bare percentage or comparison with its inputs hidden.
Never chain more than one arithmetic operation together (e.g. never
compute a rate AND THEN compare two rates to each other in your head --
if you need to compare an entity's rate to a company-wide rate, state
each rate separately with its own two visible input numbers, and let
the reader compare them, rather than computing a comparison ratio
yourself). If the two numbers a percentage/comparison would need are
NOT both cleanly present in the sub-question results, do not attempt
one -- present the raw findings you do have and stop there.

CRITICAL -- CROSS-CHECK A TOTAL AGAINST ITS OWN BREAKDOWN: if one
sub-question result gives you a single overall total (e.g. "88
unexpected rolloffs") AND another sub-question result gives you a
breakdown of that SAME metric (e.g. by recruiter), you MUST verify
the breakdown's rows actually sum to the stated total before
presenting both together. If they do NOT match (a real, verified
case: a breakdown summed to 84 while the stated total was 88), do
NOT silently present both numbers side by side as if they agree --
explicitly flag the discrepancy in your answer (e.g. "note: the
recruiter breakdown below sums to 84, which doesn't match the
separately-computed total of 88 -- this may need investigating") so
the person is never shown two contradicting numbers without being
told they contradict.

Keep the tone helpful and concise. Use Markdown formatting (bold, lists,
tables) per standard formatting rules. Do not add a closing
recommendations section of any kind -- end once the data findings are
stated."""


def decompose_insight_question(question: str, history=None) -> list[str]:
    """
    Breaks a deeper analysis/insight question into a small, bounded list
    of concrete sub-questions, each answerable by a single SQL query.
    Falls back to a single-item list (just the original question) if
    decomposition fails for any reason -- so an insight question always
    degrades gracefully to at least a simple, single-query attempt
    rather than failing outright.
    """
    system_prompt = DECOMPOSE_INSIGHT_SYSTEM_PROMPT_TEMPLATE.format(
        schema=combined_schema_text(), max_n=MAX_INSIGHT_SUB_QUESTIONS
    )
    history_block = _format_history(history)
    user_message = (
        f"{history_block}\n\nInsight question: \"{question}\"" if history_block else question
    )

    for provider in PROVIDER_CHAIN:
        if not provider.is_configured():
            continue
        try:
            raw = provider.generate_answer(system_prompt, user_message)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = [l for l in cleaned.split("\n") if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()
            sub_questions = json.loads(cleaned)
            if isinstance(sub_questions, list) and sub_questions:
                return [str(q) for q in sub_questions[:MAX_INSIGHT_SUB_QUESTIONS]]
        except Exception as e:
            print(f"[llm] {provider.name} failed to decompose insight question ({e}); trying next...")

    print(f"[llm] Insight decomposition failed for {question!r}; falling back to single sub-question.")
    return [question]


def synthesize_insight_answer(original_question: str, sub_results: list, history=None):
    """
    Given a list of (sub_question, sql, columns, rows) tuples -- each
    from a REAL, executed query -- synthesizes a final answer that
    separates data-grounded findings from any general (non-data)
    suggestions, per INSIGHT_SYNTHESIS_SYSTEM_PROMPT's strict rules.
    Returns (answer_text, provider_name_used).
    """
    facts_block_parts = []
    for sub_q, sql, columns, rows in sub_results:
        preview_rows = rows[:30]
        facts_block_parts.append(
            f'Sub-question: "{sub_q}"\nSQL: {sql}\nColumns: {columns}\nResults: {preview_rows}'
        )
    facts_block = "\n\n".join(facts_block_parts)

    history_block = _format_history(history)
    user_message = (
        f"{history_block}\n\n" if history_block else ""
    ) + f'Original question: "{original_question}"\n\nRetrieved data:\n{facts_block}'

    for provider in PROVIDER_CHAIN:
        if not provider.is_configured():
            continue
        try:
            answer = provider.generate_answer(INSIGHT_SYNTHESIS_SYSTEM_PROMPT, user_message)
            return answer.strip(), provider.name
        except Exception as e:
            print(f"[llm] {provider.name} failed insight synthesis ({e}); trying next...")

    return "I couldn't synthesize an answer right now -- all providers failed.", None