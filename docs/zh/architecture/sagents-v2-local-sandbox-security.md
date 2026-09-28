---
layout: default
title: 本机沙箱
parent: 架构
nav_order: 7
lang: zh
ref: v2-detail-sagents-v2-local-sandbox-security
---

{% include lang_switcher.html %}

# v2 本机沙箱

本机沙箱主要回答两个问题：工具可以读写哪些文件、访问哪些系统能力，以及执行进程能使用多少资源。文件和网络隔离与资源配额是不同能力。Linux 在宿主准备好 cgroup 和 XFS 配额后可强制执行硬限制；macOS 使用系统隔离和采样计量，不能承诺同样的硬配额。

## 范围与标准配置

`sage.sandbox.local-workspace` 约束官方文件、Shell、后台 Shell Job 和 Skill 写入，不隔离宿主 Python 插件或 MCP 服务，也不使用 v1 的 sagents/utils/sandbox 后端。

ResolvedSandboxSpec.resources 与 Desktop 的 component_configs["execution.sandbox"].resources 接受相同字段：

```json
{
  "cpu_percent": 100,
  "memory_mb": 1024,
  "disk_mb": 4096,
  "max_processes": 64,
  "require_hard_limits": true
}
```

CPU 100% 是一个逻辑核心配额，200% 是两个核心，不是累计 CPU 秒数或整机百分比。内存/磁盘以 MiB 计，进程限制覆盖执行进程及后代；磁盘范围包含工作区、临时目录和共享内存，宿主控制进程不进入执行 cgroup。

协议默认要求硬限制。require_hard_limits=false 允许采样计量，不取消 OS 隔离：macOS 使用 Seatbelt，Linux 使用 bubblewrap、命名空间、能力清空、seccomp、无网络和只读系统。没有普通宿主 subprocess 回退。无硬限制能力时，硬限制请求在 admission 阶段以 sandbox.resource_limits_unsupported 拒绝。非法、零、负和无穷资源值被拒绝。

filesystem.max_file_bytes / max_total_bytes 是额外文件 API 限制，不代替内核配额；继承 RLIMIT_FSIZE 提供单文件限制。

## 命令搜索路径

本地沙箱插件接受 `command_path` 字符串，Desktop 在 `execution.sandbox` 配置顶层设置，例如 `"command_path": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"`。未设置时使用插件创建时的宿主 PATH；不会自动插入 Homebrew 路径。显式配置必须由非空绝对目录组成。

直接命令解析与隔离进程内的 PATH 使用同一值。插件配置优先于宿主 PATH；只有进程策略允许 PATH 环境变量时，请求值才能覆盖插件配置。配置搜索路径不会扩大文件读取或挂载权限，目录及依赖必须已在沙箱可读范围内。

## Linux

执行路径为 LocalProcessRuntime → 固定隔离 Python 启动器 → cgroup.procs → bubblewrap → 命令及后代。启动器使用 python -I -c，不执行可写工作区脚本。Python、Sage 和隔离工具须在可写工作区外；宿主以 root 运行时，执行前清空附加组并降至指定非 root UID/GID。动态加载器环境只在隔离边界内生效。

- cpu.max、memory.max、memory.swap.max=0、pids.max 分别限制 CPU、聚合内存、swap 和后代进程/线程，写入后读回校验。
- 沙箱父 cgroup 与每命令子 cgroup 共享总额度，完成、超时与取消均清理。setsid 或关闭输出管道不能脱离 cgroup。
- 系统、/proc、/dev 只读，/dev/null 单独允许写入；工作区、/tmp、/dev/shm 的可写内容位于同一 XFS project。FD 挂载核对 inode/设备，避免路径替换及目录 FD 泄露。
- 禁止新建用户命名空间；seccomp 拒绝套接字、挂载、跨进程内存、keyring、BPF、perf、io_uring 及修改 XFS project 标志的 ioctl，包含高位别名。宿主 Unix socket 也不能绕过无网络策略。
- 管理员预先准备 cgroup 子树与 XFS project 配额。Sage 校验 accounting/enforcement、project ID 继承、文件系统与实际硬额度；实际额度不得大于请求，不执行 sudo，也不自动放宽共享项目额度。
- project 必须有 inode 硬配额，最多为磁盘字节数除以 4096。初始化拒绝符号链接、跨文件系统挂载和硬链接。

