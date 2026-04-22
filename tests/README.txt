tests/ 目录约定
================
app/          FastAPI/服务端路由与核心（与 CI: pytest tests/app/server 一致）
common/       共享 services / 模型
sagents/      与 sagents/ 包对应：agent/（含 agent/fibre/）、flow/、tool/、utils/、messages/ 等
manual/       手跑演示脚本；pytest 不递归进入（见 pytest 根配置 norecursedirs）

根目录 conftest.py 将仓库根加入 sys.path，避免各文件重复 path 与硬编码用户目录。
