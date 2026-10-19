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

`sage.sandbox.local-workspace` 约束官方文件、Shell、后台 Shell Job 和 Skill 写入，不隔离宿主 Python 插件或 MCP 服务，也不使用 v1 的 sagents/v1/utils/sandbox 后端。

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

协议默认要求硬限制。require_hard_limits=false 允许采样计量，不取消 OS 隔离：macOS 使用 Seatbelt，Linux 使用 bubblewrap、命名空间、能力清空、seccomp、默认无网络和只读系统。没有普通宿主 subprocess 回退。无硬限制能力时，硬限制请求在 admission 阶段以 sandbox.resource_limits_unsupported 拒绝。非法、零、负和无穷资源值被拒绝。

filesystem.max_file_bytes / max_total_bytes 是额外文件 API 限制，不代替内核配额；继承 RLIMIT_FSIZE 提供单文件限制。

## 命令搜索路径

本地沙箱插件接受 `command_path` 字符串，Desktop 在 `execution.sandbox` 配置顶层设置，例如 `"command_path": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"`。未设置时使用插件创建时的宿主 PATH；不会自动插入 Homebrew 路径。显式配置必须由非空绝对目录组成。

直接命令解析与隔离进程内的 PATH 使用同一值。插件配置优先于宿主 PATH；只有进程策略允许 PATH 环境变量时，请求值才能覆盖插件配置。配置搜索路径不会扩大文件读取或挂载权限。

额外可读目录由插件 `read_paths` 配置：一组绝对目录，只读放行。macOS 加入 Seatbelt `file-read*`，Linux 做只读 bind。拒绝相对路径和 `/`；落在当前工作区里的路径在启动命令时忽略。未设置时与改前一致。宿主自行写入需要放行的目录（例如打包运行时树），通用沙箱插件不认宿主环境变量。

## Shell 网络配置

Desktop 在 `component_configs["execution.sandbox"].network` 配置网络策略。默认 `none` 禁止联网，`unrestricted` 允许直接出站；另外两种模式通过每个沙箱独立的宿主代理出口联网：

```json
{
  "network": {
    "mode": "allowlist",
    "allowed_hosts": ["pypi.org", "files.pythonhosted.org", "*.npmjs.org"],
    "allowed_ports": [80, 443]
  }
}
```

```json
{
  "network": {
    "mode": "proxy",
    "proxy_url": "http://127.0.0.1:8080"
  }
}
```

`allowlist` 必须配置目标域名；精确域名不自动包含子域名，`*.example.com` 仅匹配子域名。`proxy` 必须配置上游 HTTP(S) 代理地址，可额外配置 `allowed_hosts`。上游代理需要支持向目标 IP 的 CONNECT；暂不支持 SOCKS 或含用户名密码的代理 URL。两种模式默认只允许目标端口 80/443，默认拒绝解析到私网、回环和其他非公网地址的目标；可显式设置 `deny_private_networks=false`。显式指定的上游代理可以位于内网。

系统 DNS 使用 Fake-IP 映射（例如 `198.18.0.0/15`）时，该结果属于非公网地址，默认会拒绝；确需使用这种映射时应显式设置 `deny_private_networks=false`，域名、端口和 TLS 名称检查仍然生效。

Desktop 为代理模式默认启用 HTTP/HTTPS。CLI 支持：

```bash
sage v2 run "task" --network-mode allowlist --network-host pypi.org --network-host files.pythonhosted.org
sage v2 run "task" --network-mode proxy --network-proxy http://127.0.0.1:8080
```

`run`、`chat`、`resume` 均支持这些参数。`--network-port` 可重复指定端口；`--network-allow-private` 显式允许私网目标。`none`/`unrestricted` 不能附带白名单或代理参数。Server 宿主可向 `workspace_sandbox_spec` 或 `provision_workspace` 显式传入 `NetworkPolicy`。直接构造规格时，`unrestricted` 需设置 `deny_private_networks=false`，代理模式需显式选择 `allowed_schemes`。

代理环境变量自动注入，并清空 `NO_PROXY`。它们不是隔离边界：macOS 的 Seatbelt 仅允许连接宿主代理的回环 TCP 端口，IPv4/IPv6 端口均由同一个代理占用；Linux 保留独立网络命名空间，通过一个固定挂载的 Unix socket 桥接宿主代理。可信启动器先启动桥接，再给 Shell 加载第二层 seccomp，禁止 Unix socket、监听和原有受限系统调用；用户的动态加载器/Python 环境仅在最终 Shell exec 时生效。

出口逐次检查目标域名、端口和 DNS 结果，并直接连接已检查的 IP。重定向后的新目标仍需经过出口检查。明文 HTTP 每连接仅转发一条已检查、明确长度的请求，拒绝重复头、分块上传和 Upgrade 等不支持的帧格式；HTTPS 使用 CONNECT 和原有端到端证书校验，不解密流量，检查明文 ClientHello 的 TLS 名称与 CONNECT 目标一致。暂不支持加密 ClientHello。白名单约束网络目标和 TLS 名称，不检查加密后的 HTTP Host、路径或方法。

代理使用 `max_wall_time_seconds`、`max_request_body_bytes` 和 `max_response_bytes` 限制连接时长及上传/下载字节（包括 TLS 开销）；默认 30 秒、1 MiB、10 MiB，可在 network 配置中调整。不能在 Shell 模式自定义 `allowed_methods`、`allowed_request_headers` 或 `max_redirects`，因为不解密 HTTPS 无法保证这些约束。终止沙箱会关闭出口及所有现存连接，没有直连回退。`SandboxHandle.network.request` 仍未实现真实 HTTP 请求；这里开放的是进程网络。

