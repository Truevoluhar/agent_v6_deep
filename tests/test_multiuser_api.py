from __future__ import annotations

from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_api import main as agent_main
from shared.auth.dependencies import get_repository
from shared.auth.models import CurrentUser
from shared.user_paths import UserPaths
from workspace_api import main as workspace_main


class FakeRepository:
    def __init__(self):
        self.handoffs = {}
        self.users = {
            'a': CurrentUser(uuid4(), 'alice', 'user'),
            'b': CurrentUser(uuid4(), 'bob', 'user'),
            'admin': CurrentUser(uuid4(), 'admin', 'admin'),
        }

    def resolve_local(self, guid):
        if guid.startswith('login-'):
            return next((item for item in self.users.values() if item.username==guid.removeprefix('login-')),None)
        return self.users.get(guid)

    def authenticate(self,username,password):
        user=next((item for item in self.users.values() if item.username==username),None)
        if not user or password!='secret': return None
        return f'login-{username}',datetime.now(UTC)+timedelta(hours=12),user

    def revoke(self,guid):
        self.users.pop(guid.removeprefix('login-'),None)

    def create_handoff(self,guid):
        code=f'code-{len(self.handoffs)}'
        self.handoffs[code]=guid
        return code

    def consume_handoff(self,code):
        return self.handoffs.pop(code,None)

    def list_users(self):
        return []


class FakeRuntime:
    def __init__(self, user, tmp_path):
        self.user_id = user.user_id
        self.config = SimpleNamespace(
            agent=SimpleNamespace(session_root=tmp_path / str(user.user_id) / 'sessions'),
            active_provider='fake', provider=SimpleNamespace(model='fake'),
        )
        self.config.agent.session_root.mkdir(parents=True, exist_ok=True)
        self.invocations = []

    async def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {'output': 'ok'}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'local')
    monkeypatch.setenv('USER_DATA_ROOT', str(tmp_path / 'users'))
    repo = FakeRepository()
    runtimes = {}
    def runtime(user):
        return runtimes.setdefault(user.user_id, FakeRuntime(user,tmp_path))
    monkeypatch.setattr(agent_main,'get_runtime',runtime)
    agent_main.app.dependency_overrides[get_repository] = lambda: repo
    workspace_main.app.dependency_overrides[get_repository] = lambda: repo
    yield TestClient(agent_main.app), TestClient(workspace_main.app), repo, runtimes
    agent_main.app.dependency_overrides.clear()
    workspace_main.app.dependency_overrides.clear()


def test_query_guid_required_in_both_apis(clients):
    agent,workspace,_,runtimes=clients
    assert agent.get('/v1/threads').status_code==401
    assert agent.get('/v1/threads',cookies={'guid':'a'}).status_code==401
    assert workspace.get('/v1/files',cookies={'guid':'a'}).status_code==401
    assert agent.get('/v1/threads?guid=wrong').status_code==401
    assert not runtimes


def test_threads_are_private_and_unknown_thread_does_not_invoke(clients):
    agent,_,repo,runtimes=clients
    created=agent.post('/v1/threads?guid=a').json()['thread_id']
    assert agent.get(f'/v1/threads/{created}?guid=b').status_code==404
    assert agent.get(f'/v1/threads/{created}/messages?guid=b').status_code==404
    assert agent.post(f'/v1/threads/{created}/messages?guid=b',json={'message':'hello'}).status_code==404
    assert agent.post(f'/v1/threads/{uuid4()}/messages?guid=a',json={'message':'hello'}).status_code==404
    assert not runtimes[repo.users['a'].user_id].invocations
    assert agent.post(f'/v1/threads/{created}/messages?guid=a',json={'message':'hello'}).status_code==200
    assert len(runtimes[repo.users['a'].user_id].invocations)==1


def test_workspace_is_private_and_symlink_is_rejected(clients,tmp_path):
    _,workspace,repo,_=clients
    response=workspace.post('/v1/files?guid=a',data={'destination':'uploads'},files={'file':('same.txt',b'alice')})
    assert response.status_code==200,response.text
    response=workspace.post('/v1/files?guid=b',data={'destination':'uploads'},files={'file':('same.txt',b'bob')})
    assert response.status_code==200,response.text
    assert workspace.get('/v1/files/uploads/same.txt?guid=a').content==b'alice'
    assert workspace.get('/v1/files/uploads/same.txt?guid=b').content==b'bob'
    a_root=UserPaths.for_user(repo.users['a'].user_id).workspace
    (a_root / 'uploads' / 'link.txt').symlink_to(UserPaths.for_user(repo.users['b'].user_id).workspace / 'uploads' / 'same.txt')
    assert workspace.get('/v1/files/uploads/link.txt?guid=a').status_code==400
    assert 'link.txt' not in [item['name'] for item in workspace.get('/v1/files?guid=a&path=/uploads').json()]
    assert workspace.delete('/v1/files/uploads/link.txt?guid=a').status_code==400


