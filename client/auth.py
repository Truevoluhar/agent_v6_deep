from __future__ import annotations

import os
import html
from urllib.parse import urlsplit, urlunsplit

import requests
import streamlit as st

from client.service_urls import resolve_agent_api_url
from shared.public_urls import codespaces_peer_url


def browser_agent_url() -> str:
    configured = os.environ.get('AGENT_API_PUBLIC_URL')
    if configured:
        return configured.rstrip('/')
    current = urlsplit(st.context.url)
    peer = codespaces_peer_url(st.context.url, 8501, 8081)
    if peer:
        return peer
    return urlunsplit((current.scheme, f'{current.hostname}:8081', '', '', ''))


def current_guid() -> str | None:
    return getattr(st, 'session_state', {}).get('auth_guid') or st.context.cookies.get('guid')


def _login_form(message: str | None = None) -> None:
    if message:
        st.warning(message)
    if os.environ.get('AUTH_MODE', 'local') == 'external':
        navigation_link('Prijava', f'{browser_agent_url()}/auth/login')
        st.stop()
    st.subheader('Prijava')
    with st.form('client_login'):
        username = st.text_input('Uporabniško ime')
        password = st.text_input('Geslo', type='password')
        submitted = st.form_submit_button('Prijava')
    if submitted:
        try:
            response = requests.post(
                f'{resolve_agent_api_url()}/v1/auth/login',
                json={'username': username, 'password': password},
                timeout=15,
            )
            response.raise_for_status()
            st.session_state.auth_guid = response.json()['guid']
            st.rerun()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                st.error('Nepravilno uporabniško ime ali geslo.')
            else:
                st.error('Prijava trenutno ni na voljo.')
        except (requests.RequestException, KeyError, ValueError):
            st.error('Prijava trenutno ni na voljo.')
    st.stop()


def logout() -> None:
    guid = current_guid()
    if guid and os.environ.get('AUTH_MODE', 'local') == 'local':
        try:
            response = requests.post(
                f'{resolve_agent_api_url()}/v1/auth/logout',
                params={'guid': guid},
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException:
            st.error('Odjava ni uspela. Poskusite znova.')
            return
    st.session_state.clear()
    st.rerun()


def require_login() -> tuple[str, dict]:
    code = getattr(st, 'query_params', {}).get('auth_code')
    if code:
        try:
            response = requests.post(
                f'{resolve_agent_api_url()}/v1/auth/exchange',
                json={'code':code},
                timeout=15,
            )
            response.raise_for_status()
            st.session_state.auth_guid = response.json()['guid']
        except (requests.RequestException, KeyError, ValueError):
            st.warning('Prijavna povezava je potekla. Prijavite se znova.')
        finally:
            st.query_params.clear()
    guid = current_guid()
    if not guid:
        _login_form()
    try:
        response = requests.get(f'{resolve_agent_api_url()}/v1/auth/me',params={'guid':guid},timeout=15)
        response.raise_for_status()
        user = response.json()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (401, 403):
            st.session_state.pop('auth_guid', None)
            _login_form('Prijava ni več veljavna. Prijavite se znova.')
        st.error('Storitev trenutno ni dosegljiva.')
        st.stop()
    except requests.RequestException:
        st.error('Storitev trenutno ni dosegljiva.')
        st.stop()
    previous = st.session_state.get('auth_user_id')
    if previous != user['user_id']:
        keep = {'auth_user_id'}
        if st.session_state.get('auth_guid'):
            keep.add('auth_guid')
        for key in list(st.session_state.keys()):
            if key not in keep:
                del st.session_state[key]
        st.session_state.auth_user_id = user['user_id']
    return guid,user


def with_guid(params=None):
    return {'guid':current_guid(),**(params or {})}


def safe_error(error: Exception) -> str:
    message = str(error)
    guid = current_guid()
    return message.replace(guid, '[redacted]') if guid else message


def navigation_link(label: str, url: str) -> None:
    """Navigate in this tab so Streamlit receives the new browser cookie."""
    st.markdown(
        f'<a href="{html.escape(url, quote=True)}" target="_self">{html.escape(label)}</a>',
        unsafe_allow_html=True,
    )
