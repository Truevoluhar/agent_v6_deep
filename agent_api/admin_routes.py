from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation

from shared.auth.dependencies import get_repository, require_admin
from shared.auth.models import CurrentUser
from shared.auth.repository import AuthRepository

router=APIRouter(prefix='/v1/admin')

class NewUser(BaseModel):
    username: str=Field(min_length=1)
    password: str=Field(min_length=1)
    role: str='user'

class UserUpdate(BaseModel):
    username: str | None=None
    role: str | None=None
    is_active: bool | None=None

class PasswordReset(BaseModel):
    password: str=Field(min_length=1)

@router.get('/users')
def users(admin: CurrentUser=Depends(require_admin), repository: AuthRepository=Depends(get_repository)):
    return repository.list_users()

@router.post('/users',status_code=201)
def create_user(payload: NewUser, admin: CurrentUser=Depends(require_admin),repository: AuthRepository=Depends(get_repository)):
    try:
        user_id=repository.create_user(admin.user_id,payload.username,payload.password,payload.role)
    except UniqueViolation as exc:
        raise HTTPException(409,'Username exists') from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'user_id':str(user_id)}

@router.patch('/users/{user_id}')
async def update_user(user_id: UUID,payload: UserUpdate,request: Request,admin: CurrentUser=Depends(require_admin),repository: AuthRepository=Depends(get_repository)):
    try:
        found=repository.update_user(admin.user_id,user_id,payload.model_dump(exclude_unset=True))
    except UniqueViolation as exc:
        raise HTTPException(409,'Username exists') from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if not found:
        raise HTTPException(404,'User not found')
    if payload.is_active is False:
        cancel = getattr(request.app.state, "cancel_user_tasks", None)
        if cancel:
            cancel(user_id)
    return {'updated':True}

@router.post('/users/{user_id}/reset-password')
def reset_password(user_id: UUID,payload: PasswordReset,admin: CurrentUser=Depends(require_admin),repository: AuthRepository=Depends(get_repository)):
    if os.environ.get('AUTH_MODE','local')!='local':
        raise HTTPException(404,'Local passwords unavailable')
    if not repository.reset_password(admin.user_id,user_id,payload.password):
        raise HTTPException(404,'User not found')
    return {'updated':True}

@router.post('/users/{user_id}/revoke-sessions')
def revoke_sessions(user_id: UUID,admin: CurrentUser=Depends(require_admin),repository: AuthRepository=Depends(get_repository)):
    if not repository.revoke_user_sessions(user_id):
        raise HTTPException(404,'User not found')
    return {'revoked':True}

class ExternalLink(BaseModel):
    provider: str=Field(min_length=1)
    subject: str=Field(min_length=1)

@router.post('/users/{user_id}/external-identities',status_code=201)
def link_external(user_id: UUID,payload: ExternalLink,admin: CurrentUser=Depends(require_admin),repository: AuthRepository=Depends(get_repository)):
    try:
        found=repository.link_external(admin.user_id,user_id,payload.provider,payload.subject)
    except UniqueViolation as exc:
        raise HTTPException(409,'External identity already linked') from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if not found:
        raise HTTPException(404,'User not found')
    return {'linked':True}
