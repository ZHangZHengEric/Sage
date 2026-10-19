# Server v2 沙箱前端测试环境

镜像构建时安装 Node.js **24.13.0 LTS**、npm **11.6.2**（Node 官方镜像 digest 固定，npm 随该镜像固定）、jsdom **26.1.0**、Playwright **1.58.2**。`package-lock.json` 固定完整 JS 依赖树及 integrity，使用 `npm ci`。通过该版本 Playwright 的 `install --with-deps chromium` 下载匹配的 Chromium、headless shell、FFmpeg 和 Debian 系统依赖，不使用发行版 Chromium。系统字体包含 DejaVu、Liberation、Noto CJK。Debian 系统包跟随基础镜像的软件源安全更新，不承诺 apt 层字节级可复现。

## 路径与调用

| 内容 | 沙箱路径 |
| --- | --- |
| Node / npm | `/usr/local/bin/node`、`/usr/local/bin/npm` |
| 入口 | `/usr/local/bin/sage-frontend-test` |
| JS 模块 | `/usr/local/lib/sage-frontend-test/node_modules` |
| 浏览器 | `/usr/local/lib/sage-frontend-test/browsers` |
| 字体配置 | `/usr/share/sage-frontend-test/fonts.conf` |
| 测试脚本和页面 | `/workspace/.sage-tests/` |
| 每次运行的截图、JSON 报告 | `/workspace/.sage-tests/artifacts/<mode>-<随机标识>/` |
| 浏览器 profile、缓存、临时文件 | `/tmp/sage-frontend-<随机标识>/`，入口结束时清理 |

上述 `/usr/local/bin`、`/usr/local/lib`、`/usr/share` 均由 `LocalWorkspaceSandboxProvider` 只读挂载。文件 root 所有、所有普通用户可读，目录和程序可执行；不依赖 `/root`。`FONTCONFIG_FILE` 直接指向只读字体配置，因为沙箱未挂载 `/etc/fonts`；字体缓存写隔离 `/tmp/fontconfig`，随沙箱 scratch 清理。

进程策略计入沙箱指纹，避免新旧执行策略复用同一指纹。Server 的命令白名单加入 `node`、`sage-frontend-test`，环境变量白名单加入 `NODE_PATH`、`PLAYWRIGHT_BROWSERS_PATH`、`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`、`FONTCONFIG_FILE`。入口重新设定这些固定路径；镜像禁止 npm 自动联网和浏览器自动下载。没有额外加入 npm/npx 直接执行白名单（现有 shell 策略本身并非传递性的子进程白名单）。使用入口或 `node`，不使用可能触发安装的 `npx`。

用文件工具在 `/workspace/.sage-tests/dom.cjs` 写入：

```javascript
module.exports = async ({ JSDOM, assert }) => {
  const dom = new JSDOM('<button>点击</button><p>初始</p>');
  try {
    const { document } = dom.window;
    document.querySelector('button').onclick = () => {
      document.querySelector('p').textContent = '已点击';
    };
    document.querySelector('button').click();
    assert.equal(document.querySelector('p').textContent, '已点击');
  } finally { dom.window.close(); }
};
```

通过 Shell 工具执行：

```sh
sage-frontend-test jsdom /workspace/.sage-tests/dom.cjs
```

Playwright 脚本 `/workspace/.sage-tests/browser.cjs`：

```javascript
module.exports = async ({ launch, assert, artifacts, pathToFileURL }) => {
  const browser = await launch();
  const page = await browser.newPage();
  await page.goto(pathToFileURL('/workspace/index.html').href);
  await page.getByLabel('姓名').fill('中文');
  await page.getByRole('button', {name: '确认'}).click();
  assert.equal(await page.locator('#result').textContent(), '你好，中文');
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({path: artifacts + '/chinese.png', fullPage: true});
};
```

```sh
sage-frontend-test playwright /workspace/.sage-tests/browser.cjs
```

脚本导出异步函数，入口提供 `require`（可加载预装 jsdom/playwright）、Node `assert`、`artifacts`、`tmp`、`pathToFileURL`，按模式提供 `JSDOM` 或 `launch`。此入口运行库脚本，不是 `@playwright/test` 测试发现器。非零退出表示失败，完整异常写 `report.json` 并打印；启动失败也保留报告。只支持 `.cjs`；ESM 的裸包 import 不使用 `NODE_PATH`，可通过提供的 `require` 加载依赖。入口管理浏览器关闭和临时目录清理；进程被强杀时依赖沙箱生命周期清理 scratch。

