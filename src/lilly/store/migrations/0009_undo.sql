-- Migration 0009: File undo tracking for fs.edit, fs.write, and fs.apply_moves.

CREATE TABLE IF NOT EXISTS file_undos(
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  path TEXT NOT NULL,
  original_content TEXT NOT NULL,
  before_hash TEXT NOT NULL,
  after_hash TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS file_undos_task_step ON file_undos(task_id, step_id);
