-- Agents can be given computer control (off by default) and a pet that represents them in the interface.
ALTER TABLE agents ADD COLUMN computer_allowed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agents ADD COLUMN pet TEXT NOT NULL DEFAULT 'lily';
