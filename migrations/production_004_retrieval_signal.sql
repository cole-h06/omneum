-- dependency-estimator-v4 includes retrieval as a canonical dependency signal.
-- signal_components remains the extensible representation for future signals.

BEGIN;

ALTER TABLE network.source_dependencies
    ADD COLUMN retrieval_signal double precision;

COMMIT;
