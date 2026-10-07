from __future__ import annotations

from uuid import uuid4
import asyncio

import httpx
import pytest

from shared.auth.models import AuthUnavailable, CurrentUser, UnprovisionedIdentity
from shared.auth.providers import ExternalAuthProvider, LocalAuthProvider
from shared.user_paths import UserPaths


class FakeRepo:
    def __init__(self):
        self.user=CurrentUser(uuid4(),'alice','user')
    def resolve_local(self,guid):
        return self.user if guid=='valid' else None
    def resolve_external(self,provider,subject):
        return self.user if (provider,subject)==('test','stable-1') else None


def test_local_provider_resolves_guid():
    provider=LocalAuthProvider(FakeRepo())
    assert (asyncio.run(provider.resolve_guid('valid'))).username=='alice'
    assert asyncio.run(provider.resolve_guid('wrong')) is None


def test_external_guid_changes_keep_stable_user(monkeypatch):
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,json):
            return httpx.Response(200,json={'authenticated':True,'subject':'stable-1','username':'alice'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: Client())
    provider=ExternalAuthProvider(FakeRepo(),'https://auth.example/verify','test')
    first=asyncio.run(provider.resolve_guid('first'))
    second=asyncio.run(provider.resolve_guid('second'))
    assert first.user_id==second.user_id


def test_external_unprovisioned_and_timeout(monkeypatch):
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,json):
            return httpx.Response(200,json={'authenticated':True,'subject':'other'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: Client())
    provider=ExternalAuthProvider(FakeRepo(),'https://auth.example/verify','test')
    with pytest.raises(UnprovisionedIdentity):
        asyncio.run(provider.resolve_guid('any'))
    class TimeoutClient(Client):
        async def post(self,url,json): raise httpx.TimeoutException('timeout')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: TimeoutClient())
    with pytest.raises(AuthUnavailable):
        asyncio.run(provider.resolve_guid('any'))


def test_user_paths_use_canonical_uuid_not_username(tmp_path,monkeypatch):
    monkeypatch.setenv('USER_DATA_ROOT',str(tmp_path))
    value=uuid4()
    assert UserPaths.for_user(str(value).upper()).workspace==tmp_path/str(value)/'workspace'
    with pytest.raises(ValueError):
        UserPaths.for_user('../admin')
