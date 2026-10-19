-- Migration 0014: Task outcomes, execution targets, and learned workflow playbooks.

ALTER TABLE tasks ADD COLUMN outcome TEXT NOT NULL DEFAULT 'unverified' CHECK(outcome IN ('unverified','success','partial','needs_user','blocked'));
ALTER TABLE tasks ADD COLUMN outcome_reason TEXT;
ALTER TABLE tasks ADD COLUMN target TEXT NOT NULL DEFAULT 'host' CHECK(target IN ('host','devbox'));

ALTER TABLE routines ADD COLUMN playbook_id TEXT;
ALTER TABLE routines ADD COLUMN playbook_version INTEGER;
ALTER TABLE routines ADD COLUMN target TEXT NOT NULL DEFAULT 'host' CHECK(target IN ('host','devbox'));

CREATE TABLE IF NOT EXISTS playbooks(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
  description TEXT NOT NULL DEFAULT '',
  task_signature TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  steps_json TEXT NOT NULL,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  preconditions_json TEXT NOT NULL DEFAULT '{}',
  target TEXT NOT NULL DEFAULT 'host' CHECK(target IN ('host','devbox')),
  provenance_task_id TEXT,
  success_count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','review','archived')),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS playbooks_signature ON playbooks(task_signature, status);
