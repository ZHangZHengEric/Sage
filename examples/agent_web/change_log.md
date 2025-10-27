# 变更日志

## 2025-01-19 15:30 - 修复请求格式中agent_config字段不匹配问题
**问题**: 前端代码示例和微信机器人demo中使用了agent_config字段，但后端StreamRequest模型不支持该字段
**根本原因**: 前端代码示例(CodeModal.js)和微信机器人demo(wechat_bot_demo/app.py)使用了过时的请求格式
**修复方案**: 
- 修改CodeModal.js中的请求数据格式，将agent_config字段拆解为后端期望的独立字段
- 更新所有代码示例(curl, Python, JavaScript, Go)使用正确的字段名称
- 修改wechat_bot_demo/app.py中的send_message函数，将agent_config拆解为独立字段
- 字段映射：agent_config -> deep_thinking, multi_agent, max_loop_count, system_prefix, system_context, available_workflows, llm_model_config, available_tools
**修改文件**: CodeModal.js, wechat_bot_demo/app.py
**测试结果**: 所有请求格式现在与后端StreamRequest模型完全匹配，避免了字段不匹配错误
**作者**: Eric ZZ

## 2025-10-20 09:46 - 修复CodeModal无法上下滚动的问题
**问题**: CodeModal组件的modal-content设置了overflow: hidden，导致当内容超过85vh时无法滚动查看完整内容
**解决方案**: 
- 将.code-modal .modal-content的overflow属性从hidden改为overflow-y: auto
- 添加max-height: calc(85vh - 80px)限制高度，减去header高度
- 为modal-content添加滚动条样式，提升滚动体验
**修改文件**: CodeModal.css
**测试结果**: CodeModal现在可以正常上下滚动，用户可以查看完整的代码内容
**作者**: Eric ZZ

## 2025-10-20 09:43 - 重构modal宽度控制系统，解决全局500px限制问题
**问题**: HistoryPage.css中的全局.modal-content样式设置了max-width: 500px，影响所有modal组件显示不一致
**解决方案**: 
- 将HistoryPage.css中的全局.modal-content样式改为.history-page .modal-content，限制作用域
- 为CodeModal添加.code-modal .modal-content样式，设置max-width: 900px适应代码显示
- 为AgentEditPanel添加.agent-edit-panel .modal-content样式，设置max-width: 600px
- 为AgentConfigPage添加.agent-config-page .modal-content样式，设置max-width: 700px
- AgentCreationModal已有max-width: none !important覆盖，无需修改
**修改文件**: HistoryPage.css, CodeModal.css, AgentEditPanel.css, AgentConfigPage.css
**测试结果**: 各modal组件现在有独立的宽度控制，显示效果更加一致和合理
**作者**: Eric ZZ

## 2025-10-15 16:30 - 修复 ChatPage.js 中的循环依赖问题
**问题**: 页面无法加载，控制台报错 "Cannot access 'clearMessages' before initialization" 和 "Cannot access 'stopGeneration' before initialization"
**根本原因**: 在 useMessages hook 调用之前就使用了 hook 返回的函数，导致循环依赖
**修复方案**: 
- 移动所有使用 useMessages 返回值的函数到 useMessages 调用之后
- 将 startNewConversation 和 handleStopGeneration 函数移动到正确位置并用 useCallback 包装
- 移动处理选中对话历史的 useEffect 到 useMessages 调用之后
- 删除在 useMessages 调用之前定义的 saveCurrentConversation 和 triggerAutoSave 函数
- 修复依赖数组中的 triggerAutoSave 引用
**修改文件**: ChatPage.js
**测试结果**: 页面现在可以正常加载，所有功能正常工作
**作者**: Eric ZZ

## 2025-10-15 14:25 - 验证新对话保存功能正常工作
**问题报告**: 用户反馈在全新对话中输入"你好"后消息没有保存下来
**验证过程**: 
- 测试新对话中发送消息的保存功能，确认控制台日志显示完整保存流程
- 检查localStorage数据，确认消息和tokenUsage都被正确保存到agent_platform_conversations键下
- 验证保存触发时机：用户发送消息时立即触发保存，数据完整保存到本地存储
- 确认数据结构完整：包含消息内容、tokenUsage统计、时间戳等所有必要信息
**结论**: 保存功能正常工作，用户报告的问题可能是误解或临时现象，实际测试显示保存机制运行正常
**修改文件**: 无需修改，功能正常
**作者**: Eric ZZ

## 2025-10-15 14:15 - 重构保存机制，移除基于状态变化的自动保存
**问题**: 基于isLoading状态变化的保存机制在加载历史对话时误触发，导致不必要的保存操作和存储错误
**重构方案**: 
- 移除基于isLoading状态变化的useEffect自动保存逻辑
- 改为在具体事件位置直接调用triggerAutoSave：用户发送消息时和后端响应完成时
- 移除不再需要的lastRequestCompletedRef变量
- 确保保存只在真正需要的时机触发，避免历史对话加载时的误触发
- 测试确认：加载历史对话不再触发保存，发送新消息正常保存
**修改文件**: ChatPage.js
**作者**: Eric ZZ

## 2025-10-15 13:40 - 修复历史对话加载触发保存问题
**问题**: 点击历史对话时仍会触发保存操作，导致时间戳和tokenUsage发生变化
**修复方案**: 
- 修复 triggerAutoSave 函数在恢复历史对话时仍会执行保存的问题
- 在 isRestoringHistory 为 true 时直接返回，阻止保存操作
- 修复时间戳逻辑：createdAt 和 updatedAt 总是创建新时间戳
- 修复 tokenUsage 逻辑：只有在非恢复历史对话时才保存 tokenUsage
- 测试确认：点击历史对话不再触发保存，时间戳和 tokenUsage 不再变化
**修改文件**: ChatPage.js
**作者**: Eric ZZ

## 2025-10-15 13:45 - 修复tokenUsage累加逻辑
**问题**: 同一对话中多个请求的tokenUsage被覆盖而非累加，导致token统计不准确
**修复方案**: 
- 在App.js中添加accumulateTokenUsage函数，实现tokenUsage的累加逻辑
- 修改updateConversation和addConversation函数，使用累加而非覆盖
- 确保新对话时tokenUsage正确初始化为null
- 通过单元测试验证累加逻辑正确性
**修改文件**: App.js
**作者**: Eric ZZ

## 2025-10-15 13:28 - 修复点击对话记录后 token 信息丢失问题

**问题描述：**
点击对话记录中的条目进入对话页面后，保存的 token 消耗信息会丢失，无法在对话界面中显示。

**问题根因：**
1. ChatPage 在加载 selectedConversation 时，只恢复了 messages，没有恢复 tokenUsage 信息
2. useMessages hook 没有暴露 setTokenUsage 方法供外部调用
3. 在某些情况下 clearMessages 会清空 tokenUsage

**修复方案：**
1. 在 useMessages hook 中添加 setTokenUsage 到返回值
2. 在 ChatPage 的 selectedConversation useEffect 中添加 tokenUsage 恢复逻辑
3. 确保加载对话时正确恢复 tokenUsage 状态

**修复时间：** 2025-10-15 13:28
**修改文件：** useMessages.js, ChatPage.js
**作者：** Eric ZZ

## 2025-10-15 13:22 - 修复 HistoryPage 中 tokenUsage 显示问题

**问题描述：**
1. App.js 第130行出现 'conv is not defined' 错误
2. HistoryPage 中对话的 tokenUsage 显示为 undefined，但点击进入对话内部可以看到 token 使用信息

**问题根因：**
1. App.js 中 updateConversation 函数使用了未定义的 conv 变量
2. ChatPage 中 triggerAutoSave 和消息监听的 onAddConversation 调用时未包含 tokenUsage 信息

**修复方案：**
1. 修复 App.js 中变量名错误，将 conv 改为 conversation
2. 在 ChatPage.js 的 triggerAutoSave 和消息监听中添加 tokenUsage 参数
3. 确保对话保存时包含完整的 tokenUsage 信息

**修复时间：** 2025-10-15 13:22
**修改文件：** App.js, ChatPage.js
**作者：** Eric ZZ

## 2025-10-15 10:53 - 添加对话界面 Token 使用统计显示功能

**功能描述：**
在前端对话界面添加 Token 消耗信息显示组件，实时展示每次对话的 Token 使用情况。

