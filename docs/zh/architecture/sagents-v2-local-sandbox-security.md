# Sage v2 local 沙箱：资源限制与验证

本次范围是 `sage.sandbox.local-workspace`，覆盖官方文件、Shell、后台 Shell 作业和技能写入入口。MCP 服务不在范围内。v1 的 `sagents/utils/sandbox` 不是 v2 使用的执行后端，本次没有修改其行为。

## 标准配置

`ResolvedSandboxSpec.resources` 和 Desktop 的 `component_configs["execution.sandbox"].resources` 使用相同字段：

```json
{
  "cpu_percent": 100,
  "memory_mb": 1024,
  "disk_mb": 4096,
  "max_processes": 64,
  "require_hard_limits": true
}
```

CPU 的 100% 表示一个逻辑核心的计算配额，200% 表示两个核心；不是进程累计 CPU 秒数，也不是整台机器的百分比。内存和磁盘单位为 MiB。CPU、内存、进程数限制覆盖沙箱执行进程及其后代，磁盘范围包括工作区、临时目录和共享内存文件。宿主 Sage 控制进程不属于执行 cgroup。

协议默认要求硬限制；Desktop 在原生 macOS 上明确使用 `require_hard_limits=false`，设置界面显示其能力限制，并可切换为严格拒绝模式。Linux 不会因为这个字段为 false 而回退成普通宿主 subprocess。资源参数进入 Desktop 的配置解析、策略指纹和持久化 spec。非法、零值、负数、无穷大不被接受。

`filesystem.max_file_bytes` 和 `filesystem.max_total_bytes` 仍是额外的文件接口限制，不能代替操作系统配额。单文件还通过继承的 `RLIMIT_FSIZE` 限制；完整磁盘限制以以下平台行为为准。

## Linux

执行路径为 `LocalProcessRuntime → 隔离 Python 启动器 → cgroup.procs → bubblewrap → 命令及后代`。启动器使用内存中的固定代码和 `python -I -c`，不执行工作区中的可变启动脚本；宿主 Python、Sage 沙箱实现和隔离工具必须位于可写工作区之外。动态加载器环境变量只在隔离边界内生效；若宿主服务以 root 运行，启动器在执行 bubblewrap 前清空附加组并降权到指定的非 root UID/GID。

- `cpu.max` 控制 CPU 配额，`memory.max` 限制聚合内存，`memory.swap.max=0` 禁止通过 swap 扩大额度，`pids.max` 限制全部后代线程/进程。配置写入后读回核对。
- 每个沙箱有一个父 cgroup，每次命令有一个子 cgroup。因此并发命令共享沙箱总额度，正常完成、超时、取消都清理命令 cgroup；`setsid`、关闭输出管道不能脱离 cgroup。
- bubblewrap 强制建立命名空间，默认无网络、无额外挂载、无 capabilities。系统运行时、根文件系统、`/proc`、`/dev` 只读；工作区、`/tmp`、`/dev/shm` 的可写内容均落在同一个 XFS project 中。挂载源使用 `--bind-fd` / `--ro-bind-fd`，由 bubblewrap 校验 inode、设备并关闭目录 FD，避免路径替换和宿主目录 FD 泄露。
- 禁止再次创建用户命名空间，防止在内部挂载其他可写文件系统绕开磁盘配额。seccomp 额外拒绝套接字、挂载/命名空间、跨进程读写、keyring、BPF、perf 和 io_uring 等通道，包括网络命名空间不能单独隔离的工作区宿主 Unix socket。还拒绝修改 XFS project/继承标志的 ioctl，并按内核的 32 位请求码语义匹配，防止通过高位别名绕过。
- XFS project 配额必须由管理员预先启用、分配和设置。Sage 检查 quota accounting/enforcement、project ID 继承、工作区所属文件系统，以及内核返回的实际硬额度。现有额度必须不大于请求额度；不执行 sudo，不自动修改共享项目的额度，以免放宽其他活跃沙箱的上限。降低 GUI 磁盘额度后，若宿主 quota 尚未相应降低，创建会失败。
- project 必须有 inode 硬配额，最大为请求磁盘字节数除以 4096，防止无限创建空文件。初始化拒绝符号链接、跨文件系统子挂载和硬链接。

宿主配置项：

```json
{
  "linux_cgroup_root": "/sys/fs/cgroup/sage",
  "linux_quota_mount": "/srv/sage-xfs",
  "linux_execution_uid": 1001,
  "linux_execution_gid": 1001
}
```

以上项传给 LocalWorkspaceSandboxProvider 构造函数；Desktop 放在 `execution.sandbox` 配置的顶层。要求 Linux 5.14+、提供 `quotactl_fd` 的 libc、支持 `--bind-fd`、`--ro-bind-fd`、`--disable-userns`、`--seccomp` 的 bubblewrap、xfsprogs、libseccomp2、允许用户命名空间，且 cgroup 子树已启用 `cpu memory pids` 控制器。启动时检查 bubblewrap 实际提供的参数；缺少 FD 挂载支持的旧版本会被拒绝。`quotactl_fd` 的 project 查询需要宿主具备相应权限；可由有权限的 Sage 宿主完成验证，但执行 UID/GID 必须非 root，工作区须属于执行 UID，且目录上级允许该用户进入。

