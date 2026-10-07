from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_entrypoints_import_from_isolated_script_path() -> None:
    script = """
import runpy
import sys
from types import ModuleType, SimpleNamespace

class Stopped(Exception):
    pass

class Form:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

streamlit = ModuleType('streamlit')
streamlit.context = SimpleNamespace(cookies={}, url='http://localhost:8501')
for name in ('set_page_config', 'title', 'caption', 'info', 'markdown', 'subheader'):
    setattr(streamlit, name, lambda *args, **kwargs: None)
streamlit.form = lambda *args, **kwargs: Form()
streamlit.text_input = lambda *args, **kwargs: ''
streamlit.form_submit_button = lambda *args, **kwargs: False
streamlit.stop = lambda: (_ for _ in ()).throw(Stopped())
sys.modules['streamlit'] = streamlit
sys.modules['requests'] = ModuleType('requests')

try:
    runpy.run_path(sys.argv[1], run_name='__main__')
except Stopped:
    pass
"""
    for relative in ('client/app.py', 'client/pages/workspace.py', 'client/pages/admin.py'):
        result = subprocess.run(
            [sys.executable, '-I', '-c', script, str(ROOT / relative)],
            cwd='/tmp',
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f'{relative}: {result.stderr}'
