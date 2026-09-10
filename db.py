"""
db.py (v2)
----------
MySQL connection + query execution, RBAC-aware. Every request gets its
OWN fresh connection, used once, then closed -- session variables are
connection-scoped in MySQL, so reusing a pooled connection across
different users' requests without resetting them would leak one
user's scope onto another user's query. A short-lived, per-request
connection makes that leak structurally impossible, at the cost of a
fresh handshake per question -- worth it for a low-QPS internal tool.
If this needs to scale later, a real pool is fine ONLY if every borrow
re-issues the SET statements below before use.
"""

import mysql.connector
import config
from access_guard import get_scope_for_user

SCOPED_VIEW = "candidates_masked_scoped"


def _get_connection():
    return mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )


def _apply_scope(cursor, login_id: str) -> None:
    """
    Sets every session variable candidates_scoped.sql reads. Always
    sets ALL of them (clearing the ones this scope type doesn't use)
    so a stale value from some earlier bug can never linger -- e.g. if
    @current_scope_value were only set for account_manager logins and
    never cleared, a later recruiter-scoped query on the same
    (mis-pooled) connection could accidentally still satisfy the
    account_manager branch of the view's WHERE clause.
    """
    scope = get_scope_for_user(login_id)
    scope_type = scope["scope_type"]

    cursor.execute("SET @current_scope_type = %s", (scope_type,))
    cursor.execute(
        "SET @current_can_view_restricted = %s",
        (1 if scope.get("can_view_restricted") else 0,),
    )

    if scope_type == "account_manager":
        cursor.execute("SET @current_scope_value = %s", (scope["scope_value"],))
        cursor.execute("SET @current_scope_values = NULL")
    elif scope_type in ("recruiter", "bu"):
        cursor.execute("SET @current_scope_value = NULL")
        cursor.execute("SET @current_scope_values = %s", (",".join(scope["scope_values"]),))
    else:  # unrestricted
        cursor.execute("SET @current_scope_value = NULL")
        cursor.execute("SET @current_scope_values = NULL")


def run_query(sql: str, login_id: str):
    """
    Executes `sql` (already passed sql_guard.py + access_guard.py's
    restricted-column check) against candidates_masked_scoped, under a
    fresh connection scoped to this one login for this one request.
    `sql` must reference candidates_masked_scoped only -- sql_guard.py's
    allow-list should permit nothing else for any login.
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        _apply_scope(cursor, login_id)
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return columns, rows
    finally:
        # Close (never return to a pool) so these session variables can
        # never be read by a subsequent request on the same connection.
        conn.close()