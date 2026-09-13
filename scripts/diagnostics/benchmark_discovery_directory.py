"""Offline discovery and directory round-trip benchmark; uses temporary files only."""

import asyncio
import json
import pathlib
import statistics
import tempfile
import threading
import time
from dataclasses import asdict

from sagents.skill.skill_manager import SkillManager
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


async def main():
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        for i in range(12):
            skill = root / "skills" / f"skill{i}"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: skill{i}\ndescription: example\n---\nInstructions"
            )
            for j in range(3):
                directory = skill / f"dir{j}"
                directory.mkdir()
                for k in range(10):
                    (directory / f"file{k}.txt").write_text("example")
        original_tree = SkillManager._generate_file_list
        visits = []

        def counted(self, *args, **kwargs):
            visits.append(args[0])
            return original_tree(self, *args, **kwargs)

        SkillManager._generate_file_list = counted
        managers = []
        for enabled in [True, False]:
            samples = []
            for _ in range(3):
                visits.clear()
                started = time.thread_time()
                manager = SkillManager(
                    [str(root / "skills")], isolated=True, include_file_list=enabled
                )
                samples.append((time.thread_time() - started) * 1000)
            managers.append(manager)
            print(
                "DISCOVERY",
                json.dumps(
                    {
                        "file_tree": enabled,
                        "cpu_ms": round(statistics.median(samples), 3),
                        "tree_directory_visits": len(visits),
                    }
                ),
                flush=True,
            )
        SkillManager._generate_file_list = original_tree
        for name in managers[0].list_skills():
            assert managers[0].get_skill_metadata(name) == managers[
                1
            ].get_skill_metadata(name)
            assert managers[0].get_skill_instructions(name) == managers[
                1
            ].get_skill_instructions(name)
        provider = LocalSandboxProvider(
            sandbox_id="offline",
            sandbox_agent_workspace=temp,
            volume_mounts=[VolumeMount(temp, temp)],
            macos_isolation_mode="subprocess",
            linux_isolation_mode="subprocess",
        )
        await provider.initialize()
        main_thread = threading.get_ident()
        validate = provider._validate_host_path_allowed

        def checked(*args, **kwargs):
            assert threading.get_ident() != main_thread
            return validate(*args, **kwargs)

        provider._validate_host_path_allowed = checked
        directory = str(root / "skills")
        mtime = await provider.get_mtime(directory)
        entries = await provider.list_directory(directory)
        actual_mtime, actual_entries, error = await provider.get_directory_snapshot(
            directory, 0
        )
        assert error is None and actual_mtime == mtime
        assert [asdict(x) for x in actual_entries] == [asdict(x) for x in entries]
        assert await provider.get_directory_snapshot(directory, mtime) == (
            mtime,
            None,
            None,
        )
        assert await provider.read_file(str(root / "skills" / "skill0" / "SKILL.md"))
        try:
            await provider.read_file("/outside-workspace-no-access")
        except PermissionError:
            pass
        else:
            raise AssertionError("permission check bypassed")
        print(
            "NATIVE_CHECKS metadata, directory listing, unchanged skip, permissions and worker validation OK",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
