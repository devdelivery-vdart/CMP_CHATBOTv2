"""
Registration file for `candidates_masked_scoped` -- REBUILT for the new schema
(imported from an Excel/CSV export in staffing_db_v2, replacing the old
65-table schema). Key differences from the previous version of this file:
  - THREE email columns now (candidate_email, _2, _3), not one
  - account_manager_1-8 are now EMAIL ADDRESSES, not names -- newly masked
  - No linkedin_url, no work_email, no reporting_manager_* or
    client_tag_poc_* fields exist in this schema at all
  - No bu_name column exists in this schema (unlike the old one, so the
    old bu_name-is-always-NULL warning doesn't apply here -- there's
    simply no such column)
  - pay_rate/client_rate are TEXT with inconsistent formats (currency
    symbols, "+ Benefits", comma-thousands separators, a small number of
    "X | Y" pairs of unclear meaning) -- pay_rate_numeric/
    client_rate_numeric are cleaned, derived DECIMAL columns for
    aggregate math, added during import cleanup.
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="candidates_masked_scoped",
    description="""
Table: candidates_masked_scoped
(Masked view. candidate_email/_2/_3, vendor_contact_email,
bu_head_emailid, account_manager_1-8, and client_resource_manager_email
are all partially masked, e.g. "jo****@gmail.com". candidate_phone and
vendor_contact_number are masked to show only the first 3 digits. DOB is
fully hidden (always NULL in this view).)

Columns:
- Status (text) -- 'Active' or 'Inactive'. NOTE the capital S -- this
  column is named "Status" not "status" in this schema (different from
  the previous schema version).
- plc_code (text), sap_id (text) -- internal reference codes
- candidate_name (text) -- NAME MATCHING RULE, same as recruiter_name
  below: a person asking about a specific candidate by name may type it
  slightly differently than it's stored (different spacing, a missing
  middle name, minor spelling variation). Do NOT use an exact `=` match
  by default -- use `candidate_name LIKE '%<name>%'` instead, and
  ALWAYS include candidate_name itself in the SELECT so the actual
  matched value is visible. A real, verified bug: searching for a
  candidate by their exact correct name still returned "not found"
  because of this exact-match issue. If the LIKE match returns more
  than one distinct candidate, do NOT guess -- list the matches and ask
  which one, same as the recruiter_name disambiguation rule.
  Example: SELECT candidate_name, project_city FROM candidates_masked_scoped
  WHERE candidate_name LIKE '%Lavanya%Adapala%'
- candidate_phone (text, MASKED)
- candidate_email (text, MASKED) -- primary email
- candidate_email_2 (text, MASKED) -- secondary email, often blank
- candidate_email_3 (text, MASKED) -- tertiary email, often blank
- DOB (always NULL, fully hidden)
- client (text), client_track (text), end_client (text) -- client is the
  company name a candidate is placed/working with. IMPORTANT: when a
  question says "candidates with <company>", "candidates working with
  <company>", "candidates at <company>", or similar -- and <company> is
  a company/client name (e.g. Accenture, HCL, Cognizant, LTIMindtree,
  etc.) -- this means WHERE client = '<company>', NOT a skills search.
  A well-known consulting/staffing client name is never a technical
  skill, so do not search primary_skills/secondary_skills for a company
  name under any circumstance -- that produces a meaningless zero-match
  result. Only search primary_skills/secondary_skills when the question
  is clearly about a technology/tool/programming language (e.g. "Java",
  "AWS", "Python").
- job_title (text)
- primary_skills (text), secondary_skills (text) -- free text, use LIKE
  for matching TECHNICAL skills/technologies only (e.g. WHERE
  primary_skills LIKE '%Java%') -- never search these columns for a
  company/client name (see the client column note above).
