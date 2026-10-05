-- MCP servers the owner added, and the exact tool list they reviewed and approved for each.
CREATE TABLE mcp_servers (
    name        TEXT PRIMARY KEY CHECK (length(name) BETWEEN 1 AND 32),
    config_json TEXT NOT NULL,                       -- command, args, env, secret_env, data_label, idle_stop_s
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at  REAL NOT NULL
);

CREATE TABLE mcp_approvals (
    server      TEXT PRIMARY KEY REFERENCES mcp_servers(name) ON DELETE CASCADE,
    tools_json  TEXT NOT NULL,                       -- the reviewed list: name, description, input schema
    risks_json  TEXT NOT NULL,                       -- tool name -> risk level the owner chose
    approved_at REAL NOT NULL
);
