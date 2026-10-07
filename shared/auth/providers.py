from __future__ import annotations

import os
from typing import Protocol

from shared.auth.models import AuthUnavailable, CurrentUser, UnprovisionedIdentity
from shared.auth.repository import AuthRepository


class AuthProvider(Protocol):
    async def resolve_guid(self, guid: str) -> CurrentUser | None: ...


class LocalAuthProvider:
    def __init__(self, repository: AuthRepository):
        self.repository = repository

    async def resolve_guid(self, guid: str):
        return self.repository.resolve_local(guid)


class ExternalAuthProvider:
    def __init__(self, repository: AuthRepository, verify_url: str, provider: str = 'external'):
        self.repository = repository
        self.verify_url = verify_url
        self.provider = provider

    async def resolve_guid(self, guid: str):
        import httpx
        try:
            async with httpx.AsyncClient(timeout=float(os.environ.get('AUTH_VERIFY_TIMEOUT_SECONDS','5'))) as client:
                response = await client.post(self.verify_url, json={'guid':guid})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise AuthUnavailable('External verifier unavailable') from exc
        if not isinstance(payload,dict) or not isinstance(payload.get('authenticated'),bool):
            raise AuthUnavailable('Invalid verifier response')
        if not payload['authenticated']:
            return None
        subject = payload.get('subject')
        if not isinstance(subject,str) or not subject:
            raise AuthUnavailable('Verifier omitted subject')
        user = self.repository.resolve_external(self.provider,subject)
        if user is None:
            raise UnprovisionedIdentity('Contact administrator to link external identity')
        return user


def make_provider(repository: AuthRepository) -> AuthProvider:
    mode = os.environ.get('AUTH_MODE','local')
    if mode == 'local':
        return LocalAuthProvider(repository)
    if mode == 'external':
        url = os.environ.get('AUTH_VERIFY_URL')
        if not url:
            raise ValueError('AUTH_VERIFY_URL required')
        return ExternalAuthProvider(repository,url,os.environ.get('AUTH_EXTERNAL_PROVIDER','external'))
    raise ValueError('Invalid AUTH_MODE')
