# Node.js 环境配置

Sage 使用独立的 Node.js 环境来运行某些技能和工具，避免与系统全局 Node 环境冲突。

## 环境目录位置

```
~/.sage/.sage_node_env/
```

## 用途说明

Sage 的 Node 环境主要用于：

1. **运行 Skill 依赖的 Node 工具**
   - `agent-browser` - 浏览器自动化相关技能
   - `docx` - Word 文档生成技能

2. **执行 npx 命令**
   - 某些工具需要通过 npx 运行
   - 在隔离环境中安装和运行，不影响系统环境

3. **避免版本冲突**
   - 不同项目可能需要不同版本的 Node 工具
   - 隔离环境确保 Sage 的工具依赖稳定运行

## 目录结构

```
~/.sage/.sage_node_env/
├── package.json          # npm 项目配置
├── package-lock.json     # 依赖锁定文件
├── .npmrc               # npm 配置文件（使用国内镜像源）
└── node_modules/        # 安装的依赖包
    ├── agent-browser/
    ├── docx/
    └── ...
```

## 初始化过程

Sage 启动时会自动检查和初始化 Node 环境：

1. **检查目录是否存在**
   - 如果不存在，创建 `~/.sage/.sage_node_env/`

2. **初始化 npm 项目**
   - 创建 `package.json` 文件
   - 配置为国内镜像源（淘宝 npm 镜像）

3. **安装预设依赖**
   - 自动安装 `agent-browser`
   - 自动安装 `docx`

## 预设安装的包

| 包名 | 用途 | 说明 |
|------|------|------|
| `agent-browser` | 浏览器自动化 | 用于 social-push、agent-browser 等技能 |
| `docx` | Word 文档生成 | 用于 docx skill 创建 Word 文档 |

## npm 配置

Sage 使用以下 npm 配置（存储在 `.npmrc`）：

```ini
registry=https://registry.npmmirror.com
@anthropics:registry=https://registry.npmmirror.com
@modelcontextprotocol:registry=https://registry.npmmirror.com
```

这确保：
- 使用国内镜像源，加速下载
- 避免访问官方 npm  registry 的网络问题

## 手动管理

### 查看已安装的包

```bash
cd ~/.sage/.sage_node_env
npm list
```

### 安装新包

如果需要为 Skill 添加新的 Node 依赖：

```bash
cd ~/.sage/.sage_node_env
npm install <package-name>
```

### 更新包

```bash
cd ~/.sage/.sage_node_env
npm update
```

### 重新初始化

如果 Node 环境损坏，可以删除后重启 Sage：

```bash
# 停止 Sage 应用
rm -rf ~/.sage/.sage_node_env
# 重启 Sage，会自动重新初始化
```

## 在 Skill 中使用

### 调用 Node 工具

在 Skill 中可以通过绝对路径调用 Node 工具：

```python
import subprocess

node_modules_dir = "~/.sage/.sage_node_env/node_modules"
result = subprocess.run(
    ["node", f"{node_modules_dir}/.bin/docx"],
    capture_output=True,
    text=True
)
```

### 使用 npx

```python
import subprocess

# 使用 Sage 的 Node 环境运行 npx
sage_node_env = "~/.sage/.sage_node_env"
result = subprocess.run(
    ["npx", "--prefix", sage_node_env, "some-package"],
    capture_output=True,
    text=True
)
```

## 故障排查

### Node 环境初始化失败

**症状**: Sage 启动时提示 Node 环境初始化失败

**解决方案**:
1. 检查 Node.js 是否已安装：
   ```bash
   node --version
   npm --version
   ```
2. 删除 Node 环境目录，让 Sage 重新初始化：
   ```bash
   rm -rf ~/.sage/.sage_node_env
   ```
3. 重启 Sage 应用

### 包安装失败

**症状**: 某些 Skill 无法运行，提示找不到模块

**解决方案**:
1. 手动进入目录安装：
   ```bash
   cd ~/.sage/.sage_node_env
   npm install
   ```
2. 检查网络连接，确保能访问 npm 镜像源
3. 尝试更换 npm 源：
   ```bash
   npm config set registry https://registry.npmjs.org/
   ```

### 版本冲突

**症状**: Skill 运行时报版本不兼容错误

**解决方案**:
1. 查看 Skill 要求的版本
2. 在 Node 环境中安装指定版本：
   ```bash
   cd ~/.sage/.sage_node_env
   npm install package@version
   ```

## 开发者说明

### 添加新的预设包

如果需要添加新的预设 Node 包，编辑 `app/desktop/tauri/src/main.rs`：

```rust
const PRESET_NPX_PACKAGES: &[&str] = &[
    "agent-browser",
    "docx",
    "your-new-package",  // 添加新包
];
```

### 在 Skill 中声明 Node 依赖

在 Skill 的 `SKILL.md` 中声明 Node 依赖：

```markdown
## 依赖

- Node.js >= 16.0.0
- npm 包:
  - puppeteer
  - cheerio

## 安装

```bash
cd ~/.sage/.sage_node_env
npm install puppeteer cheerio
```
```

## 与系统 Node 环境的关系

| 特性 | Sage Node 环境 | 系统 Node 环境 |
|------|---------------|---------------|
| 位置 | `~/.sage/.sage_node_env` | 系统全局 |
| 用途 | Sage 内部 Skill 使用 | 用户其他项目 |
| 隔离性 | 完全隔离 | 共享全局 |
| 版本控制 | 由 Sage 管理 | 用户自行管理 |

这种设计确保：
- Sage 的工具依赖不会干扰用户的其他项目
- 用户可以随意升级系统 Node 版本而不影响 Sage
- Skill 开发有稳定的运行环境
