-- Agent questions are approvals that return an optional user choice.
CREATE TABLE approvals_new(
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('step','model','question')),
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired')),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  decided_at REAL
) WITHOUT ROWID;
INSERT INTO approvals_new SELECT id, task_id, step_id, kind, summary, payload_json, payload_hash,
  status, created_at, expires_at, decided_at FROM approvals;
DROP TABLE approvals;
ALTER TABLE approvals_new RENAME TO approvals;
CREATE INDEX approvals_status ON approvals(status, created_at DESC);
CREATE INDEX approvals_task ON approvals(task_id);