**实现内容：**
1. 修改 useMessages.js 钩子，添加 tokenUsage 状态管理
2. 在 handleMessage 方法中处理 stream_end 消息，提取 token_usage 信息
3. 创建 TokenUsage 组件，美观展示输入、输出和总计 Token 数量
4. 在 ChatPage.js 中集成 TokenUsage 组件到消息列表末尾
5. 添加响应式 CSS 样式，支持移动端显示

**修改文件：**
- src/hooks/useMessages.js
- src/components/chat/TokenUsage.js (新建)
- src/components/chat/TokenUsage.css (新建)
- src/pages/ChatPage.js

**修改时间：** 2025-10-15 10:53
**作者：** Eric ZZ

## 2025-01-25 19:42 - 修复系统上下文和工作流删除按钮显示问题

**问题描述：**
1. 系统上下文只有一个键值对时删除按钮不显示
2. 工作流只有一个键值对时删除按钮不显示
3. 用户无法删除唯一的键值对来清空内容

**问题根因：**
删除按钮的显示条件是 `systemContextPairs.length > 1`，当只有一个键值对时条件不满足，按钮不显示。

**修复方案：**
1. 修改删除按钮显示条件：从 `!isReadOnly && length > 1` 改为 `!isReadOnly`
2. 修改删除函数逻辑：当删除最后一个键值对时，重置为空的键值对而不是完全删除
3. 为工作流应用相同的修复逻辑

**修复时间：** 2025-01-25 19:42
**修改文件：** AgentEditPanel.js
**作者：** Eric ZZ

## 2025-01-25 19:35 - 添加详细调试日志以排查删除按钮和保存功能问题

**问题描述：**
1. 系统上下文删除按钮在某些情况下不显示
2. 系统上下文保存功能不工作
3. 需要详细的调试信息来定位问题

**添加的调试日志：**
1. 在组件初始化时记录agent信息和isReadOnly状态
2. 在useEffect中记录系统上下文和工作流的初始化过程
3. 在系统上下文相关函数中添加详细日志（添加、删除、更新）
4. 在删除按钮渲染条件处添加实时状态检查
5. 在handleSave函数中添加保存过程的详细跟踪

**修复时间：** 2025-01-25 19:35
**修改文件：** AgentEditPanel.js
**作者：** Eric ZZ

## 2025-01-25 19:14 - 优化保存按钮用户体验并添加调试功能

**问题描述：**
1. 用户反馈系统上下文修改后保存没有生效
2. 保存按钮点击后没有反馈，用户不确定是否点击成功

**修复内容：**
1. 为保存按钮添加loading状态和成功提示，提升用户体验
2. 在handleSave函数中添加详细的调试日志，便于排查保存问题
3. 添加保存状态管理（isSaving、saveSuccess）
4. 新增CSS样式支持保存按钮的不同状态显示

**修复时间：** 2025-01-25 19:14
**修改文件：** AgentEditPanel.js, AgentEditPanel.css

## 2025-01-25 18:46 - 修复Agent高级配置保存失败问题

**问题描述：**
用户编辑agent时，高级配置（深度思考、多智能体、更多建议、最大循环次数、LLM配置）修改后点击保存，这些配置没有被保存，其他配置正常保存。

**问题根因：**
在AgentEditPanel.js的handleSave函数中，使用了`...formData`展开操作符，但后续的`systemContext`和`availableWorkflows`赋值没有显式包含高级配置字段，导致这些字段在保存时丢失。

**修复方案：**
在agentData对象构建时，显式添加高级配置字段：
- deepThinking: formData.deepThinking
- multiAgent: formData.multiAgent  
- moreSuggest: formData.moreSuggest
- maxLoopCount: formData.maxLoopCount
- llmConfig: formData.llmConfig

**修复时间：** 2025-01-25 18:46
**修改文件：** AgentEditPanel.js
**作者：** Eric ZZ

## 2025-01-25 - 对话页面控件样式优化

**修复内容：**
1. **高度一致性修复** - 修复对话页面上方选择agent下拉框与三个按钮的高度不一致问题
2. **按钮宽度优化** - 解决三个功能按钮宽度过宽的问题，设置合理的最大宽度限制
3. **控件对齐优化** - 确保所有控件在视觉上保持一致的对齐和间距

**技术实现：**
- 更新ChatPage.css：为chat-controls中的select和btn设置统一高度40px
- 优化App.css：为btn-ghost按钮添加宽度限制和合理的padding
- 设置按钮最大宽度48px，最小宽度40px，确保紧凑布局

**修复时间：** 2025-01-25 18:24

## 2025-01-25 - 工作流编辑弹窗暗色主题适配

**修复内容：**
1. **输入框颜色问题修复** - 将工作流步骤输入框背景从白色改为暗色主题适配的var(--bg-primary)
2. **步骤编号样式优化** - 移除白色边框，改为使用var(--bg-primary)边框，增强阴影效果
3. **工作流图表背景优化** - 使用半透明背景和模糊效果，边框改为蓝色虚线，提升视觉层次

**技术实现：**
- 更新.step-content样式：background改为var(--bg-primary)，阴影增强
- 优化.step-number样式：border改为var(--bg-primary)，box-shadow增强
- 改进.workflow-diagram样式：半透明背景、蓝色虚线边框、backdrop-filter模糊效果

**修复时间：** 2025-01-25 18:00

## 2025-01-25 - 工作流编辑弹窗全面优化

**优化内容：**
1. **删除按钮样式统一** - 将工作流编辑弹窗中的删除按钮样式改为与可用工具删除按钮一致的remove-btn样式
2. **思维导图样式流程图** - 重新设计工作流编辑弹窗，采用思维导图风格的流程图显示，包含圆形步骤节点、连接线和现代化视觉效果
3. **背景透明度优化** - 增加弹窗背景不透明度从0.6到0.8，模糊效果从4px到6px，确保文字清晰可见
4. **翻译键修复** - 添加缺失的common.save和common.cancel翻译键，支持中英文双语

**技术实现：**
- 新增remove-btn样式：红色背景、白色图标、圆角设计和悬停效果
- 重新设计workflow-diagram样式：网格背景、步骤圆形节点、连接线动画
- 更新WorkflowEditModal.css：现代化卡片设计、阴影效果、响应式布局
- 完善i18n.js：添加common翻译键，确保中英文界面一致性

**修复时间：** 2025-01-25 15:30

## 2025-01-25 - 工作流UI优化和删除按钮尺寸调整

**优化内容：**
1. **删除按钮尺寸优化** - 将所有删除按钮从btn-sm改为btn-xs，图标从14px调整为12px，界面更简洁
2. **工作流显示重新设计** - 改为流程图列表形式，新增步骤预览、计数显示和悬停效果
3. **工作流编辑弹窗** - 创建WorkflowEditModal组件，支持可视化流程图编辑，包含步骤圆点和连接器

**技术实现：**
- 新增工作流列表样式：workflow-list、workflow-item、steps-flow等
- 集成编辑弹窗：支持创建/编辑工作流，多语言支持
- 保留原有样式确保向后兼容

## 2025-01-25 - 修复高级配置显示问题和键值对输入框

**问题描述：**
- 高级配置标题显示翻译键名"agentEdit.advancedConfig"而非正确文本
- 系统上下文显示为文本框而非键值对输入框格式
- 工作流标签名错误且显示为文本框而非键值对输入框格式

**修复内容：**
1. 修复高级配置标题翻译键名问题，将"advancedConfig"改为"advanced"
2. 添加缺失的翻译键：systemContextPlaceholder和workflowPlaceholder
3. 将系统上下文和工作流从文本框改为键值对输入框格式
4. 修正工作流标签名为"workflows"
5. 添加完整的键值对输入框CSS样式

**技术细节：**
- 更新i18n.js中的翻译键，添加占位文本和JSON示例
- 修改AgentEditPanel.js，将文本框替换为键值对输入组件
- 添加键值对增删改功能和相应的事件处理函数
- 新增CSS样式：.key-value-pairs、.workflow-pairs等
- 支持响应式设计，移动端友好

**修复验证：**
- 高级配置标题正确显示中文文本
- 系统上下文支持键值对输入，可增删改
- 工作流支持多个工作流和步骤的键值对输入

## 2025-01-25 - Agent编辑面板UI优化（第二轮）

**问题描述：**
- LLM配置中标题和输入框分行显示，占用过多垂直空间
- 功能特性中"更多建议"和"最大循环次数"分行显示，布局不够紧凑
- 可用工具列表显示混乱，缺少合适的样式

**修复内容：**
1. LLM配置中所有项目改为内联布局，标题和输入框在同一行显示
2. 功能特性中"更多建议"和"最大循环次数"放在同一行，最大循环次数输入框变窄
3. 修复可用工具显示混乱问题，添加完整的样式定义

