from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.auth import require_login, with_guid, logout, safe_error

try:
    from service_urls import resolve_agent_api_url, resolve_workspace_api_url
except ModuleNotFoundError:
    from client.service_urls import resolve_agent_api_url, resolve_workspace_api_url

DEFAULT_UPLOAD_DIR = os.environ.get("CLIENT_DEFAULT_UPLOAD_DIR", "uploads")
DEFAULT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

st.set_page_config(page_title="ZPIZAgent platforma", layout="wide")
st.title("ZPIZAgent platforma")
st.caption("Pogovarjajte se z agentom in brskajte po deljenem delovnem prostoru.")
guid, current_user = require_login()
legacy_root = Path(os.environ.get("USER_DATA_ROOT", str(Path(os.environ.get("AGENT_DATA_ROOT", "/data")) / "users"))) / current_user["user_id"] / "legacy_sessions"
if legacy_root.exists() and any(legacy_root.iterdir()):
    st.info("Stara zgodovina je arhivirana. Novi pogovori ne nadaljujejo starega modelnega stanja.")


def api_get(url: str, **kwargs: Any) -> Any:
    kwargs["params"] = with_guid(kwargs.get("params"))
    response = requests.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def api_post(url: str, **kwargs: Any) -> Any:
    kwargs["params"] = with_guid(kwargs.get("params"))
    response = requests.post(url, timeout=600, **kwargs)
    response.raise_for_status()
    return response.json()


def api_delete(url: str, **kwargs: Any) -> Any:
    kwargs["params"] = with_guid(kwargs.get("params"))
    response = requests.delete(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def load_threads() -> list[dict[str, Any]]:
    try:
        return api_get(f"{resolve_agent_api_url()}/v1/threads")
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Pogovorov ni bilo mogoče naložiti: {safe_error(exc)}")
        return []


def load_messages(thread_id: str) -> list[dict[str, Any]]:
    try:
        return api_get(f"{resolve_agent_api_url()}/v1/threads/{thread_id}/messages")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Sporočil ni bilo mogoče naložiti: {safe_error(exc)}")
        return []


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None

with st.sidebar:
    st.caption(f"Prijavljen: {current_user['username']}")
    if st.button('Odjava', use_container_width=True):
        logout()
    if current_user["role"] == "admin":
        st.page_link("pages/admin.py", label="Uporabniki", icon=":material/admin_panel_settings:", use_container_width=True)
    st.subheader("Pogovori")
    if st.button("Nov pogovor", use_container_width=True):
        try:
            thread = api_post(f"{resolve_agent_api_url()}/v1/threads")
            st.session_state.thread_id = thread["thread_id"]
        except Exception as exc:  # noqa: BLE001
            st.error(f"Pogovora ni bilo mogoče ustvariti: {safe_error(exc)}")

    threads = load_threads()
    if threads:
        thread_options = {
            f"{item['thread_id']} | {item.get('title') or 'Brez naslova'}": item["thread_id"]
            for item in threads
        }
        selected = st.selectbox(
            "Izberite pogovor",
            options=list(thread_options.keys()),
            index=0 if st.session_state.thread_id is None else next(
                (
                    idx
                    for idx, thread_key in enumerate(thread_options.keys())
                    if thread_options[thread_key] == st.session_state.thread_id
                ),
                0,
            ),
        )
        st.session_state.thread_id = thread_options[selected]
    else:
        st.info("Ni še nobenega pogovora.")

    st.subheader("Nalaganje datotek")
    upload_dir = st.text_input("Ciljna mapa", value=DEFAULT_UPLOAD_DIR)
    uploaded = st.file_uploader("Izberite datoteko")
    if st.button("Naloži datoteko", use_container_width=True, disabled=uploaded is None):
        files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")}
        data = {"destination": upload_dir}
        try:
            result = api_post(f"{resolve_workspace_api_url()}/v1/files", files=files, data=data)
            st.success(f"Datoteka je naložena v {result['path']}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Nalaganje ni uspelo: {safe_error(exc)}")

    st.page_link(
        "pages/workspace.py",
        label="Odpri delovni prostor",
        icon=":material/folder_open:",
        use_container_width=True,
    )


thread_id = st.session_state.thread_id

left, right = st.columns([3, 2])

with left:
    st.subheader("Klepet")
    if thread_id is None:
        st.info("Za začetek ustvarite pogovor.")
    else:
        response_format_label = st.selectbox("Oblika odgovora", ["Privzeta", "Shema JSON"])
        response_schema_text = None
        if response_format_label == "Shema JSON":
            response_schema_text = st.text_area(
                "Shema JSON",
                value=json.dumps(DEFAULT_RESPONSE_SCHEMA, indent=2),
                height=220,
            )
            st.caption(
                "Strogi način zahteva vse navedene lastnosti in nastavitev "
                "`additionalProperties: false` pri vsakem objektu."
            )
        for message in load_messages(thread_id):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Napišite sporočilo agentu za delo v deljenem delovnem prostoru")
        if prompt:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Agent izvaja opravilo ..."):
                    try:
                        request_payload = {"message": prompt}
                        if response_schema_text is not None:
                            response_schema = json.loads(response_schema_text)
                            if not isinstance(response_schema, dict):
                                raise ValueError("Shema mora biti objekt JSON.")
                            request_payload["response_schema"] = response_schema
                        response = api_post(
                            f"{resolve_agent_api_url()}/v1/threads/{thread_id}/messages",
                            json=request_payload,
                        )
                        if response_schema_text is not None:
                            st.code(response["reply"], language="json")
                        else:
                            st.markdown(response["reply"])
                        st.caption(f"{response['provider']} | {response['model']}")
                    except (json.JSONDecodeError, ValueError) as exc:
                        st.error(f"Neveljavna shema JSON: {safe_error(exc)}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Zahteva za agenta ni bilo mogoče izvesti: {safe_error(exc)}")
            st.rerun()

with right:
    st.subheader("Delovni prostor")
    st.page_link(
        "pages/workspace.py",
        label="Pregled map in datotek",
        icon=":material/folder_open:",
        use_container_width=True,
    )
