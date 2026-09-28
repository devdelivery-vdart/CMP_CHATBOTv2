"""
access_guard.py (v4 -- MDM smoke-test logins added)
-----------------------------------------------------
Login -> scope lookup, plus the restricted-column fast-reject. The
REAL row-level enforcement lives in the database (candidates_scoped.sql
+ candidates_masked_scoped.sql for CMP; deployed_candidates_scoped.sql
+ deployed_candidates_masked_scoped.sql for MDM) -- this file's job is
just to (a) fail closed for unrecognized logins, (b) hand db.py the
right session variable values, and (c) cheaply reject a query that
asks for a restricted column before ever hitting the database.

TWO DIFFERENT MATCHING DIRECTIONS, BY SCOPE TYPE (see
candidates_scoped.sql's header comment for the full explanation):
  - "account_manager": ONE login identity (their real email) may
    appear in MANY rows' comma-separated account_managers list.
    scope_value is a SINGLE string -- the login's own confirmed email.
  - "recruiter" / "bu": the ROW holds one value, but the SAME PERSON
    may be spelled multiple ways across rows. scope_values is a LIST
    of that person's confirmed name variants.

Every real account_manager entry below has a confirmed real
candidate_count next to it, taken from staffing_db_v2 (the OLD CMP
database) -- these numbers are NOT meaningful against mdm_chatbot,
which currently holds only synthetic/placeholder data. See the
MDM SMOKE-TEST LOGINS block below for entries specific to testing the
new deployed_candidates_* views.
"""

import re


class AccessDenied(Exception):
    """Raised for an unrecognized login (fail closed) or a query that
    touches a column this login is never permitted to see at all."""


