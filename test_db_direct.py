"""
test_db_direct.py
------------------
Bypasses main.py's CLI loop entirely and calls the same connection +
scope + query path that db.run_query() uses, but with use_pure=True,
which forces mysql-connector-python's pure-Python driver instead of
its compiled C extension.

Why: exit code -1073741819 (0xC0000005 / STATUS_ACCESS_VIOLATION) means
the process crashed natively -- almost always the C extension, not a
normal Python bug. If this script runs cleanly where the CLI crashed,
that confirms the C extension as the cause, and the fix is either to
switch db.py to use_pure=True permanently, or reinstall the C extension
build cleanly for your exact Python 3.11.9.

Run with:
    python test_db_direct.py
"""

import mysql.connector
import config
from access_guard import get_scope_for_user

LOGIN_ID = "david.s@vdartinc.com"
TEST_SQL = "SELECT 1 AS ok"


def get_connection_pure():
    return mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        use_pure=True,  # <-- forces pure-Python driver, skips the C extension
    )


def apply_scope(cursor, login_id):
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
    else:
        cursor.execute("SET @current_scope_value = NULL")
        cursor.execute("SET @current_scope_values = NULL")


def main():
    print("Step 1: connecting with use_pure=True ...")
    conn = get_connection_pure()
    print("  connected OK")

    print("Step 2: getting scope for login...")
    cursor = conn.cursor()
    apply_scope(cursor, LOGIN_ID)
    print("  scope applied OK")

    print(f"Step 3: running test query: {TEST_SQL}")
    cursor.execute(TEST_SQL)
    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    print(f"  columns: {columns}")
    print(f"  rows: {rows}")

    conn.close()
    print("\nDone. If you see this line, the pure-Python driver did NOT crash.")


if __name__ == "__main__":
    main()