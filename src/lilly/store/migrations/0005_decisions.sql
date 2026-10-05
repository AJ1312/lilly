-- What the cheap deciders were asked and what they answered. Short redacted summaries only, never full text.
CREATE TABLE decision_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    task_id    TEXT,
    kind       TEXT NOT NULL,
    decider    TEXT,                                 -- who answered; NULL when there was no decision
    choice     TEXT,                                 -- the option id answered (in shadow mode: would have answered)
    confidence REAL,
    shadow     INTEGER NOT NULL DEFAULT 0 CHECK (shadow IN (0, 1)),
    outcome    TEXT NOT NULL DEFAULT 'unknown' CHECK (outcome IN ('accepted', 'corrected', 'unknown')),
    options    INTEGER NOT NULL,                     -- how many options were offered
    summary    TEXT NOT NULL DEFAULT '' CHECK (length(summary) <= 300),
    reason     TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 200)
);
CREATE INDEX decision_log_ts ON decision_log(ts);
CREATE INDEX decision_log_kind ON decision_log(kind, decider);