# --- Login -> scope mapping ---
# Every real login must have exactly one entry. An unlisted login is
# denied outright -- never silently treated as unrestricted.
USER_SCOPES = {
    "david.s@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "david.s@vdartinc.com",       "can_view_restricted": False},  # 333
    "aditya.u@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "aditya.u@vdartinc.com",      "can_view_restricted": False},  # 328
    "ajay@vdartinc.com":          {"scope_type": "account_manager", "scope_value": "ajay@vdartinc.com",          "can_view_restricted": False},  # 272
    "vinay@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "vinay@vdartinc.com",         "can_view_restricted": False},  # 209
    "tharun.s@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "tharun.s@vdartinc.com",      "can_view_restricted": False},  # 208
    "jenifer.t@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "jenifer.t@vdartinc.com",     "can_view_restricted": False},  # 187
    "manoj@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "manoj@vdartinc.com",         "can_view_restricted": False},  # 176
    "prassanna.v@vdartinc.com":   {"scope_type": "account_manager", "scope_value": "prassanna.v@vdartinc.com",   "can_view_restricted": False},  # 165
    "abhishek.shah@vdartinc.com": {"scope_type": "account_manager", "scope_value": "abhishek.shah@vdartinc.com", "can_view_restricted": False},  # 141
    "vijay.c@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "vijay.c@vdartinc.com",       "can_view_restricted": False},  # 137
    "prasanna.j@vdartinc.com":    {"scope_type": "account_manager", "scope_value": "prasanna.j@vdartinc.com",    "can_view_restricted": False},  # 134
    "prasanth.s@vdartinc.com":    {"scope_type": "account_manager", "scope_value": "prasanth.s@vdartinc.com",    "can_view_restricted": False},  # 132
    "prashanth.r@vdartinc.com":   {"scope_type": "account_manager", "scope_value": "prashanth.r@vdartinc.com",   "can_view_restricted": False},  # 112
    "don@vdartinc.com":           {"scope_type": "account_manager", "scope_value": "don@vdartinc.com",           "can_view_restricted": False},  # 112 -- tied with prashanth.r
    "richa.v@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "richa.v@vdartinc.com",       "can_view_restricted": False},  # 104
    "namburaj@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "namburaj@vdartinc.com",      "can_view_restricted": False},  # 103
    "murugesan.s@vdartinc.com":   {"scope_type": "account_manager", "scope_value": "murugesan.s@vdartinc.com",   "can_view_restricted": False},  # 101
    "iyngaran.c@vdartinc.com":    {"scope_type": "account_manager", "scope_value": "iyngaran.c@vdartinc.com",    "can_view_restricted": False},  # 96
    "keerthivasan.s@vdartinc.com":{"scope_type": "account_manager", "scope_value": "keerthivasan.s@vdartinc.com","can_view_restricted": False},  # 94
    "faisal.m@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "faisal.m@vdartinc.com",      "can_view_restricted": False},  # 93
    "solomon@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "solomon@vdartinc.com",       "can_view_restricted": False},  # 93 -- tied with faisal.m
    "sini@vdartinc.com":          {"scope_type": "account_manager", "scope_value": "sini@vdartinc.com",          "can_view_restricted": False},  # 89
    "manikandan.c@vdartinc.com":  {"scope_type": "account_manager", "scope_value": "manikandan.c@vdartinc.com",  "can_view_restricted": False},  # 85
    "parijat@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "parijat@vdartinc.com",       "can_view_restricted": False},  # 84
    "sherman@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "sherman@vdartinc.com",       "can_view_restricted": False},  # 84 -- tied with parijat
    "priya.c@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "priya.c@vdartinc.com",       "can_view_restricted": False},  # 73
    "veera.b@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "veera.b@vdartinc.com",       "can_view_restricted": False},  # 72 -- three-way tie
    "deepak.g@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "deepak.g@vdartinc.com",      "can_view_restricted": False},  # 72 -- three-way tie
    "kvalli.p@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "kvalli.p@vdartinc.com",      "can_view_restricted": False},  # 72 -- three-way tie
    "narayan@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "narayan@vdartinc.com",       "can_view_restricted": False},  # 52
    "felix@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "felix@vdartinc.com",         "can_view_restricted": False},  # 51
    "devna@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "devna@vdartinc.com",         "can_view_restricted": False},  # 46
    "sudip.d@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "sudip.d@vdartinc.com",       "can_view_restricted": False},  # 45
    "celestine@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "celestine@vdartinc.com",     "can_view_restricted": False},  # 40
    "melina@vdartinc.com":        {"scope_type": "account_manager", "scope_value": "melina@vdartinc.com",        "can_view_restricted": False},  # 35
    "johnathan@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "johnathan@vdartinc.com",     "can_view_restricted": False},  # 28
    "vijay@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "vijay@vdartinc.com",         "can_view_restricted": False},  # 21 -- NOTE: distinct from vijay.c@vdartinc.com (137) above
    "lance@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "lance@vdartinc.com",         "can_view_restricted": False},  # 20
    "vandhana@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "vandhana@vdartinc.com",      "can_view_restricted": False},  # 18
    "omar.m@vdartinc.com":        {"scope_type": "account_manager", "scope_value": "omar.m@vdartinc.com",        "can_view_restricted": False},  # 18 -- tied with vandhana
    "siraj.m@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "siraj.m@vdartinc.com",       "can_view_restricted": False},  # 17
    "alfahd.m@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "alfahd.m@vdartinc.com",      "can_view_restricted": False},  # 16
    "dino@vdartinc.com":          {"scope_type": "account_manager", "scope_value": "dino@vdartinc.com",          "can_view_restricted": False},  # 15
    "rahul.d@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "rahul.d@vdartinc.com",       "can_view_restricted": False},  # 8
    "valerie.s@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "valerie.s@vdartinc.com",     "can_view_restricted": False},  # 8 -- tied with rahul.d
    "balaji.m@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "balaji.m@vdartinc.com",      "can_view_restricted": False},  # 8 -- three-way tie
    "suganth.t@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "suganth.t@vdartinc.com",     "can_view_restricted": False},  # 7
    "pradeap.t@vdartinc.com":     {"scope_type": "account_manager", "scope_value": "pradeap.t@vdartinc.com",     "can_view_restricted": False},  # 4
    "monserrat.b@vdartinc.com":   {"scope_type": "account_manager", "scope_value": "monserrat.b@vdartinc.com",   "can_view_restricted": False},  # 4 -- tied with pradeap.t
    "gauravkumar.b@vdartinc.com": {"scope_type": "account_manager", "scope_value": "gauravkumar.b@vdartinc.com", "can_view_restricted": False},  # 3
    "suriya.s@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "suriya.s@vdartinc.com",      "can_view_restricted": False},  # 2
    "ibrahim@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "ibrahim@vdartinc.com",       "can_view_restricted": False},  # 2 -- three-way tie
    "rohan.h@vdartinc.com":       {"scope_type": "account_manager", "scope_value": "rohan.h@vdartinc.com",       "can_view_restricted": False},  # 2 -- three-way tie
    "jerry@vdartinc.com":         {"scope_type": "account_manager", "scope_value": "jerry@vdartinc.com",         "can_view_restricted": False},  # 1 -- smallest non-zero case
    "dipesh.s@vdartinc.com":      {"scope_type": "account_manager", "scope_value": "dipesh.s@vdartinc.com",      "can_view_restricted": False},  # 1 -- tied with jerry

    # --- Non-account-manager scope types (kept from the earlier version) ---
    "balamurugan.k": {
        "scope_type": "recruiter",
        "scope_values": ["Balamurugan", "Balamurugan K"],
        "can_view_restricted": False,
    },  # NOTE: this login string doesn't match the @vdartinc.com email
        # format everything else uses -- confirm this is genuinely what
        # he'll type into the login gate, or standardize it to a real
        # email like the rest, before he tries to actually sign in.

    "admin.user@vdartinc.com": {
        "scope_type": "unrestricted",
        "can_view_restricted": True,
    },

    # ---------------------------------------------------------------
    # MDM SMOKE-TEST LOGINS -- deliberately fake @gmail.com addresses,
    # matching the placeholder values just written into
    # mdm_chatbot.deployed_candidates (id=2, id=3). These exist ONLY to
    # prove the new deployed_candidates_masked_scoped view chain works
    # end-to-end (row scope, masking, restricted-column gating) against
    # real emails already wired through the whole pipeline -- they are
    # NOT real people and carry no meaningful candidate_count. Remove
    # this whole block once real Ceipal-synced data and real MDM logins
    # exist, and remove/replace the corresponding UPDATE'd test rows in
    # deployed_candidates at the same time so nothing stale lingers.
    # ---------------------------------------------------------------
    "test.am1@gmail.com": {
        "scope_type": "account_manager",
        "scope_value": "test.am1@gmail.com",
        "can_view_restricted": False,
    },  # shares deployed_candidates.id=2 ("John Doe") with test.am2 --
        # tests that two different account managers on the SAME row
        # both correctly see it.
    "test.am2@gmail.com": {
        "scope_type": "account_manager",
        "scope_value": "test.am2@gmail.com",
        "can_view_restricted": False,
    },  # shares id=2 with test.am1 -- see above.
    "test.am3@gmail.com": {
        "scope_type": "account_manager",
        "scope_value": "test.am3@gmail.com",
        "can_view_restricted": False,
    },  # sole account manager on deployed_candidates.id=3 ("Roll Test")
        # -- should NEVER see id=2, proving isolation from test.am1/am2.
    "test.recruiter@gmail.com": {
        "scope_type": "recruiter",
        "scope_values": ["Test Recruiter"],
        "can_view_restricted": False,
    },  # matches recruiter_name = 'Test Recruiter' on id=3 only.
    "test.bu@gmail.com": {
        "scope_type": "bu",
        "scope_values": ["TestBU"],
        "can_view_restricted": False,
    },  # matches bu_head = 'TestBU' on id=3 only -- combined with
        # test.am3 and test.recruiter both also resolving to id=3, this
        # lets you confirm all three scope TYPES independently arrive
        # at the same correct row via three completely different
        # matching mechanisms.
}