配置变化计入沙箱指纹，已有运行不就地扩权。`unrestricted` 保留文件隔离和禁止监听规则，允许公网、内网及本机 IP 出站；Linux 只读挂载 DNS 配置和系统证书，macOS 只放行必要的系统 DNS/证书通道。可执行文件和文件读取策略继续生效。

## Linux

执行路径为 LocalProcessRuntime → 固定隔离 Python 启动器 → cgroup.procs → bubblewrap → 命令及后代。启动器使用 python -I -c，不执行可写工作区脚本。Python、Sage 和隔离工具须在可写工作区外；宿主以 root 运行时，执行前清空附加组并降至指定非 root UID/GID。动态加载器环境只在隔离边界内生效。

- cpu.max、memory.max、memory.swap.max=0、pids.max 分别限制 CPU、聚合内存、swap 和后代进程/线程，写入后读回校验。
- 沙箱父 cgroup 与每命令子 cgroup 共享总额度，完成、超时与取消均清理。setsid 或关闭输出管道不能脱离 cgroup。
- 系统、/proc、/dev 只读，/dev/null 单独允许写入；工作区、/tmp、/dev/shm 的可写内容位于同一 XFS project。FD 挂载核对 inode/设备，避免路径替换及目录 FD 泄露。
- 禁止新建用户命名空间；断网模式的 seccomp 拒绝套接字；两种模式均拒绝挂载、跨进程内存、keyring、BPF、perf、io_uring 及修改 XFS project 标志的 ioctl，包含高位别名。宿主 Unix socket 也不能绕过无网络策略。
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

## 本地沙箱的标准目录与环境说明

本地插件在已有宿主工作区内创建以下目录；不搬迁现有项目文件，也不把宿主工作区视为操作系统的 `/`：

| 用途 | 宿主存储（相对工作区） | Linux 进程路径 | 原生 macOS 进程路径 |
| --- | --- | --- | --- |
| 工作区 | `.` | `workspace_root` | 宿主工作区绝对路径 |
| 临时文件 | `.sage-sandbox-tmp/` | `/tmp`、`/var/tmp`（另与 `/dev/shm` 共用存储） | 工作区内真实路径 |
| Home | `.sage-sandbox-home/` | `/home/agent` | 工作区内真实路径 |
| 缓存 | `.sage-sandbox-home/.cache/` | `$HOME/.cache` | `$HOME/.cache` |
| 配置 | `.sage-sandbox-home/.config/` | `$HOME/.config` | `$HOME/.config` |
| 数据、状态 | `.sage-sandbox-home/.local/share/`、`.local/state/` | Home 下相应目录 | Home 下相应目录 |

插件提供 `HOME`、`TMPDIR`、`TMP`、`TEMP`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`、`XDG_DATA_HOME`、`XDG_STATE_HOME`。临时目录沿用原位置；Home 与临时目录分开。所有这些目录计入工作区磁盘额度，生命周期跟随宿主工作区；主动共享工作区的 Run 也共享这些目录。只读策略继续适用，不因目录存在而获得写权限。

文件工具接受相对工作区路径、工作区内的宿主绝对路径，以及 `~/`、`$HOME/`、`${TMPDIR}/` 和上述环境变量的前缀形式。只使用插件的目录变量，不读取宿主用户的 HOME，不执行任意 shell 展开。Linux 同时接受进程可见的挂载路径。路径遍历、符号链接、保护路径和签名授权检查继续执行。

文件工具返回的规范路径与当前平台 Shell 可见的路径一致：Linux 返回挂载后的虚拟路径；原生 macOS 返回真实工作区绝对路径。macOS 文件工具仍接受原 `workspace_root` 别名作为兼容输入，但 Shell 不提供绝对路径重映射；应使用规范输出或环境变量，而非把 `/tmp`、`/private/tmp` 当成工作区别名。Linux 的 `workspace_root` 不能与 `/home/agent`、`/var/tmp` 的挂载路径重叠。

本地 handle 的 `describe_environment()` 返回操作系统、隔离方式、工作区、目录环境变量、网络模式、资源额度和路径规则。通用组合层只把可选描述投影为 `<sandbox_environment>` 上下文，不解释本地目录布局。其他插件不提供此方法时保持原行为。宿主通过注册和配置选择执行绑定，不自行组合 Agent loop，见 [yiii 接入说明](sagents-v2-yiii-sandbox-directories-integration.md)。

## Team 共享实例与 Run 租约

标准 Builder 的 Team 成员默认通过本地插件的 `share` 能力获得父沙箱租约，使用同一 sandbox_id、目录、进程并发槽和资源监督。每个租约仍有独立的 owner_run_id 和签名校验。关闭成员仅取消该成员的运行中及排队任务；同租约有多个 attach handle 时，最后一个 handle 关闭才释放该租约；最后一个有效租约释放才关闭物理环境。正常成员退出不会关闭其他成员环境。

`LocalWorkspaceExecutionBindingProvider` 由标准插件 `sage.execution.binding.local-workspace` 提供，在 runtime 的 `execution.binding` 选择项中配置。自定义绑定实现通过 `builder.register()` 注册能力协议，Desktop 与其他宿主使用同一标准执行路径。Team 使用共享策略而插件没有 Run 租约能力时明确报不支持；显式独立工作区策略仍按宿主配置单独获取。

临时目录/Home/XDG 环境变量不改变本机访问授权，只决定默认存储位置；具体文件、系统和电脑控制能力仍由所选执行插件及宿主工具授权决定。
