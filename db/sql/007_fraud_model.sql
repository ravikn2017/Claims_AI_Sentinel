-- Fraud model runs and per-technique metrics. Does not drop schemas.
SET ROLE claims_owner;

CREATE TABLE IF NOT EXISTS fraud.model_run (
    run_id text PRIMARY KEY,
    trained_at timestamptz NOT NULL DEFAULT now(),
    row_count integer NOT NULL,
    fraud_count integer NOT NULL,
    active_technique text,
    model_version text,
    thresholds jsonb,
    status text NOT NULL,
    error text,
    CONSTRAINT model_run_status CHECK (status IN ('succeeded', 'failed'))
);

CREATE TABLE IF NOT EXISTS fraud.technique_result (
    run_id text NOT NULL REFERENCES fraud.model_run (run_id),
    technique text NOT NULL,
    threshold numeric NOT NULL,
    tp integer NOT NULL,
    tn integer NOT NULL,
    fp integer NOT NULL,
    fn integer NOT NULL,
    precision numeric NOT NULL,
    recall numeric NOT NULL,
    f1 numeric NOT NULL,
    selected boolean NOT NULL DEFAULT false,
    PRIMARY KEY (run_id, technique),
    CONSTRAINT technique_result_name CHECK (
        technique IN ('logistic_regression', 'random_forest', 'xgboost', 'soft_voting_ensemble')
    )
);

INSERT INTO fraud.excluded_provider (npi, excluded_from, reason)
VALUES ('9999999999', DATE '2020-01-01', 'Synthetic exclusion list')
ON CONFLICT (npi) DO NOTHING;

RESET ROLE;
