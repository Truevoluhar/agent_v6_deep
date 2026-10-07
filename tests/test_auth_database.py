"""Run with TEST_AUTH_DATABASE_URL pointing to a disposable PostgreSQL server."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from shared.auth.repository import AuthRepository


def test_postgres_bootstrap_sessions_and_admin_invariant(monkeypatch):
    base=os.environ.get('TEST_AUTH_DATABASE_URL')
    if not base:
        pytest.skip('TEST_AUTH_DATABASE_URL is not configured')
    psycopg=pytest.importorskip('psycopg')
    from psycopg.conninfo import make_conninfo
    name='auth_test_'+uuid4().hex[:12]
    with psycopg.connect(base,autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE {name}')
    try:
        monkeypatch.setenv('AUTH_MODE','local')
        repo=AuthRepository(make_conninfo(base,dbname=name))
        repo.initialize()
        admin_login=repo.authenticate('admin','admin123')
        assert admin_login is not None
        handoff=repo.create_handoff(admin_login[0])
        assert repo.consume_handoff(handoff)==admin_login[0]
        assert repo.consume_handoff(handoff) is None
        admin=admin_login[2]
        assert admin.role=='admin'
        user_id=repo.create_user(admin.user_id,' Alice ','secret','user')
        assert repo.authenticate('alice','secret')[2].user_id==user_id
        assert repo.link_external(admin.user_id,user_id,'test','stable-subject')
        assert repo.resolve_external('test','stable-subject').user_id==user_id
        repo.reset_password(admin.user_id,admin.user_id,'changed')
        repo.initialize()
        assert repo.authenticate('admin','admin123') is None
        assert repo.authenticate('admin','changed') is not None
        assert repo.resolve_local(admin_login[0]) is None
        with pytest.raises(ValueError,match='last active admin'):
            repo.update_user(admin.user_id,admin.user_id,{'is_active':False})
    finally:
        with psycopg.connect(base,autocommit=True) as conn:
            conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
            conn.execute(f'DROP DATABASE {name}')
