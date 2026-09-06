"""Native local execution boundaries. macOS accounting is explicitly best effort.

Linux requires an administrator-delegated cgroup v2 subtree and an XFS
workspace with project quota enforcement already enabled. Sage never mounts
filesystems or invokes sudo. Missing controls are fatal, never a host fallback.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

from ..contracts import FileOperation, NetworkMode


# Keep the trampoline in memory. Executing a helper file from a workspace
# checkout would let a prior command rewrite code that runs BEFORE isolation.
_LAUNCH_CODE = """
import os, resource, sys
cgroup, file_limit, uid, gid, *argv = sys.argv[1:]
if cgroup != '-':
    with open(os.path.join(cgroup, 'cgroup.procs'), 'w') as stream:
        stream.write(str(os.getpid()))
if os.geteuid() == 0:
    if int(uid) == 0 or int(gid) == 0:
        raise PermissionError('sandbox payload cannot run as host root')
    os.setgroups([])
    os.setgid(int(gid))
    os.setuid(int(uid))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
if int(file_limit):
    resource.setrlimit(resource.RLIMIT_FSIZE, (int(file_limit), int(file_limit)))
os.execv(argv[0], argv)
"""


def _write_checked(path: Path, value: str) -> None:
    path.write_text(value)
    if path.read_text().strip() != value:
        raise RuntimeError(f"kernel did not accept {path.name}={value}")


def _trusted_utility(name: str, workspace: Path) -> str:
    candidate = shutil.which(name)
    if candidate is None:
        raise RuntimeError(f"{name} is required")
    resolved = Path(candidate).resolve(strict=True)
    if resolved == workspace or workspace in resolved.parents:
        raise PermissionError(
            f"{name} must be installed outside the writable workspace"
        )
    return str(resolved)


def _seccomp_filter() -> int:
    """Deny alternate networking, host IPC and namespace/kernel control paths."""
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_export_bpf.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]

    class Argument(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_int),
            ("a", ctypes.c_uint64),
            ("b", ctypes.c_uint64),
        ]

    library.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(Argument),
    ]
    library.seccomp_rule_add_array.restype = ctypes.c_int
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("cannot initialize seccomp filter")
    fd = None
    try:
        for name in (
            "socket",
            "connect",
            "bind",
            "listen",
            "accept",
            "accept4",
            "ptrace",
            "process_vm_readv",
            "process_vm_writev",
            "pidfd_getfd",
            "bpf",
            "perf_event_open",
            "keyctl",
            "add_key",
            "request_key",
            "userfaultfd",
            "open_by_handle_at",
            "mount",
            "umount2",
            "unshare",
            "setns",
            "fsopen",
            "fsmount",
            "move_mount",
            "open_tree",
            "mount_setattr",
            "io_uring_setup",
            "quotactl",
            "quotactl_fd",
        ):
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number < 0:
                if name in {"socket", "connect", "bind"}:
                    raise RuntimeError(
                        f"seccomp cannot resolve required syscall {name}"
                    )
                continue
            if library.seccomp_rule_add(context, 0x00050001, number, 0) != 0:  # EPERM
                raise RuntimeError(f"cannot deny syscall {name}")
        # Directory owners can clear PROJINHERIT without changing their project
        # ID. Block both XFS fsxattr and legacy flag setters, or new files could
        # fall back to project 0 and escape quota accounting.
        ioctl = library.seccomp_syscall_resolve_name(b"ioctl")
        if ioctl < 0:
            raise RuntimeError("seccomp cannot resolve ioctl")
        for command in (0x401C5820, 0x40086602, 0x40046602):
            # ioctl's request is truncated to 32 bits by the kernel. Mask high
            # bits too, otherwise a 64-bit alias could bypass an equality rule.
            argument = Argument(1, 7, 0xFFFFFFFF, command)  # SCMP_CMP_MASKED_EQ
            if (
                library.seccomp_rule_add_array(
                    context, 0x00050001, ioctl, 1, ctypes.byref(argument)
                )
                != 0
            ):
                raise RuntimeError("cannot protect XFS project inheritance")
        fd = os.memfd_create("sage-seccomp", os.MFD_CLOEXEC)
        if library.seccomp_export_bpf(context, fd) != 0:
            raise RuntimeError("cannot export seccomp filter")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    finally:
        library.seccomp_release(context)


class _XfsQuota(ctypes.Structure):
    # linux/dqblk_xfs.h, fs_disk_quota_t; block limits use 512-byte units.
    _fields_ = [
        ("version", ctypes.c_int8),
        ("flags", ctypes.c_int8),
        ("fieldmask", ctypes.c_uint16),
        ("id", ctypes.c_uint32),
        ("blk_hardlimit", ctypes.c_uint64),
        ("blk_softlimit", ctypes.c_uint64),
        ("ino_hardlimit", ctypes.c_uint64),
        ("ino_softlimit", ctypes.c_uint64),
        ("bcount", ctypes.c_uint64),
        ("icount", ctypes.c_uint64),
        ("rest", ctypes.c_byte * 56),
    ]


def check_project_quota(root: Path, mount: Path, limit_bytes: int) -> int:
    """Read back enforced quota and project inheritance, not config claims."""
    import fcntl
    import subprocess

    if root == mount or mount not in root.parents:
        raise ValueError("workspace must be a subdirectory of linux_quota_mount")
    if root.stat().st_dev != mount.stat().st_dev:
        raise ValueError("workspace is not on the quota filesystem")
    utility = _trusted_utility("xfs_quota", root)
    result = subprocess.run(
        [utility, "-x", "-c", "state -p", str(mount)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        env={"LC_ALL": "C"},
    )
    if "Accounting: ON" not in result.stdout or "Enforcement: ON" not in result.stdout:
        raise RuntimeError("XFS project quota accounting and enforcement must be ON")

    def attributes(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            # FS_IOC_FSGETXATTR = _IOR('X', 31, struct fsxattr[28]).
            data = fcntl.ioctl(fd, 0x801C581F, bytes(28))
            flags, _, _, project_id = struct.unpack_from("=4I", data)
            return flags, project_id
        finally:
            os.close(fd)

    flags, project_id = attributes(root)
    if not project_id or not flags & 0x200:
        raise RuntimeError("workspace needs a nonzero XFS project with PROJINHERIT")
    # Reject pre-existing ways around accounting before admitting any command.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name
            if path.is_symlink():
                raise PermissionError("quota workspace cannot contain symlinks")
            stat = path.stat()
            if stat.st_dev != root.stat().st_dev:
                raise PermissionError("nested mounts are forbidden in quota workspace")
            flags, child_id = attributes(path)
            if child_id != project_id or (path.is_dir() and not flags & 0x200):
                raise RuntimeError("workspace descendants must inherit the XFS project")
            if path.is_file() and stat.st_nlink > 1:
                raise PermissionError("hard links are forbidden in quota workspace")
    libc = ctypes.CDLL(None, use_errno=True)
    quota = _XfsQuota()
    fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY)
    try:
        query = getattr(libc, "quotactl_fd", None)
        if query is None:
            raise RuntimeError("quotactl_fd requires a recent Linux libc/kernel")
        if query(fd, 0x580302, project_id, ctypes.byref(quota)) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(fd)
    if not quota.blk_hardlimit or quota.blk_hardlimit * 512 > limit_bytes:
        raise RuntimeError(
            "XFS project hard quota exceeds resources.disk_mb; ask the host administrator to lower it"
        )
    if not quota.ino_hardlimit or quota.ino_hardlimit > limit_bytes // 4096:
        raise RuntimeError(
            "XFS project needs an inode hard quota no greater than disk bytes / 4096"
        )
    return project_id


class LocalResourceBoundary:
    def __init__(
        self,
        row,
        *,
        cgroup_root=None,
        quota_mount=None,
        execution_uid=None,
        execution_gid=None,
    ):
        self.row = row
        self.host_python = Path(sys.executable).resolve(strict=True)
        self.cgroup_root = Path(cgroup_root) if cgroup_root else None
        self.quota_mount = Path(quota_mount) if quota_mount else None
        self.cgroup = None
        self.execution_uid = os.geteuid() if execution_uid is None else execution_uid
        self.execution_gid = os.getegid() if execution_gid is None else execution_gid
        self.jobs: dict[int, Path] = {}
        self._monitors: dict[int, asyncio.Task] = {}
        self._tracked = {}
        self._root_processes = {}
        self.scratch = row.root / ".sage-sandbox-tmp"

    async def prepare(self):
        for trusted_path in (self.host_python, __file__, os.__file__):
            resolved = Path(trusted_path).resolve(strict=True)
            if resolved == self.row.root or self.row.root in resolved.parents:
                raise PermissionError(
                    "host sandbox runtime must be installed outside the writable workspace"
                )
        if self.row.spec.network.mode != NetworkMode.NONE:
            raise ValueError(
                "native local isolation currently supports network mode none only"
            )
        if self.row.spec.mounts:
            raise ValueError("native local isolation does not allow extra mounts")
        if (
            self.row.spec.process.enabled
            and self.row.spec.filesystem.allowed_operations
            not in {
                frozenset(FileOperation),
                frozenset({FileOperation.READ, FileOperation.LIST}),
            }
        ):
            raise ValueError(
                "native processes require full workspace operations or read/list only; partial write policies cannot be enforced"
            )
        if self.row.spec.process.enabled and self.row.spec.filesystem.allowed_roots != (
            self.row.spec.workspace_root,
        ):
            raise ValueError(
                "process isolation requires the entire workspace as its allowed root"
            )
        if sys.platform == "linux":
            import subprocess

            bwrap = _trusted_utility("bwrap", self.row.root)
            help_result = await asyncio.to_thread(
                subprocess.run,
                [bwrap, "--help"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env={"PATH": os.defpath, "LANG": "C"},
            )
            if any(
                flag not in help_result.stdout
                for flag in (
                    "--bind-fd",
                    "--ro-bind-fd",
                    "--disable-userns",
                    "--seccomp",
                )
            ):
                raise RuntimeError(
                    "bubblewrap must support checked FD mounts, disabling user namespaces and seccomp"
                )
            probe_fd = _seccomp_filter()
            os.close(probe_fd)
            virtual_root = Path(self.row.spec.workspace_root)
            if (
                not virtual_root.is_absolute()
                or ".." in virtual_root.parts
                or str(virtual_root) == "/"
                or virtual_root.parts[1]
                in {
                    "usr",
                    "bin",
                    "sbin",
                    "lib",
                    "lib64",
                    "dev",
                    "proc",
                    "sys",
                    "tmp",
                }
            ):
                raise ValueError(
                    "workspace_root overlaps the Linux runtime or is not canonical"
                )
            if (
                not shutil.which("bwrap")
                or not self.cgroup_root
                or not self.quota_mount
            ):
                raise RuntimeError(
                    "Linux local sandbox requires bwrap, linux_cgroup_root and linux_quota_mount"
                )
            # A root host process must use a dedicated unprivileged worker.
            if self.execution_uid == 0 or self.execution_gid == 0:
                raise PermissionError(
                    "configure non-root linux_execution_uid and linux_execution_gid"
                )
            if self.row.root.stat().st_uid != self.execution_uid:
                raise PermissionError(
                    "workspace must belong to the sandbox execution user"
                )
            await asyncio.to_thread(
                check_project_quota,
                self.row.root,
                self.quota_mount.resolve(strict=True),
                self.row.spec.resources.disk_mb * 1024**2,
            )
            controllers = (
                (self.cgroup_root / "cgroup.subtree_control").read_text().split()
            )
            if not {"cpu", "memory", "pids"}.issubset(controllers):
                raise RuntimeError(
                    "delegate cpu, memory and pids controllers before provisioning"
                )
            self.cgroup = self.cgroup_root / self.row.ref.sandbox_id
            self.cgroup.mkdir()
            try:
                limits = self.row.spec.resources
                _write_checked(
                    self.cgroup / "cpu.max", f"{int(limits.cpu_percent * 1000)} 100000"
                )
                _write_checked(
                    self.cgroup / "memory.max", str(limits.memory_mb * 1024**2)
                )
                _write_checked(self.cgroup / "memory.swap.max", "0")
                _write_checked(self.cgroup / "memory.oom.group", "1")
                _write_checked(self.cgroup / "pids.max", str(limits.max_processes))
                if not (self.cgroup / "cgroup.kill").exists():
                    raise RuntimeError("cgroup.kill support is required (Linux 5.14+)")
                (self.cgroup / "cgroup.subtree_control").write_text(
                    "+cpu +memory +pids"
                )
            except BaseException:
                self.cgroup.rmdir()
                self.cgroup = None
                raise
        elif sys.platform == "darwin":
            if self.row.spec.resources.require_hard_limits:
                raise RuntimeError(
                    "native macOS cannot enforce aggregate CPU/memory/disk hard limits"
                )
            if not Path("/usr/bin/sandbox-exec").exists():
                raise RuntimeError("Seatbelt sandbox-exec is unavailable")
            import psutil

            psutil.Process()  # Verify the monitor dependency before admitting work.
            await asyncio.to_thread(self._check_hardlinks)
        else:
            raise RuntimeError("native local sandbox supports Linux and macOS only")
        if self.scratch.is_symlink():
            raise PermissionError("sandbox scratch directory cannot be a symlink")
        self.scratch.mkdir(mode=0o700, exist_ok=True)
        if os.geteuid() == 0:
            fd = os.open(self.scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fchown(fd, self.execution_uid, self.execution_gid)
            finally:
                os.close(fd)
        if self._disk_bytes() > self.row.spec.resources.disk_mb * 1024**2:
            raise ValueError("existing workspace exceeds resources.disk_mb")

    def command(self, executable, argv, cwd, env):
        spec = self.row.spec
        file_limit = min(
            spec.filesystem.max_file_bytes or spec.resources.disk_mb * 1024**2,
            spec.resources.disk_mb * 1024**2,
        )
        job = None
        launch_fds = []
        if sys.platform == "linux":
            from sagents.v2.contracts.common import new_id

            bwrap = _trusted_utility("bwrap", self.row.root)
            job = self.cgroup / new_id("job")
            job.mkdir()
            try:
                launch_fds = [
                    os.open(self.row.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                ]
                launch_fds.append(
                    os.open(self.scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                )
                launch_fds.append(_seccomp_filter())
                # Each --bind-fd consumes and closes its descriptor. Use a
                # distinct duplicate for the second scratch mount.
                launch_fds.append(os.dup(launch_fds[1]))
            except BaseException:
                for fd in launch_fds:
                    os.close(fd)
                job.rmdir()
                raise
            root_source, scratch_source = [str(fd) for fd in launch_fds[:2]]
            writable = (
                bool(
                    spec.filesystem.allowed_operations
                    & {
                        FileOperation.WRITE,
                        FileOperation.CREATE,
                        FileOperation.DELETE,
                    }
                )
                and not spec.process.read_only
            )
            command = [
                bwrap,
                "--unshare-all",
                "--disable-userns",
                "--die-with-parent",
                "--new-session",
                "--cap-drop",
                "ALL",
                "--clearenv",
                "--seccomp",
                str(launch_fds[2]),
            ]
            for path in (
                "/usr/bin",
                "/usr/sbin",
                "/usr/lib",
                "/usr/lib64",
                "/usr/libexec",
                "/usr/share",
                "/usr/local/bin",
                "/usr/local/lib",
                "/bin",
                "/sbin",
                "/lib",
                "/lib64",
            ):
                if Path(path).exists():
                    command += ["--ro-bind", path, path]
            command += [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--ro-bind",
                "/dev/null",
                "/dev/null",
                "--bind-fd" if writable else "--ro-bind-fd",
                root_source,
                spec.workspace_root,
                "--bind-fd",
                scratch_source,
                "/tmp",
                "--bind-fd",
                str(launch_fds[3]),
                "/dev/shm",
                "--chdir",
                spec.workspace_root.rstrip("/")
                + "/"
                + cwd.relative_to(self.row.root).as_posix(),
            ]
            for key, value in env.items():
                command += ["--setenv", key, value]
            command += [
                "--setenv",
                "TMPDIR",
                "/tmp",
                "--setenv",
                "HOME",
                "/tmp",
                "--remount-ro",
                "/proc",
                "--remount-ro",
                "/dev",
                "--remount-ro",
                "/",
                "--",
                executable,
                *argv,
            ]
        else:

            def quote(value):
                return json.dumps(str(value), ensure_ascii=False)

            reads = [
                "/System/Library",
                "/usr/bin",
                "/usr/sbin",
                "/usr/lib",
                "/usr/libexec",
                "/usr/share",
                "/usr/local/bin",
                "/usr/local/lib",
                "/bin",
                "/sbin",
                "/Library/Frameworks",
                "/Library/Developer/CommandLineTools",
                "/opt/homebrew/bin",
                "/opt/homebrew/lib",
                "/opt/homebrew/libexec",
                "/opt/homebrew/share",
                "/opt/homebrew/Cellar",
                "/opt/homebrew/Frameworks",
                str(self.row.root),
            ]
            profile = [
                "(version 1)",
                "(deny default)",
                "(allow process*)",
                "(allow sysctl-read)",
                "(allow file-read-metadata)",
                '(allow file-read* (literal "/"))',
                "(allow file-read* "
                + " ".join(f"(subpath {quote(p)})" for p in reads)
                + ")",
                '(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
                '(allow file-write* (literal "/dev/null"))',
            ]
            if not spec.process.read_only and spec.filesystem.allowed_operations & {
                FileOperation.WRITE,
                FileOperation.CREATE,
                FileOperation.DELETE,
            }:
                profile += [f"(allow file-write* (subpath {quote(self.row.root)}))"]
            env["TMPDIR"] = str(self.scratch)
            env["HOME"] = str(self.scratch)
            command = [
                "/usr/bin/sandbox-exec",
                "-p",
                "\n".join(profile),
                "/usr/bin/env",
                "-i",
                *[f"{key}={value}" for key, value in env.items()],
                executable,
                *argv,
            ]
        # Loader variables must take effect only AFTER the isolation boundary.
        env.clear()
        env.update({"PATH": os.defpath, "LANG": "C"})
        return (
            [
                str(self.host_python),
                "-I",
                "-c",
                _LAUNCH_CODE,
                str(job) if job else "-",
                str(file_limit),
                str(self.execution_uid),
                str(self.execution_gid),
                *command,
            ],
            job,
            launch_fds,
        )

    def started(self, process, job):
        if job is not None:
            self.jobs[process.pid] = job
        else:
            import psutil

            try:
                self._root_processes[process.pid] = psutil.Process(process.pid)
            except psutil.NoSuchProcess:
                return
            if not self._monitors:
                self._monitors[0] = asyncio.create_task(self._monitor())

    async def _monitor(self):
        import psutil

        last = time.monotonic()
        cpu_previous = {}
        try:
            while self._root_processes:
                for root in list(self._root_processes.values()):
                    try:
                        for process in [root, *root.children(recursive=True)]:
                            self._tracked[(process.pid, process.create_time())] = (
                                process
                            )
                    except psutil.NoSuchProcess:
                        pass
                rss, cpu_delta = 0, 0.0
                for key, process in list(self._tracked.items()):
                    try:
                        usage = process.cpu_times()
                        total = usage.user + usage.system
                        cpu_delta += max(0, total - cpu_previous.get(key, total))
                        cpu_previous[key] = total
                        rss += process.memory_info().rss
                    except psutil.NoSuchProcess:
                        self._tracked.pop(key, None)
                limits = self.row.spec.resources
                used = await asyncio.to_thread(self._disk_bytes)
                if (
                    rss > limits.memory_mb * 1024**2
                    or used > limits.disk_mb * 1024**2
                    or len(self._tracked) > limits.max_processes
                ):
                    self.row.state = type(self.row.state).LOST
                    for process in list(self._tracked.values()):
                        try:
                            process.kill()
                        except psutil.NoSuchProcess:
                            pass
                    return
                elapsed = time.monotonic() - last
                delay = max(0, cpu_delta / (limits.cpu_percent / 100) - elapsed)
                paused = []
                try:
                    if delay:
                        for process in list(self._tracked.values()):
                            try:
                                process.suspend()
                                paused.append(process)
                            except psutil.NoSuchProcess:
                                pass
                        await asyncio.sleep(delay)
                finally:
                    for process in paused:
                        try:
                            process.resume()
                        except psutil.NoSuchProcess:
                            pass
                last = time.monotonic()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Losing the monitor cannot silently turn into unmonitored execution.
            self.row.state = type(self.row.state).LOST
            for process in list(self._tracked.values()):
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            raise

    def _disk_bytes(self):
        return sum(
            path.stat().st_size
            for path in self.row.root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

    def _check_hardlinks(self):
        for path in self.row.root.rglob("*"):
            if not path.is_symlink() and path.is_file() and path.stat().st_nlink > 1:
                raise PermissionError(
                    "workspace contains a hard link; its other names may be outside the sandbox"
                )

    async def finish(self, process):
        job = self.jobs.pop(process.pid, None)
        if job:
            await self.finish_job(job)
        self._root_processes.pop(process.pid, None)
        if not self._root_processes and self._monitors:
            for task in self._monitors.values():
                task.cancel()
            await asyncio.gather(*self._monitors.values(), return_exceptions=True)
            self._monitors.clear()
            import psutil

            for tracked in list(self._tracked.values()):
                try:
                    tracked.kill()
                except psutil.NoSuchProcess:
                    pass
            self._tracked.clear()
        if self._disk_bytes() > self.row.spec.resources.disk_mb * 1024**2:
            self.row.state = type(self.row.state).LOST
            raise RuntimeError("sandbox exceeded resources.disk_mb")

    async def finish_job(self, job):
        (job / "cgroup.kill").write_text("1")
        for _ in range(100):
            if "populated 0" in (job / "cgroup.events").read_text():
                job.rmdir()
                return
            await asyncio.sleep(0.02)
        raise RuntimeError("sandbox cgroup still contains descendants")

    def kill_job(self, pid):
        job = self.jobs.get(pid)
        if job is not None:
            (job / "cgroup.kill").write_text("1")

    async def terminate(self):
        if self.cgroup:
            (self.cgroup / "cgroup.kill").write_text("1")

    def remove(self):
        if self.cgroup and self.cgroup.exists():
            self.cgroup.rmdir()
