-- Chat bridges: which chat accounts are linked, how far each platform's update feed has been read, and which
-- agents may be reached from a chat app (none until the owner says so).
ALTER TABLE agents ADD COLUMN chat_allowed INTEGER NOT NULL DEFAULT 0 CHECK (chat_allowed IN (0, 1));

CREATE TABLE bridge_identities (
    platform  TEXT    NOT NULL CHECK (length(platform) BETWEEN 1 AND 20),
    user_id   INTEGER NOT NULL,                    -- the platform's numeric account id, never a display name
    chat_id   INTEGER NOT NULL,
    label     TEXT    NOT NULL DEFAULT '' CHECK (length(label) <= 80),
    paired_at REAL    NOT NULL,
    PRIMARY KEY (platform, user_id)
) WITHOUT ROWID;

CREATE TABLE bridge_offsets (
    platform       TEXT    PRIMARY KEY,
    last_update_id INTEGER NOT NULL DEFAULT 0      -- updates at or below this were handled: a replay is ignored
) WITHOUT ROWID;
