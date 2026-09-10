"""
rbac_regression.py (v2 -- full coverage)
------------------------------------------
Adversarial-style regression suite for RBAC scoping, mirroring
test_regression.py's philosophy: every entry here is a (login_id,
expected_count) pair confirmed against a real ground-truth query, so
future changes to candidates_scoped.sql / access_guard.py / db.py can
be re-checked in seconds instead of by hand in phpMyAdmin.

WHY THIS MATTERS MORE THAN AN ORDINARY REGRESSION FAILURE: a bug here
doesn't just mean a wrong number -- it can mean one person seeing
another person's candidates. Treat any FAIL below as more urgent than
a normal SQL-correctness regression.

These 55 counts are taken directly from a real query grouping the raw
account_managers column by email -- not from a phpMyAdmin browse-grid
preview (which defaults to a 25-row page and can look like a wrong
count when it's just pagination -- this is exactly what happened with
priya.c@vdartinc.com earlier: 25 shown on one page, 73 confirmed as
the real total).

NOTE: these 55 numbers will NOT sum to the total candidate count
(~1,121) -- a candidate with multiple account managers is counted once
per AM here, so the sum is expected to be much larger than the total
headcount. That is correct, not a bug.

Run with:
    python rbac_regression.py
"""

import sys
from access_guard import USER_SCOPES
import db

# (login_id, expected_count) -- keep in sync with access_guard.py's
# USER_SCOPES comments; if one changes, update the other.
EXPECTED_COUNTS = {
    "david.s@vdartinc.com": 333,
    "aditya.u@vdartinc.com": 328,
    "ajay@vdartinc.com": 272,
    "vinay@vdartinc.com": 209,
    "tharun.s@vdartinc.com": 208,
    "jenifer.t@vdartinc.com": 187,
    "manoj@vdartinc.com": 176,
    "prassanna.v@vdartinc.com": 165,
    "abhishek.shah@vdartinc.com": 141,
    "vijay.c@vdartinc.com": 137,
    "prasanna.j@vdartinc.com": 134,
    "prasanth.s@vdartinc.com": 132,
    "prashanth.r@vdartinc.com": 112,
    "don@vdartinc.com": 112,
    "richa.v@vdartinc.com": 104,
    "namburaj@vdartinc.com": 103,
    "murugesan.s@vdartinc.com": 101,
    "iyngaran.c@vdartinc.com": 96,
    "keerthivasan.s@vdartinc.com": 94,
    "faisal.m@vdartinc.com": 93,
    "solomon@vdartinc.com": 93,
    "sini@vdartinc.com": 89,
    "manikandan.c@vdartinc.com": 85,
    "parijat@vdartinc.com": 84,
    "sherman@vdartinc.com": 84,
    "priya.c@vdartinc.com": 73,
    "veera.b@vdartinc.com": 72,
    "deepak.g@vdartinc.com": 72,
    "kvalli.p@vdartinc.com": 72,
    "narayan@vdartinc.com": 52,
    "felix@vdartinc.com": 51,
    "devna@vdartinc.com": 46,
    "sudip.d@vdartinc.com": 45,
    "celestine@vdartinc.com": 40,
    "melina@vdartinc.com": 35,
    "johnathan@vdartinc.com": 28,
    "vijay@vdartinc.com": 21,
    "lance@vdartinc.com": 20,
    "vandhana@vdartinc.com": 18,
    "omar.m@vdartinc.com": 18,
    "siraj.m@vdartinc.com": 17,
    "alfahd.m@vdartinc.com": 16,
    "dino@vdartinc.com": 15,
    "rahul.d@vdartinc.com": 8,
    "valerie.s@vdartinc.com": 8,
    "balaji.m@vdartinc.com": 8,
    "suganth.t@vdartinc.com": 7,
    "pradeap.t@vdartinc.com": 4,
    "monserrat.b@vdartinc.com": 4,
    "gauravkumar.b@vdartinc.com": 3,
    "suriya.s@vdartinc.com": 2,
    "ibrahim@vdartinc.com": 2,
    "rohan.h@vdartinc.com": 2,
    "jerry@vdartinc.com": 1,
    "dipesh.s@vdartinc.com": 1,
}


def run_count_checks() -> bool:
    passed = 0
    failed = 0
    failures = []

    for login_id, expected in EXPECTED_COUNTS.items():
        if login_id not in USER_SCOPES:
            failed += 1
            failures.append((login_id, "NOT IN access_guard.USER_SCOPES -- "
                                        "this test file and access_guard.py have drifted apart"))
            print(f"[FAIL] {login_id}: not configured in USER_SCOPES")
            continue
        try:
            _columns, rows = db.run_query(
                "SELECT COUNT(*) FROM candidates_masked_scoped", login_id
            )
            actual = rows[0][0]
        except Exception as e:
            failed += 1
            failures.append((login_id, f"CRASHED: {e}"))
            print(f"[CRASH] {login_id}: {e}")
            continue

        if actual == expected:
            passed += 1
            print(f"[PASS] {login_id}: {actual}")
        else:
            failed += 1
            failures.append((login_id, f"expected {expected}, got {actual}"))
            print(f"[FAIL] {login_id}: expected {expected}, got {actual}")

    print()
    print("=" * 60)
    print(f"COUNT CHECKS: {passed} passed, {failed} failed, {len(EXPECTED_COUNTS)} total")
    print("=" * 60)
    if failures:
        print("\nFAILURES (investigate before trusting RBAC in production):")
        for login_id, reason in failures:
            print(f"  - {login_id}: {reason}")

    return failed == 0


def check_cross_user_isolation() -> bool:
    """
    A count matching doesn't rule out every mistake -- two DIFFERENT
    logins could still resolve to the exact same SET of candidates
    (e.g. a copy-pasted scope_value) while each individually "passing"
    its own count check, if the mistake happened to also be reflected
    correctly in EXPECTED_COUNTS. This check catches that directly: no
    two tested logins should ever see an identical row set. With 55
    logins now covered, including three separate 3-way count ties
    (112, 72, and 8, and a 3-way tie at 2), this is a much stronger
    check than it was with 11 -- a copy-paste mistake between two
    same-count logins would previously have been invisible to the
    count check alone.
    """
    seen_row_sets = {}
    collisions = []

    for login_id in EXPECTED_COUNTS:
        if login_id not in USER_SCOPES:
            continue
        try:
            _columns, rows = db.run_query(
                "SELECT candidate_name FROM candidates_masked_scoped ORDER BY candidate_name",
                login_id,
            )
        except Exception:
            continue
        row_set = frozenset(r[0] for r in rows)
        if not row_set:
            continue
        for other_login, other_set in seen_row_sets.items():
            if row_set == other_set:
                collisions.append((login_id, other_login))
        seen_row_sets[login_id] = row_set

    print()
    if collisions:
        print("[FAIL] Identical row sets found between different logins -- "
              "possible copy-pasted scope_value:")
        for a, b in collisions:
            print(f"  - {a} == {b}")
        return False
    else:
        print("[PASS] No two tested logins return identical row sets "
              "(including all same-count ties).")
        return True


if __name__ == "__main__":
    counts_ok = run_count_checks()
    isolation_ok = check_cross_user_isolation()
    sys.exit(0 if (counts_ok and isolation_ok) else 1)