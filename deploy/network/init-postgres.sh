#!/bin/sh
set -eu
# Docker entrypoint runs this only on a new disposable PostgreSQL volume.
for migration in \
  production_001.sql \
  production_002_ingestion.sql \
  production_003_dependency_evidence.sql \
  production_003_observation_subtypes.sql \
  production_004_assertion_subtype_integrity.sql \
  production_004_retrieval_signal.sql \
  production_005_contribution_reports.sql \
  production_006_credentials.sql \
  production_007_self_service.sql; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "/migrations/$migration"
done
OMNEUM_LOCAL_INGESTION_PASSWORD="$(cat /config/ingestion-password)" \
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv password OMNEUM_LOCAL_INGESTION_PASSWORD
ALTER ROLE omneum_ingestion LOGIN PASSWORD :'password';
SQL
