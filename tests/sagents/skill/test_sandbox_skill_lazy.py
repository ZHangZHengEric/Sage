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
            child = f[len(base) + 1:].split("/")[0]
            child_path = base + "/" + child
            if child_path in seen:
                continue
            seen.add(child_path)
            is_dir = child_path in self.dirs or any(
                x.startswith(child_path + "/") for x in list(self.files) + list(self.dirs)
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
