-- AptiorDesk schema v9: retire the former planning and application-tracking tables.
-- Data is archived and verified by the migration runner before this transaction.

DROP TABLE IF EXISTS action_items;
DROP TABLE IF EXISTS opportunity_reviews;
DROP TABLE IF EXISTS contact_interactions;
DROP TABLE IF EXISTS contacts;
DROP TABLE IF EXISTS career_campaigns;
DROP TABLE IF EXISTS application_events;
DROP TABLE IF EXISTS applications;

DELETE FROM settings
WHERE key LIKE 'jobsearch.%' OR key LIKE 'jobsource.%';
