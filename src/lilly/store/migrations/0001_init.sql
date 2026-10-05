-- Lilly schema v1. One writer, WAL, FTS5. Every table here is read or written by real code.

CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE spaces(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 1000),
  created_at REAL NOT NULL
) WITHOUT ROWID;

CREATE TABLE agents(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  instructions TEXT NOT NULL CHECK(length(instructions) <= 8000),
  mode INTEGER NOT NULL CHECK(mode BETWEEN 0 AND 2),
  research_allowed INTEGER NOT NULL DEFAULT 1 CHECK(research_allowed IN (0,1)),
  memory_allowed INTEGER NOT NULL DEFAULT 1 CHECK(memory_allowed IN (0,1)),
  files_allowed INTEGER NOT NULL DEFAULT 0 CHECK(files_allowed IN (0,1)),
  space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
  created_at REAL NOT NULL
) WITHOUT ROWID;

CREATE TABLE conversations(
  id TEXT PRIMARY KEY,
  space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
  title TEXT NOT NULL CHECK(length(title) <= 200),
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
) WITHOUT ROWID;
CREATE INDEX conversations_recent ON conversations(archived, updated_at DESC);

CREATE TABLE tasks(
  id TEXT PRIMARY KEY,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
  agent_id TEXT REFERENCES agents(id) ON DELETE SET NULL,
  state TEXT NOT NULL CHECK(state IN ('PENDING','PLANNING','RUNNING','WAITING_APPROVAL',
                                      'VERIFYING','DONE','FAILED','CANCELLED','EXPIRED')),
  goal TEXT NOT NULL CHECK(length(goal) <= 4000),
  mode INTEGER NOT NULL CHECK(mode BETWEEN 0 AND 2),
  label INTEGER NOT NULL DEFAULT 0 CHECK(label BETWEEN 0 AND 2),
  tainted INTEGER NOT NULL DEFAULT 0 CHECK(tainted IN (0,1)),
  skill TEXT,
  plan_json TEXT,
  pinned_model TEXT,
  answer TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  finished_at REAL
) WITHOUT ROWID;
CREATE INDEX tasks_state ON tasks(state, updated_at);
CREATE INDEX tasks_recent ON tasks(created_at DESC);
CREATE INDEX tasks_conversation ON tasks(conversation_id, created_at);

CREATE TABLE messages(
  id INTEGER PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL CHECK(length(content) <= 32000),
  label INTEGER NOT NULL DEFAULT 0 CHECK(label BETWEEN 0 AND 2),
  untrusted INTEGER NOT NULL DEFAULT 0 CHECK(untrusted IN (0,1)),
  created_at REAL NOT NULL
);
CREATE INDEX messages_conversation ON messages(conversation_id, id);
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='id',
                                             tokenize='porter unicode61');
CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END;
CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content); END;

CREATE TABLE events(
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL CHECK(length(payload) <= 65536),
  prov TEXT NOT NULL CHECK(prov IN ('user','model','system','tool')),
  ts REAL NOT NULL,
  prev TEXT NOT NULL,
  hash TEXT NOT NULL,
  PRIMARY KEY(task_id, seq)
) WITHOUT ROWID;
CREATE TRIGGER events_append_only BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE task_summaries(
  task_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  state TEXT NOT NULL,
  last_seq INTEGER NOT NULL,
  last_hash TEXT NOT NULL,
  finished_at REAL NOT NULL
) WITHOUT ROWID;

CREATE TABLE steps(
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  tool TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','running','waiting','done','failed','skipped')),
  args_json TEXT NOT NULL CHECK(length(args_json) <= 16384),
  output TEXT CHECK(length(output) <= 262144),
  label INTEGER NOT NULL DEFAULT 0 CHECK(label BETWEEN 0 AND 2),
  untrusted INTEGER NOT NULL DEFAULT 0 CHECK(untrusted IN (0,1)),
  error TEXT,
  started_at REAL,
  finished_at REAL,
  PRIMARY KEY(task_id, step_id)
) WITHOUT ROWID;

CREATE TABLE approvals(
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('step','model')),
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired')),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  decided_at REAL
) WITHOUT ROWID;
CREATE INDEX approvals_status ON approvals(status, created_at DESC);
CREATE INDEX approvals_task ON approvals(task_id);

CREATE TABLE quota_usage(
  model TEXT PRIMARY KEY,
  day INTEGER NOT NULL,        -- date.toordinal() in the model's quota time zone
  count INTEGER NOT NULL CHECK(count >= 0)
) WITHOUT ROWID;

CREATE TABLE memory(
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 8000),
  label INTEGER NOT NULL DEFAULT 1 CHECK(label BETWEEN 0 AND 2),
  source TEXT NOT NULL CHECK(source IN ('user','agent')),
  created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE memory_fts USING fts5(text, content='memory', content_rowid='id',
                                           tokenize='porter unicode61');
CREATE TRIGGER memory_ai AFTER INSERT ON memory BEGIN
  INSERT INTO memory_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER memory_ad AFTER DELETE ON memory BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TRIGGER memory_au AFTER UPDATE OF text ON memory BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO memory_fts(rowid, text) VALUES (new.id, new.text); END;

CREATE TABLE pages(
  id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES pages(id) ON DELETE SET NULL,
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
  content TEXT NOT NULL CHECK(length(content) <= 200000),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX pages_space ON pages(space_id, updated_at DESC);
CREATE VIRTUAL TABLE pages_fts USING fts5(title, content, content='pages', content_rowid='rowid',
                                          tokenize='porter unicode61');
CREATE TRIGGER pages_ai AFTER INSERT ON pages BEGIN
  INSERT INTO pages_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;
CREATE TRIGGER pages_ad AFTER DELETE ON pages BEGIN
  INSERT INTO pages_fts(pages_fts, rowid, title, content)
  VALUES ('delete', old.rowid, old.title, old.content); END;
CREATE TRIGGER pages_au AFTER UPDATE OF title, content ON pages BEGIN
  INSERT INTO pages_fts(pages_fts, rowid, title, content)
  VALUES ('delete', old.rowid, old.title, old.content);
  INSERT INTO pages_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;
