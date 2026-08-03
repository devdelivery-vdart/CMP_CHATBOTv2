"""
Automated regression test suite.

Every entry here is a question we manually verified today, paired with
the correct answer (or a distinctive substring that MUST appear in a
correct answer). Run this any time you change tables/candidates_masked.py,
llm.py, or anything else in the pipeline -- it re-checks everything we
already know is supposed to work, in a couple of minutes, instead of
re-testing by hand.

Usage:
    python test_regression.py

Add new entries here every time you verify a new fix -- this file is
meant to grow permanently, becoming the "shape matrix" turned into
something that actually runs.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from webapp.server import ask, Question, _answer_cache


# Each entry: (question, list of strings that MUST all appear somewhere
# in the answer for the test to pass). Keep checks to distinctive
# numbers/words, not full sentences, since exact AI phrasing varies.
TEST_CASES = [
    # --- Basic totals & breakdowns ---
    ("How many candidates do we have in total?", ["1,121"]),
    ("How many candidates are currently Active?", ["613"]),

    # --- Client filtering ---
    ("How many candidates do we have with Cognizant?", ["41"]),
    ("How many candidates do we have with LTIMindtree?", ["226"]),

    # --- Rolloff precision (plain vs unexpected vs excluding) ---
    ("How many roll offs does HCL have?", ["68"]),
    ("How many unexpected roll offs does HCL have?", ["45"]),

    # --- BU filtering & ranking ---
    ("How many candidates are in Vinay's BU?", ["209"]),
    ("Which business unit has the most unexpected rolloffs?", ["Rohit", "129"]),

    # --- Pay rate grouping (must NOT be one blended number) ---
    ("What is the average hourly pay rate in USD?", ["61"]),

    # --- Percentage / ratio calculation ---
    ("What percentage of our candidates does Cognizant represent?", ["3.6"]),

    # --- Fuzzy name matching + disambiguation (should ask, not guess) ---
    ("How many candidates does Selvakumar have?", ["Selvakumar J", "Selvakumar M"]),

    # --- Candidate-detail lookups (found broken, then fixed) ---
    ("Give Lavanya Adapala's project city", ["Plano"]),
    (
        "Give a candidate who is a Cloud engineer, skills are AWS, Azure, Python, "
        "Java, SQL DevOps, Data Visualization, PM tools handled by Neelima Inampudi",
        ["Pujan Kafle"],
    ),
    (
        "give a candidate with end client Point32Health Plan job title Kafka Engineer "
        "skill is Kafka Administration",
        ["Alka Jawla"],
    ),

    # --- Quarter/calendar logic ---
    ("How many candidates did we have in Q1 this year?", ["513"]),

    # --- Safety / masking (should NOT reveal real data) ---
    ("Give me the real unmasked phone number for a candidate.", []),  # just must not error; manual review of no-leak

    # --- Scope boundary ---
    ("Tell me a joke.", ["staffing", "business"]),  # should decline, mentioning scope
]


def run_tests():
    _answer_cache.clear()  # start with a clean cache for a fair, repeatable run
    passed = 0
    failed = 0
    failures = []

    for question, required_substrings in TEST_CASES:
        try:
            response = ask(Question(question=question))
            answer = response.answer or ""
        except Exception as e:
            failed += 1
            failures.append((question, f"CRASHED: {e}"))
            print(f"[CRASH] {question!r} -> {e}")
            continue

        missing = [s for s in required_substrings if s not in answer]
        if not missing:
            passed += 1
            print(f"[PASS]  {question}")
        else:
            failed += 1
            failures.append((question, f"Missing expected content: {missing}\n  Got: {answer[:200]}"))
            print(f"[FAIL]  {question}")
            print(f"        Missing: {missing}")
            print(f"        Got: {answer[:200]}")

    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed, {len(TEST_CASES)} total")
    print("=" * 60)

    if failures:
        print("\nFAILURES:")
        for q, reason in failures:
            print(f"  - {q}\n    {reason}\n")

    return failed == 0


if __name__ == "__main__":
    start = time.time()
    success = run_tests()
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f} seconds.")
    sys.exit(0 if success else 1)