- start_date (date), end_date (date) -- end_date is NULL for all
  currently Active candidates (they simply have no end date yet, this is
  expected, not missing data). Use end_date <= CURDATE() for a plain
  "rolloff" style question (any candidate whose engagement has ended,
  POINT-IN-TIME / HISTORICAL COMPARISON QUESTIONS -- IMPORTANT: this
  data has NO stored historical snapshots (no "headcount as of last
  quarter" table) -- but questions like "how many active contractors
  did we have last quarter/N months ago" or "how does this compare to
  3 months ago" ARE still answerable, as an APPROXIMATION, using
  start_date and end_date: a candidate was "active as of" a given past
  date if start_date <= that_date AND (end_date IS NULL OR end_date >
  that_date). Example, for "how many were active 3 months ago":
  SELECT COUNT(*) FROM candidates_masked_scoped
  WHERE start_date <= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
  AND (end_date IS NULL OR end_date > DATE_SUB(CURDATE(), INTERVAL 3 MONTH))
  Do NOT decline these questions as "outside our database" or route
  them to general knowledge -- they ARE answerable this way. This IS a
  database question (usually is_insight=true, since it involves
  comparing two points in time). ALWAYS disclose that this is an
  approximation based on start/end dates, not a literal stored
  historical record, when answering this way. Also note: since this
  approximation is calculated relative to CURDATE() (today), the exact
  result can shift by a small amount day to day as "today" itself
  moves forward -- this is expected, normal behavior, not a bug, if the
  same question asked on two different days gives a slightly different
  number for "N months ago".
  CRITICAL -- NEVER SPLIT A HISTORICAL POINT-IN-TIME COUNT BY THE
  CURRENT Status FIELD: the Status column (Active/Inactive) reflects
  ONLY today's status -- it has NO historical memory of what a
  candidate's status was at some past date. A question like "how many
  candidates did Vinay's BU have 6 months ago" must return ONE single
  count from the start_date/end_date approximation above -- NEVER
  split that historical count into "Active" and "Inactive" sub-totals,
  since that requires knowing PAST status, which this data cannot
  provide. A real, verified bug: an answer stated "76 Active + 15
  Inactive = 91 candidates 6 months ago" -- the "91" and the "15
  Inactive" portion were fabricated; the correctly-computed historical
  count was 76 alone (matching the point-in-time formula above exactly,
  with nothing added on top).
  CRITICAL -- NEVER CLAIM "EVER BEEN ACTIVE/INACTIVE" OR ANY OTHER
  STATUS-HISTORY CONCEPT: this schema stores only ONE current Status
  value per candidate, with no log of status changes over time. NEVER
  state a number for "candidates who have ever been active", "used to
  be active", or similar phrasing -- this cannot be determined from
  this data at all, and stating such a number (even one that sounds
  plausible) is unsupported and must not be presented as fact. If asked
  something requiring status history, clearly say this isn't tracked.
  QUARTER / HALF-YEAR / FISCAL PERIOD DEFINITIONS -- CONFIRMED WITH THE
  BUSINESS: this company uses a standard CALENDAR fiscal year (January
  to December), NOT an offset fiscal year. Quarters and halves are:
  Q1 = January 1 - March 31
  Q2 = April 1 - June 30
  Q3 = July 1 - September 30
  Q4 = October 1 - December 31
  H1 (first half) = January 1 - June 30
  H2 (second half) = July 1 - December 31
  "This year" means the current calendar year (use YEAR(CURDATE())).
  "LAST YEAR" means the PREVIOUS calendar year -- use
  (YEAR(CURDATE()) - 1), NOT YEAR(CURDATE()). A real, verified bug:
  "Q3 last year" was answered as 0 active/inactive candidates, because
  the query likely used the WRONG year (this year, or a malformed
  date) instead of correctly subtracting 1 from the current year.
  Example -- "how many were active at the end of Q3 last year":
  SELECT COUNT(*) FROM candidates_masked_scoped WHERE start_date <=
  CONCAT(YEAR(CURDATE()) - 1, '-09-30') AND (end_date IS NULL OR
  end_date > CONCAT(YEAR(CURDATE()) - 1, '-09-30'))
  "Last quarter" / "last year" means the immediately preceding
  calendar quarter/year relative to today, NOT a rolling N-day window
  -- e.g. if today is in Q3, "last quarter" means Q2 of this same
  year, with FIXED boundaries (April 1 - June 30), not "the last 90
  days from today". Use the point-in-time technique above with these
  FIXED calendar boundaries rather than DATE_SUB rolling windows when a
  question names a specific quarter/half/year (Q1, Q2, "first half",
  "this year", etc.) -- reserve the rolling DATE_SUB approach only for
  genuinely relative phrasing like "3 months ago" or "last 90 days"
  that doesn't name a calendar period.
  Example -- "how many candidates were active at the end of Q2 this
  year": SELECT COUNT(*) FROM candidates_masked_scoped WHERE start_date <=
  CONCAT(YEAR(CURDATE()), '-06-30') AND (end_date IS NULL OR end_date >
  CONCAT(YEAR(CURDATE()), '-06-30'))
  Example -- "how many candidates started in Q2 this year": SELECT
  COUNT(*) FROM candidates_masked_scoped WHERE start_date BETWEEN
  CONCAT(YEAR(CURDATE()), '-04-01') AND CONCAT(YEAR(CURDATE()), '-06-30')
  CRITICAL -- CONSISTENCY ACROSS MULTI-PERIOD COMPARISONS: when a
  question compares the SAME metric across multiple periods (e.g. "Q1
  vs Q3 this year"), use the EXACT SAME query logic/structure for
  every period -- only the date literals should differ, nothing else
  about the WHERE clause's shape. A real, verified, serious
  reliability bug: asking for Q1's active headcount alone correctly
  returned 513, but asking the SAME Q1 active headcount as part of a
  "Q1 vs Q3" comparison incorrectly returned 0 in the same session --
  the identical real-world fact must never produce different answers
  depending on what else is in the question. When building a
  multi-period comparison, mentally verify each period's query is
  structurally identical to how you'd answer it as a standalone
  question, only changing the date boundaries.
  Example -- "compare headcount between Q1 and Q3 this year":
  SELECT 'Q1' AS period, COUNT(*) AS active_headcount FROM candidates_masked_scoped
  WHERE start_date <= CONCAT(YEAR(CURDATE()), '-03-31')
  AND (end_date IS NULL OR end_date > CONCAT(YEAR(CURDATE()), '-03-31'))
  UNION ALL
  SELECT 'Q3' AS period, COUNT(*) FROM candidates_masked_scoped
  WHERE start_date <= CONCAT(YEAR(CURDATE()), '-09-30')
  AND (end_date IS NULL OR end_date > CONCAT(YEAR(CURDATE()), '-09-30'))
  IN-PROGRESS QUARTER HANDLING: if a question asks about the CURRENT
  quarter (e.g. "Q3" when today's date is actually within Q3), that
  quarter hasn't finished yet -- using its theoretical future end date
  would count based on a date that hasn't happened. Instead, use
  CURDATE() itself as the boundary for the current, still-in-progress
  quarter (not the quarter's official end date), and explicitly
  disclose that the quarter is still in progress so this is a live,
  current snapshot rather than a completed-quarter figure.
  CRITICAL -- NEVER HARDCODE A LITERAL YEAR NUMBER: for "this year",
  "this quarter", "Q2", etc. (with no year explicitly stated), you MUST
  compute the year dynamically using YEAR(CURDATE()) in the SQL itself
  -- NEVER write a literal year like '2023' or any other specific year
  in the query unless the person's question explicitly names that
  year (e.g. "in 2023" or "in Q2 2024"). A real, verified, serious bug:
  a question asking about "this year" produced SQL using the literal
  year 2023 -- a year with no connection to the actual current date at
  all. Always use CONCAT(YEAR(CURDATE()), '-MM-DD') to build date
  boundaries dynamically, never a hardcoded year string.
  CRITICAL -- "HOW MANY CANDIDATES DID WE HAVE IN [PERIOD]" MEANS
  TOTAL/ACTIVE HEADCOUNT, NOT "STARTED": a question phrased as "how
  many candidates did we have in Q2" or "how many candidates were there
  in the first half" is asking for a HEADCOUNT SNAPSHOT (the
  point-in-time active-count technique, typically as of the END of that
  period) -- NOT "how many candidates started" during that period,
  which is a different, narrower metric. Only interpret a question as
  asking about "started" if it explicitly says "started", "began", "new
  candidates", or similar -- a plain "how many did we have" defaults to
  the broader active/total headcount interpretation.
  regardless of whether it ended on schedule).
  IMPORTANT -- "UNEXPECTED rolloff" is a DIFFERENT, more specific
  business term, confirmed with the business: it means a candidate whose
  end_date is EARLIER than their originally planned sow_end_date (an
  early exit vs. the plan), NOT simply any past rolloff. Use:
  end_date IS NOT NULL AND sow_end_date IS NOT NULL AND end_date < sow_end_date
  Do not use plain "end_date <= CURDATE()" for "unexpected" rolloff
  questions -- that would overcount by including candidates who left
  exactly on schedule. See the two separate examples below for each.
  DEFAULT DIRECTION -- READ CAREFULLY: the word "unexpected" MUST be
  explicitly present in the question (or clearly implied by history,
  e.g. a direct follow-up to a question that already said
  "unexpected") for the unexpected-rolloff definition to apply. A plain
  question like "how many roll offs does HCL have", "how many rolloffs
  do we have", "roll off count for X" -- with NO word like "unexpected"
  anywhere -- ALWAYS means the plain end_date <= CURDATE() definition,
  and is a SIMPLE, single-fact question (is_insight should be FALSE for
  it, just like "how many candidates does X have"). Do NOT default to
  the unexpected definition just because a lot of guidance about
  unexpected rolloffs exists elsewhere in this schema -- when in doubt,
  a plain "rolloff" with no qualifying word means the plain definition.
  "ON-SCHEDULE" / "EXCLUDING UNEXPECTED" ROLLOFF -- a third, named
  derived metric: a question like "roll offs excluding unexpected
  ones", "on-schedule rolloffs", or "rolloffs that happened as planned"
  means the SET DIFFERENCE: plain rolloffs MINUS unexpected rolloffs --
  i.e. candidates whose end_date has passed, but NOT earlier than their
  sow_end_date. Correct SQL:
  SELECT COUNT(*) FROM candidates_masked_scoped
  WHERE end_date IS NOT NULL AND end_date <= CURDATE()
  AND NOT (sow_end_date IS NOT NULL AND end_date < sow_end_date)
  Do NOT just subtract the two numbers yourself in prose (that would
  violate the no-self-calculation rule) -- write this as ONE single
  query using the SQL pattern above, so the database computes the
  correct set-difference directly. A real, verified bug: this exact
  question was answered as "67" for HCL when the correct value (68
  total minus 45 unexpected) is 23 -- a completely wrong number from
  misinterpreting what "excluding" meant, not just an arithmetic slip.
- sow_end_date (date), sow_end_month (text), extended_sow_date (date,
  sparsely populated -- only ~2 of 1121 rows have this filled)
  IMPORTANT -- FORWARD-LOOKING "ENDING SOON" QUESTIONS: for any question
  about candidates/contracts ENDING in the future (e.g. "candidates
  ending their contract in the next 30/60/90 days", "who is rolling off
  soon", "upcoming contract expirations"), you MUST use sow_end_date
  (the planned end date), NOT end_date. end_date is NULL for all
  currently Active candidates (see the end_date note above) -- so
  filtering active/ongoing engagements by a future end_date will always
  incorrectly return zero, since active people simply don't have an
  end_date populated yet. sow_end_date is the planned/scheduled end
  date and is what should be checked for anything forward-looking.
  Example: "candidates ending in the next 30 days" ->
  WHERE sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
  MULTI-WINDOW QUESTIONS: if a question explicitly asks for MULTIPLE
  time windows at once (e.g. "in the next 30/60/90 days"), you MUST
  compute ALL of the requested numbers in a single query and state ALL
  of them in the answer -- never answer just the first window and treat
  the rest as an optional follow-up. Use one query with multiple
  conditional sums, e.g.:
  SELECT
    SUM(CASE WHEN sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS next_30,
    SUM(CASE WHEN sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 60 DAY) THEN 1 ELSE 0 END) AS next_60,
    SUM(CASE WHEN sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 90 DAY) THEN 1 ELSE 0 END) AS next_90
  FROM candidates_masked_scoped
- extension_status (text) -- WARNING: this column is 100% blank/empty
  across every single row in this data. Never use it to check whether
  any action, extension, or follow-up has occurred -- it holds no
  signal at all right now.
- extended_count (text)
NO RATE-REVIEW TRACKING: there is no column anywhere in this data
representing when a pay_rate/client_rate was last reviewed or updated
(no "rate_last_reviewed_date" or similar field exists). If asked "which
contractors are on rates that haven't been reviewed in a long time",
do NOT attempt to answer this by querying for some proxy and stating a
count like "0 unreviewed" -- that implies false certainty. Instead,
run a simple query showing current pay rates and clearly state in your
answer that rate-review-date history specifically isn't tracked in this
data, so that particular detail can't be determined -- but this is
STILL a normal database_question about pay rate data (is_insight can
still be true if it's asking for analysis) -- this is NOT a signal to
decline the question as out-of-scope or route it to general knowledge.
A missing column is a normal, answerable-with-caveats database
limitation, not a reason to refuse the whole question.
CRITICAL -- WHICH COLUMN TO USE FOR THE "CURRENT PAY RATES" FALLBACK:
the fallback query showing current pay rates MUST use pay_rate_numeric
grouped by pay_rate_currency and pay_rate_payment_basis (the exact same
established pattern as any other pay-rate question -- see the
pay_rate_numeric notes above) -- NEVER query or display the raw
pay_rate TEXT column directly. A real, verified bug: a fallback query
grouped on the raw pay_rate column and displayed dozens of nearly
useless single-row entries like "20+HST", "62 + GST", producing an
unreadable wall of messy raw text instead of a clean, useful summary.
Correct fallback query:
SELECT pay_rate_currency, pay_rate_payment_basis,
AVG(pay_rate_numeric) AS avg_rate, COUNT(*)
FROM candidates_masked_scoped
GROUP BY pay_rate_currency, pay_rate_payment_basis
ORDER BY COUNT(*) DESC
"OVERDUE CANDIDATE" -- a specific business term, defined as: a candidate
  whose sow_end_date has already passed, where the responsible Account
  Manager has not yet taken action (e.g. connecting with the candidate,
  client, or vendor). IMPORTANT: there is NO column in this data that
  tracks whether an Account Manager actually took action -- this
  business fact is not captured anywhere. The best available PROXY is:
  sow_end_date < CURDATE() AND end_date IS NULL
  (i.e. the SOW date passed, but the record was never formally closed
  out with an end_date -- a reasonable but IMPERFECT signal for "no
  action/closure happened"). Verified count using this proxy: 107 of
  1121 candidates, out of 468 total whose sow_end_date has passed.
  MANDATORY: whenever answering an "overdue candidate" question, you
  MUST explicitly disclose that this is an approximation based on
  missing end_date, since Account Manager action itself isn't tracked
  in this data -- never present the count as a verified fact about
  whether anyone actually followed up.
- contractor_status (text) -- e.g. 'C2C'
- project_city (text), project_state (text), project_country (text)
  IMPORTANT -- project_state stores US STATE ABBREVIATIONS (e.g. 'TX',
  'FL', 'CA'), NOT full state names. A real, verified case: searching
  for project_state LIKE '%Texas%' found nothing, even though 10 real
  candidates exist with project_state = 'TX' -- "Texas" and "TX" never
  match via LIKE since the full word never appears in the data. If a
  question names a full US state (Texas, Florida, California, etc.),
  convert it to the standard 2-letter abbreviation before filtering --
  e.g. "candidates in Texas" means WHERE project_state = 'TX', not
  LIKE '%Texas%'.
  (9 rows previously had garbage values 'YES'/'CAD' in this column and
  were cleaned to NULL -- real values now: USA, CAN, IND, Brazil, NULL)
  REGIONAL RATE COMPARISON QUESTIONS: for "are our rates competitive by
  region" style questions, GROUP BY project_country AND
  pay_rate_currency together (not country alone) -- a country doesn't
  guarantee a single currency (e.g. some CAN-based candidates could in
  principle be paid in USD), so grouping by country alone risks the
  same currency-blending problem as ungrouped pay rate averages
  elsewhere in this schema. Also apply the same pattern for comparing
  pay_rate_numeric vs client_rate_numeric together (require
  pay_rate_currency = client_rate_currency, same as the margin
  calculation notes above).
- pay_rate_currency (text) -- values: 'USD', 'CAD', 'INR', 'NA'
  (a 'CAN' typo variant was found and normalized to 'CAD' during cleanup)
- pay_rate (text) -- RAW original value, inconsistent formats: plain
  numbers, "$135000 + Benefits", comma-thousands separators like
  "2,20,000" (Indian lakh notation), and ~44 rows with a "X | Y" pattern
  (e.g. "67 | 11") whose meaning is NOT confirmed -- do not assume what
  the second number means. Prefer pay_rate_numeric for any math.
- pay_rate_numeric (decimal) -- CLEANED numeric extraction from pay_rate
  (commas stripped, first number extracted). For the ~44 "X | Y" rows,
  only the first (X) number is captured here.
  CRITICAL: pay_rate_numeric mixes wildly different scales depending on
  pay_rate_payment_basis (hourly ~$60-70 vs monthly/annual salaries in
  the hundreds of thousands) AND pay_rate_currency (USD vs CAD vs INR).
  NEVER average or sum pay_rate_numeric without GROUP BY both
  pay_rate_currency AND pay_rate_payment_basis together -- averaging
  across different currencies or bases produces meaningless numbers.
  THIS RULE APPLIES EVEN IF THE QUESTION DOES NOT MENTION A SPECIFIC
  CURRENCY OR BASIS AT ALL -- e.g. "what's the average pay rate for
  candidates?" (no currency/basis named) is NOT a signal to run a
  single blind AVG() across everything. It means: GROUP BY
  pay_rate_currency, pay_rate_payment_basis and return the breakdown
  (as a table, per the formatting rules), so each group's average is
  shown separately and meaningfully -- never collapse them into one
  blended number just because the question was phrased generically.
  A verified real example of the bug this causes: a blind, ungrouped
  AVG(pay_rate_numeric) across this data returns approximately 8274,
  which is a meaningless number that matches no real group at all.
- pay_rate_payment_basis (text) -- e.g. 'Hourly', 'Monthly', 'Annum'
- client_rate_currency (text), client_rate (text, same caveats as
  pay_rate), client_rate_numeric (decimal, same caveats as
  pay_rate_numeric), client_rate_payment_basis (text)
- margin_value (text) -- kept as text, may contain 'NA' or non-numeric
  values. WARNING: this stored value appears STALE/UNRELIABLE for a
  meaningful portion of rows -- spot-checking confirmed roughly half the
  rows match client_rate_numeric - pay_rate_numeric exactly, but the
  other half are off by inconsistent, non-proportional amounts (e.g. one
  row's margin_value was 15.64 while the current rates imply 27.00) --
  this pattern suggests margin_value was calculated once and never
  recalculated after pay_rate/client_rate were later updated, rather
  than reflecting a different legitimate business formula. For ANY
  "what is the margin" question, calculate it live as
  (client_rate_numeric - pay_rate_numeric) instead of reading the stored
  margin_value column -- and remember to only do so where both pay_rate
  and client_rate share the same currency and payment basis (see the
  pay_rate_numeric note above).
  CRITICAL, RESTATED FOR CLIENT-PROFITABILITY QUESTIONS SPECIFICALLY:
  a question like "which clients give us the best/worst margins" or
  "which clients are barely profitable" is asking about client
  profitability -- this STILL means: use client_rate_numeric -
  pay_rate_numeric, NEVER SUM or AVERAGE the raw margin_value column,
  and GROUP BY client, pay_rate_currency, pay_rate_payment_basis
  together (summing/averaging margin across different currencies
  produces meaningless, wildly wrong numbers in the millions -- a real
  verified bug: an ungrouped/wrong-column margin query produced a
  stated average margin of -1,489,066.90 for one client, which is not
  a plausible per-candidate margin figure by any measure). Correct
  pattern:
  SELECT client, pay_rate_currency, pay_rate_payment_basis,
  AVG(client_rate_numeric - pay_rate_numeric) AS avg_margin, COUNT(*)
  FROM candidates_masked_scoped
  WHERE pay_rate_currency = client_rate_currency
  AND pay_rate_payment_basis = client_rate_payment_basis
  GROUP BY client, pay_rate_currency, pay_rate_payment_basis
  ORDER BY avg_margin DESC
  CRITICAL -- CONSISTENT FILTERS ACROSS RELATED MARGIN SUB-QUESTIONS: if
  a margin/profitability insight question needs BOTH a count of
  candidates with positive/negative margin AND an average margin figure
  (as separate sub-questions), BOTH sub-questions MUST use the EXACT
  SAME WHERE conditions (pay_rate_currency = client_rate_currency AND
  pay_rate_payment_basis = client_rate_payment_basis) -- never let one
  sub-question count without this filter while another applies it, as
  that produces self-contradicting results (a real, verified bug: one
  client showed "79 positive-margin candidates" from an uncensored
  count, alongside "N/A average margin" from a properly-filtered
  average -- an internally inconsistent, confusing pair of numbers that
  should never both appear together like that).
  CRITICAL -- PLAIN "HOW MUCH IS OUR MARGIN" QUESTIONS (no specific
  client mentioned) ALSO NEED GROUPING, same rule as everything above:
  a simple company-wide "what is our margin" or "how much is our
  margin" question must STILL be grouped by pay_rate_currency and
  pay_rate_payment_basis -- NEVER compute one single blended average
  margin across the whole company. A real, verified bug: an ungrouped
  company-wide margin query produced a stated "average margin across
  all candidates" of -2382.04, a meaningless negative number caused by
  blending USD hourly margins (tens of dollars) with INR monthly/annual
  margins (hundreds of thousands) together -- even though the
  PER-CLIENT breakdown shown in the same answer was correctly grouped
  and plausible. If a question asks for one overall margin figure with
  no client/currency/basis specified, answer with the grouped
  breakdown (by currency + payment basis) directly -- do NOT also state
  a single blended "overall average" summary number, since no single
  correct company-wide average margin figure exists when currencies and
  payment bases differ this much.
  CRITICAL -- RANKING ENTITIES (BU/client/recruiter) BY MARGIN, WHEN AN
  ENTITY HAS MULTIPLE CURRENCY/BASIS SUBGROUPS: do NOT collapse an
  entity's margin down to ONE number by picking whichever currency/
  basis subgroup happens to have the highest (or most extreme) average
  -- this is just as misleading as blending, arguably worse, because it
  silently misrepresents a tiny subgroup as if it applies to the whole
  entity. A real, verified, SERIOUS bug: a BU-ranking answer stated
  "Vinay's BU has the best average margin at 315030.71" alongside
  Vinay's FULL headcount of 209 -- but that 315030.71 figure actually
  came from only 7 of those 209 people (an INR/Monthly subgroup); the
  other 202 people in Vinay's BU actually average around $7.66/hour,
  nothing close to that number. Presenting one atypical subgroup's
  average next to an unrelated total headcount is a serious,
  business-relevant error, not a rounding nuance.
  CORRECT APPROACH: when ranking BUs/clients/recruiters by margin,
  ALWAYS show the FULL breakdown table -- one row per (entity, currency,
  payment_basis) combination, each with its OWN correct headcount for
  that specific combination (matching the pattern already used
  correctly for "which clients give us the best margins", which
  produces multiple rows per client when a client spans more than one
  currency/basis). NEVER reduce a multi-subgroup entity to a single
  summary row with one cherry-picked number and a mismatched total
  headcount, for BUs, clients, OR recruiters.
- contractor_vendor_name (text)
- vendor_contact_person (text) -- "HANDLED BY" a specific person, when
  referring to a vendor/staffing-agency contact (not a recruiter or
  account manager), means this column -- e.g. "handled by Neelima
  Inampudi" means vendor_contact_person LIKE '%Neelima%'. NOTE: this
  interpretation is a reasonable best guess, not yet confirmed with the
  business -- if "handled by" could also mean recruiter_name or an
  account_manager column in a given context, treat it as ambiguous and
  consider asking for clarification rather than assuming.
  CRITICAL -- MULTI-CRITERIA SEARCHES (job title + several skills +
  a contact person, all at once): a real, verified bug happened here --
  a candidate (Pujan Kafle) who genuinely matched every single stated
  criterion (job title "Cloud engineer", skills AWS/Azure/Python/Java/
  SQL/DevOps/Data Visualization/PM tools split across primary_skills
  and secondary_skills, and vendor_contact_person "Neelima Inampudi")
  was incorrectly reported as "no match found". When a question lists
  MULTIPLE required skills alongside a job title and/or a contact
  person, build the query as follows:
  - job_title: use LIKE '%...%', not an exact match (phrasing/casing varies)
  - EACH individual skill mentioned gets its OWN LIKE condition against
    EITHER primary_skills OR secondary_skills (a skill could be stored
    in either column) -- do NOT try to match the entire skill list as
    one literal concatenated string, and do NOT assume all skills live
    in the same column.
  - When a person lists several skills as requirements for one
    candidate (e.g. "skills are AWS, Azure, Python..."), this normally
    means the candidate should have ALL of them -- combine each skill's
    condition with AND, not OR, unless the question clearly asks for
    "any of" these skills instead.
  - Combine the job title, all skill conditions, and any contact-person
    condition together with AND across categories.
  - "END CLIENT [name]" means the end_client column (LIKE '%...%', not
    exact match) -- this is a DIFFERENT column from "client", and is
    another common filter dimension in these multi-criteria searches,
    alongside job_title, skills, and vendor_contact_person. A real,
    verified case: "candidate with end client Point32Health Plan, job
    title Kafka Engineer, skill is Kafka Administration" should match
    end_client LIKE '%Point32Health%' AND job_title LIKE '%Kafka
    Engineer%' AND (primary_skills LIKE '%Kafka Administration%' OR
    secondary_skills LIKE '%Kafka Administration%') -- combine ALL
    stated criteria (end_client, job_title, skills, contact person --
    whichever are present in the question) together with AND.
  Correct pattern for the Pujan Kafle case:
  SELECT candidate_name, job_title, primary_skills, secondary_skills, vendor_contact_person
  FROM candidates_masked_scoped
  WHERE job_title LIKE '%Cloud engineer%'
  AND (primary_skills LIKE '%AWS%' OR secondary_skills LIKE '%AWS%')
  AND (primary_skills LIKE '%Azure%' OR secondary_skills LIKE '%Azure%')
  AND (primary_skills LIKE '%Python%' OR secondary_skills LIKE '%Python%')
  AND vendor_contact_person LIKE '%Neelima%'
  CRITICAL -- DON'T CONTRADICT A RECORD ALREADY SHOWN IN THIS
  CONVERSATION: if recent history already displayed a specific
  candidate's full details, and the new question asks whether that
  same candidate satisfies some criteria, check the ALREADY-DISPLAYED
  details from history directly rather than blindly re-running a fresh
  search -- a real, verified bug: after correctly displaying Pujan
  Kafle's full matching details, a follow-up asking "does this person
  satisfy my previous query" incorrectly said no, contradicting the
  record just shown in the very same conversation.
- vendor_contact_number (text, MASKED)
- vendor_contact_email (text, MASKED)
- bu_head (text) -- Business Unit head's name. Use this for any
  "business unit"/"BU" question (e.g. "candidates in Vinay's BU" means
  bu_head = 'Vinay'). NOTE: unlike the previous schema, there is no
  bu_name column in this schema at all -- don't reference it, it doesn't
  exist here.
- bu_head_emailid (text, MASKED)
- cal_name (text), dal_name (text), dm_name (text), add_name (text)
- passthrough_owner (text), passthrough_support (text)
- lead_recruiter (text), team_lead_name (text)
- recruiter_name (text) -- use for "candidates per recruiter" questions.
  WARNING: this column contains a number of values that are NOT actual
  recruiter names, but process/status codes. The FULL known list is:
  'PT', 'PTR', 'TBD', 'NA', 'Vendor Change', 'Vendor consolidation',
  'Redeployement', 'Redeployment'.
  DEFAULT RULE: when a question asks to exclude "non-recruiter codes" or
  asks "how many candidates have a real/actual recruiter" WITHOUT naming
  specific codes, exclude this FULL list, not just a subset -- this
  avoids ambiguity between similar-sounding questions producing
  different numbers. Only use a narrower/different list if the question
  explicitly names specific codes to exclude (e.g. "excluding just PT
  and PTR" should exclude only those two, and the answer should make
  clear that's a narrower filter than the full known non-recruiter list).
  When asked "how many recruiters do we have" or "list our recruiters",
  exclude the full non-recruiter list. When asked "how many candidates
  per recruiter" as a full breakdown, it's fine to include them as-is
  (they represent real candidate counts, just not tied to an individual
  recruiter) but don't refer to them as "recruiters" in the phrased
  answer -- call them out separately, e.g. "X candidates are tagged with
  non-recruiter status codes like PT/PTR/TBD."
  Also expect the same person's name to appear with slightly different
  spelling/formatting across rows (e.g. "Guna Sekaran" vs "Guna Sekaran
  S", "Midunsathya" vs "Midunsathyaa") -- these are very likely the same
  individual, not different recruiters, though this hasn't been
  independently confirmed against a master recruiter list.
  NAME MATCHING RULE (important -- read carefully): a real person asking
  about a recruiter will often type a partial or informal version of
  the name (e.g. "Selvakumar" instead of the full "Selvakumar M" stored
  in the data). To handle this reliably:
  - When a question names a recruiter, do NOT use an exact `=` match by
    default -- use `recruiter_name LIKE '%<name>%'` instead, and ALWAYS
    include recruiter_name itself in the SELECT/GROUP BY so the actual
    matched value(s) are visible in the result, e.g.:
    SELECT recruiter_name, COUNT(*) AS candidate_count
    FROM candidates_masked_scoped WHERE recruiter_name LIKE '%Selvakumar%'
    GROUP BY recruiter_name
  - This query's result will naturally reveal whether there is ONE
    matching recruiter or SEVERAL different ones with similar names
    (e.g. "Selvakumar M" and "Selvakumar J" might both match
    "%Selvakumar%"). The answer-phrasing step (see ANSWER_SYSTEM_PROMPT)
    is responsible for deciding whether to answer directly (one match)
    or ask the person to clarify which one they meant (multiple
    distinct matches) -- never silently guess or combine multiple
    different people's counts together as if they were one person.
- recruiter_emp_id (text)
- deal_pt_ptr (text)
- client_project_manager (text), client_resource_manager (text)
- client_resource_manager_email (text, MASKED)
- account_manager_1 through account_manager_8 (text, ALL MASKED) --
  IMPORTANT: in THIS schema these are EMAIL ADDRESSES, not names (this
  is different from the old schema where these were person names). A
  candidate can have multiple account managers spread across these 8
  columns -- check all 8 with OR conditions for "handled by account
  manager X" style questions, matching on the visible domain/prefix
  since the values are masked.

Notes for writing SQL:
- If a question asks for BOTH a breakdown AND an overall total in the
  same request (e.g. "candidates per recruiter, and the total"), do NOT
  attempt to combine these into one clever query (e.g. GROUP BY ... WITH
  ROLLUP) -- that approach has caused real permission and labeling bugs
  in this environment and is not worth the complexity. Instead, simply
  answer with the breakdown as normal, and separately mention the
  overall total using a plain COUNT(*) style calculation over the same
  filter conditions. Two simple, correct pieces of information beat one
  fragile combined query.
- Always use table name "candidates_masked_scoped" -- never "candidates".
- Only SELECT statements.
- This schema has NO linkedin_url, NO work_email, NO reporting_manager_*
  fields, and NO client_tag_poc_* fields -- do not reference these column
  names, they don't exist in this version of the table.
- Status column is capitalized "Status", not "status".
""".strip(),
    examples=(
        Example(
            question="How many candidates do we have in total?",
            sql="SELECT COUNT(*) FROM candidates_masked_scoped",
        ),
        Example(
            question=(
                "Give a candidate who is a Cloud engineer, skills are AWS, Azure, Python, "
                "Java, SQL DevOps, Data Visualization, PM tools handled by Neelima Inampudi"
            ),
            sql=(
                "SELECT candidate_name, job_title, primary_skills, secondary_skills, "
                "vendor_contact_person FROM candidates_masked_scoped "
                "WHERE job_title LIKE '%Cloud engineer%' "
                "AND (primary_skills LIKE '%AWS%' OR secondary_skills LIKE '%AWS%') "
                "AND (primary_skills LIKE '%Azure%' OR secondary_skills LIKE '%Azure%') "
                "AND (primary_skills LIKE '%Python%' OR secondary_skills LIKE '%Python%') "
                "AND (primary_skills LIKE '%Java%' OR secondary_skills LIKE '%Java%') "
                "AND vendor_contact_person LIKE '%Neelima%'"
            ),
        ),
        Example(
            question=(
                "give a candidate with end client Point32Health Plan job title Kafka "
                "Engineer skill is Kafka Administration"
            ),
            sql=(
                "SELECT candidate_name, job_title, primary_skills, secondary_skills, end_client "
                "FROM candidates_masked_scoped "
                "WHERE end_client LIKE '%Point32Health%' "
                "AND job_title LIKE '%Kafka Engineer%' "
                "AND (primary_skills LIKE '%Kafka Administration%' OR secondary_skills LIKE '%Kafka Administration%')"
            ),
        ),
        Example(
            question="Which clients give us the best margins?",
            sql=(
                "SELECT client, pay_rate_currency, pay_rate_payment_basis, "
                "AVG(client_rate_numeric - pay_rate_numeric) AS avg_margin, COUNT(*) AS candidate_count "
                "FROM candidates_masked_scoped "
                "WHERE pay_rate_currency = client_rate_currency "
                "AND pay_rate_payment_basis = client_rate_payment_basis "
                "AND client IS NOT NULL AND client != '' "
                "GROUP BY client, pay_rate_currency, pay_rate_payment_basis "
                "HAVING COUNT(*) >= 3 "
                "ORDER BY avg_margin DESC"
            ),
        ),
        Example(
            question="Which BU has the best margins?",
            sql=(
                "SELECT bu_head, pay_rate_currency, pay_rate_payment_basis, "
                "AVG(client_rate_numeric - pay_rate_numeric) AS avg_margin, COUNT(*) AS candidate_count "
                "FROM candidates_masked_scoped "
                "WHERE pay_rate_currency = client_rate_currency "
                "AND pay_rate_payment_basis = client_rate_payment_basis "
                "AND bu_head IS NOT NULL AND bu_head != '' "
                "GROUP BY bu_head, pay_rate_currency, pay_rate_payment_basis "
                "ORDER BY avg_margin DESC"
            ),
        ),
        Example(
            question="How many overdue candidates do we have?",
            sql=(
                "SELECT COUNT(*) FROM candidates_masked_scoped "
                "WHERE sow_end_date IS NOT NULL AND sow_end_date < CURDATE() "
                "AND end_date IS NULL"
            ),
        ),
        Example(
            question="How many candidates do we have with Accenture?",
            sql="SELECT COUNT(*) FROM candidates_masked_scoped WHERE client = 'Accenture'",
        ),
        Example(
            question="How many candidates does Selvakumar have?",
            sql=(
                "SELECT recruiter_name, COUNT(*) AS candidate_count "
                "FROM candidates_masked_scoped WHERE recruiter_name LIKE '%Selvakumar%' "
                "GROUP BY recruiter_name"
            ),
        ),
        Example(
            question="How many candidates are Active vs Inactive?",
            sql="SELECT Status, COUNT(*) FROM candidates_masked_scoped GROUP BY Status",
        ),
        Example(
            question="How many candidates have Java as a primary or secondary skill?",
            sql=(
                "SELECT COUNT(*) FROM candidates_masked_scoped WHERE "
                "primary_skills LIKE '%Java%' OR secondary_skills LIKE '%Java%'"
            ),
        ),
        Example(
            question="What's the average pay rate for candidates?",
            sql=(
                "SELECT pay_rate_currency, pay_rate_payment_basis, "
                "AVG(pay_rate_numeric) AS avg_pay_rate, COUNT(*) AS candidate_count "
                "FROM candidates_masked_scoped "
                "GROUP BY pay_rate_currency, pay_rate_payment_basis "
                "ORDER BY candidate_count DESC"
            ),
        ),
        Example(
            question="What is the average hourly pay rate in USD?",
            sql=(
                "SELECT AVG(pay_rate_numeric) FROM candidates_masked_scoped "
                "WHERE pay_rate_currency = 'USD' AND pay_rate_payment_basis = 'Hourly'"
            ),
        ),
        Example(
            question="How many candidates does each recruiter have?",
            sql=(
                "SELECT COALESCE(recruiter_name, 'Unassigned') AS recruiter, "
                "COUNT(*) AS candidate_count FROM candidates_masked_scoped "
                "GROUP BY recruiter_name ORDER BY candidate_count DESC"
            ),
        ),
        Example(
            question="How many rolloffs have happened till date?",
            sql=(
                "SELECT COUNT(*) FROM candidates_masked_scoped "
                "WHERE end_date IS NOT NULL AND end_date <= CURDATE()"
            ),
        ),
        Example(
            question="How many unexpected rolloffs have we had, BU wise? Which BU has the most?",
            sql=(
                "SELECT bu_head, COUNT(*) AS unexpected_rolloffs FROM candidates_masked_scoped "
                "WHERE end_date IS NOT NULL AND sow_end_date IS NOT NULL "
                "AND end_date < sow_end_date "
                "GROUP BY bu_head ORDER BY unexpected_rolloffs DESC"
            ),
        ),
        Example(
            question="How many candidates in Vinay's BU are ending in the next 60 days?",
            sql=(
                "SELECT COUNT(*) FROM candidates_masked_scoped "
                "WHERE end_date IS NOT NULL "
                "AND end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 60 DAY) "
                "AND bu_head = 'Vinay'"
            ),
        ),
    ),
)