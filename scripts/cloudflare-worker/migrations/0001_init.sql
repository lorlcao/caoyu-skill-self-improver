CREATE TABLE IF NOT EXISTS aggregates (
  fingerprint TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  skill_name TEXT NOT NULL,
  skill_version TEXT NOT NULL,
  event_type TEXT NOT NULL,
  stage_code TEXT NOT NULL,
  issue_code TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  result TEXT NOT NULL,
  severity TEXT NOT NULL,
  client_version TEXT NOT NULL,
  occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1)
);

CREATE INDEX IF NOT EXISTS aggregates_priority
ON aggregates (severity, occurrence_count DESC);
