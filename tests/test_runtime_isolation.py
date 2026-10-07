from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from deepagents.middleware.filesystem import supports_execution

from agent_api.runtime import AgentRuntime
from agent_api.workspace import WorkspaceManager


def test_agent_backend_has_no_execute_and_checkpoint_is_user_scoped(tmp_path,monkeypatch):
    import deepagents
    import agent_api.model_factory as model_factory

    captured={}
    class FakeAgent:
        async def ainvoke(self,payload,config):
            captured['checkpoint_thread_id']=config['configurable']['thread_id']
            return {'output':'ok'}
    def fake_create(**kwargs):
        captured['backend']=kwargs['backend']
        return FakeAgent()
    monkeypatch.setattr(deepagents,'create_deep_agent',fake_create)
    monkeypatch.setattr(model_factory,'build_chat_model',lambda *args,**kwargs: object())
    user_id=uuid4()
    workspace=WorkspaceManager(tmp_path)
    workspace.ensure_layout()
    runtime=AgentRuntime(
        config=SimpleNamespace(agent=SimpleNamespace(workspace_root=tmp_path,memory_root=tmp_path,memory_files=[],skills_root='/.agent/skills',use_checkpointer=False,database_url=None,recursion_limit=20,system_prompt='test'),provider=SimpleNamespace()),
        workspace=workspace,process_manager=None,shell_env={},tool_collection=SimpleNamespace(tools=[],toolkits=[]),user_id=user_id,
    )
    thread_id=str(uuid4())
    assert asyncio.run(runtime.invoke(thread_id,'hello'))=={'output':'ok'}
    assert not supports_execution(captured['backend'])
    assert captured['checkpoint_thread_id']==f'{user_id}:{thread_id}'


def test_agent_filesystem_quota_rejects_excess_write(tmp_path,monkeypatch):
    from agent_api.quota_backend import QuotaFilesystemBackend
    monkeypatch.setenv('WORKSPACE_QUOTA_BYTES','5')
    backend=QuotaFilesystemBackend(root_dir=tmp_path,virtual_mode=True)
    backend.write('/note.txt','12345')
    try:
        backend.write('/note.txt','123456')
    except ValueError as exc:
        assert 'quota' in str(exc)
    else:
        raise AssertionError('Oversized write was accepted')
    assert (tmp_path/'note.txt').read_text()=='12345'
