-- Cleanup script for search-discovered companies migration
-- Run after schema rebuild to ensure data integrity

-- Delete the literal 'nan' company and any empty-name companies
DELETE FROM companies WHERE name = 'nan' OR name = '' OR name = 'Unknown';

-- Ensure all non-seed companies have inactive search-discovered watchlist entries
-- Uses watchlist metadata instead of hardcoding company names
INSERT OR IGNORE INTO user_watchlist (user_id, company_id, active, added_reason)
SELECT 1, c.id, 0, 'search'
FROM companies c
WHERE NOT EXISTS (
    SELECT 1 FROM user_watchlist w WHERE w.company_id = c.id
);

-- Ensure seed companies have active watchlist entries
-- Seed companies are identified by existing watchlist entries with added_reason='seed'
INSERT OR IGNORE INTO user_watchlist (user_id, company_id, active, added_reason)
SELECT 1, c.id, 1, 'seed'
FROM user_watchlist w
JOIN companies c ON c.id = w.company_id
WHERE w.added_reason = 'seed'
  AND w.active = 0;

-- Verification query
SELECT w.active, w.added_reason, COUNT(*)
FROM user_watchlist w
JOIN companies c ON c.id = w.company_id
WHERE w.user_id = 1
GROUP BY w.active, w.added_reason;
