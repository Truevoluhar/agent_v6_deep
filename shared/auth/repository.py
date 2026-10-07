from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from shared.auth.models import CurrentUser


class AuthRepository:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get('AUTH_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'postgresql://deepagents:deepagents@localhost:5432/deepagents'

    def connect(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def initialize(self) -> None:
        sql = (Path(__file__).resolve().parents[2] / 'migrations' / '001_users.sql').read_text()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                if os.environ.get('AUTH_MODE', 'local') == 'local':
                    cur.execute('SELECT pg_advisory_xact_lock(7721031)')
                    username = os.environ.get('AUTH_BOOTSTRAP_ADMIN_USERNAME', 'admin').strip()
                    cur.execute('SELECT id, role FROM app_users WHERE lower(username)=lower(%s)', (username,))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute('INSERT INTO app_users(id,username,password_plain,role) VALUES(%s,%s,%s,%s)', (uuid4(), username, os.environ.get('AUTH_BOOTSTRAP_ADMIN_PASSWORD', 'admin123'), 'admin'))
                    elif row[1] != 'admin':
                        raise RuntimeError('Bootstrap admin username belongs to a non-admin account')

    def authenticate(self, username: str, password: str):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT id,username,role FROM app_users WHERE lower(username)=lower(%s) AND password_plain=%s AND is_active=TRUE', (username.strip(), password))
            row = cur.fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            expires = datetime.now(UTC) + timedelta(seconds=int(os.environ.get('AUTH_SESSION_TTL_SECONDS', '43200')))
            cur.execute('INSERT INTO auth_sessions(guid,user_id,expires_at) VALUES(%s,%s,%s)', (token, row[0], expires))
            return token, expires, CurrentUser(*row)

    def resolve_local(self, guid: str):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('''SELECT u.id,u.username,u.role FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
                WHERE s.guid=%s AND s.revoked_at IS NULL AND s.expires_at>now() AND u.is_active=TRUE''', (guid,))
            row = cur.fetchone()
            return CurrentUser(*row) if row else None

    def resolve_external(self, provider: str, subject: str):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('''SELECT u.id,u.username,u.role FROM external_identities e JOIN app_users u ON u.id=e.user_id
                WHERE e.provider=%s AND e.subject=%s AND u.is_active=TRUE''', (provider,subject))
            row = cur.fetchone()
            return CurrentUser(*row) if row else None

    def revoke(self, guid: str):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('UPDATE auth_sessions SET revoked_at=now() WHERE guid=%s', (guid,))

    def create_handoff(self, guid: str) -> str:
        code = secrets.token_urlsafe(32)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM auth_handoffs WHERE expires_at <= now()')
            cur.execute(
                "INSERT INTO auth_handoffs(code,guid,expires_at) VALUES(%s,%s,now() + interval '60 seconds')",
                (code, guid),
            )
        return code

    def consume_handoff(self, code: str) -> str | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM auth_handoffs WHERE code=%s AND expires_at>now() RETURNING guid', (code,))
            row = cur.fetchone()
        if row and self.resolve_local(row[0]) is not None:
            return row[0]
        return None

    def list_users(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT id,username,role,is_active,created_at,updated_at FROM app_users ORDER BY lower(username)')
            return [self._user_row(row) for row in cur.fetchall()]

    @staticmethod
    def _user_row(row):
        return dict(zip(('user_id','username','role','is_active','created_at','updated_at'), row))

    def create_user(self, actor: UUID, username: str, password: str, role: str):
        username = username.strip()
        if not username or role not in ('user','admin'):
            raise ValueError('Invalid username or role')
        user_id = uuid4()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO app_users(id,username,password_plain,role) VALUES(%s,%s,%s,%s)', (user_id,username,password,role))
            cur.execute('INSERT INTO admin_audit(actor_user_id,target_user_id,action) VALUES(%s,%s,%s)', (actor,user_id,'create'))
        return user_id

    def update_user(self, actor: UUID, user_id: UUID, changes: dict):
        allowed = {'username','role','is_active'}
        if not changes or set(changes)-allowed or any(value is None for value in changes.values()):
            raise ValueError('Invalid update')
        if 'username' in changes:
            changes['username'] = changes['username'].strip()
            if not changes['username']:
                raise ValueError('Empty username')
        if 'role' in changes and changes['role'] not in ('user','admin'):
            raise ValueError('Invalid role')
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT role,is_active FROM app_users WHERE id=%s FOR UPDATE', (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            if row[0]=='admin' and row[1] and (changes.get('role')=='user' or changes.get('is_active') is False):
                cur.execute('SELECT pg_advisory_xact_lock(7721032)')
                cur.execute("SELECT count(*) FROM app_users WHERE role='admin' AND is_active=TRUE")
                if cur.fetchone()[0] <= 1:
                    raise ValueError('Cannot remove the last active admin')
            for key,value in changes.items():
                cur.execute(f'UPDATE app_users SET {key}=%s,updated_at=now() WHERE id=%s', (value,user_id))
            if changes.get('is_active') is False:
                cur.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user_id,))
            actions = []
            if 'username' in changes:
                actions.append('rename')
            if 'role' in changes:
                actions.append('change_role')
            if changes.get('is_active') is False:
                actions.append('deactivate')
            elif changes.get('is_active') is True:
                actions.append('activate')
            for action in actions:
                cur.execute('INSERT INTO admin_audit(actor_user_id,target_user_id,action) VALUES(%s,%s,%s)', (actor,user_id,action))
        return True

    def reset_password(self, actor: UUID, user_id: UUID, password: str):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('UPDATE app_users SET password_plain=%s,updated_at=now() WHERE id=%s', (password,user_id))
            if not cur.rowcount:
                return False
            cur.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user_id,))
            cur.execute('INSERT INTO admin_audit(actor_user_id,target_user_id,action) VALUES(%s,%s,%s)', (actor,user_id,'reset_password'))
        return True

    def revoke_user_sessions(self, user_id: UUID):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1 FROM app_users WHERE id=%s', (user_id,))
            if not cur.fetchone():
                return False
            cur.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user_id,))
        return True

    def link_external(self, actor: UUID, user_id: UUID, provider: str, subject: str) -> bool:
        if not provider.strip() or not subject.strip():
            raise ValueError('Provider and subject are required')
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1 FROM app_users WHERE id=%s',(user_id,))
            if not cur.fetchone():
                return False
            cur.execute('INSERT INTO external_identities(provider,subject,user_id) VALUES(%s,%s,%s)',(provider.strip(),subject.strip(),user_id))
            cur.execute('INSERT INTO admin_audit(actor_user_id,target_user_id,action) VALUES(%s,%s,%s)',(actor,user_id,'link_external'))
        return True
