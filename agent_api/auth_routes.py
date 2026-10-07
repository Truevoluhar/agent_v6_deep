from __future__ import annotations

import os
import re
import secrets
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from shared.auth.dependencies import get_repository, require_user
from shared.auth.models import CurrentUser
from shared.auth.repository import AuthRepository
from shared.public_urls import codespaces_peer_url

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class HandoffRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)


def _local() -> None:
    if os.environ.get('AUTH_MODE','local') != 'local':
        raise HTTPException(404,'Local login unavailable')


def _cookie(response, guid: str, request: Request):
    response.set_cookie('guid',guid,max_age=int(os.environ.get('AUTH_SESSION_TTL_SECONDS','43200')),
                        httponly=True,samesite='lax',secure=request.url.scheme == 'https' or _codespaces_peer(request) is not None or os.environ.get('AUTH_COOKIE_SECURE','false').lower()=='true',path='/')


def _codespaces_origin() -> str | None:
    name = os.environ.get('CODESPACE_NAME', '')
    if not re.fullmatch(r'[a-z0-9-]+', name):
        return None
    return f'https://{name}-8081.app.github.dev'


def _codespaces_peer(request: Request) -> str | None:
    peer = codespaces_peer_url(str(request.url), 8081, 8501)
    if peer:
        return peer
    expected = _codespaces_origin()
    forwarded_host = request.headers.get('x-forwarded-host', '').split(',')[0].strip()
    forwarded_proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip()
    if expected and ((request.headers.get('origin') == expected) or
                     (forwarded_host == urlparse(expected).netloc and forwarded_proto == 'https')):
        return codespaces_peer_url(expected, 8081, 8501)
    return None


def _public_url(request: Request):
    return _codespaces_peer(request) or os.environ.get('APP_PUBLIC_URL','http://localhost:8501')


def _login_redirect(request: Request, guid: str, repository: AuthRepository):
    peer = _codespaces_peer(request)
    target = f'{peer}/?{urlencode({"auth_code": repository.create_handoff(guid)})}' if peer else _public_url(request)
    response = RedirectResponse(target,status_code=303,headers={'Cache-Control':'no-store'})
    _cookie(response,guid,request)
    return response


def _check_origin(request: Request):
    origin=request.headers.get('origin')
    if origin:
        parsed=urlparse(origin)
        expected_scheme = 'https' if codespaces_peer_url(str(request.url),8081,8501) else request.url.scheme
        direct = parsed.hostname == request.url.hostname and parsed.scheme == expected_scheme
        codespaces = origin == _codespaces_origin()
        proxied_codespaces = (
            _codespaces_peer(request) is not None
            and request.headers.get('x-forwarded-host') == urlparse(_codespaces_origin() or '').netloc
            and parsed.scheme == 'http'
            and parsed.hostname in ('localhost', '127.0.0.1')
            and parsed.port == 8081
            and request.url.hostname in ('localhost', '127.0.0.1')
        )
        if not direct and not codespaces and not proxied_codespaces:
            raise HTTPException(403,'Invalid Origin')


@router.get('/auth/login')
def html_login(request: Request, repository: AuthRepository=Depends(get_repository)):
    if os.environ.get('AUTH_MODE','local')=='external':
        url=os.environ.get('AUTH_LOGIN_URL')
        if not url:
            raise HTTPException(503,'External login URL missing')
        return RedirectResponse(url)
    existing_guid = request.cookies.get('guid','')
    if existing_guid and _codespaces_peer(request) and repository.resolve_local(existing_guid):
        return _login_redirect(request,existing_guid,repository)
    nonce=secrets.token_urlsafe(24)
    body=f'''<!doctype html><html><head><meta charset="utf-8"><title>Prijava</title></head><body>
    <h1>Prijava</h1><form method="post" action="/auth/login">
    <input type="hidden" name="csrf" value="{nonce}">
    <label>Uporabnik <input name="username" required></label>
    <label>Geslo <input name="password" type="password" required></label>
    <button type="submit">Prijava</button></form></body></html>'''
    response=HTMLResponse(body,headers={'Cache-Control':'no-store'})
    response.set_cookie('login_csrf',nonce,httponly=True,samesite='lax',path='/',max_age=600)
    return response