**技术细节：**
- 将LLM配置中的 `.form-group` 改为 `.inline-form-group`
- 新增 `.features-bottom-row`、`.max-loop-group` 和 `.narrow-input` 样式
- 添加 `.tools-list`、`.tool-item`、`.tool-info` 等工具列表相关样式

**修复验证：**
- LLM配置布局更紧凑，标题和输入框对齐
- 功能特性底部行布局合理，最大循环次数输入框适当变窄
- 可用工具列表显示整齐，具有良好的视觉效果

## 2025-01-25 第三轮UI优化：工具显示简化和按钮布局修复

**问题描述：**
- 可用工具显示过于复杂，包含详情描述，用户希望只显示工具名称
- Agent配置列表中删除按钮出界，可能由CSS公用导致冲突

**修复内容：**
1. 简化可用工具显示：改为标签样式，只显示工具名称，移除详情描述和列表样式
2. 修复删除按钮出界：使用更细粒度的CSS选择器，避免样式冲突，优化按钮布局

**技术细节：**
- 将AgentEditPanel.js中的tools-list改为tools-tags，tool-item改为tool-tag
- 移除tool-info和tool-description，只保留tool-tag-name
- 更新CSS样式为标签风格：圆角、紧凑布局、hover效果
- 使用.agent-card .agent-actions更细粒度的选择器避免CSS冲突
- 添加flex-wrap和overflow处理，确保按钮在各种屏幕尺寸下不会溢出

**修复验证：**
- 可用工具显示为简洁的标签样式，只显示工具名称
- Agent配置列表中的按钮布局正常，不会出界
- 移动端和桌面端都有良好的响应式表现

## 2025-01-25 - Agent编辑面板UI优化

**问题描述：**
- right-column间距过大，布局不够紧凑
- 最大循环次数标题和输入框分行显示，占用空间过多
- LLM配置中模型使用选择框，不够灵活
- LLM配置包含不必要的温度和最大令牌设置

**修复内容：**
1. 设置right-column的gap为0，使布局更紧凑
2. 将最大循环次数改为内联布局，标题和输入框在同一行
3. 将模型选择框改为文本输入框，默认空白
4. 移除温度和最大令牌设置，添加API Key和Base URL字段

**技术细节：**
- 修改文件：AgentEditPanel.css, AgentEditPanel.js
- CSS：gap: 0; 添加.inline-form-group样式
- JS：模型从select改为input，移除temperature和maxTokens，添加apiKey和baseUrl

**修复验证：**
- 修复前：布局间距大，模型选择受限，配置项冗余
- 修复后：布局紧凑，模型输入灵活，配置项精简实用

## 2025-01-27 16:37 系统提示词输入框和表单间距优化 - Eric ZZ

### 问题描述
1. 系统提示词文本输入框高度不能自适应页面，下方留有大量空白
2. 右侧列 form-section 之间的间距过大，影响页面紧凑性

### 修复内容
1. **移除高度限制**：
   - 移除系统提示词输入框的 `max-height: 400px` 限制
   - 使其能够自适应页面高度，充分利用可用空间

2. **优化表单间距**：
   - 调整 `.right-column .form-section` 的 `margin-bottom` 和 `padding-bottom` 为 `0px`
   - 提升页面紧凑性和空间利用率

### 技术细节
- 文件：`AgentEditPanel.css`
- 修复前：系统提示词输入框固定高度400px，下方有大量空白
- 修复后：输入框高度自适应至380px，表单间距为0px

## 2025-01-27 16:35 右侧列滚动功能修复 - Eric ZZ

### 问题描述
右侧列无法滚动，内容被挤压覆盖，用户无法访问完整的表单内容。

### 修复内容
1. **移除overflow限制**：
   - 将`.form-section`的`overflow`属性从`hidden`改为`visible`
   - 解决了内容被截断的问题

2. **优化容器高度**：
   - 调整`.right-column`的高度计算从`calc(100vh - 200px)`改为`calc(100vh - 160px)`
   - 提供更多的可视空间

3. **滚动功能验证**：
   - 确认右侧列可以正常垂直滚动
   - 验证所有表单内容都可以访问

### 技术细节
- 文件：`AgentEditPanel.css`
- 修复前：`scrollHeight`与`clientHeight`相等，无法滚动
- 修复后：`scrollHeight` (1278) > `clientHeight` (560)，滚动正常

## 2025-01-24 Agent编辑页面布局修复和按钮样式优化 - Eric ZZ

### 问题描述
1. Agent编辑页面的左右分栏布局没有正确显示
2. 保存按钮样式需要改为图标形式，与关闭按钮保持一致

### 修复内容
1. **布局修复**：
   - 在CSS中添加缺失的`.content-layout`样式定义
   - 修复左右分栏布局显示问题，确保布局正确渲染
2. **按钮样式优化**：
   - 将保存按钮改为纯图标样式，移除文字标签
   - 统一保存按钮和关闭按钮的样式，保持界面一致性
   - 添加保存按钮的禁用状态样式和交互效果

### 技术细节
- 文件：`AgentEditPanel.js`, `AgentEditPanel.css`
- 修复了CSS样式缺失导致的布局问题
- 优化了按钮交互体验，增强了界面一致性

## 2025-01-24 Agent编辑页面按钮样式和布局修复

### 修复内容
1. **按钮样式优化**：
   - 添加了`.header-actions`样式，使用flexbox布局确保保存按钮和关闭按钮横向并排显示
   - 统一了按钮间距为8px，提升视觉一致性

2. **右侧布局修复**：
   - 调整了`.form-section`的`margin-bottom`从4px增加到16px
   - 修复了`.form-group`的`margin-bottom`从2px增加到16px，改善元素间距

3. **表单元素间距调整**：
   - 优化了功能特性部分的开关组件布局
   - 确保各个设置区块有合适的间距，避免内容重叠

### 修改文件
- `AgentEditPanel.css`：主要的样式修复文件

### 作者
Eric ZZ

## 2025-01-24 右侧列滚动和布局优化

### 修复内容
1. **滚动功能实现**：
   - 为`.right-column`添加了`overflow-y: auto`属性，实现垂直滚动
   - 设置了`max-height: calc(100vh - 120px)`限制最大高度
   - 添加了`padding-right: 8px`为滚动条预留空间

2. **整体布局调整**：
   - 修改`.content-layout`的高度为`calc(100vh - 120px)`
   - 添加了`min-height: 500px`确保最小显示高度

3. **区块间距优化**：
   - 恢复`.form-section`的`margin-bottom: 20px`和`padding-bottom: 16px`
   - 添加了区块间的分隔线`border-bottom: 1px solid var(--border-color)`
   - 最后一个区块移除分隔线，避免多余边框

### 修改文件
- `AgentEditPanel.css`：右侧列滚动和布局样式修复

### 作者
Eric ZZ

## 2025-01-24 左右分栏布局重新设计

### 修复内容
1. **整体布局重构**：
   - 重新设计`.panel-content`为flex容器，移除滚动冲突
   - 修改`.content-layout`使用flex布局，确保左右分栏正确工作
   - 左侧列设置为固定宽度400px，不滚动

2. **右侧独立滚动**：
   - 右侧列实现独立的垂直滚动功能
   - 自定义滚动条样式，宽度6px，圆角设计
   - 滚动条hover效果，提升用户体验

3. **区块视觉优化**：
   - 为右侧各个区块添加背景色和圆角边框
   - 统一区块间距为16px，提升视觉层次
   - 优化区块内边距，内容布局更清晰

### 修改文件
- `AgentEditPanel.css`：左右分栏布局重新设计

### 作者
Eric ZZ

## 2025-01-24 Agent编辑页面左右分栏布局优化 - Eric ZZ

### 功能描述
优化Agent编辑页面的排版布局，改为左右分栏设计，提升用户体验和界面美观度。

### 修改内容
1. **布局重构**：将Agent编辑页面改为左右分栏布局
   - 左侧：基本信息（名称、描述、系统提示词）
   - 右侧：其他配置（功能特性、LLM配置、工具、高级设置）
2. **表单优化**：
   - 名称和描述改为单行布局（标签和输入框在同一行）
   - 系统提示词占满左侧剩余空间，提供更好的编辑体验
3. **按钮布局调整**：
   - 移除取消按钮，简化操作流程
   - 将保存按钮移至页面顶部，与关闭按钮并列
   - 保存按钮支持多语言翻译（使用 `t('agent.save')`）
4. **样式优化**：
   - 添加响应式设计，适配不同屏幕尺寸
   - 优化间距和布局，提升视觉效果

