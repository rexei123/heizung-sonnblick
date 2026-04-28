-- ChirpStack v4 verlangt pg_trgm fuer Trigram-Suche.
-- Wird beim ersten Start von chirpstack-postgres ausgefuehrt.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
