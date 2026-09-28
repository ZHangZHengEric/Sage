tests/ 目录约定
================
app/          FastAPI/服务端路由与核心（与 CI: pytest tests/app/v1/server 一致）
app/v1/common/  旧版应用 services / 模型
sagents/v1/   旧运行时测试：agent/、flow/、tool/、utils/、messages/ 等
sagents/v2/   v2 运行时测试
app/v1/       旧 Desktop / Server 测试；v2 和跨版本 CLI 测试保留原位置
manual/       手跑演示脚本；pytest 不递归进入（见 pytest 根配置 norecursedirs）

根目录 conftest.py 将仓库根加入 sys.path，避免各文件重复 path 与硬编码用户目录。
