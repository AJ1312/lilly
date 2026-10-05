-- Routines: saved requests that run on a schedule. Each run is an ordinary task.
CREATE TABLE routines(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  goal TEXT NOT NULL CHECK(length(goal) BETWEEN 1 AND 4000),
  agent_id TEXT,
  schedule_json TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  next_run REAL,
  last_run REAL,
  last_task_id TEXT,
  last_state TEXT,
  last_error TEXT,
  failures INTEGER NOT NULL DEFAULT 0,
  pause_reason TEXT,
  created_at REAL NOT NULL
) WITHOUT ROWID;
CREATE INDEX routines_due ON routines(next_run) WHERE enabled = 1;
