-- candidates_scoped.sql
--
-- Layer 1 of 2. Sits directly on the RAW `candidates` table -- BEFORE
-- masking. This has to be the order (filter first, mask second)
-- because account-manager row-scoping needs to compare a logged-in
-- AM's real email against the real (unmasked) `account_managers`
-- list -- if this filter ran on top of the already-masked view
-- instead, every email would already be truncated to "pr****@..." and
-- no exact match could ever succeed.
--
-- This view is NEVER queried directly by the LLM -- only
-- candidates_masked_scoped.sql (layer 2, built on top of this) is on
-- sql_guard.py's allow-list. This view exists purely so masking (layer
-- 2) has already-filtered rows to mask, never unfiltered ones.
--
-- SESSION VARIABLES (see db.py's _apply_scope):
--   @current_scope_type   -- 'unrestricted' | 'account_manager' | 'recruiter' | 'bu'
--   @current_scope_value  -- SINGLE string: the current login's own
--                             identity (their real email, for
--                             account_manager scope) -- used as the
--                             NEEDLE when a row can hold MULTIPLE
--                             values (see note below).
--   @current_scope_values -- comma-separated list of this login's
--                             CONFIRMED name variants -- used as the
--                             HAYSTACK when a row holds exactly ONE
--                             value (recruiter_name, bu_head), the
--                             same direction as the original design.
--
-- WHY THE DIRECTION DIFFERS BY SCOPE TYPE:
--   account_manager: candidates_scoped is a comma list, row values      HAYSTACK
--                     the login is one identity                        the row
--                     -> FIND_IN_SET(@current_scope_value, account_managers)
--   recruiter/bu:     the row is one value,                             NEEDLE
--                     the login may have several confirmed spellings    the row
--                     -> FIND_IN_SET(recruiter_name, @current_scope_values)
-- Mixing these up silently matches nothing (fails closed, at least --
-- but worth testing explicitly; see the adversarial test list below).
--
-- WHY THIS FILE ALSO CREATES FOUR TINY FUNCTIONS:
-- MySQL/MariaDB refuses to CREATE VIEW if the view's SELECT contains a
-- bare @variable reference at all (error 1351 -- confirmed hitting this
-- on MariaDB 10.4.32, but it is NOT version-specific; every MySQL/
-- MariaDB version enforces this). Views ARE allowed to call stored
-- functions, though -- so each session variable gets a one-line
-- wrapper function that just returns it, and the view calls the
-- function instead of referencing the variable directly. db.py's
-- _apply_scope() is UNCHANGED -- it still just runs plain
-- `SET @current_scope_type = ...` etc.; only the view's own text
-- changes, from `@current_scope_type` to `get_current_scope_type()`.

DELIMITER $$

CREATE FUNCTION IF NOT EXISTS get_current_scope_type() RETURNS VARCHAR(20)
    READS SQL DATA
BEGIN
    RETURN @current_scope_type;
END$$

CREATE FUNCTION IF NOT EXISTS get_current_scope_value() RETURNS VARCHAR(255)
    READS SQL DATA
BEGIN
    RETURN @current_scope_value;
END$$

CREATE FUNCTION IF NOT EXISTS get_current_scope_values() RETURNS TEXT
    READS SQL DATA
BEGIN
    RETURN @current_scope_values;
END$$

CREATE FUNCTION IF NOT EXISTS get_current_can_view_restricted() RETURNS TINYINT
    READS SQL DATA
BEGIN
    RETURN @current_can_view_restricted;
END$$

DELIMITER ;

-- NOTE on READS SQL DATA: these functions don't actually touch any
-- table, but MariaDB requires a characteristic (DETERMINISTIC, READS
-- SQL DATA, MODIFIES SQL DATA, or NO SQL) to be declared, and forbids
-- marking a function that reads mutable session state as DETERMINISTIC
-- (it isn't -- the same call can return a different value from request
-- to request, by design). READS SQL DATA is the closest honest fit.
--
-- IF CREATING THESE FUNCTIONS FAILS with an error like "This function
-- has none of DETERMINISTIC..." or a binary-logging permission error:
-- your MariaDB instance likely has binary logging on and
-- log_bin_trust_function_creators disabled. Fix (needs admin/SUPER):
--     SET GLOBAL log_bin_trust_function_creators = 1;
-- then re-run the CREATE FUNCTION statements above.

CREATE OR REPLACE VIEW candidates_scoped AS
SELECT *
FROM candidates
WHERE
    get_current_scope_type() = 'unrestricted'
    OR (get_current_scope_type() = 'account_manager'
        AND get_current_scope_value() IS NOT NULL
        AND FIND_IN_SET(get_current_scope_value(), account_managers) > 0)
    OR (get_current_scope_type() = 'recruiter'
        AND get_current_scope_values() IS NOT NULL
        AND FIND_IN_SET(recruiter_name, get_current_scope_values()) > 0)
    OR (get_current_scope_type() = 'bu'
        AND get_current_scope_values() IS NOT NULL
        AND FIND_IN_SET(bu_head, get_current_scope_values()) > 0);

-- FAIL-CLOSED: as before, unset session variables are NULL by default
-- in MySQL, and every branch above is false/unknown against NULL --
-- so a connection that skips _apply_scope() sees zero rows, never
-- everything.

-- ONE-TIME DATA CHECKS WORTH RUNNING BEFORE TRUSTING THIS:
--   1. Confirm no real account_managers value contains a literal comma
--      inside a single email (would break FIND_IN_SET's split):
--        SELECT account_managers FROM candidates
--        WHERE account_managers REGEXP '[^,]@[^,]*,[^,]*@' LIMIT 20;
--   2. Confirm each AM's login email is byte-identical to how it's
--      stored in account_managers (case, whitespace, typos) -- FIND_IN_SET
--      is case-INsensitive for the default collation but not
--      whitespace-tolerant, so a stray trailing space in the raw data
--      would silently break the match for that one candidate.