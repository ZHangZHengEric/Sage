# withling 验收记录（2026-10-16）

本页是当时旧沙箱装配路径的历史记录。当前 `acceptance.py` 已迁到标准 SDK；此记录不能代替迁移后镜像的重新验收。

预装已实现，**完整 Chromium 验收未通过**。不能将本环境称为可用的浏览器端到端测试环境；目前可用的是离线 jsdom 交互测试。

仅在 `withling` 上构建 Sage 独立候选镜像 `sage-server:frontend-validation-20261016`，调用 Server v2 的 `install_sandbox`、`provision_workspace` 和签名 grant 执行验收。不挂载生产数据，不替换正在运行的服务，不修改 `/srv/Sage` checkout，不修改 Wishseen 代码或部署。容器外层 `--network none`，沙箱 `network=none`，外层其余隔离参数沿用 Sage v2 Compose。

| 检查 | 结果 |
| --- | --- |
| 文件 API 拒绝写 `/tmp` | 通过，`path is outside the workspace` |
| 普通执行身份、内部隔离 | UID/GID 10001，CapEff 全零，NoNewPrivs=1，Seccomp=2，独立 PID/net namespace |
| Node、npm、jsdom、Playwright | 24.13.0、11.6.2、26.1.0、1.58.2，沙箱内加载通过 |
| 安装位置、权限、环境变量 | `/usr/local/lib/sage-frontend-test` 内模块及浏览器可读/执行，NODE_PATH、浏览器路径、字体配置可见 |
| 中文字体 | `fc-match` 匹配 `Noto Sans CJK SC` |
| IPv4/IPv6 外网连接 | 均被拒绝，`Operation not permitted` |
| Node ignored stdio | `/dev/null` 修正后通过 |
| jsdom 点击、输入和 DOM 更新断言 | 通过，结果 `你好，沙箱`，生成 JSON 报告 |
| Chromium 无头启动 | 失败，`No usable sandbox!` / `Chromium sandboxing failed!` |
| Chromium 本地页面、点击、输入、断言、中文截图 | 未到达，未生成截图，不能声明通过 |

## 已修复的前置问题

首次实际沙箱启动 Playwright 返回 `spawn ... EACCES`。诊断确认 headless shell 文件为 0755，普通用户在服务容器中和实际沙箱中均可执行 `--version`。实际沙箱 `/dev/null` 的普通 `--bind` 挂载含 `nodev`，使 ignored stdio 打开设备失败。

只将 `/dev/null` 的绑定改成 `--dev-bind` 后，Chromium 实际创建出进程，进入下一阶段并报 `No usable sandbox!`。新增 ignored stdio 验收检查；没有放行其他宿主设备，没有修改 seccomp、网络和 namespace 策略。相应 Linux 启动参数回归检查已更新。

## 当前阻塞与适配方案

现行 bubblewrap 明确使用 `--disable-userns`；内部 seccomp 拒绝 `unshare/setns/mount`，无网络模式还拒绝 `socket/connect`。Chromium 自身 namespace 沙箱无法在此配置下建立，SUID 提权也被 nosuid、能力清空和 NoNewPrivs 阻止。浏览器原始错误中的 AppArmor 文案是 Chromium 的通用提示，不能据此认定此次故障来自宿主 AppArmor。

保持 `chromiumSandbox: true`，未采用错误提示中的 `chromiumSandbox: false` / `--no-sandbox`，未增加 privileged，也未改变 Compose 原有外层权限。`--disable-dev-shm-usage` 仅将可回退的共享内存文件放到隔离 `/tmp`；`/dev/shm` 与 `/tmp` 仍映射同一 scratch。增大 Docker shm 不能解决此 namespace 问题。

建议后续建立浏览器专用 provider/worker：在独立 user/PID/IPC/network namespace 中只读挂载运行时，单独定义 Chromium 所需的嵌套 namespace 与内部 Unix IPC，继续禁止 IP 外联、宿主 Unix socket 访问和任意宿主文件读写；也可采用独立 VM 浏览器 worker。不要对通用 provider 直接开放全部 socket/unshare。namespace 适配后仍需验证 IPC：当前无网络 seccomp 拒绝所有 socket，尚未单独放开并验收 Chromium IPC。

## 验证范围

本地 Server 沙箱配置/身份/网络与 Linux 启动参数定向回归 **48 passed**，ruff、Node 脚本语法和 diff whitespace 检查通过。额外 Linux 资源检查选择集为 4 passed、1 skipped。macOS 原生沙箱广泛回归未全绿，受到嵌套 Seatbelt、主机 Rosetta Python 和 venv 读取路径限制影响；这些结果不作为 Linux 浏览器能力证明。

最终候选镜像 ID：`sha256:17e07e4dbfe9a4bd745206ffa3f66491595c93c37551628b6cb5cc1d154c014e`。最终容器检查：`network=none`、`privileged=false`、`mounts=[]`、退出码 1（Chromium 失败）。已通过实际 `unshare(CLONE_NEWUSER)` 调用验证 `EPERM`，不是仅从配置推断。

初始诊断的实际 mountinfo 确认 `/usr/local/bin`、`/usr/local/lib`、`/usr/share` 都是 `ro,nosuid,nodev`；`/tmp` 和 `/dev/shm` 的来源均为同一个 workspace scratch。浏览器文件 mode 0755，在沙箱内执行 `--version` 返回 `Google Chrome for Testing 145.0.7632.6`。

远端原始产物已从最终容器提取到 `/tmp/sage-frontend-evidence-20261016`，临时验收容器已停止（running=false、pid=0），Docker 已标记 removing，但远端回收命令尚未返回；候选镜像保留。未重启 Docker daemon，也未操作其他项目容器。未部署到正式服务。

最终原始验收输出保存在同目录 `validation.withling.json`。其中 Playwright 失败应使验收程序退出 1；这是保留真实失败，不是全通过标记。调用方式、文件和产物位置见 `README.md`。
