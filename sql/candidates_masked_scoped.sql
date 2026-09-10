-- candidates_masked_scoped.sql  (v2 -- supersedes the earlier version,
-- which masked directly off `candidates` instead of `candidates_scoped`)
--
-- Layer 2 of 2. Reads from candidates_scoped (already row-filtered),
-- and does ONLY masking here -- no access-control logic in this view
-- at all, so the two concerns (who can see which rows / what a
-- visible row looks like) stay cleanly separated and independently
-- testable.
--
-- This is the ONLY view on sql_guard.py's allow-list. The LLM is
-- never told candidates_scoped or the raw candidates table exist.

CREATE OR REPLACE VIEW candidates_masked_scoped AS
SELECT
    c.Status, c.plc_code, c.sap_id, c.candidate_name,

    CONCAT(LEFT(c.candidate_phone, 3), 'XXXXX')                          AS candidate_phone,
    CONCAT(LEFT(c.candidate_email, 2), '****@', SUBSTRING_INDEX(c.candidate_email, '@', -1))   AS candidate_email,
    CASE WHEN c.candidate_email_2 IS NULL OR c.candidate_email_2 = '' THEN c.candidate_email_2
         ELSE CONCAT(LEFT(c.candidate_email_2, 2), '****@', SUBSTRING_INDEX(c.candidate_email_2, '@', -1)) END AS candidate_email_2,
    CASE WHEN c.candidate_email_3 IS NULL OR c.candidate_email_3 = '' THEN c.candidate_email_3
         ELSE CONCAT(LEFT(c.candidate_email_3, 2), '****@', SUBSTRING_INDEX(c.candidate_email_3, '@', -1)) END AS candidate_email_3,
    NULL AS DOB,   -- fully hidden, as in the original candidates_masked

    c.client, c.client_track, c.end_client, c.job_title, c.primary_skills, c.secondary_skills,
    c.start_date, c.end_date, c.sow_end_date, c.sow_end_month, c.extended_sow_date,
    c.extension_status, c.extended_count, c.contractor_status,
    c.project_city, c.project_state, c.project_country,
    c.pay_rate_currency, c.pay_rate, c.pay_rate_numeric, c.pay_rate_payment_basis,

    -- Restricted (margin/client-rate) columns: same as before, NULLed
    -- for any session not explicitly permitted, independent of row scope.
    CASE WHEN get_current_can_view_restricted() = 1 THEN c.client_rate_currency ELSE NULL END AS client_rate_currency,
    CASE WHEN get_current_can_view_restricted() = 1 THEN c.client_rate ELSE NULL END AS client_rate,
    CASE WHEN get_current_can_view_restricted() = 1 THEN c.client_rate_numeric ELSE NULL END AS client_rate_numeric,
    CASE WHEN get_current_can_view_restricted() = 1 THEN c.client_rate_payment_basis ELSE NULL END AS client_rate_payment_basis,
    CASE WHEN get_current_can_view_restricted() = 1 THEN c.margin_value ELSE NULL END AS margin_value,

    c.contractor_vendor_name, c.vendor_contact_person,
    CONCAT(LEFT(c.vendor_contact_number, 3), 'XXXXX') AS vendor_contact_number,
    CASE WHEN c.vendor_contact_email IS NULL OR c.vendor_contact_email = '' THEN c.vendor_contact_email
         ELSE CONCAT(LEFT(c.vendor_contact_email, 2), '****@', SUBSTRING_INDEX(c.vendor_contact_email, '@', -1)) END AS vendor_contact_email,

    c.bu_head,
    CASE WHEN c.bu_head_emailid IS NULL OR c.bu_head_emailid = '' THEN c.bu_head_emailid
         ELSE CONCAT(LEFT(c.bu_head_emailid, 2), '****@', SUBSTRING_INDEX(c.bu_head_emailid, '@', -1)) END AS bu_head_emailid,
    c.cal_name, c.dal_name, c.dm_name, c.add_name,
    c.passthrough_owner, c.passthrough_support, c.lead_recruiter, c.team_lead_name,
    c.recruiter_name, c.recruiter_emp_id, c.deal_pt_ptr,
    c.client_project_manager, c.client_resource_manager,
    CASE WHEN c.client_resource_manager_email IS NULL OR c.client_resource_manager_email = '' THEN c.client_resource_manager_email
         ELSE CONCAT(LEFT(c.client_resource_manager_email, 2), '****@', SUBSTRING_INDEX(c.client_resource_manager_email, '@', -1)) END AS client_resource_manager_email,

    -- account_managers: mask EACH email in the comma list individually,
    -- rather than masking the whole string as one blob (which would
    -- destroy the "domain still visible" masking convention the other
    -- account_manager_* fields already use).
    --
    -- CONFIRMED RUNNING ON MariaDB 10.4.32 -- JSON_TABLE does not exist
    -- until MariaDB 10.6, so this uses a plain numbers-table split
    -- instead (SUBSTRING_INDEX double-nesting), which has worked in
    -- MySQL/MariaDB for a very long time. Caps at 8 entries, matching
    -- the original account_manager_1..8 column count this replaced --
    -- if a row somehow ever has more than 8, entries beyond the 8th
    -- are silently dropped from the masked output (not from the
    -- row-scope match in candidates_scoped.sql, which reads the full
    -- raw string via FIND_IN_SET and has no such cap).
    (
        SELECT GROUP_CONCAT(
            CONCAT(
                LEFT(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(c.account_managers, ',', nums.n), ',', -1)), 2),
                '****@',
                SUBSTRING_INDEX(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(c.account_managers, ',', nums.n), ',', -1)), '@', -1)
            )
            SEPARATOR ', '
        )
        FROM (
            SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
            UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
        ) AS nums
        WHERE c.account_managers IS NOT NULL AND c.account_managers != ''
          AND nums.n <= 1 + LENGTH(c.account_managers) - LENGTH(REPLACE(c.account_managers, ',', ''))
          AND TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(c.account_managers, ',', nums.n), ',', -1)) != ''
    ) AS account_managers

FROM candidates_scoped AS c;

-- NOTE: the "nums" derived table above is a plain, non-correlated list
-- of 1-8 -- it does NOT reference c itself, so this whole construct is
-- an ordinary correlated subquery (correlation only in the enclosing
-- SELECT-list/WHERE), which MariaDB 10.4 supports without needing
-- LATERAL derived tables (also not available until 10.6+). If you ever
-- upgrade to MariaDB 10.6+/MySQL 8.0.19+, the earlier JSON_TABLE
-- version is slightly more readable and can be swapped back in --
-- functionally equivalent either way.