-- Payer service reads the submission log to satisfy the claim foreign key
-- and to tell PROCESSING from an unknown submission.
GRANT USAGE ON SCHEMA portal TO payer_app;
GRANT SELECT ON portal.submission_log TO payer_app;
