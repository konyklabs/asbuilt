-- Stack B's fact model (D-013; konyklabs/asbuilt#4), plain SQL, no migration
-- tool. store.py applies it inside the schema named by ASBUILT_PG_SCHEMA
-- (default asbuilt), after `CREATE EXTENSION vector` in public, and drops and
-- re-applies it on a full (non-incremental) ingest.
--
-- Two clocks, Graphiti's shape: valid_at / invalid_at are world time (when a
-- statement held); created_at / expired_at are stored time (when this store
-- knew it). A snapshot is a named point in stored time, never a copy.

CREATE TABLE source (
    id          text PRIMARY KEY,  -- wiki | docs | tickets | pulls | repo | runs
    description text
);

CREATE TABLE document (
    id           text PRIMARY KEY,  -- wiki/<slug>, doc/<id>, ticket/<KEY>, pull/<n>, code/<path>, run/<id>
    source_id    text NOT NULL REFERENCES source (id),
    kind         text NOT NULL,
    version      text,              -- page version, head revision, commit SHA, updated stamp
    lastmodified timestamptz,
    title        text,
    content_hash text,
    visibility   text NOT NULL DEFAULT 'internal',  -- D-013 boundary (4), carried from the start
    ingested_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE entity (
    id         text PRIMARY KEY,
    name       text NOT NULL,
    kind       text NOT NULL,       -- the fixed vocabulary every arm gets
    aliases    text[] NOT NULL DEFAULT '{}',
    folded     text[] NOT NULL DEFAULT '{}',  -- separator-folded name and aliases
    embedding  vector(384),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX entity_name_lower ON entity (lower(name));
CREATE INDEX entity_folded ON entity USING gin (folded);

CREATE TABLE entity_relation (
    src  text NOT NULL REFERENCES entity (id),
    dst  text NOT NULL REFERENCES entity (id),
    kind text NOT NULL,             -- part_of | related
    PRIMARY KEY (src, dst, kind)
);
CREATE INDEX entity_relation_dst ON entity_relation (dst);

CREATE TABLE fact (
    id              text PRIMARY KEY,  -- base_id, or base_id.<episode>
    base_id         text NOT NULL,     -- hash of the claim key plus the normalised statement
    episode         integer NOT NULL DEFAULT 0,
    statement       text NOT NULL,
    detail          text NOT NULL DEFAULT '',
    category        text NOT NULL CHECK (category IN
                        ('business-logic', 'technical-implementation', 'operations', 'history')),
    tier            text NOT NULL CHECK (tier IN ('executed', 'code', 'documented')),
    confidence      real,
    claim_entity    text REFERENCES entity (id),
    claim_attribute text,
    claim_value     text,              -- the normalised value as text
    claim_number    double precision,  -- the same value when numeric
    claim_unit      text,
    source_key      text,              -- the extractor's origin, e.g. test:<node id>
    valid_at        timestamptz,
    invalid_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    expired_at      timestamptz,
    superseded_by   text REFERENCES fact (id),
    embedding       vector(384),
    tsv             tsvector GENERATED ALWAYS AS
                        (to_tsvector('english', statement || ' ' || detail)) STORED,
    UNIQUE (base_id, episode),
    CHECK ((claim_entity IS NULL) = (claim_attribute IS NULL))
);
CREATE INDEX fact_tsv ON fact USING gin (tsv);
CREATE INDEX fact_claim ON fact (claim_entity, claim_attribute);
CREATE INDEX fact_source_key ON fact (source_key);
CREATE INDEX fact_valid_at ON fact (valid_at);
CREATE INDEX fact_embedding ON fact USING hnsw (embedding vector_cosine_ops);

CREATE TABLE fact_entity (
    fact_id   text NOT NULL REFERENCES fact (id) ON DELETE CASCADE,
    entity_id text NOT NULL REFERENCES entity (id),
    position  integer NOT NULL,
    PRIMARY KEY (fact_id, entity_id)
);
CREATE INDEX fact_entity_entity ON fact_entity (entity_id);

-- Every fact cites (AGENTS.md); store.py refuses a fact with no citation.
CREATE TABLE citation (
    fact_id     text NOT NULL REFERENCES fact (id) ON DELETE CASCADE,
    document_id text NOT NULL REFERENCES document (id),
    location    text NOT NULL DEFAULT '',  -- anchor, comment id, symbol, node id; '' when none
    version     text NOT NULL DEFAULT '',
    position    integer NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fact_id, document_id, location, version)
);
CREATE INDEX citation_document ON citation (document_id);

CREATE TABLE contradiction (
    id          text PRIMARY KEY,   -- hash of the sorted fact pair
    fact_a      text NOT NULL REFERENCES fact (id),
    fact_b      text NOT NULL REFERENCES fact (id),
    label       text NOT NULL CHECK (label IN ('supports', 'refutes')),
    winner      text REFERENCES fact (id),
    kind        text NOT NULL CHECK (kind IN ('claim', 'prose', 'run')),
    reason      text,
    opened_at   timestamptz,
    resolved_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX contradiction_a ON contradiction (fact_a);
CREATE INDEX contradiction_b ON contradiction (fact_b);

CREATE TABLE snapshot (
    name     text PRIMARY KEY,
    taken_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    step     text                  -- the history step an ingest reached, when it names one
);