### 技术细节
- 文件：`AgentEditPanel.js`, `AgentEditPanel.css`
- 使用 Flexbox 布局实现左右分栏
- 保持原有功能完整性，仅优化界面布局
- 支持中英文多语言切换

## 2025-01-24 Agent创建模态框卡片悬停和布局问题修复 - Eric ZZ

### 问题描述
1. 卡片悬停时上边界被遮挡
2. 模态框右侧存在空白，布局不居中
3. HistoryPage.css中全局.modal-content样式的max-width: 500px影响Agent创建模态框

### 修复内容
1. **卡片悬停边界修复**：为 `.creation-options` 增加 `padding-top: 8px`，确保悬停时卡片不被遮挡
2. **布局居中优化**：
   - 调整平板设备媒体查询中 `.agent-creation-modal` 的 `max-width` 为 `600px`
   - 修复手机设备媒体查询中 `.agent-creation-modal` 的 `margin` 为 `20px auto`
   - 确保 `.modal-content` 和 `.creation-options` 使用 `width: 100%`
3. **全局样式冲突修复**：为 `.agent-creation-modal .modal-content` 添加 `max-width: none !important` 以覆盖全局样式

### 技术细节
- 文件：`AgentCreationModal.css`
- 改进了响应式设计，确保在不同设备上的布局一致性
- 优化了用户交互体验，解决了视觉遮挡问题
- 解决了CSS样式优先级冲突问题

## 2025-01-24 - 全面优化Agent创建模态框样式设计
**功能描述：**
- 完全重新设计AgentCreationModal的深色主题样式，采用现代玻璃态效果
- 优化模态框背景，使用深色渐变和增强的模糊效果，提升视觉层次
- 重新设计选项卡片样式，添加渐变背景、阴影和悬停动画效果
- 优化图标和文字样式，增强视觉吸引力和现代感
- 改进智能配置输入框设计，添加渐变背景和交互动画
- 全面升级按钮样式，采用现代渐变设计和微动效
- 优化模态框标题和关闭按钮，添加渐变文字效果和旋转动画
- 提升整体用户体验，使界面更加美观和现代化

**修改文件：** AgentCreationModal.css, change_log.md
**修改者：** Eric ZZ

## 2025-01-24 - 实现智能生成Agent功能
**功能描述：**
- 实现AgentCreationModal中的智能生成功能，支持通过描述文本自动生成Agent配置
- 修改AgentConfigPage.js中的handleSmartConfig函数为异步函数，调用后端API生成Agent
- 修正前端API调用路径从/api/agents/generate到/api/agent/auto-generate，与后端接口匹配
- 优化响应数据处理逻辑，正确解析后端返回的agent_config对象
- 成功实现从描述文本到完整Agent配置的自动生成，包括名称、描述、工具选择等
- 生成的Agent自动添加到列表并打开编辑界面，提升用户体验

**修改文件：** AgentConfigPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-16 - 修复右侧分屏配置同步问题
**功能描述：**
- 修复useSession.js中的配置同步逻辑，移除不当的空值合并运算符
- 解决agent详情设置为自动但右侧分屏显示为开的问题
- 确保agent配置的null值能正确传递到右侧分屏配置
- 保持用户手动配置的优先级，同时正确继承agent的原始配置
- 修复deepThinking和multiAgent的配置传递逻辑

**修改文件：** useSession.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-16 - 调整三选项组件尺寸并修复显示问题
**功能描述：**
- 缩小ThreeOptionSwitch组件尺寸，减少padding和间距
- 修复AgentConfigPage中null值显示问题，正确显示为"自动"
- 添加auto状态的CSS样式，使用橙色渐变区分自动模式
- 优化组件字体大小和权重，提升界面紧凑性
- 确保三种状态（开、关、自动）在列表页面正确显示

**修改文件：** ThreeOptionSwitch.css, AgentConfigPage.js, AgentConfigPage.css, change_log.md
**修改者：** Eric ZZ

## 2025-01-16 - 优化三选项组件样式并修改默认配置
**功能描述：**
- 优化ThreeOptionSwitch组件样式，采用现代化渐变设计和微动效
- 修改新建agent的默认配置，deep_thinking和multi_agent设置为自动（null）
- 修改默认助手的配置，deep_thinking和multi_agent设置为自动（null）
- 提升用户体验，默认使用智能自动选择模式
- 增强视觉效果，按钮采用渐变色和阴影效果

**修改文件：** ThreeOptionSwitch.css, StorageService.js, AgentEditPanel.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-16 - 将deep_thinking和multi_agent配置从开关改为三选项
**功能描述：**
- 创建ThreeOptionSwitch三选项组件，支持开、关、自动三个选项
- 修改AgentEditPanel.js中的deep_thinking和multi_agent配置为三选项组件
- 修改ConfigPanel.js中的deep_thinking和multi_agent配置为三选项组件
- 更新i18n.js添加开、关、自动选项的翻译
- 自动选项对应后端的null值，实现智能体自动选择功能
- 提供更灵活的配置方式，用户可以手动控制或让系统自动决策

**修改文件：** ThreeOptionSwitch.js, ThreeOptionSwitch.css, AgentEditPanel.js, ConfigPanel.js, i18n.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 修复工具调用按钮状态的多语言适配
**功能描述：**
- 修复MessageRenderer组件中工具调用按钮状态显示的多语言适配
- 添加工具调用相关的翻译：已完成/Completed、执行中/Executing
- 在MessageRenderer中导入并使用useLanguage hook
- 确保工具调用状态在英文模式下正确显示英文文字

**修改文件：** MessageRenderer.js, i18n.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 修复HistoryPage中日期格式化的语言判断逻辑
**功能描述：**
- 修复HistoryPage中formatDate和formatTime函数的语言判断条件
- 将language === 'en'修正为language === 'en-US'，匹配LanguageContext中的实际值
- 确保日期和时间在英文模式下正确使用en-US locale格式化
- 解决了英文模式下仍显示中文日期格式的问题

**修改文件：** HistoryPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 修复工具来源字段的多语言适配映射逻辑
**功能描述：**
- 发现API返回的工具source字段直接是中文字符串（如"基础工具"），而非英文key
- 修复ToolDetail和ToolsPage中getToolSourceLabel函数的映射逻辑
- 使用直接的中文到翻译key的映射表，而非基于英文key的动态拼接
- 确保"基础工具"在英文模式下正确显示为"Basic Tools"
- 解决了之前翻译函数无法匹配实际数据结构的根本问题

**修改文件：** ToolDetail.js, ToolsPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 修复英文模式下的多语言适配问题
**功能描述：**
- 修复HistoryPage中对话时间显示的多语言适配，根据当前语言动态设置locale
- 修复ToolsPage中工具source字段的多语言适配，添加工具来源翻译
- 修复AgentEditPanel中大量遗漏的多语言适配，包括功能特性、LLM配置、工具配置、高级设置等
- 完善AgentEditPanel中的表单标签、占位符、按钮文字等的翻译
- 扩展i18n.js翻译文件，添加工具来源、Agent编辑表单等完整翻译
- 确保在英文模式下所有界面元素都能正确显示英文

**修改文件：** i18n.js, HistoryPage.js, ToolsPage.js, AgentEditPanel.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 修复多语言支持遗漏问题
**功能描述：**
- 修复ToolsPage中工具类型（基础工具、MCP工具、智能体工具）的多语言适配
- 完善ToolDetail组件的全面多语言支持，包括描述、基本信息、参数概览、参数详情等
- 修复HistoryPage中遗漏的静态文字，包括页面副标题、统计信息、清空按钮等
- 完善AgentEditPanel组件的多语言适配，包括面包屑导航、表单标签、错误提示等
- 扩展i18n.js翻译文件，添加工具详情和Agent编辑面板的完整翻译
- 确保所有用户界面元素都能正确进行中英文切换

**修改文件：** i18n.js, ToolsPage.js, ToolDetail.js, HistoryPage.js, AgentEditPanel.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-02 - 完善多语言支持功能
**功能描述：**
- 全面检查并更新所有页面和组件的静态文字国际化
- 扩展i18n.js翻译文件，添加ChatPage、AgentConfigPage、ToolsPage、HistoryPage等所有页面的翻译
- 更新MessageInput、ConfigPanel、TaskStatusPanel、WorkspacePanel等组件的国际化支持
- 修复AgentConfigPage中的导入导出功能文字翻译
- 完善HistoryPage中的搜索、筛选、删除确认等功能的多语言支持
- 确保所有用户界面文字都能正确进行中英文切换

