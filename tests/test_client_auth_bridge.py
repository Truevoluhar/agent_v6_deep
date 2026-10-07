from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace


class SessionState(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def test_codespaces_handoff_stays_in_streamlit_session(monkeypatch):
    streamlit = ModuleType('streamlit')
    streamlit.context = SimpleNamespace(
        url='https://demo-space-8501.app.github.dev/', cookies={}
    )
    streamlit.query_params = {'auth_code': 'one-time-code'}
    streamlit.session_state = SessionState()
    monkeypatch.setitem(sys.modules, 'streamlit', streamlit)

    import client.auth as auth
    importlib.reload(auth)
    monkeypatch.setattr(auth, 'resolve_agent_api_url', lambda: 'http://agent-api:8081')

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def post(url, **kwargs):
        assert url.endswith('/v1/auth/exchange')
        assert kwargs['json'] == {'code': 'one-time-code'}
        response = Response()
        response.payload = {'guid': 'verified-guid'}
        return response

    def get(url, **kwargs):
        assert url.endswith('/v1/auth/me')
        assert kwargs['params'] == {'guid': 'verified-guid'}
        response = Response()
        response.payload = {'user_id': 'user-uuid', 'username': 'alice', 'role': 'user'}
        return response

    monkeypatch.setattr(auth.requests, 'post', post)
    monkeypatch.setattr(auth.requests, 'get', get)
    assert auth.browser_agent_url() == 'https://demo-space-8081.app.github.dev'
    assert auth.require_login()[0] == 'verified-guid'
    assert not streamlit.query_params
    assert auth.require_login()[0] == 'verified-guid'


def test_streamlit_login_and_logout_use_session_token(monkeypatch):
    class Stopped(Exception):
        pass

    class Rerun(Exception):
        pass

    class Form:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    streamlit = ModuleType('streamlit')
    streamlit.context = SimpleNamespace(url='https://demo-space-8501.app.github.dev/', cookies={})
    streamlit.query_params = {}
    streamlit.session_state = SessionState()
    streamlit.subheader = lambda *args, **kwargs: None
    streamlit.form = lambda *args, **kwargs: Form()
    streamlit.text_input = lambda label, **kwargs: 'alice' if label == 'Uporabniško ime' else 'secret'
    streamlit.form_submit_button = lambda *args, **kwargs: True
    streamlit.rerun = lambda: (_ for _ in ()).throw(Rerun())
    streamlit.stop = lambda: (_ for _ in ()).throw(Stopped())
    monkeypatch.setitem(sys.modules, 'streamlit', streamlit)

    import client.auth as auth
    importlib.reload(auth)
    monkeypatch.setenv('AUTH_MODE', 'local')
    monkeypatch.setattr(auth, 'resolve_agent_api_url', lambda: 'http://agent-api:8081')

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({'guid': 'verified-guid'})

    monkeypatch.setattr(auth.requests, 'post', post)
    monkeypatch.setattr(auth.requests, 'get', lambda *args, **kwargs: Response({
        'user_id': 'user-uuid', 'username': 'alice', 'role': 'user',
    }))
    import pytest
    with pytest.raises(Rerun):
        auth.require_login()
    assert calls[0][0].endswith('/v1/auth/login')
    assert calls[0][1]['json'] == {'username': 'alice', 'password': 'secret'}
    assert auth.require_login()[0] == 'verified-guid'
    with pytest.raises(Rerun):
        auth.logout()
    assert calls[1][0].endswith('/v1/auth/logout')
    assert calls[1][1]['params'] == {'guid': 'verified-guid'}
    assert not streamlit.session_state
