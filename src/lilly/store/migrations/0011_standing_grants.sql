-- Standing approvals: remember owner grants for specific tool+target combinations
CREATE TABLE standing_grants (
  id INTEGER PRIMARY KEY,
  tool TEXT NOT NULL,
  target TEXT NOT NULL,
  created_at REAL NOT NULL,
  revoked_at REAL,
  uses INTEGER NOT NULL DEFAULT 0,
  last_used_at REAL,
  UNIQUE(tool, target)
);