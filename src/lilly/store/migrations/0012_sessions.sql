CREATE TABLE session_snapshots(
  session_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  status TEXT NOT NULL,
  session_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  state_json TEXT NOT NULL,
  artifacts_json TEXT NOT NULL,
  events_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE INDEX session_snapshots_task_idx ON session_snapshots(task_id);
