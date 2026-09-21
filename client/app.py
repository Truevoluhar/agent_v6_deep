from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://localhost:8080")
WORKSPACE_API_URL = os.environ.get("WORKSPACE_API_URL", "http://localhost:8090")
DEFAULT_UPLOAD_DIR = os.environ.get("CLIENT_DEFAULT_UPLOAD_DIR", "uploads")

st.set_page_config(page_title="DeepAgents Platform", layout="wide")
st.title("DeepAgents Platform")
st.caption("Chat with the workflow service and browse the shared workspace.")


def api_get(url: str, **kwargs: Any) -> Any:
    response = requests.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def api_post(url: str, **kwargs: Any) -> Any:
    response = requests.post(url, timeout=600, **kwargs)
    response.raise_for_status()
    return response.json()


def api_delete(url: str, **kwargs: Any) -> Any:
    response = requests.delete(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def load_threads() -> list[dict[str, Any]]:
    try:
        return api_get(f"{AGENT_API_URL}/v1/threads")
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Failed to load threads: {exc}")
        return []


def load_messages(thread_id: str) -> list[dict[str, Any]]:
    try:
        return api_get(f"{AGENT_API_URL}/v1/threads/{thread_id}/messages")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load messages: {exc}")
        return []


def load_files(path: str) -> list[dict[str, Any]]:
    try:
        return api_get(f"{WORKSPACE_API_URL}/v1/files", params={"path": path})
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load files: {exc}")
        return []


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None

with st.sidebar:
    st.subheader("Threads")
    if st.button("New Thread", use_container_width=True):
        thread = api_post(f"{AGENT_API_URL}/v1/threads")
        st.session_state.thread_id = thread["thread_id"]

    threads = load_threads()
    if threads:
        thread_options = {
            f"{item['thread_id']} | {item.get('title') or 'Untitled'}": item["thread_id"]
            for item in threads
        }
        selected = st.selectbox(
            "Choose thread",
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
        st.info("No threads yet.")

    st.subheader("Upload")
    upload_dir = st.text_input("Destination", value=DEFAULT_UPLOAD_DIR)
    uploaded = st.file_uploader("Choose a file")
    if st.button("Upload File", use_container_width=True, disabled=uploaded is None):
        files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")}
        data = {"destination": upload_dir}
        try:
            result = api_post(f"{WORKSPACE_API_URL}/v1/files", files=files, data=data)
            st.success(f"Uploaded to {result['path']}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Upload failed: {exc}")

    st.subheader("Workspace")
    browse_path = st.text_input("Browse path", value=st.session_state.get("browse_path", "/"))
    if st.button("Refresh Files", use_container_width=True):
        st.session_state["browse_path"] = browse_path


thread_id = st.session_state.thread_id

left, right = st.columns([3, 2])

with left:
    st.subheader("Chat")
    if thread_id is None:
        st.info("Create a thread to begin.")
    else:
        for message in load_messages(thread_id):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Ask the agent to work in the shared workspace")
        if prompt:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Running agent..."):
                    try:
                        response = api_post(
                            f"{AGENT_API_URL}/v1/threads/{thread_id}/messages",
                            json={"message": prompt},
                        )
                        st.markdown(response["reply"])
                        st.caption(f"{response['provider']} | {response['model']}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Agent request failed: {exc}")
            st.rerun()

with right:
    st.subheader("Workspace Files")
    current_path = st.session_state.get("browse_path", "/")
    st.caption(f"Listing `{current_path}`")
    entries = load_files(current_path)
    if not entries:
        st.write("No files found.")
    for entry in entries:
        cols = st.columns([4, 2, 1])
        cols[0].write(entry["path"])
        cols[1].write("dir" if entry["is_dir"] else f"{entry.get('size', 0)} bytes")
        if not entry["is_dir"]:
            if cols[2].button("Delete", key=f"delete:{entry['path']}"):
                try:
                    api_delete(f"{WORKSPACE_API_URL}/v1/files/{entry['path'].lstrip('/')}")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Delete failed: {exc}")
