-- Pets get a look (validated JSON), skills (free text the owner writes) and an optional model they always use.
ALTER TABLE agents ADD COLUMN skills TEXT NOT NULL DEFAULT '' CHECK (length(skills) <= 6000);
ALTER TABLE agents ADD COLUMN model  TEXT NOT NULL DEFAULT '' CHECK (length(model) <= 80);
ALTER TABLE agents ADD COLUMN look   TEXT NOT NULL DEFAULT '{}';