管理员在**专用 XFS 测试卷和专用目录**上准备配额的示例（不要直接用于未核对的现有项目）：

```sh
# 文件系统需已使用 prjquota 挂载；project ID 应由管理员分配，避免与现有项目冲突。
xfs_quota -x -c 'project -s -p /srv/sage-xfs/workspace 1001' /srv/sage-xfs
xfs_quota -x -c 'limit -p bhard=4096m ihard=1048576 1001' /srv/sage-xfs
```

缺少控制器、未启用 quota、实际额度大于请求、工作区不符合要求、内核不支持清理时，均拒绝运行，不回退到无隔离执行。CPU 和内存限制按 sandbox 计；主动共享同一工作区的 Run 共享该项目的磁盘容量，彼此的文件不是保密边界。

## 原生 macOS

Seatbelt 使用默认拒绝规则，只允许工作区写入、必要系统运行时读取及进程创建，默认拒绝网络。临时目录位于工作区内。文件 API 使用目录 FD、`O_NOFOLLOW` 和硬链接检查，避免检查路径后通过替换链接读写宿主文件；macOS 工作区中预先存在的硬链接也会在运行前被拒绝。

CPU 按已发现的进程树 CPU 时间进行暂停/恢复节流；内存使用聚合 RSS 采样；磁盘使用目录累计文件大小。内存、进程数或磁盘超限会杀死已追踪进程，并将沙箱标为 LOST，禁止继续使用。磁盘还在命令结束时检查，避免快速写完后被误报成功。

非系统路径安装的 SDK 可能被拒绝；不能为兼容性放开整个 HOME。需要的运行时应由管理员部署在允许的只读运行时目录。

这些不是内核硬配额：采样存在延迟，短时超限可能发生；极快脱离父进程的后代可能逃过资源监控，但继承的 Seatbelt 文件和网络限制仍生效。磁盘检查是逻辑文件大小，不等价于物理块、快照和文件系统元数据计费；超限后不会删除用户文件。因此不能将原生 macOS 模式用于要求恶意负载绝不超额的场景。选择 `require_hard_limits=true` 会明确拒绝，绝不声称已满足 Linux 等级的硬限制。

## 入口与生命周期加固

- 官方 Shell（包括后台 Job）统一调用 sandbox.process.run；没有宿主执行回退。
- 授权签名绑定 argv、cwd、环境变量、stdin 摘要和 timeout；修改任一输入需要新授权。
- shell 入口还必须显式允许 `allow_shell`；可执行文件白名单约束初始程序，解释器内部调用依靠 OS 边界约束。只读模式保留受限命令语法和 Git 加固，逐个引用参数后在系统只读边界内执行管道。
- `protected_paths` 的文件 API 保护继续生效；配置了受保护子路径时，可写进程请求直接拒绝，只读进程可以执行，避免进程绕过文件 API 修改受保护文件。
- timeout 包括向 stdin 写入阻塞的时间。取消、终止和正常完成均执行后代清理，排队操作在获取执行槽后重新检查状态。
- 沙箱终止主动取消正在执行的进程任务；清理未完成不报告成功释放。
- 技能材料写入改走 SandboxSkillWorkspace，使用相同文件策略与签名授权。
- 内存模型插件只用于语义测试，默认拒绝硬资源限制请求。测试需显式选择非硬限制模式。

任意加载进 Sage 主进程的 Python 插件、管理员配置和 MCP 服务属于宿主信任边界；这个沙箱不隔离 Sage 自身，也不把第三方宿主插件变为不可信代码的执行容器。

## 验证

macOS 的真实测试必须在允许创建 Seatbelt 子沙箱的宿主环境中运行。某些开发工具自身的外层沙箱会禁止 `sandbox-exec`；这时应让测试失败并检查部署权限，不能跳过隔离执行。

```sh
python -m pytest tests/sagents/v2/test_local_sandbox_resource_limits.py \
  tests/sagents/v2/test_local_workspace_sandbox_matrix.py
```

Linux 集成测试显式依赖管理员准备好的、空白的专用工作区（8 MiB project 硬额度，inode 硬额度最多 2048）。设置以下环境变量再运行同一测试文件：

```text
SAGE_TEST_CGROUP_ROOT
SAGE_TEST_QUOTA_MOUNT
SAGE_TEST_QUOTA_WORKSPACE
SAGE_TEST_EXECUTION_UID
SAGE_TEST_EXECUTION_GID
```

本次开发宿主是 macOS；Linux 命令构造和失败处理有单元验证，真实 cgroup/XFS 集成测试在此环境跳过，不能据此宣称 Linux 实机验收已完成。

设计依据：[Linux cgroup v2 文档](https://www.kernel.org/doc/html/v6.8/admin-guide/cgroup-v2.html)、[xfs_quota 手册](https://www.man7.org/linux/man-pages/man8/xfs_quota.8.html)。
