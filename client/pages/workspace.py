from __future__ import annotations

import base64
import mimetypes
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

try:
    from service_urls import resolve_workspace_api_url
except ModuleNotFoundError:
    from client.service_urls import resolve_workspace_api_url

WORKSPACE_API = resolve_workspace_api_url()
MAX_ENTRIES = 10_000
MAX_PREVIEW_BYTES = 1_000_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx",
    ".py", ".sh", ".bash", ".sql", ".log", ".ini", ".conf", ".env", ".dockerfile",
    ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".swift",
}
CODE_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".json": "json", ".html": "html", ".htm": "html",
    ".css": "css", ".sh": "bash", ".bash": "bash", ".sql": "sql", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".xml": "xml", ".md": "markdown",
    ".java": "java", ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift",
}

st.set_page_config(page_title="Delovni prostor | ZPIZAgent platforma", layout="wide")
st.page_link("app.py", label="Nazaj na klepet", icon=":material/arrow_back:")
st.title("Delovni prostor")
st.caption("Brskajte po mapah in datotekah delovnega prostora.")


def get_entries(path: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{WORKSPACE_API}/v1/files",
        params={"path": path, "max_entries": MAX_ENTRIES},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def get_file_response(path: str) -> requests.Response:
    encoded_path = quote(path.lstrip("/"), safe="/")
    response = requests.get(f"{WORKSPACE_API}/v1/files/{encoded_path}", timeout=600)
    response.raise_for_status()
    return response


def get_archive(path: str) -> tuple[str, bytes]:
    response = requests.get(
        f"{WORKSPACE_API}/v1/archives",
        params={"path": path},
        timeout=600,
    )
    response.raise_for_status()
    disposition = response.headers.get("content-disposition", "")
    filename = disposition.partition("filename*=UTF-8''")[2]
    if filename:
        from urllib.parse import unquote

        filename = unquote(filename)
    else:
        filename = f"{PurePosixPath(path).name or 'workspace'}.zip"
    return filename, response.content


def is_previewable(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    media_type = mimetypes.guess_type(path)[0] or ""
    return (
        suffix in IMAGE_SUFFIXES
        or suffix in TEXT_SUFFIXES
        or suffix == ".pdf"
        or media_type.startswith(("audio/", "video/", "text/"))
    )


def save_download(filename: str, content: bytes, media_type: str) -> None:
    st.session_state["workspace_download"] = {
        "filename": filename,
        "content": content,
        "media_type": media_type,
    }


current_path = st.session_state.get("workspace_current_path", "/")
path_parts = PurePosixPath(current_path).parts[1:]
breadcrumb_items = [("Delovni prostor", "/")]
breadcrumb_path = ""
for part in path_parts:
    breadcrumb_path = f"{breadcrumb_path}/{part}"
    breadcrumb_items.append((part, breadcrumb_path))

breadcrumb_columns = st.columns([1] * len(breadcrumb_items))
for index, (label, path) in enumerate(breadcrumb_items):
    if index < len(breadcrumb_items) - 1:
        if breadcrumb_columns[index].button(
            label,
            key=f"breadcrumb:{path}",
            icon=":material/folder_open:",
            help=f"Odpri {path}",
        ):
            st.session_state["workspace_current_path"] = path
            st.session_state.pop("workspace_delete_path", None)
            st.rerun()
    else:
        breadcrumb_columns[index].markdown(f"**{label}**")

with st.form("create_workspace_directory", clear_on_submit=True):
    st.subheader("Nova mapa")
    st.caption(f"Ustvari v mapi `{current_path}`")
    name_col, submit_col = st.columns([3, 1])
    directory_name = name_col.text_input("Ime nove mape")
    create_submitted = submit_col.form_submit_button("Ustvari mapo", icon=":material/create_new_folder:")

if create_submitted:
    clean_name = directory_name.strip()
    if not clean_name or clean_name in {".", ".."} or "/" in clean_name or "\\" in clean_name:
        st.error("Vnesite veljavno ime mape brez poševnic.")
    else:
        new_path = (PurePosixPath(current_path) / clean_name).as_posix()
        try:
            response = requests.post(
                f"{WORKSPACE_API}/v1/directories",
                params={"path": new_path},
                timeout=60,
            )
            response.raise_for_status()
            st.success(f"Mapa {new_path} je ustvarjena.")
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Mape ni bilo mogoče ustvariti: {exc}")

toolbar_col, refresh_col = st.columns([5, 1])
filter_text = toolbar_col.text_input(
    "Filter v tej mapi",
    placeholder="Iščite mapo ali datoteko",
    key=f"workspace_filter:{current_path}",
)
refresh_col.write("")
refresh_col.write("")
if refresh_col.button("Osveži", icon=":material/refresh:", use_container_width=True):
    st.rerun()

try:
    entries = get_entries(current_path)
except requests.RequestException as exc:
    st.error(f"Vsebine mape ni bilo mogoče naložiti: {exc}")
    entries = []

if len(entries) >= MAX_ENTRIES:
    st.warning(f"Prikazanih je največ {MAX_ENTRIES:,} elementov."
               .replace(",", " "))

filtered_entries = [
    entry for entry in entries if filter_text.strip().lower() in entry["name"].lower()
]
directory_count = sum(entry["is_dir"] for entry in entries)
file_count = len(entries) - directory_count
metric_dirs, metric_files, metric_total = st.columns(3)
metric_dirs.metric("Mape", directory_count)
metric_files.metric("Datoteke", file_count)
metric_total.metric("Elementi v mapi", len(filtered_entries))

archive_col, _ = st.columns([1, 4])
if archive_col.button(
    "Prenesi celoten workspace",
    icon=":material/archive:",
    use_container_width=True,
):
    try:
        archive_name, archive_content = get_archive("/")
        save_download(archive_name, archive_content, "application/zip")
        st.rerun()
    except requests.RequestException as exc:
        st.error(f"Arhiva ni bilo mogoče pripraviti: {exc}")

pending_download = st.session_state.get("workspace_download")
if pending_download:
    st.download_button(
        f"Shrani: {pending_download['filename']}",
        data=pending_download["content"],
        file_name=pending_download["filename"],
        mime=pending_download["media_type"],
        icon=":material/download:",
        key="workspace_pending_download",
        on_click="ignore",
    )

pending_delete = st.session_state.get("workspace_delete_path")
if pending_delete:
    pending_entry = next((item for item in entries if item["path"] == pending_delete), None)
    if pending_entry:
        description = "mapo in vso njeno vsebino" if pending_entry["is_dir"] else "datoteko"
        st.warning(f"Ali res želite izbrisati {description} `{pending_delete}`? Tega dejanja ni mogoče razveljaviti.")
        confirm_col, cancel_col = st.columns([1, 1])
        if confirm_col.button("Potrdi brisanje", type="primary", key="confirm_workspace_delete"):
            try:
                encoded_path = quote(pending_delete.lstrip("/"), safe="/")
                response = requests.delete(
                    f"{WORKSPACE_API}/v1/files/{encoded_path}",
                    params={"recursive": "true"} if pending_entry["is_dir"] else None,
                    timeout=60,
                )
                response.raise_for_status()
                st.session_state.pop("workspace_delete_path", None)
                if st.session_state.get("workspace_preview_path") == pending_delete:
                    st.session_state.pop("workspace_preview_path", None)
                st.success(f"{pending_delete} je izbrisana.")
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Brisanje ni uspelo: {exc}")
        if cancel_col.button("Prekliči", key="cancel_workspace_delete"):
            st.session_state.pop("workspace_delete_path", None)
            st.rerun()
    else:
        st.session_state.pop("workspace_delete_path", None)

st.subheader(f"Vsebina mape: {current_path}")
if not filtered_entries:
    st.info("V tej mapi ni elementov, ki bi ustrezali filtru." if entries else "Ta mapa je prazna.")
else:
    st.caption(f"Prikazanih je {len(filtered_entries)} od {len(entries)} elementov v tej mapi.")
    for entry in filtered_entries:
        path = entry["path"]
        is_directory = entry["is_dir"]
        row = st.columns([5, 1, 1.2, 1.2, 1.2])
        if is_directory:
            if row[0].button(
                entry["name"],
                icon=":material/folder:",
                help=f"Odpri mapo {entry['name']}",
                key=f"open:{path}",
                use_container_width=True,
            ):
                st.session_state["workspace_current_path"] = path
                st.session_state.pop("workspace_delete_path", None)
                st.rerun()
        else:
            row[0].text(entry["name"])
        row[1].write("Mapa" if is_directory else f"{entry.get('size', 0):,} B".replace(",", " "))

        if is_directory:
            if row[2].button(
                "ZIP",
                icon=":material/archive:",
                help="Prenesi mapo skupaj z vsebino kot ZIP",
                key=f"zip:{path}",
                use_container_width=True,
            ):
                try:
                    archive_name, archive_content = get_archive(path)
                    save_download(archive_name, archive_content, "application/zip")
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Arhiva mape ni bilo mogoče pripraviti: {exc}")
        else:
            if row[2].button(
                "Prenesi",
                icon=":material/download:",
                key=f"download:{path}",
                use_container_width=True,
            ):
                try:
                    response = get_file_response(path)
                    save_download(
                        PurePosixPath(path).name,
                        response.content,
                        response.headers.get("content-type", "application/octet-stream"),
                    )
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Datoteke ni bilo mogoče prenesti: {exc}")
            if is_previewable(path):
                if row[3].button(
                    "Predogled",
                    icon=":material/visibility:",
                    key=f"preview:{path}",
                    use_container_width=True,
                ):
                    st.session_state["workspace_preview_path"] = path
                    st.rerun()

        if row[4].button(
            "Izbriši",
            icon=":material/delete_outline:",
            key=f"delete:{path}",
            use_container_width=True,
        ):
            st.session_state["workspace_delete_path"] = path
            st.rerun()

preview_path = st.session_state.get("workspace_preview_path")
if preview_path:
    st.divider()
    preview_heading, close_preview_col = st.columns([8, 1])
    preview_heading.subheader(f"Predogled: {preview_path}")
    if close_preview_col.button("Zapri", key="close_workspace_preview"):
        st.session_state.pop("workspace_preview_path", None)
        st.rerun()
    try:
        preview_response = get_file_response(preview_path)
        preview_content = preview_response.content
        suffix = PurePosixPath(preview_path).suffix.lower()
        if len(preview_content) > MAX_PREVIEW_BYTES:
            st.info("Datoteka je prevelika za predogled. Lahko jo prenesete.")
        elif suffix in IMAGE_SUFFIXES:
            st.image(preview_content, caption=preview_path, use_container_width=True)
        elif suffix == ".pdf":
            pdf_data = base64.b64encode(preview_content).decode("ascii")
            st.components.v1.html(
                f'<iframe src="data:application/pdf;base64,{pdf_data}" width="100%" height="700" '
                'style="border:0"></iframe>',
                height=710,
                scrolling=True,
            )
        elif (mimetypes.guess_type(preview_path)[0] or "").startswith("audio/"):
            st.audio(preview_content)
        elif (mimetypes.guess_type(preview_path)[0] or "").startswith("video/"):
            st.video(preview_content)
        else:
            try:
                preview_text = preview_content.decode("utf-8-sig")
            except UnicodeDecodeError:
                st.info("Datoteke ni mogoče prikazati kot besedilo.")
            else:
                if suffix in {".md", ".markdown"}:
                    st.markdown(preview_text)
                else:
                    st.code(preview_text, language=CODE_LANGUAGES.get(suffix))
    except requests.RequestException as exc:
        st.error(f"Predogleda ni bilo mogoče naložiti: {exc}")