# Columns NEVER shown to a scoped (non-unrestricted, non-can_view_restricted)
# login, regardless of whose row it is. The view's CASE WHEN is the real
# enforcement (it NULLs these unconditionally for such sessions); this
# list is only a fast, cheap pre-reject so an obviously-doomed query
# never even reaches the database.
RESTRICTED_COLUMNS_FOR_SCOPED_USERS = {
    "margin_value",
    "client_rate",
    "client_rate_numeric",
    "client_rate_currency",
    "client_rate_payment_basis",
}

_SELECT_STAR_RE = re.compile(r"SELECT\s+\*", re.IGNORECASE)
_COLUMN_REF_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")


def get_scope_for_user(login_id: str) -> dict:
    """Returns this login's scope dict. Raises AccessDenied if the
    login isn't explicitly configured -- fails CLOSED, never falls
    through to unrestricted access for an unrecognized identity."""
    scope = USER_SCOPES.get(login_id.strip().lower())
    if scope is None:
        raise AccessDenied(
            f"No access scope configured for '{login_id}'. Add them to "
            f"USER_SCOPES in access_guard.py before they can use the chatbot."
        )
    return scope


def check_restricted_columns(sql: str, login_id: str) -> None:
    """
    Cheap pre-reject: raises AccessDenied if a scoped login's query
    would touch a restricted column OR uses `SELECT *` (which would
    silently include restricted columns as NULLs from the view -- not
    a security hole, since the view already NULLs them, but a wasted,
    confusing round trip that looks like a bug rather than a policy).

    This is NOT the security boundary -- the view's CASE WHEN NULLing
    is. This function exists purely to fail fast and legibly.
    """
    scope = get_scope_for_user(login_id)
    if scope.get("can_view_restricted"):
        return

    if _SELECT_STAR_RE.search(sql):
        raise AccessDenied(
            "SELECT * is not permitted for this login -- name the columns "
            "you need explicitly (restricted columns will be rejected below)."
        )

    referenced = {tok.lower() for tok in _COLUMN_REF_RE.findall(sql)}
    hit = referenced & RESTRICTED_COLUMNS_FOR_SCOPED_USERS
    if hit:
        raise AccessDenied(
            f"This question requires column(s) {sorted(hit)}, which "
            f"'{login_id}' is not permitted to view."
        )