def test_admin_and_disabled_shell(clients):
    agent,_,_,_=clients
    assert agent.get('/v1/admin/users?guid=a').status_code==403
    assert agent.get('/v1/admin/users?guid=admin').status_code==200
    assert agent.post('/v1/processes?guid=a',json={'command':'cat /etc/passwd'}).status_code==403
    assert agent.get('/v1/processes/not-a-uuid?guid=a').status_code==422


def test_api_and_html_login_cookie_flow(clients):
    agent,_,_,_=clients
    response=agent.post('/v1/auth/login',json={'username':'alice','password':'secret'})
    assert response.status_code==200
    assert response.json()['guid']=='login-alice'
    assert response.headers['cache-control']=='no-store'
    assert agent.get('/v1/auth/me',params={'guid':'login-alice'}).json()['username']=='alice'
    login_page=agent.get('/auth/login')
    nonce=re.search(r'name="csrf" value="([^"]+)"',login_page.text).group(1)
    response=agent.post('/auth/login',data={'username':'alice','password':'secret','csrf':nonce},follow_redirects=False)
    assert response.status_code==303
    assert 'guid=login-alice' in response.headers['set-cookie']
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'samesite=lax' in response.headers['set-cookie'].lower()
    assert agent.post('/auth/login',data={'username':'alice','password':'secret','csrf':'wrong'},follow_redirects=False).status_code==403


def test_upload_quota_rejects_and_keeps_existing_file(clients,monkeypatch):
    _,workspace,_,_=clients
    first=workspace.post('/v1/files?guid=a',data={'destination':'uploads'},files={'file':('note.txt',b'first')})
    assert first.status_code==200
    monkeypatch.setenv('WORKSPACE_QUOTA_BYTES','6')
    rejected=workspace.post('/v1/files?guid=a',data={'destination':'uploads'},files={'file':('note.txt',b'too long')})
    assert rejected.status_code==413
    assert workspace.get('/v1/files/uploads/note.txt?guid=a').content==b'first'


def test_codespaces_browser_login_uses_one_time_handoff(clients):
    _,_,_,_=clients
    agent=TestClient(agent_main.app,base_url='https://demo-space-8081.app.github.dev')
    page=agent.get('/auth/login')
    nonce=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
    response=agent.post(
        '/auth/login',
        data={'username':'alice','password':'secret','csrf':nonce},
        headers={'Origin':'https://demo-space-8081.app.github.dev'},
        follow_redirects=False,
    )
    assert response.status_code==303
    assert response.headers['location']=='https://demo-space-8501.app.github.dev/?auth_code=code-0'
    assert 'secure' in response.headers['set-cookie'].lower()
    exchanged=agent.post('/v1/auth/exchange',json={'code':'code-0'})
    assert exchanged.json()['guid']=='login-alice'
    assert agent.post('/v1/auth/exchange',json={'code':'code-0'}).status_code==401


def test_codespaces_origin_behind_local_proxy(clients, monkeypatch):
    monkeypatch.setenv('CODESPACE_NAME', 'demo-space')
    agent = TestClient(agent_main.app, base_url='https://localhost:8081')
    forwarded = {
        'X-Forwarded-Host': 'demo-space-8081.app.github.dev',
        'X-Forwarded-Proto': 'https',
    }
    page = agent.get('/auth/login')
    nonce = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = agent.post(
        '/auth/login',
        data={'username': 'alice', 'password': 'secret', 'csrf': nonce},
        headers={**forwarded, 'Origin': 'http://localhost:8081'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers['location'] == 'https://demo-space-8501.app.github.dev/?auth_code=code-0'
    assert 'secure' in response.headers['set-cookie'].lower()
    rejected = agent.post(
        '/auth/login',
        data={'username': 'alice', 'password': 'secret', 'csrf': nonce},
        headers={**forwarded, 'Origin': 'https://other-space-8081.app.github.dev'},
        follow_redirects=False,
    )
    assert rejected.status_code == 403