@router.post('/auth/login')
def html_login_post(request: Request, username: str=Form(...), password: str=Form(...), csrf: str=Form(...), repository: AuthRepository=Depends(get_repository)):
    _local(); _check_origin(request)
    if not secrets.compare_digest(csrf,request.cookies.get('login_csrf','')):
        raise HTTPException(403,'Invalid CSRF token')
    result=repository.authenticate(username,password)
    if not result:
        return HTMLResponse('<h1>Nepravilna prijava</h1><a href="/auth/login">Poskusite znova</a>',status_code=401,headers={'Cache-Control':'no-store'})
    response=_login_redirect(request,result[0],repository)
    response.delete_cookie('login_csrf',path='/')
    return response


@router.post('/v1/auth/exchange')
def exchange_handoff(payload: HandoffRequest, repository: AuthRepository=Depends(get_repository)):
    _local()
    guid = repository.consume_handoff(payload.code)
    if not guid:
        raise HTTPException(401,'Invalid or expired login code')
    from fastapi.responses import JSONResponse
    return JSONResponse({'guid':guid},headers={'Cache-Control':'no-store'})


@router.post('/v1/auth/login')
def api_login(payload: LoginRequest, repository: AuthRepository=Depends(get_repository)):
    _local()
    result=repository.authenticate(payload.username,payload.password)
    if not result:
        raise HTTPException(401,'Invalid credentials')
    guid,expires,user=result
    from fastapi.responses import JSONResponse
    return JSONResponse({'guid':guid,'expires_at':expires.isoformat(),'user':{'user_id':str(user.user_id),'username':user.username,'role':user.role}},headers={'Cache-Control':'no-store'})


@router.get('/v1/auth/me')
def me(user: CurrentUser=Depends(require_user)):
    from fastapi.responses import JSONResponse
    return JSONResponse({'user_id':str(user.user_id),'username':user.username,'role':user.role,'auth_mode':os.environ.get('AUTH_MODE','local')},headers={'Cache-Control':'no-store'})


@router.post('/v1/auth/logout')
def api_logout(request: Request, user: CurrentUser=Depends(require_user), repository: AuthRepository=Depends(get_repository)):
    if os.environ.get('AUTH_MODE','local')!='local':
        raise HTTPException(501,'Use the external identity provider to log out')
    repository.revoke(request.query_params['guid'])
    from fastapi.responses import JSONResponse
    return JSONResponse({'logged_out':True},headers={'Cache-Control':'no-store'})


@router.post('/auth/logout')
async def html_logout(request: Request, repository: AuthRepository=Depends(get_repository)):
    _check_origin(request)
    form=await request.form()
    csrf=str(form.get('csrf',''))
    if not csrf or not secrets.compare_digest(csrf,request.cookies.get('logout_csrf','')):
        raise HTTPException(403,'Invalid CSRF token')
    if os.environ.get('AUTH_MODE','local')=='external':
        url=os.environ.get('AUTH_LOGOUT_URL')
        if not url:
            raise HTTPException(501,'External logout URL missing')
        return RedirectResponse(url,status_code=303,headers={'Cache-Control':'no-store'})
    guid=request.cookies.get('guid','')
    if guid:
        repository.revoke(guid)
    response=RedirectResponse(_public_url(request),status_code=303,headers={'Cache-Control':'no-store'})
    response.delete_cookie('guid',path='/'); response.delete_cookie('logout_csrf',path='/')
    return response


@router.get('/auth/logout')
def logout_form():
    nonce=secrets.token_urlsafe(24)
    response=HTMLResponse(f'<form method="post" action="/auth/logout"><input type="hidden" name="csrf" value="{nonce}"><button type="submit">Odjava</button></form>',headers={'Cache-Control':'no-store'})
    response.set_cookie('logout_csrf',nonce,httponly=True,samesite='lax',path='/',max_age=600)
    return response
