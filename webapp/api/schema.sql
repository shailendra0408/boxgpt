CREATE TABLE IF NOT EXISTS web_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_expires_at
ON web_sessions (expires_at);

-- Question history is retained so users can revisit answers and admins can review them.
CREATE TABLE IF NOT EXISTS web_question_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES web_users(id) ON DELETE SET NULL,
    question TEXT,
    answer TEXT,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    elapsed_ms INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    feedback TEXT CHECK (feedback IN ('accurate', 'needs_review')),
    reviewed_by BIGINT REFERENCES web_users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add fields to existing demo databases without losing their aggregate history.
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES web_users(id) ON DELETE SET NULL;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS question TEXT;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS answer TEXT;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS feedback TEXT;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS reviewed_by BIGINT REFERENCES web_users(id) ON DELETE SET NULL;
ALTER TABLE web_question_events ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_web_question_events_user_created_at
ON web_question_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_web_question_events_created_at
ON web_question_events (created_at);
