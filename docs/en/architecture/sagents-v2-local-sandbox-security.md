---
layout: default
title: Local Sandbox
parent: Architecture
nav_order: 7
lang: en
ref: v2-detail-sagents-v2-local-sandbox-security
---

{% include lang_switcher.html %}

# v2 Local Sandbox

## Scope and standard configuration

`sage.sandbox.local-workspace` constrains official file tools, Shell, background Shell Jobs, and Skill writes. It does not isolate host Python plugins or MCP services and does not use the v1 sagents/utils/sandbox backend.

ResolvedSandboxSpec.resources and Desktop component_configs["execution.sandbox"].resources accept the same fields:

```json
{
  "cpu_percent": 100,
  "memory_mb": 1024,
  "disk_mb": 4096,
  "max_processes": 64,
  "require_hard_limits": true
}
```

CPU 100% is one logical core's quota; 200% is two cores, not cumulative CPU seconds or a percentage of the entire machine. Memory/disk units are MiB. Process limits cover execution processes and descendants. Disk scope includes workspace, temporary files, and shared memory; the host control process stays outside the execution cgroup.

The protocol defaults to hard limits. require_hard_limits=false permits sampled metering without removing OS isolation: Seatbelt on macOS; bubblewrap, namespaces, cleared capabilities, seccomp, no network, and read-only system paths on Linux. There is no plain host-subprocess fallback. Without hard-limit capabilities, hard-limit requests fail during admission with sandbox.resource_limits_unsupported. Invalid, zero, negative, and infinite resource values are rejected.

filesystem.max_file_bytes / max_total_bytes are additional file-API limits, not substitutes for kernel quotas. Inherited RLIMIT_FSIZE supplies a per-file limit.

## Linux

Execution follows LocalProcessRuntime → fixed isolated Python launcher → cgroup.procs → bubblewrap → command and descendants. The launcher uses python -I -c, never a writable workspace script. Python, Sage, and isolation tools must be outside the writable workspace. A root host clears supplementary groups and switches to the configured non-root UID/GID before execution. Dynamic-loader environment changes apply only inside isolation.

- cpu.max, memory.max, memory.swap.max=0, and pids.max constrain CPU, aggregate memory, swap, and descendant processes/threads. Values are read back after writing.
- A sandbox parent cgroup and per-command child cgroups share total limits. Completion, timeout, and cancellation clean up; setsid or closing output pipes cannot escape the cgroup.
- System paths, /proc, and /dev are read-only, with /dev/null separately writable. Writable workspace, /tmp, and /dev/shm content belongs to one XFS project. FD mounts check inode/device identity to prevent path replacement and directory-FD leaks.
- New user namespaces are forbidden. Seccomp rejects sockets, mounts, cross-process memory access, keyring, BPF, perf, io_uring, and XFS-project-changing ioctls including high-bit aliases. Host Unix sockets cannot bypass the no-network policy.
- Administrators prepare the cgroup subtree and XFS project quota. Sage checks accounting/enforcement, project-ID inheritance, filesystem identity, and actual hard limits. Existing limits must not exceed requested limits. Sage does not run sudo or relax shared project quotas automatically.
- The project must have an inode hard quota of at most requested disk bytes divided by 4096. Initialization rejects symlinks, cross-filesystem mounts, and hard links.

These host parameters belong to LocalWorkspaceSandboxProvider; Desktop places them at the top level of execution.sandbox configuration:

```json
{
  "linux_cgroup_root": "/sys/fs/cgroup/sage",
  "linux_quota_mount": "/srv/sage-xfs",
  "linux_execution_uid": 1001,
  "linux_execution_gid": 1001
}
```

Without cgroup/quota configuration, no hard quota is created or verified. Process-tree sampling matches macOS while isolation remains enforced. Partial configuration or failed hard-limit verification rejects execution.

Hard limits require Linux 5.14+, quotactl_fd, xfsprogs, libseccomp2, permitted user namespaces, and a cgroup subtree with cpu memory pids enabled. Bubblewrap must support --bind-fd, --ro-bind-fd, --unshare-user, --disable-userns, and --seccomp. --disable-userns needs explicit --unshare-user. Ubuntu AppArmor namespace restrictions may prevent uid-map creation, requiring administrator preparation. Execution identity must be non-root, own the workspace, and traverse its parent directories.

This example is only for a dedicated test volume. Administrators assign project IDs, and the filesystem must be mounted with prjquota:

```sh
xfs_quota -x -c 'project -s -p /srv/sage-xfs/workspace 1001' /srv/sage-xfs
xfs_quota -x -c 'limit -p bhard=4096m ihard=1048576 1001' /srv/sage-xfs
```

CPU/memory are per sandbox. Runs deliberately sharing a workspace share disk capacity and have no file-confidentiality boundary between them. workspace_root cannot be below /usr, /bin, /sbin, /lib, /lib64, /dev, /proc, /sys, or /tmp, which would conflict with runtime mounts. CLI/Desktop modes that use host paths directly therefore cannot use /tmp workspaces.

## Native macOS

Seatbelt denies by default, allowing workspace writes, required read-only runtime paths, and process creation, with no network by default. Temporary files stay in the workspace. File APIs use directory FDs, O_NOFOLLOW, and hard-link checks; existing workspace hard links are also rejected.

CPU throttling samples discovered process-tree time; memory sums RSS, and disk measures logical file sizes. Exceeding limits terminates tracked processes and marks the sandbox LOST; disk is also checked after commands. Required SDKs must live in allowed read-only runtime directories; never allow the entire HOME. Standard Xcode/CommandLineTools runtime directories are readable.

Sampling has latency. Very fast detached descendants may escape resource metering while retaining inherited Seatbelt file/network restrictions. Logical file sizes are not physical blocks, snapshots, or metadata accounting. Exceeding quota does not delete user files. require_hard_limits=true is explicitly rejected on macOS, which does not claim Linux-grade hard quotas.

## Authorization and lifecycle

Shell and background Jobs use sandbox.process.run. Grant signatures bind argv, cwd, environment, stdin digest, and timeout; changing any input requires a new grant. Shell also requires allow_shell. Executable allowlists constrain the initial program; subsequent interpreter execution depends on OS isolation.

Configured protected_paths reject writable processes to prevent bypassing file APIs. Read-only mode retains restricted command syntax and Git hardening. Timeout includes blocked stdin writes. Cancellation, termination, and completion clean up descendants; queued operations recheck state after acquiring a slot. Release is not reported successful until cleanup finishes. Skills use SandboxSkillWorkspace and the same file policy.

The memory sandbox is for semantic tests and rejects hard-limit requests by default. Host plugins, administrator configuration, and MCP remain within the host trust boundary.

## Validation

```sh
python -m pytest tests/sagents/v2/test_local_sandbox_resource_limits.py   tests/sagents/v2/test_local_workspace_sandbox_matrix.py
```

macOS tests require permission to create Seatbelt child sandboxes; an outer development-tool sandbox may forbid sandbox-exec. Linux hard-quota integration tests need an administrator-prepared empty dedicated workspace with an 8 MiB project hard quota, at most 2048 inodes, and these variables:

```text
SAGE_TEST_CGROUP_ROOT
SAGE_TEST_QUOTA_MOUNT
SAGE_TEST_QUOTA_WORKSPACE
SAGE_TEST_EXECUTION_UID
SAGE_TEST_EXECUTION_GID
```

Skipped tests due to missing platforms or dedicated resources are not passes. Command-construction unit tests do not establish real Linux cgroup/XFS acceptance.
