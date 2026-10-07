CREATE TABLE IF NOT EXISTS app_users (
 id UUID PRIMARY KEY, username TEXT NOT NULL, password_plain TEXT,
 role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS app_users_username_ci ON app_users (lower(username));
CREATE TABLE IF NOT EXISTS auth_sessions (
 guid TEXT PRIMARY KEY, user_id UUID NOT NULL REFERENCES app_users(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS auth_sessions_user_id ON auth_sessions(user_id);
CREATE TABLE IF NOT EXISTS auth_handoffs (
 code TEXT PRIMARY KEY,
 guid TEXT NOT NULL REFERENCES auth_sessions(guid),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_handoffs_expires_at ON auth_handoffs(expires_at);
CREATE TABLE IF NOT EXISTS external_identities (
 provider TEXT NOT NULL, subject TEXT NOT NULL,
 user_id UUID NOT NULL REFERENCES app_users(id),
 PRIMARY KEY(provider,subject), UNIQUE(provider,user_id)
);
CREATE TABLE IF NOT EXISTS admin_audit (
 id BIGSERIAL PRIMARY KEY, actor_user_id UUID NOT NULL,
 target_user_id UUID NOT NULL, action TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