LocalWorkspaceSandboxProvider 的宿主参数如下；Desktop 放在 execution.sandbox 配置顶层：

```json
{
  "linux_cgroup_root": "/sys/fs/cgroup/sage",
  "linux_quota_mount": "/srv/sage-xfs",
  "linux_execution_uid": 1001,
  "linux_execution_gid": 1001
}
```

不配置 cgroup/quota 时不创建或校验硬配额，采用与 macOS 相同的进程树采样，隔离仍生效。部分配置或硬额度核验失败会拒绝执行。

硬限制需要 Linux 5.14+、quotactl_fd、xfsprogs、libseccomp2、允许用户命名空间，以及启用 cpu memory pids 的 cgroup 子树。bubblewrap 必须支持 --bind-fd、--ro-bind-fd、--unshare-user、--disable-userns 和 --seccomp。--disable-userns 要求显式 --unshare-user。Ubuntu 的 AppArmor 用户命名空间限制可能阻止 uid map 创建，需管理员准备相应宿主权限；执行身份必须非 root，拥有工作区且可穿过父目录。

以下仅为专用测试卷示例，project ID 由管理员分配，文件系统须以 prjquota 挂载：

```sh
xfs_quota -x -c 'project -s -p /srv/sage-xfs/workspace 1001' /srv/sage-xfs
xfs_quota -x -c 'limit -p bhard=4096m ihard=1048576 1001' /srv/sage-xfs
```

CPU/内存按沙箱计；主动共享工作区的 Run 共享磁盘容量，文件之间没有保密边界。workspace_root 不能落在 /usr、/bin、/sbin、/lib、/lib64、/dev、/proc、/sys 或 /tmp 下，以免覆盖运行时挂载。直接使用宿主路径的 CLI/Desktop 因此不能使用 /tmp 工作区。

## 原生 macOS

Seatbelt 默认拒绝，仅允许工作区写入、必要运行时只读和进程创建，默认禁止网络；临时目录在工作区内。文件 API 使用目录 FD、O_NOFOLLOW 和硬链接检查，预先存在的工作区硬链接也会被拒绝。

CPU 使用已发现进程树的采样时间节流；内存统计聚合 RSS，磁盘统计逻辑文件大小。超限终止已追踪进程并将沙箱标为 LOST；命令结束时也检查磁盘。必要 SDK 应位于允许的只读运行时目录，不能放开整个 HOME。标准 Xcode/CommandLineTools 运行时目录可只读访问。

采样存在延迟，极快脱离父进程的后代可能逃过资源计量，但继承的 Seatbelt 文件/网络隔离仍生效。磁盘逻辑大小不等于物理块、快照及元数据计费，超限不删除用户文件。require_hard_limits=true 在 macOS 明确拒绝，不宣称提供 Linux 级硬配额。

## 授权与生命周期

Shell 和后台 Job 统一走 sandbox.process.run。授权签名绑定 argv、cwd、环境、stdin 摘要和 timeout；任意更改需要新授权。shell 还需 allow_shell，可执行白名单只限制初始程序，解释器后续执行靠 OS 边界。

配置 protected_paths 时拒绝可写进程，避免绕过文件 API；只读模式保留受限命令语法与 Git 加固。timeout 包含阻塞 stdin，取消、终止和完成都清理后代，排队操作获取槽位后再次检查状态。清理未结束不报告成功释放。Skill 使用 SandboxSkillWorkspace 和相同文件策略。

内存沙箱只用于语义测试，默认拒绝硬限制请求。宿主插件、管理员配置与 MCP 属于宿主信任边界。

## 验证

```sh
python -m pytest tests/sagents/v2/test_local_sandbox_resource_limits.py   tests/sagents/v2/test_local_workspace_sandbox_matrix.py
```

macOS 测试要求能创建 Seatbelt 子沙箱，外层开发工具沙箱可能禁止 sandbox-exec。Linux 硬配额集成测试要求管理员准备空白专用工作区，8 MiB project 硬额度、inode 硬额度最多 2048，并设置：

```text
SAGE_TEST_CGROUP_ROOT
SAGE_TEST_QUOTA_MOUNT
SAGE_TEST_QUOTA_WORKSPACE
SAGE_TEST_EXECUTION_UID
SAGE_TEST_EXECUTION_GID
```

缺失平台或专用资源时的跳过不算通过。命令构造单元测试不代表 Linux cgroup/XFS 实机验收。
