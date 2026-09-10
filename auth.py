"""
auth.py
-------
Minimal, swappable "who is making this request" resolver.

TODAY: no real authentication exists yet in this project -- this module
gets a login id from whatever's easiest to test with (CLI: prompted
once and cached for the process; web: a request header). LATER, when
real SSO/OIDC is wired in, only the INSIDE of get_login_id_cli() and
get_login_id_from_request() needs to change -- every caller (main.py,
webapp/server.py) keeps calling the exact same two function names with
the exact same return type (a plain login_id string), so swapping the
mechanism never means hunting down and editing call sites elsewhere in
the app. That's the whole point of this file existing on its own
rather than inlining `input()`/header-reading directly into main.py
and server.py.

SECURITY NOTE -- READ BEFORE THIS TOUCHES REAL USERS:
The web path (get_login_id_from_request) currently trusts a
client-supplied header (X-Login-Id) with ZERO verification. Anyone can
claim to be anyone by setting that header themselves in a request --
this is a claimed identity, not an authenticated one. It is fine ONLY
for local testing on a machine/network you already fully trust. Before
any real user other than you touches this, that header-trust needs to
be replaced with a verified identity (a validated SSO/OIDC token, a
session cookie checked against a real session store, etc.) -- see
"SWAPPING IN REAL AUTH LATER" at the bottom of this file for exactly
what changes when you're ready.

Both entry points fail fast (raise AccessDenied) the moment an
unrecognized login is seen -- BEFORE any question is even asked -- so
a bad/unconfigured login is caught here, not as a confusing later
error deep inside db.run_query().
"""

from access_guard import get_scope_for_user, AccessDenied

_cli_session_login_id: str | None = None  # cached for the life of one `python main.py` run


def get_login_id_cli() -> str:
    """
    CLI entry point (main.py). Prompts once per process run, validates
    it against access_guard.USER_SCOPES immediately, and reuses the
    same login for every question asked in that run -- so you're not
    re-entering your email before every single question.
    """
    global _cli_session_login_id
    if _cli_session_login_id is not None:
        return _cli_session_login_id

    while True:
        candidate = input("Enter your login email: ").strip().lower()
        try:
            get_scope_for_user(candidate)  # raises AccessDenied if unconfigured
        except AccessDenied as e:
            print(f"[auth] {e}")
            continue
        _cli_session_login_id = candidate
        print(f"[auth] Logged in as: {candidate}")
        return candidate


def get_login_id_from_request(request) -> str:
    """
    Web entry point (webapp/server.py). `request` is a FastAPI Request
    object. Reads the login identity from a header -- see the SECURITY
    NOTE above; this is a claimed identity today, not a verified one.

    Raises AccessDenied if the header is missing OR the login isn't
    configured in access_guard.USER_SCOPES -- callers should catch this
    the same way they already catch it from db.run_query(), and return
    an HTTP 401/403 rather than a 500.
    """
    login_id = request.headers.get("X-Login-Id", "").strip().lower()
    if not login_id:
        raise AccessDenied("No X-Login-Id header supplied -- who is asking?")
    get_scope_for_user(login_id)  # fail fast, same validation as the CLI path
    return login_id


# ---------------------------------------------------------------------
# SWAPPING IN REAL AUTH LATER (read this when you're ready to do it --
# no other file in this project needs to change to make this swap):
#
# CLI (main.py's usage): if this ever needs real auth too (e.g. an
# internal SSO device-code flow), replace the body of
# get_login_id_cli() with that flow's login call, keeping the same
# `-> str` return type and the same `get_scope_for_user(candidate)`
# validation call before returning.
#
# Web (webapp/server.py's usage): replace get_login_id_from_request()'s
# body with real verification -- e.g. decode a JWT from an
# Authorization header via your SSO provider's public key, or look up
# a session cookie against a real session store -- and return the
# verified identity (email/username) from THAT, never from a raw
# client-supplied header again. The function's signature
# (`request -> str`, raising AccessDenied on failure) stays identical,
# so main.py and webapp/server.py's call sites don't change at all.
# ---------------------------------------------------------------------