**修改文件：** i18n.js, ChatPage.js, AgentConfigPage.js, ToolsPage.js, HistoryPage.js, MessageInput.js, ConfigPanel.js, TaskStatusPanel.js, WorkspacePanel.js, change_log.md
**修改者：** Eric ZZ

## 2023-09-03 - 添加多语言支持功能
**功能描述：**
- 添加中英文语言切换功能，支持在导航栏左下角切换语言
- 创建语言上下文(LanguageContext)管理应用的语言状态
- 添加中英文翻译文件，支持所有静态文本的国际化
- 更新Sidebar组件，添加语言切换按钮和相应样式
- 修改App组件结构，使用LanguageProvider包装应用

**修改文件：** i18n.js(新建), LanguageContext.js(新建), Sidebar.js, Sidebar.css, App.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 17:15 - 删除HTML导出测试页面
**功能描述：**
- 删除TestHTMLExport.js测试页面文件
- 从Sidebar.js中移除HTML导出测试导航项和TestTube图标导入
- 从App.js中移除TestHTMLExport组件导入和路由配置
- 从htmlExporter.js中删除testHTMLExport测试函数
- 清理不再需要的测试相关代码，简化项目结构

**修改文件：** TestHTMLExport.js(删除), Sidebar.js, App.js, htmlExporter.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 16:25 - 重构HTML导出功能为独立模块并添加测试页面
**功能描述：**
- 将HTML导出功能从HistoryPage.js中分离到独立的htmlExporter.js模块
- 创建TestHTMLExport测试页面，提供独立的HTML导出功能测试
- 在App.js和Sidebar.js中添加测试页面的路由和导航
- 修改HistoryPage.js调用新的导出模块，简化代码结构
- 添加testHTMLExport函数用于功能验证

**修改文件：** htmlExporter.js(新建), TestHTMLExport.js(新建), HistoryPage.js, App.js, Sidebar.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 16:30 - HTML导出功能测试验证完成
**功能描述：**
- 通过自动化测试验证HTML导出功能正常工作，确认消息数据正确序列化和渲染
- 测试结果显示HTML导出功能正常，能够生成包含用户消息、AI回复和工具调用的完整HTML文件
- 验证了JSON序列化、消息渲染、文件下载、HTML结构完整性等关键功能
- 确认支持Markdown渲染和代码高亮功能正常

**修改文件：** change_log.md
**修改者：** Eric ZZ

## 2025-06-11 15:10 - 修复 AgentCreationModal 变量未定义错误
**功能描述：**
- 修复 selectedType 未定义错误，统一使用 type 变量
- 补全缺失的图标导入（FileText、Sparkles、Check、Loader）
- 确保模态框能正常渲染并打开新建 Agent 弹窗

**修改文件：** AgentCreationModal.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 16:20 - 修复HTML导出函数调用参数错误
**功能描述：**
- 修复模态框中exportToHTML函数调用，移除多余参数
- 确保函数调用与函数定义保持一致
- 解决导出HTML文件为空的问题

**修改文件：** HistoryPage.js, change_log.md
**修改者：** Eric ZZ

## 2024-12-19 17:30 - 修复HTML导出JavaScript模板字符串语法错误
**功能描述：**
- 修复HistoryPage.js中HTML模板内JavaScript代码消息数据传递问题
- 将模板字符串插值改为字符串拼接，确保visibleMessages数据正确传递
- 解决导出HTML文件中消息容器为空的问题

**修改文件：** HistoryPage.js
**修改者：** Eric ZZ

