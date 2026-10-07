from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request
from shared.auth.models import AuthUnavailable, CurrentUser, UnprovisionedIdentity
from shared.auth.providers import make_provider
from shared.auth.repository import AuthRepository


def get_repository(request: Request) -> AuthRepository:
    return getattr(request.app.state,'auth_repository',None) or AuthRepository()


async def resolve_guid(guid: str, repository: AuthRepository) -> CurrentUser:
    if not guid:
        raise HTTPException(401,'Missing guid')
    try:
        user = await make_provider(repository).resolve_guid(guid)
    except AuthUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc
    except UnprovisionedIdentity as exc:
        raise HTTPException(403,str(exc)) from exc
    if user is None:
        raise HTTPException(401,'Invalid guid')
    return user


async def require_user(guid: str | None = Query(default=None), repository: AuthRepository = Depends(get_repository)) -> CurrentUser:
    return await resolve_guid(guid or '',repository)


async def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role != 'admin':
        raise HTTPException(403,'Admin required')
    return user
