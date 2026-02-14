# Change Log

## 2026-02-14
- 增强 `SkillProxy` (`sagents/skill/skill_proxy.py`)：支持嵌套代理 `SkillManager`，确保 Session 级 Skill 优先级覆盖全局 Skill，并统一 `available_skills` 合并逻辑。
- 修复 Sandbox (`sagents/utils/sandbox/sandbox.py`)：更新 seatbelt profile 允许 WebAssembly 执行 (`sysctl`, `ipc-posix`, `file-map-executable`)；重定向 `npm_config_cache` 及 `HOME` 目录至沙箱内部，解决 `clawhub` 等工具在 macOS 下的权限错误。
- 优化 Sandbox (`sagents/utils/sandbox/sandbox.py`)：针对 Docker 容器环境下的 V8 WebAssembly OOM 问题，解除 `RLIMIT_AS` 与物理内存 (`cgroup`) 的强绑定，并将虚拟内存限制倍率从 8x 提升至 32x (最低 16GB)，以满足 V8 引擎的大内存预留需求。
