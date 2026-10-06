-- Migration 0010: optional bounded tags for long-term memory.
ALTER TABLE memory ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';