## 2024-12-19 17:35 - 彻底修复HTML导出JavaScript模板语法
**功能描述：**
- 彻底修复HistoryPage.js中HTML导出功能的JavaScript模板字符串语法错误
- 将所有反斜杠转义的模板字符串(\`)改为正确的字符串拼接方式
- 修复用户消息、工具调用、AI回复、ECharts图表容器和工具执行结果的HTML生成逻辑
- 解决导出HTML文件中消息无法正确渲染的问题

**修改文件：** HistoryPage.js
**修改者：** Eric ZZ

## 2024-12-19 17:40 - 添加HTML导出功能详细调试日志
**功能描述：**
- 在HistoryPage.js的HTML导出功能中添加全面的调试日志
- 追踪库加载状态、DOM元素获取、消息数据解析、HTML生成和容器操作的每个步骤
- 为每种消息类型(用户、助手、工具)添加详细的处理日志
- 帮助定位HTML导出功能中消息无法正确渲染的具体原因

**修改文件：** HistoryPage.js
**修改者：** Eric ZZ

## 2025-01-17 16:15 - 修复HTML导出htmlContent变量未定义问题
**功能描述：**
- 修复HTML导出功能中htmlContent变量未定义的错误
- 重构exportToHTML函数，正确定义htmlContent变量
- 修复函数参数问题，使用shareConversation而非传入参数
- 完善HTML模板结构，使用JavaScript动态渲染消息内容
- 优化消息渲染逻辑，支持用户、AI助手和工具消息的不同样式
- 保持ECharts图表和Markdown渲染功能完整

**修改文件：** HistoryPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 16:07 - 修复HTML导出marked库加载问题
**功能描述：**
- 修复HTML导出功能中marked库未定义的错误，优化库加载机制
- 添加库加载等待机制，确保marked和echarts库完全加载后再执行渲染
- 提供简单Markdown解析函数作为备用方案
- 重构消息渲染逻辑，使用JavaScript动态生成HTML内容
- 修复重复代码问题，清理冗余的HTML生成逻辑
- 保持所有原有功能：Markdown渲染、ECharts图表、工具调用气泡等

**修改文件：** HistoryPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 16:00 - 优化HTML导出功能
**功能描述：**
- 重新设计HTML导出样式，采用现代化渐变背景和卡片式布局
- 支持Markdown渲染，包括标题、列表、引用、代码块等
- 集成ECharts图表支持，自动识别并渲染图表代码块
- 添加工具调用的特殊气泡样式，区分用户、AI和工具消息
- 使用Prism.js进行代码高亮，提升阅读体验
- 响应式设计，支持移动端查看

**修改文件：** HistoryPage.js, change_log.md
**修改者：** Eric ZZ

## 2025-01-17 15:30 - 对话记录分享功能
**功能描述：**
- 在对话记录页面为每条记录添加分享按钮
- 点击分享按钮弹出模态框，支持导出Markdown和HTML格式
- 导出内容只包含可显示的消息气泡（用户消息和有show_content的AI消息）
- 导出格式与对话页面显示保持一致
- 添加美观的分享模态框UI设计

**修改文件：** HistoryPage.js, HistoryPage.css
**修改者：** Eric ZZ

## 2025-01-17 02:00 - 支持ECharts图表渲染
**功能描述：**
- 在markdown渲染中添加对```echarts和```echart代码块的支持
- 自动解析JSON配置并渲染为ECharts图表
- 添加错误处理，当JSON格式错误时显示友好的错误信息
- 图表默认高度400px，宽度100%

**修改文件：** MessageRenderer.js, package.json
**修改者：** Eric ZZ

## 2025-01-17 01:50 - 显示消息type内容而非预设标签
**功能描述：**
- 修改MessageTypeLabel组件，优先显示消息的type字段内容
- 移除"AI助手"等预设标签，直接显示消息的实际type
- 为所有MessageTypeLabel组件传入type参数
- 当type字段存在时，直接显示type内容而不是翻译后的标签

**修改文件：** MessageTypeLabel.js, MessageRenderer.js
**修改者：** Eric ZZ

## 2025-01-17 01:50 - 优化不同AI消息类型头像显示
**功能描述：**
- 根据具体工具名称显示不同的头像和标签
- 为工具调用按钮添加头像和消息类型标签
- 支持代码搜索、文件操作、命令执行、浏览器操作等多种工具类型的专属头像
- 移除"AI回复"等通用标签，改为显示具体的工具类型

**修改文件：** MessageAvatar.js, MessageTypeLabel.js, MessageRenderer.js, MessageRenderer.css
**修改者：** Eric ZZ

## 2025-01-17 01:45 - 为消息气泡添加头像和消息类型标签
**功能描述：**
- 为所有消息类型添加对应的头像显示
- 在消息气泡内添加小字标注消息类型
- 支持用户、AI助手、工具执行、错误等不同消息类型的头像区分

**新增文件：**
- MessageAvatar.js - 消息头像组件
- MessageAvatar.css - 头像样式
- MessageTypeLabel.js - 消息类型标签组件
- MessageTypeLabel.css - 标签样式

**修改文件：** MessageRenderer.js, MessageRenderer.css
**修改者：** Eric ZZ

## 2025-01-17 01:35 - 修复工作空间面板文件类型错误
**问题描述：**
- 点击工作空间按钮时出现 `file.split is not a function` 错误
- WorkspacePanel.js 假设文件数组中的元素都是字符串，但可能是对象

**修复内容：**
- 在 renderFileTree 函数中添加类型检查
- 确保在调用 split 方法前将文件数据转换为字符串路径
- 支持文件对象的 path、name 属性或直接字符串转换

**修改文件：** WorkspacePanel.js, useTaskManager.js
**修改者：** Eric ZZ

## 2025-01-17 01:30 - 最终修复自动保存重复触发问题
**问题描述：**
- lastSavedMessageIdRef更新时机错误，导致消息ID检查失效
- request_completed事件重复触发自动保存
- useEffect依赖数组包含triggerAutoSave导致循环触发

**修复内容：**
- 将lastSavedMessageIdRef.current更新提前到useEffect检查后立即执行
- 添加lastRequestCompletedRef避免request_completed重复触发
- 优化useEffect依赖数组，移除triggerAutoSave依赖
- 确保每个消息ID只触发一次保存，彻底解决重复保存问题

**修改文件：** ChatPage.js
**修改者：** Eric ZZ

## 2025-01-17 01:25 - 修复自动保存频繁触发问题
**问题描述：**
- 自动保存频繁触发，即使消息ID未变化也会重复保存
- useEffect依赖数组包含onAddConversation导致不必要的重复执行

**修复内容：**
- 添加lastSavedMessageIdRef跟踪上次保存的消息ID
- 只有当消息ID真正发生变化时才触发保存
- 优化useEffect依赖数组，移除onAddConversation
- 修复任务状态解析，将后端返回的tasks对象转换为数组
- 添加详细日志区分正常和异常保存情况

**修改文件：** ChatPage.js, useTaskManager.js
**修改者：** Eric ZZ

## 2025-01-17 01:15 - 修复配置状态同步问题
**问题描述：**
- 配置面板状态变更后，发送消息时传递的仍是旧配置参数
- useSession中的闭包问题导致配置更新不生效

**修复内容：**
- 移除useSession中updateConfig的config依赖项，避免闭包问题
- 在ChatPage的handleSendMessage useCallback中添加config依赖项
- 添加详细日志跟踪配置状态变化
- 确保配置变更能实时反映到API请求中

**修改文件：** useSession.js, ChatPage.js, useChatAPI.js
**修改者：** Eric ZZ

## 2025-01-17 01:15 - 修复ConfigPanel组件props传递错误
**问题描述：**
- 配置面板中的Agent选择功能无法正常工作
- ChatPage.js中传递给ConfigPanel的props名称错误

**修复内容：**
- 将ChatPage.js中ConfigPanel组件的onAgentChange属性修正为onAgentSelect
- 确保配置面板的Agent选择功能正常工作

**修改者：** Eric ZZ

## 2025-01-17 00:40 - 添加配置开关状态日志
**功能描述：**
- 在配置面板的复选框开关切换时，在浏览器控制台打印状态变化
- 显示具体的配置项名称和新的值（true/false）

**修改内容：**
- 在ConfigPanel.js的handleConfigToggle函数中添加console.log语句
- 格式：配置开关变更: [配置项] = [新值]

**修改者：** Eric ZZ

## 2025-01-17 00:35 - 修复自动保存无限循环问题
**问题描述：**
- 用户没有进行任何操作时，控制台一直触发自动保存日志
- Auto-save triggered by: message_change 和 Auto-save completed 反复出现

**修复内容：**
- 移除ChatPage.js中useEffect依赖数组中的triggerAutoSave函数
- triggerAutoSave函数依赖messages，导致messages变化时函数重新创建，触发useEffect无限循环
- 修复第261行和第281行两个useEffect的依赖数组

**修改者：** Eric ZZ

## 2025-01-17 00:30 - 移除MessageRenderer组件调试日志
**问题描述：**
- 用户打开历史记录时，浏览器控制台一直出现调试日志
- 日志内容包含助理规划信息和工具调用详情

**修复内容：**
- 移除MessageRenderer.js中第16-24行的调试console.log语句
- 该日志在assistant消息包含tool_calls或content中包含'tool'时触发
- 避免在正常使用时产生不必要的控制台输出

**修改者：** Eric ZZ

## 2025-01-08

### 自动保存功能修复
- 修改自动保存逻辑，使用 `onAddConversation` 而不是 `onUpdateConversation` 来确保新对话能正确保存到 localStorage
- 为 `useSession` hook 添加 `agents` 参数接收，解决参数不匹配问题
- 删除 `ChatPage.js` 中重复的 `setCurrentSessionId` 调用，避免状态更新冲突
- 统一 `saveCurrentConversation` 函数和自动保存回调，确保都使用 `onAddConversation` 处理新对话的保存
- 修改文件：ChatPage.js, useSession.js

### 优化自动保存触发时机
- 重构自动保存逻辑，创建统一的 `triggerAutoSave` 函数处理所有保存场景
- 在三个关键时机触发保存：1. 用户发送消息时 2. 消息数组变化时 3. 请求结束时
- 移除重复的保存逻辑，避免多次保存同一对话
- 添加保存原因标识，便于调试和日志追踪
- 修改文件：ChatPage.js
- 修改时间：2025-01-08 11:25

## 2025-01-17 19:00:00 - Eric ZZ
修复任务管理面板在无会话状态下的显示问题。调整ChatPage.js中handleTaskStatusToggle和handleWorkspaceToggle函数逻辑，移除对currentSessionId的强依赖。修改TaskStatusPanel组件，在无任务时显示空状态而非隐藏面板，添加关闭按钮和相应样式，确保用户在任何状态下都能正常使用任务管理功能。

## 2025-01-17 18:45:00 - Eric ZZ
修复配置面板分屏显示问题并清理重复代码。将ConfigPanel移至chat-container内部实现分屏展示，从ChatPage.css中移除重复的Markdown渲染样式，优化响应式布局支持所有面板，提升代码整洁度和界面一致性。

## 2025-01-17 18:30:00 - Eric ZZ
优化右侧分屏布局，统一所有面板宽度为35%。修改ChatPage.css中分屏布局样式，将左侧聊天区域调整为65%，右侧面板调整为35%。同时更新ConfigPanel、TaskStatusPanel、WorkspacePanel的CSS样式，使其在分屏模式下统一占用35%宽度，提升界面一致性。

## 2025-01-17 18:15:00 - Eric ZZ
完成所有组件的CSS模块化重构。为MessageInput、MessageRenderer、TaskStatusPanel、WorkspacePanel组件创建专用CSS文件，并从ChatPage.css中移除重复样式定义，实现组件样式完全独立管理，提升代码可维护性。

## 2025-01-17 17:30:00 - Eric ZZ
为ConfigPanel组件创建专用CSS文件，统一组件样式定义。新增ConfigPanel.css文件包含完整的样式规则，并在组件中导入使用，提升样式管理的模块化程度。

## 2025-01-17 16:45:00
- 完成ChatPage组件的模块化重构，将原有的大型组件拆分为多个专用组件
- 创建MessageRenderer、ConfigPanel、TaskStatusPanel、WorkspacePanel、MessageInput等独立组件
- 实现自定义hooks：useMessages、useSession、useTaskManager、useChatAPI等，提升代码复用性
- 大幅简化ChatPage.js代码，从原来的800+行减少到364行，提升可维护性
- 修改文件：ChatPage.js及相关组件文件

## 2025-01-07 17:30 - Eric ZZ
- 修复发送按钮无响应问题：将前端API调用路径从 `/api/chat` 改为 `/api/stream`
- 修复请求数据格式：将 `message` 字段改为 `messages` 数组，匹配后端 `StreamRequest` 模型
- 清理 `ChatPage.js` 中不必要的状态变量传递，简化代码结构

## 2025-01-07 17:40 - Eric ZZ
- 修复前端未传递agent配置参数问题：在 `useChatAPI.js` 中添加 `selectedAgent` 配置传递
- 完善请求体参数：添加 `system_context`、`available_workflows`、`llm_model_config`、`system_prefix`、`available_tools` 等字段
- 确保前端根据选择的agent配置正确传递参数给后端，解决后端接收到默认值的问题

## 2025-01-17 15:30:00
- 修复stopGeneration后页面消失的问题
- 在useEffect中添加messages.length === 0条件，避免在停止生成后误清空有内容的对话
- 解决用户反馈的"消息回复完成后页面消失"问题
- 修改文件：ChatPage.js

## 2025-01-17 01:45:00 - 最终修复"Request was aborted"问题
- 修复useEffect中selectedConversation变化时的清空逻辑，避免在发送消息过程中误触发abort
- 添加isLoading状态检查，只有在非加载状态时才清空对话
- 彻底解决了发送消息时出现"Request was aborted"错误的问题
- 修改文件：ChatPage.js

## 2025-01-07 15:47
彻底修复useEffect无限循环问题：重构清空对话逻辑，只在没有选中对话但有会话ID时清空状态，并优化依赖数组避免循环触发。消息显示和保存功能现已正常工作。

## 2025-01-07 15:40
修复会话清空逻辑问题：在useEffect中添加currentSessionId检查条件，避免在有会话ID时错误清空对话。

## 2025-01-07 12:15:30
- 实现工作空间和任务管理器的实时同步更新
- 在message id变更时自动更新工作空间文件和任务状态
- 点击工作空间和任务管理器按钮时同步更新所有数据

## 2025-01-07 12:01:26
- 优化前端工作空间功能和任务执行结果显示
- 支持结构化JSON数据展示，提升用户体验
- 修复点击工作空间和任务管理器按钮导致对话流中断的问题
- 使用useCallback优化事件处理函数，防止不必要的重新渲染

## 2025-01-16 22:30
**修复前端分块消息处理不当导致422错误**
- 问题描述：后端大JSON响应分块发送时，前端未能正确处理chunk_end和json_chunk消息，导致消息缺少role字段，进而引发422验证错误
- 修复内容：重构前端分块消息处理逻辑，确保正确重组JSON数据并在chunk_end时提取必要字段
- 修改文件：ChatPage.js

## 2025-01-16 23:15
**完善分块消息处理和后端模型验证**
- 问题描述：前端缺少chunk_start处理，后端ChatMessage模型role和content字段过于严格导致分块控制消息验证失败
- 修复内容：1)前端添加chunk_start消息处理；2)后端ChatMessage模型role和content字段改为可选，支持分块控制消息
- 修改文件：ChatPage.js, server.py

## 2025-01-16 23:25
**修复Agent配置页面导航切换问题**
- 问题描述：在Agent编辑详情页面时，点击左侧导航栏无法切换到其他页面
- 修复内容：修改页面切换逻辑，导航切换时重置currentView状态为'list'并清除编辑状态
- 修改文件：App.js

## 2025-01-16 23:30
**修复聊天页面Markdown表格显示问题**
- 问题描述：聊天页面无法正确显示Markdown表格格式
- 修复内容：安装remark-gfm插件支持GitHub Flavored Markdown，在ReactMarkdown组件中添加remarkGfm插件配置
- 修改文件：package.json, ChatPage.js

## 2025-01-17 00:07:15 - 彻底修复"Request was aborted"问题
- 修复App.js中onNewChat函数的调用顺序，避免双重abort
- 修改ChatPage.js中useEffect监听selectedConversation变化时的abort逻辑
- 修改startNewConversation函数中的abort调用，只在有正在进行的请求时才中断
- 优化AbortController的创建和清理逻辑
- 修改文件：App.js, ChatPage.js

## 2025-01-05 17:38 - 实现默认助手只读模式

**修改内容：**
- 将默认助手设置为不可编辑，只可查看
- 修复模型显示与实际保存一致，空值时显示默认值deepseek-chat
- 为默认助手添加指定的工具列表
- 在编辑面板中禁用所有输入字段、按钮和操作

**修改者：** Eric ZZ

## 2025-01-05 17:23 - 修复对话记录页面滚动功能

**修改内容：**
- 为对话卡片添加 `flex-shrink: 0` 和 `min-height: 120px`，防止被flex布局压缩
- 修复对话列表滚动问题，现在内容超出容器时可以正常上下滚动
- 对话卡片保持固定最小高度，不再被挤压变形
- 滚动区域从481px高度显示1022px内容，滚动功能正常

**修改者：** Eric ZZ

## 2025-01-05 17:19 - 全面优化对话记录页面响应式布局

**修改内容：**
- 重构页面布局为flex容器，确保在不同屏幕高度下正确显示
- 添加 `.conversations-container` 包装器，使用flex布局自动分配剩余空间
- 移除固定高度限制，改为基于视口高度的动态计算
- 添加响应式媒体查询，优化小屏幕设备的显示效果
- 对话卡片内边距根据屏幕高度自适应调整
- 页面头部间距在小屏幕上自动减少，为对话列表留出更多空间

**修改者：** Eric ZZ

## 2025-01-05 16:30 - 修复对话记录页面滚动和删除功能

**问题描述：**
- 对话记录页面只显示4个记录且无法滚动查看更多
- 批量删除功能只能删除一个记录

**解决方案：**
- 移除App.css中body的overflow: hidden限制，允许页面滚动
- 修改main-content的overflow为overflow-y: auto，支持垂直滚动
- 修复deleteConversation函数使用函数式状态更新，避免批量删除时的竞态条件
- 确保批量删除操作能正确删除所有选中的对话记录

**修复效果：**
- 对话记录页面现在可以正常滚动查看所有记录
- 批量删除功能正常工作，可以同时删除多个选中的对话
- 删除操作后对话数量和消息数量统计正确更新

## 2024-12-20
- 修复分块消息重复处理问题：添加chunk_index去重检查，避免重复添加相同分块，解决收到30块数据而非预期15块的问题。修改文件：useMessages.js
- 修复分块消息排序问题：修复分块数据按接收顺序拼接导致的JSON解析错误，改为按chunk_index排序后拼接，确保数据正确顺序，移除冗余的chunk_data字段，优化内存使用。修改文件：useMessages.js
- 优化日志输出：移除普通消息处理的冗余日志，只保留分块消息的调试日志，简化前端日志输出，提高性能和可读性。修改文件：useChatAPI.js、useMessages.js、ChatPage.js
- 修复分块消息message_id缺失问题：后端json_chunk消息中添加message_id字段，解决前端分组失败问题，修复前端无法正确识别和合并分块消息的根本原因。修改文件：server.py
- 增加分块消息调试日志：在useChatAPI.js中添加WebSocket流数据读取的详细日志，在useMessages.js中为handleMessage和handleChunkMessage添加调试信息，在ChatPage.js中为消息发送流程添加完整的日志跟踪，使用emoji标识不同类型的日志便于快速识别问题。修改文件：useChatAPI.js、useMessages.js、ChatPage.js
- 修复分块消息处理逻辑：修复handleChunkMessage函数中chunk_id处理逻辑错误，使用message_id作为分组标识符确保所有chunk正确合并，添加详细调试日志便于排查问题，修复chunk_end时直接调用handleMessage而非手动添加到messages，添加容错处理防止chunk丢失导致异常。修改文件：useMessages.js
- 修复工具气泡点击报错问题：解决React渲染对象导致的"Objects are not valid as a React child"错误
- 优化工具详情面板结果显示：添加类型检查，确保对象正确序列化为JSON字符串
- 重构消息渲染逻辑：使用useMemo优化性能，避免在渲染过程中的副作用和状态更新警告

## 2024-12-19
- 从Create React App迁移到Vite构建工具
- 更新package.json依赖和构建脚本
- 创建vite.config.js配置文件，包含开发服务器、代理和构建设置
- 调整项目结构：重命名src/index.js为src/main.jsx，更新index.html
- 修复StorageService.js导出问题，改为默认导出
- 配置esbuild支持JSX语法解析
- 修改前端端口为23233，后端API代理端口为23232
- 修复工具集页面卡片显示问题：统一卡片高度为200px，优化布局使用flex布局，调整描述文本行数限制为2行，确保元数据区域固定在底部
- 优化工具集页面UI：减小卡片尺寸至140px高度，增强边界视觉效果（2px边框+阴影），移除功能描述文本，统一网格布局为固定三列，添加响应式设计支持不同屏幕尺寸
- 更新README.md文档反映Vite相关配置和命令

## 2024-12-19 (下午)
- 重构Agent配置界面：将弹窗模式改为右侧面板模式，提升用户体验
- 修改App.js添加右侧面板条件渲染逻辑和布局调整
- 更新App.css支持右侧面板显示时的主内容区域位移
- 简化AgentConfigPage.js，移除弹窗相关代码，专注于Agent列表展示
- 更新AgentEditPanel组件，添加面包屑导航和返回按钮，优化交互体验

## 2024-12-20 00:02
优化ToolDetail组件层次感：增强边框和阴影效果，添加多层次的毛玻璃效果和内发光，提升视觉层次感和高级感，使弹窗更加精致。

## 2024-12-19 23:58
修改ToolDetail组件样式：将白色背景改为深色渐变背景，统一所有文本颜色为白色，添加毛玻璃效果，与工具列表页面保持一致的视觉风格。

## 2024-12-19 23:55
重构工具详情显示：删除ToolsPage中的弹窗代码，创建独立的ToolDetail组件，提供更好的用户体验和代码组织。

## 2024-12-19 (晚上)
- Agent配置界面全屏模式重构及UI优化
- **App.js**: 将Agent配置界面从右侧面板改为全屏显示模式，修改状态管理逻辑
- **AgentEditPanel.js**: 添加工具选择全选功能，优化用户体验和操作效率
- **AgentEditPanel.css**: 全面重构UI设计，采用现代化气泡样式，包括:
  - 表单组件添加阴影和圆角效果
  - 按钮和输入框的悬停动画效果
  - 工具标签采用圆角气泡设计
  - 工具搜索弹窗优化，添加背景模糊效果
  - 全选功能的自定义复选框样式
  - 修复界面宽度问题，改为真正的自适应布局，移除固定宽度限制 (2024-12-19 22:05)
  - 修复工具搜索弹窗布局问题，添加正确的modal背景和居中定位 (2024-12-19)
- 减少编辑页面留白，优化响应式布局 (2024-12-19)
- 将系统上下文和工作流配置从JSON输入改为键值对输入框形式，提升用户体验 (2024-12-19)
- 修复工具搜索弹窗透明问题，增强背景模糊效果 (2024-12-19)
- 重新设计工具列表为3列卡片布局，添加工具按钮移至左上角，简化工具显示信息 (2024-12-19)
- 进一步优化工具卡片尺寸和显示，缩小卡片高度并简化内容布局 (2024-12-19)
- 减少配置区域间距，优化整体页面布局紧凑性 (2024-12-19)
- 进一步压缩配置区域间距和内容区域padding，提升页面空间利用率 (2024-12-19)
- **功能增强**: 工具选择支持全选/取消全选，提升批量操作效率

## 2024-12-19 15:45
- 进一步压缩配置区域间距和内容区域内边距以提升页面空间利用率
- 将配置区域间距从16px减少到8px，内容区域padding从16px减少到12px并相应调整响应式布局

## 2024-12-19 15:50
- 彻底优化配置区域内部间距，减少section-content、form-group、section-header的padding和margin
- 调整tools-grid的margin-top从12px到6px，switches-grid的margin-bottom从16px到8px

## 2025-01-05 14:20
- 修复对话记录被清空的问题：将App.js中addConversation和updateConversation函数改为函数式状态更新
- 解决React警告：移除ChatPage.js中useEffect内的onClearSelectedConversation调用和setTimeout中的setMessages调用
- 清理调试日志：移除App.js和StorageService.js中的所有调试console.log语句
- 优化状态管理：确保localStorage数据正确保存，对话记录不再丢失

## 2024-12-19 15:55
- 进一步压缩折叠panel间距，将form-section的margin-bottom从8px减少到4px，实现紧密排列

## 2024-12-19 16:00
- 修复panel间距问题：发现AgentConfigPage.css中的样式覆盖了设置，使用更具体的选择器.panel-content .form-section确保4px间距生效
- 关键修复：移除form-section的padding-bottom: 24px，这是导致panel间距过大的真正原因
- 移除section-title的margin底部16px间距，进一步优化panel内部布局

## 2024-12-19 23:45
- 移除 section-title 底部 16px 间距，通过在 AgentEditPanel.css 的 .section-title 样式中添加 margin: 0，覆盖 AgentConfigPage.css 中的设置，进一步优化面板内部布局

## 2024-12-20 00:15
- 重构工作流步骤编辑功能，将原来的逗号分隔输入改为独立步骤列表，每个步骤都有单独的输入框和删除按钮，支持动态添加/删除步骤，提升用户体验和操作便利性

## 2024-12-20 00:25
- 优化可用工具卡片样式：高度压缩至32px单行显示，宽度固定320px可容纳40字符，边框加粗至2px增强视觉边界，字体调整为12px，文字溢出显示省略号，布局改为flex自适应排列

## 2024-12-20 00:35
- 分离工具卡片样式：将AgentEditPanel中的工具卡片样式从tool-card重命名为agent-tool-card，避免与ToolsPage样式冲突，创建独立的agent设置工具样式，边框改为1px，悬停效果更轻量化

## 2024-12-20 00:40
- 优化工具集页面卡片布局：设置tool-card固定宽度范围280-320px，将tools-grid从grid布局改为flex布局，确保工具卡片宽度一致，排列整齐美观

## 2024-12-20 00:45
- 实现工具集页面响应式自适应布局：移除固定宽度限制，使用flex自适应填充空间，添加多个媒体查询断点(1200px/900px/600px)，不同屏幕尺寸下自动调整每行卡片数量，消除右侧空余空间

## 2024-12-19 14:02 - 添加Agent选择的浏览器记录功能

**功能描述：**
- 在浏览器localStorage中记录用户选择的agent
- 页面刷新后自动恢复之前选择的agent
- 如果没有选择过agent，默认选择第一个并记录

**实现内容：**
- 修改selectedAgent初始化逻辑，从localStorage恢复选择
- 添加useEffect监听selectedAgent变化并保存到localStorage
- 确保agent列表变化时正确处理保存的选择

## 2024-12-19 14:01 - 修复发送按钮无反应和移除冲突按钮

**问题描述：**
- 发送按钮点击无反应
- 右上角新对话按钮与左侧导航栏功能冲突

**解决方案：**
- 添加 useEffect 确保 agents 变化时正确设置 selectedAgent
- 移除右上角的新对话按钮，避免与左侧导航栏冲突

## 2024-12-19 13:57 - 修复输入框回车键无反应问题
 
**问题描述：**
- 用户在输入框输入内容后按回车键没有反应
 
**解决方案：**
- 将 `textarea` 的 `onKeyPress` 事件改为 `onKeyDown` 事件，因为 `onKeyPress` 在 React 中已被废弃

## 2024-12-19 14:10 - 增强对话自动保存机制

**功能描述：**
- 每次服务器回复完消息后，自动保存该session id的历史记录
- 确保所有请求和响应都会被及时保存，防止数据丢失
- 在流式响应结束和请求异常时都进行保存操作

**实现内容：**
- 在`stream_end`处理逻辑中添加最终保存操作
- 在`finally`块中添加保存逻辑，确保异常情况下也能保存
- 保证每次对话交互都会更新历史记录的时间戳
- 提升数据持久化的可靠性

## 2024-12-19 14:00 - 实现新会话保存功能

**功能描述：**
- 点击"新会话"按钮时，如果当前页面存在session id，自动将当前会话保存到历史对话中
- 清空当前页面状态，等待用户新的输入并生成新的session id
- 所有对话记录通过session id进行统一管理

**实现内容：**
- 修改`ChatPage.js`中的`startNewConversation`函数，增加会话保存逻辑
- 统一`sendMessage`和`startNewConversation`中的对话记录格式
- 优化`App.js`中的`addConversation`函数，避免重复添加相同会话
- 支持基于session id的重复检测和更新机制

## 2025-01-05

### 添加工具弹窗完整重构
- 弹窗背景改为完全不透明，增强边框显示效果（3px主色调边框+阴影）
- 重构工具列表为表格布局：添加"选择"、"工具名称"、"类型"、"描述"表头，增加横竖分割线
- 优化全选功能：改为按钮样式，支持悬停和选中状态视觉反馈
- 新增确认添加按钮：底部操作区域包含"取消"和"确认添加"按钮，显示选中工具数量
- 完善交互逻辑：点击工具项选中/取消选中，复选框阻止事件冒泡，禁用状态样式
- 提升用户体验：清晰的表格结构、明确的操作流程、直观的选中状态反馈
- 修复 selectedTools 未定义错误：添加状态变量定义和 handleToolSelect 函数
## 2024-07-30
- 修复前端 SSL 代理错误：在 `vite.config.js` 中添加 `ws: false` 和 `timeout: 30000` 配置，并设置 `Connection: keep-alive` 头部，以避免协议混乱导致的 SSL 错误。
- 修复 `QuotaExceededError`：在 `StorageService.js` 的 `saveConversation` 方法中增加了对话数量限制，防止超出浏览器本地存储配额。