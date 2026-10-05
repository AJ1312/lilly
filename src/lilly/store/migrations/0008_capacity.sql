-- Migration 0008: Capacity tracking, model_calls ledger, task delegation, and pet sheets.

CREATE TABLE IF NOT EXISTS model_calls(
  id TEXT PRIMARY KEY,
  task_id TEXT,
  turn INTEGER,
  role TEXT,
  model TEXT NOT NULL,
  started_at REAL NOT NULL,
  ms INTEGER NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  waited_ms INTEGER NOT NULL DEFAULT 0,
  outcome TEXT NOT NULL CHECK(outcome IN ('ok', 'rate_limited', 'error', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS model_calls_task ON model_calls(task_id);

ALTER TABLE quota_usage ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agents ADD COLUMN sheet TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN sheet_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agents ADD COLUMN parent_template TEXT NOT NULL DEFAULT '';

-- Populate sheet for existing agents so an unchanged agent assembles the same owner text as before
UPDATE agents
SET sheet = '## Persona' || char(10) || instructions || CASE WHEN trim(skills) != '' THEN char(10) || char(10) || 'Skills of this agent:' || char(10) || skills ELSE '' END
WHERE sheet = '' AND (instructions != '' OR skills != '');

ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN depth INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN profile_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE steps ADD COLUMN turn INTEGER;
