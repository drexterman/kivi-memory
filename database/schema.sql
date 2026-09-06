PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    raw_asr TEXT NOT NULL,
    formatted_text TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transcripts_timestamp ON transcripts(timestamp);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('FACT', 'PREFERENCE', 'EPISODE')),
    title TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'UNCERTAIN', 'DELETED')),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_subject ON memories(subject);

CREATE TABLE IF NOT EXISTS memory_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    transcript_id INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE,
    UNIQUE(memory_id, transcript_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_sources_memory ON memory_sources(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_transcript ON memory_sources(transcript_id);

CREATE TABLE IF NOT EXISTS memory_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    source_transcript_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (source_transcript_id) REFERENCES transcripts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_history_memory ON memory_history(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_history_source ON memory_history(source_transcript_id);

-- Every extraction attempt is observable, including deliberate rejection.
CREATE TABLE IF NOT EXISTS memory_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id INTEGER NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('CREATE', 'UPDATE', 'RETAIN', 'REJECT', 'UNCERTAIN')),
    candidate TEXT NOT NULL,
    reason TEXT NOT NULL,
    resulting_memory_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE,
    FOREIGN KEY (resulting_memory_id) REFERENCES memories(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_decisions_transcript
    ON memory_decisions(transcript_id);
CREATE INDEX IF NOT EXISTS idx_memory_decisions_decision
    ON memory_decisions(decision);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    raw_asr,
    formatted_text,
    content='transcripts',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, raw_asr, formatted_text)
    VALUES (new.id, new.raw_asr, new.formatted_text);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, raw_asr, formatted_text)
    VALUES ('delete', old.id, old.raw_asr, old.formatted_text);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, raw_asr, formatted_text)
    VALUES ('delete', old.id, old.raw_asr, old.formatted_text);
    INSERT INTO transcripts_fts(rowid, raw_asr, formatted_text)
    VALUES (new.id, new.raw_asr, new.formatted_text);
END;


CREATE TABLE IF NOT EXISTS answer_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT,
    memory_ids TEXT NOT NULL DEFAULT '[]',
    source_transcript_ids TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL CHECK (decision IN ('ANSWER', 'ABSTAIN')),
    evidence_verdict TEXT NOT NULL CHECK (evidence_verdict IN ('SUPPORTED', 'CONTRADICTED', 'UNCERTAIN', 'UNSUPPORTED')),
    evidence_reason TEXT NOT NULL,
    latency_ms REAL,
    model TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_answer_runs_created_at ON answer_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_answer_runs_decision ON answer_runs(decision);
