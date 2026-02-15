# 移除 show_content 字段重构计划

## 目标
移除 `Message` 类中的 `show_content` 字段，统一使用 `content` 字段。并将原有的 `show_content` 逻辑迁移至 `content` 或 `SessionContext.audit_status`。

## 待办事项

### 1. 代码审查与分析
- [ ] **差异分析**: 检查所有使用 `show_content` 的地方，对比其与 `content` 的值是否一致。
- [ ] **数据丢失风险评估**: 确认如果直接将 `show_content` 的值赋给 `content`，是否会覆盖有用的 `content` 信息。
- [ ] **MessageManager 检查**: 重点审查 `/Users/zhangzheng/zavixai/Sage/sagents/context/messages/message_manager.py` (L481-546)，确认是否使用了旧的结构化 content。

### 2. 核心修改
- [ ] **Message 类定义**: 在 `/Users/zhangzheng/zavixai/Sage/sagents/context/messages/message.py` 中删除 `show_content` 字段。
- [ ] **赋值逻辑迁移**: 将所有对 `show_content` 的赋值操作改为对 `content` 的赋值。
- [ ] **Audit Status 迁移**: 评估是否将部分 `show_content` 逻辑（如审计相关的显示状态）迁移到 `SessionContext.audit_status`。

### 3. 应用层适配 (需要修改)
- [ ] **Sage CLI**: 修正 `/Users/zhangzheng/zavixai/Sage/app/sage_cli.py`。
- [ ] **Sage Demo**: 修正 `/Users/zhangzheng/zavixai/Sage/app/sage_demo.py`。
- [ ] **Sage Server**: 修正 `/Users/zhangzheng/zavixai/Sage/app/sage_server.py`。

### 4. 避免修改的范围
- [ ] **废弃代码**: 不修改 `/Users/zhangzheng/zavixai/Sage/sagents/agent/simple_agent_v2.py`。
- [ ] **Web/Server 目录**: 尽量不修改 `/Users/zhangzheng/zavixai/Sage/app/server` 和 `/Users/zhangzheng/zavixai/Sage/app/web` 下的代码（除上述明确提到的入口文件外）。

### 5. 测试计划
- [ ] **单元测试**: 为修改的组件编写或更新单元测试。
- [ ] **联调测试**: 确保 CLI 和 Demo 运行正常。
