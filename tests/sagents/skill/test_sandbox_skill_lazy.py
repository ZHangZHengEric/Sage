"""沙箱技能懒加载行为测试。

验证 SandboxSkillManager：
- 会话初始化（sync_from_host）不再逐个拷贝技能，只登记"已知"元数据；
- 全部技能仍被广告给模型（list_skills / list_skill_info）；
- 真正 load 时（ensure_materialized）才把该技能拷进沙箱，且只拷一次；
- 落地一个技能后，广告列表不会缩水成一个（守护 effective_skill_manager 回归）。
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

from sagents.skill.sandbox_skill_manager import SandboxSkillManager
from sagents.skill.skill_schema import SkillSchema


class FakeSandbox:
    """带内存文件系统的假沙箱，copy_from_host 从真实宿主目录读入。"""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.dirs: set[str] = set()
        self.copy_calls: list[tuple[str, str]] = []

    async def file_exists(self, path):
        p = path.rstrip("/")
        return p in self.files or p in self.dirs

    async def read_file(self, path, encoding="utf-8"):
        return self.files[path.rstrip("/")]

    async def ensure_directory(self, path):
        self.dirs.add(path.rstrip("/"))

    async def list_directory(self, path, include_hidden=False):
        base = path.rstrip("/")
        entries = []
        seen = set()
        for f in list(self.files) + list(self.dirs):
            if f == base or not f.startswith(base + "/"):
                continue
            child = f[len(base) + 1 :].split("/")[0]
            child_path = base + "/" + child
            if child_path in seen:
                continue
            seen.add(child_path)
            is_dir = child_path in self.dirs or any(
                x.startswith(child_path + "/")
                for x in list(self.files) + list(self.dirs)
            )
            entries.append(
                SimpleNamespace(
                    path=child_path,
                    is_dir=is_dir,
                    is_file=not is_dir,
                    size=0,
                    modified_time=0.0,
                )
            )
        return entries

    async def copy_from_host(self, host_path, sandbox_path):
        self.copy_calls.append((host_path, sandbox_path))
        # 主动让出控制权，逼出并发交错（用于验证落地锁）
        await asyncio.sleep(0)
        sp = sandbox_path.rstrip("/")
        self.dirs.add(sp)
        for root, subdirs, filenames in os.walk(host_path):
            rel = os.path.relpath(root, host_path)
            vbase = sp if rel == "." else sp + "/" + rel.replace(os.sep, "/")
            self.dirs.add(vbase)
            for d in subdirs:
                self.dirs.add(vbase + "/" + d)
            for fn in filenames:
                with open(os.path.join(root, fn), "r", encoding="utf-8") as fh:
                    self.files[vbase + "/" + fn] = fh.read()


class FakeHostSkillManager:
    def __init__(self, skills: dict[str, SkillSchema]):
        self._skills = skills

    def list_skills(self):
        return list(self._skills.keys())

    @property
    def skills(self):
        return self._skills


def _make_host_skill(tmp_path, name, description, extra=None):
    d = tmp_path / "host_skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )
    for fn, content in (extra or {}).items():
        (d / fn).write_text(content, encoding="utf-8")
    return SkillSchema(name=name, description=description, path=str(d))


def _host_with(tmp_path, *specs):
    return FakeHostSkillManager(
        {name: _make_host_skill(tmp_path, name, desc) for name, desc in specs}
    )


SKILLS_DIR = "/sage-workspace/skills"


async def test_sync_registers_known_without_copying(tmp_path):
    host = _host_with(tmp_path, ("alpha", "Alpha skill"), ("beta", "Beta skill"))
    sandbox = FakeSandbox()
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)

    await mgr.sync_from_host(host)

    # 关键：初始化时零拷贝
    assert sandbox.copy_calls == []
    # 但全部技能都被广告
    assert mgr.list_skills() == ["alpha", "beta"]
    assert {s.name for s in mgr.list_skill_info()} == {"alpha", "beta"}
    # 没有任何技能落地
    assert mgr._skills_cache == {}


async def test_ensure_materialized_copies_once(tmp_path):
    host = _host_with(tmp_path, ("alpha", "Alpha skill"), ("beta", "Beta skill"))
    sandbox = FakeSandbox()
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)
    await mgr.sync_from_host(host)

    skill = await mgr.ensure_materialized("alpha")
    assert skill is not None
    assert skill.name == "alpha"
    assert skill.path == f"{SKILLS_DIR}/alpha"
    assert len(sandbox.copy_calls) == 1
    assert "alpha" in mgr._skills_cache

    # 二次调用不重复拷贝，直接返回缓存
    again = await mgr.ensure_materialized("alpha")
    assert again is skill or again.name == "alpha"
    assert len(sandbox.copy_calls) == 1


async def test_advertising_stays_complete_after_materializing_one(tmp_path):
    """落地一个技能后，广告列表仍是全部，不缩水（守护回归）。"""
    host = _host_with(tmp_path, ("alpha", "Alpha skill"), ("beta", "Beta skill"))
    sandbox = FakeSandbox()
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)
    await mgr.sync_from_host(host)

    await mgr.ensure_materialized("alpha")

    assert mgr.list_skills() == ["alpha", "beta"]
    assert {s.name for s in mgr.list_skill_info()} == {"alpha", "beta"}


async def test_concurrent_ensure_materialized_copies_once(tmp_path):
    """两个协程并发落地同一技能，落地锁保证只拷一次。"""
    host = _host_with(tmp_path, ("alpha", "Alpha skill"))
    sandbox = FakeSandbox()
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)
    await mgr.sync_from_host(host)

    results = await asyncio.gather(
        mgr.ensure_materialized("alpha"),
        mgr.ensure_materialized("alpha"),
    )

    assert all(r is not None and r.name == "alpha" for r in results)
    assert len(sandbox.copy_calls) == 1


async def test_ensure_materialized_unknown_returns_none(tmp_path):
    host = _host_with(tmp_path, ("alpha", "Alpha skill"))
    sandbox = FakeSandbox()
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)
    await mgr.sync_from_host(host)

    assert await mgr.ensure_materialized("missing") is None
    assert sandbox.copy_calls == []


async def test_preexisting_sandbox_skill_loaded_without_copy(tmp_path):
    """沙箱里已有（用户手加/手改）的技能在 sync 时直接加载，不触发拷贝。"""
    host = _host_with(tmp_path, ("alpha", "Alpha skill"))
    sandbox = FakeSandbox()
    # 预置沙箱内已有 alpha（内容与宿主不同，模拟用户手改）
    sandbox.dirs.add(SKILLS_DIR)
    sandbox.dirs.add(f"{SKILLS_DIR}/alpha")
    sandbox.files[f"{SKILLS_DIR}/alpha/SKILL.md"] = (
        "---\nname: alpha\ndescription: user edited\n---\n# alpha edited\n"
    )
    mgr = SandboxSkillManager(sandbox, skills_dir=SKILLS_DIR)

    await mgr.sync_from_host(host)

    assert sandbox.copy_calls == []
    assert "alpha" in mgr._skills_cache
    # 已落地的是沙箱内的手改版
    assert mgr._skills_cache["alpha"].description == "user edited"
    # 再 ensure 也不会重新拷贝
    await mgr.ensure_materialized("alpha")
    assert sandbox.copy_calls == []


async def test_existing_skill_metadata_stays_live_but_tree_is_deferred(tmp_path):
    host = _host_with(tmp_path, ("alpha", "Host description"))
    sandbox = FakeSandbox()
    sandbox.dirs.update(
        {SKILLS_DIR, SKILLS_DIR + "/alpha", SKILLS_DIR + "/alpha/nested"}
    )
    sandbox.files[SKILLS_DIR + "/alpha/SKILL.md"] = (
        "---\nname: alpha\ndescription: Edited description\n---\nEdited instructions"
    )
    sandbox.files[SKILLS_DIR + "/alpha/nested/example.txt"] = "example"
    lists = []
    original_list = sandbox.list_directory

    async def recording_list(path, **kwargs):
        lists.append(path)
        return await original_list(path, **kwargs)

    sandbox.list_directory = recording_list
    mgr = SandboxSkillManager(sandbox, SKILLS_DIR)
    await mgr.sync_from_host(host)
    skill = mgr.get_skill("alpha")
    assert skill.description == "Edited description"
    assert "Edited instructions" in skill.instructions
    assert lists == []
    assert skill.file_list == ""
    results = await asyncio.gather(
        mgr.ensure_materialized("alpha"), mgr.ensure_materialized("alpha")
    )
    assert results[0] is results[1]
    assert "example.txt" in results[0].file_list
    assert lists == [SKILLS_DIR + "/alpha", SKILLS_DIR + "/alpha/nested"]
    assert sandbox.copy_calls == []
    await mgr.sync_from_host(host)
    assert mgr.get_skill("alpha").file_list == ""


async def test_local_batch_matches_sequential_live_skill_view(tmp_path, monkeypatch):
    from sagents.utils.sandbox.config import VolumeMount
    from sagents.utils.sandbox.providers.local import local as local_module
    from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider

    class SequentialProvider(LocalSandboxProvider):
        pass

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    names = [f'skill{i}' for i in range(24)] + ['missing', 'invalid', 'empty']
    host = _host_with(tmp_path, *((name, 'host description') for name in names))
    for name in names:
        if name == 'missing':
            continue
        directory = workspace / 'skills' / name
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text(
            '' if name == 'empty' else '---\nname: [\n---' if name == 'invalid'
            else f'---\nname: {name}\ndescription: user edited\n---\nLive content'
        )
    def manager(cls):
        return SandboxSkillManager(cls(
            sandbox_id='batch-skills', sandbox_agent_workspace=str(workspace),
            volume_mounts=[VolumeMount(str(workspace), str(workspace))],
            macos_isolation_mode='subprocess', linux_isolation_mode='subprocess',
        ), skills_dir=str(workspace / 'skills'))

    calls = []
    original = local_module.diagnostic_to_thread
    async def tracked(name, fn, *args, **kwargs):
        calls.append(name)
        return await original(name, fn, *args, **kwargs)
    monkeypatch.setattr(local_module, 'diagnostic_to_thread', tracked)
    batched, sequential = manager(LocalSandboxProvider), manager(SequentialProvider)
    await batched.sync_from_host(host)
    batch_reads = [name for name in calls if name in {'local.read_existing_files', 'local.read_file', 'local.file_exists'}]
    assert batch_reads == ['local.file_exists', 'local.read_existing_files']
    await sequential.sync_from_host(host)
    assert batched._skills_cache == sequential._skills_cache
    assert batched._known_skills == sequential._known_skills
    assert len(batched._skills_cache) == 24
    assert not batched._file_lists_loaded
    # No stale cross-request metadata cache: live edits are visible on resync.
    changed = workspace / 'skills' / 'skill0' / 'SKILL.md'
    changed.write_text('---\nname: skill0\ndescription: newer edit\n---\nNew body')
    await batched.sync_from_host(host)
    assert batched._skills_cache['skill0'].description == 'newer edit'


async def test_metadata_discovery_preserves_materialized_skill_output(tmp_path, monkeypatch):
    from sagents.skill.skill_manager import SkillManager
    root = tmp_path / 'host'
    skill_dir = root / 'alpha'
    (skill_dir / 'src').mkdir(parents=True)
    (skill_dir / 'SKILL.md').write_text('---\nname: alpha\ndescription: Alpha\n---\nInstructions')
    (skill_dir / 'src' / 'example.py').write_text('print(1)')
    eager = SkillManager([str(root)], isolated=True)
    assert 'example.py' in eager.skills['alpha'].file_list
    original = SkillManager._generate_file_list
    def forbidden(*args, **kwargs):
        raise AssertionError('metadata discovery must not scan file trees')
    monkeypatch.setattr(SkillManager, '_generate_file_list', forbidden)
    metadata = SkillManager([str(root)], isolated=True, include_file_list=False)
    assert metadata.list_skills() == eager.list_skills()
    assert metadata.get_skill_metadata('alpha') == eager.get_skill_metadata('alpha')
    assert metadata.get_skill_instructions('alpha') == eager.get_skill_instructions('alpha')
    monkeypatch.setattr(SkillManager, '_generate_file_list', original)
    managers = [SandboxSkillManager(FakeSandbox(), skills_dir=SKILLS_DIR) for _ in range(2)]
    for mgr, host in zip(managers, [eager, metadata]):
        await mgr.sync_from_host(host)
    assert await managers[0].ensure_materialized('alpha') == await managers[1].ensure_materialized('alpha')
