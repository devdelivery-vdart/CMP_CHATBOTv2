# Staffing Data Q&A Pipeline (Test Version)

Ask plain-English questions about your staffing data. Behind the scenes:
question -> LLM writes SQL -> SQL is safety-checked -> runs against the
masked view (`candidates_masked`) using a restricted, read-only database
user -> LLM phrases the result as a plain-English answer.

Uses **Groq (Llama 3.3)** first since it's free/cheap for testing, and
falls back to **OpenAI** automatically only if Groq fails or produces an
unsafe/invalid query.

## Prerequisites (should already be done from earlier setup)

- XAMPP running, MySQL started
- `staffing_db` database with the `candidates` table loaded
- The `candidates_masked` view created
- The restricted `app_readonly` MySQL user created (SELECT-only on
  `candidates_masked`, no access to `candidates`)

## Setup

1. **Install Python 3.9+** if you haven't already (check with `python --version`).

2. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

3. **Set up your environment file:**
   - Copy `.env.example` to a new file named `.env`
   - Fill in your real values:
     - `DB_PASSWORD` -- the password you set for `app_readonly`
     - `GROQ_API_KEY` -- from https://console.groq.com
     - `OPENAI_API_KEY` -- optional but recommended as fallback

   **Never commit or share your real `.env` file.**

4. **Run it:**
   ```
   python main.py
   ```

5. Type a question, e.g.:
   ```
   > How many candidates does recruiter Karthik D have?
   > How many candidates are currently Active vs Inactive?
   > List clients with more than 20 candidates.
   ```
   Type `exit` to quit.

## What's safe and what isn't

- The pipeline can **only** run `SELECT` queries.
- The pipeline can **only** query the `candidates_masked` view -- never
  the raw `candidates` table. This is enforced twice: once in code
  (`sql_guard.py`), and once at the database permission level (the
  `app_readonly` user literally cannot read `candidates`, confirmed
  during setup).
- Any query that fails these checks is rejected before it ever reaches
  the database, and you'll see a `[BLOCKED]` message explaining why.

## File overview

| File | Purpose |
|---|---|
| `config.py` | Loads DB credentials + API keys from `.env` |
| `sql_guard.py` | Validates generated SQL before execution (the safety gate) |
| `db.py` | MySQL connection + query execution |
| `llm.py` | Generic orchestration -- walks whatever providers are registered |
| `main.py` | Command-line loop tying it all together |
| `tables/` | **Pluggable**: one file per queryable table/view (see below) |
| `providers/` | **Pluggable**: one file per LLM provider (see below) |

## Adding a new table/view later (no core code changes needed)

1. Build the masked view in MySQL, e.g. `jobs_masked`.
2. Copy `tables/candidates_masked.py` to `tables/jobs_masked.py`.
3. Change the `TableSpec(name=..., description=...)` to describe the new
   table's real columns.
4. Save the file.

That's it. `tables/registry.py` auto-discovers every file in this folder
at startup, so the new table is automatically:
- added to the SQL safety allow-list (`sql_guard.py`)
- included in the schema context given to the LLM

A disabled placeholder for `rd_candidate` (the 907-row bench pool found
during setup) is already included as `tables/rd_candidate_masked.py` --
it's set to `enabled=False` until its masked view actually exists. Flip
that flag once it's ready.

## Adding a new LLM provider later (no core code changes needed)

1. Copy `providers/groq_provider.py` (or `openai_provider.py`) to a new
   file, e.g. `providers/anthropic_provider.py`.
2. Implement the same three methods (`generate_sql`, `generate_answer`,
   `is_configured`) for the new provider's SDK.
3. Open `providers/provider_chain.py`, import your new class, and add
   one line to the `PROVIDER_CHAIN` list in whatever priority order you
   want (e.g. as a third fallback after Groq and OpenAI).

`llm.py` has no provider-specific code in it at all -- it just walks
`PROVIDER_CHAIN` in order and uses whichever one is configured and
succeeds first, for both SQL generation and answer phrasing.

## Web UI (chat interface, for demos)

A simple browser-based chat UI sits on top of the exact same pipeline --
`webapp/server.py` is a thin FastAPI wrapper that calls the same
`generate_sql` / `db.run_query` / `phrase_answer` functions `main.py` uses.
No logic is duplicated; the safety gate and masked view are exactly the
same underneath.

1. Make sure `.env` is set up (same as the command-line version above).
2. Run:
   ```
   uvicorn webapp.server:app --reload --port 8000
   ```
3. Open **http://127.0.0.1:8000** in your browser.
4. Type a question, or click one of the suggested chips.

Each answer shows which provider generated it (Groq or the OpenAI
fallback) and the actual SQL that ran, in a small strip under the answer
-- useful for demos and for spotting when the fallback kicks in.

## Few-shot examples (improves accuracy)

Each table registered in `tables/` can include `Example` question->SQL
pairs (see `tables/candidates_masked.py`). These are shown to the LLM
alongside the schema description and meaningfully improve accuracy on
similar future questions -- especially for resolving known ambiguities
(e.g. which column/join is the "correct" one for a given business term).

**To add more examples**: add `Example(question=..., sql=...)` entries to
a table's `examples=(...)` tuple. No other file needs to change --
`tables/registry.py` automatically includes them in every prompt.

⚠️ Note: the "rolloff" example currently uses `last_working_date` as the
definition -- this was NOT confirmed with the business team, it's a
placeholder. Confirm the correct definition and update this example if
needed (see the test checklist for the 3 candidate definitions found).

## Download / export feature

Any question that returns a genuinely tabular result (more than one row,
or more than one column) automatically gets a downloadable `.xlsx` file
-- a "Download" button appears under the answer in the web UI.

- `export.py` handles the file generation -- it only ever touches data
  that already passed through the masked view and safety gate, it never
  queries the database itself.
- Generated files are temporary (`webapp/downloads/`), auto-cleaned up
  after 6 hours.
- A single-number answer (like "how many candidates in total") does not
  get a download button, since there's nothing tabular to export.

## Next steps (not built yet)

- A proper web interface (Streamlit or FastAPI + frontend) instead of
  command-line only
- An audit log table recording every question, SQL, provider used, and
  result
- Masking rules extended to `client_tag_poc_*` fields if needed
- Filling in and enabling `tables/rd_candidate_masked.py` once that
  masked view is built