文件工具**只能写 `/workspace`**，不要要求文件工具写 `/tmp`。入口可以自行管理隔离 `/tmp`。交付业务文件时，排除 `.sage-tests`、`.sage-sandbox-tmp` 和其中的脚本、截图、报告；如果任务涉及网站发布，使用明确的业务文件清单，不能递归上传整个 `/workspace`。本变更不新增发布功能，也不规定业务文件目录。`file://` 适合无服务器的静态页面；有 ES module fetch/CORS 或后端依赖的应用不能据此视为验收通过。禁止监听的策略下不能临时起 localhost HTTP 服务。

## 隔离策略与 Chromium 限制

修复已有 `/dev/null` 的挂载方式：普通 `--bind` 会加 `nodev`，导致 Playwright 的 ignored stdio 打开设备时 `EACCES`；改为仅对 `/dev/null` 使用 `--dev-bind`，保留该原有设备的可读写语义，不开放其他设备。验收增加 Node `stdio: ignore` 回归检查。

保留现有 bubblewrap `--unshare-all --unshare-user --disable-userns`、独立 PID/网络命名空间、能力清空、只读系统挂载和 seccomp。`network=none` 的 seccomp 拒绝 `socket/connect`；所有模式拒绝 `unshare/setns/mount` 等。Chromium 多进程启动依赖 Unix IPC/socket 和自身命名空间沙箱，可能被这些策略拒绝。入口显式 `chromiumSandbox: true`，不自动尝试 `--no-sandbox`、`--single-process` 或开放网络。

`/dev/shm` 已映射为同一个沙箱 scratch（与 `/tmp` 相同），不是 Docker 宿主共享内存；保持原状。启动参数 `--disable-dev-shm-usage` 将 Chromium 可回退的共享内存文件放 `/tmp`，不增加宿主 IPC 权限。仅增大 Compose `shm_size` 不能解决 socket/user namespace 被拒绝的问题。

Compose 既有 `SYS_ADMIN`、`seccomp=unconfined`、`apparmor=unconfined`、`systempaths=unconfined` 用于外层 bubblewrap 启动，本变更未增删；真正载荷仍经过非 root 身份、bubblewrap 和内部 seccomp。不新增 privileged，也不取消内部过滤。

若 Chromium 被阻止，适配方案是新增经过安全评审的浏览器专用 provider/worker：独立 user/PID/IPC/network namespace、无宿主 Unix socket 挂载、受约束的内部 Unix IPC、允许 Chromium 所需的嵌套 namespace，同时继续禁止 IP 出站/监听、只读系统、工作区授权和资源计量。或者独立 VM 中运行浏览器 worker，通过文件/受控 RPC 交换测试和产物。不能直接对通用 provider 开放所有 socket/unshare，不能靠关闭 Chromium 沙箱绕过。本次不实现或启用该权限扩展。

## 真实沙箱验收

在候选 Server 镜像中执行：

```sh
python deploy/images/frontend-test/acceptance.py
```

该程序通过 `register → build → load_agent → run_stream` 执行离线模型请求的官方文件和 Shell 工具，采用 Server 的标准进程策略参数与 `network=none`；Sage 负责创建沙箱、签名 grant 和释放 Run 资源。它依次检查文件 API 拒绝 `/tmp` 写入、普通用户读取和执行 Node/预装模块/浏览器及匹配中文字体、IPv4/IPv6 外网被禁止、jsdom 点击更新 DOM、Chromium `file://` 页面点击/输入/断言和中文截图。截图和每项原始 stdout/stderr 留在打印的临时 workspace，父目录有汇总 `acceptance.json`；任何一项失败都非零退出，不以服务容器内成功代替实际沙箱通过。

在独立候选容器中沿用生产 Compose 的外层隔离配置运行，并增加外层断网：

```sh
docker run --name sage-frontend-acceptance --network none --init \
  --cap-add SYS_ADMIN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined \
  --memory 2g --cpus 1 --entrypoint python \
  sage-server:frontend-validation-20261016 \
  deploy/images/frontend-test/acceptance.py
```

不挂载生产数据卷。验收结束后，先用 `docker cp` 从打印的临时父目录提取 `acceptance.json` 与 workspace，再删除该临时容器。不要替换生产镜像或停止正式服务。完整结果见本目录 `VALIDATION.md`。

Playwright 与浏览器版本配对及构建时安装方式见 [Playwright 官方文档](https://playwright.dev/docs/browsers)。Node 版本来自 [官方 24.13.0 发布目录](https://nodejs.org/download/release/v24.13.0/)。
