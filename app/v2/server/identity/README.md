# Server 身份与认证

本目录按 Server 身份领域组织，不是通用插件目录。运行时 Agent 插件、Hindsight 等知识适配器不属于这里。

| 模块 | 职责 |
| --- | --- |
| `users.py` / `repository.py` | 内部用户、角色、执行策略与持久化；不在用户对象中携带密码。账号与可选密码凭据以一个事务创建。 |
| `local.py` / `passwords.py` | 本地密码认证、PBKDF2 哈希与有界线程池；无需参与 JWT 或第三方协议。 |
| `federation.py` | 将已验证的 `(issuer, subject)` 显式绑定到内部 `user_id`，支持无密码账号；不按邮箱或用户名自动合并账号。 |
| `sessions.py` / `jwt.py` | 持久化、可撤销的登录会话，以及带 `sid` 的 JWT；每次认证重新读取内部用户，JWT 中的角色不作为授权依据。 |
| `http.py` | Cookie 名称、浏览器 Origin 与 CSRF 校验；路由负责 HTTP 响应。 |
| `keys.py` / `key_repository.py` / `credentials.py` / `external.py` | 面向 Agent/A2A 的机器 API Key、scope 与授权；与人员登录分开。 |
| `context.py` | 内部用户到请求 Actor/租户上下文的映射。当前默认以用户 ID 隔离资源，尚无组织/成员关系模型。 |
| `orm.py` / `migrations.py` | 数据表与启动时旧账号迁移。 |
| `service.py` | 应用入口，组合认证方式、内部用户与登录会话。 |

## 启动与升级

`ServerHost.start()` 在接受请求之前调用 `create_host_schema()`：补建表、升级用户数据，成功后再初始化管理员和其他服务。MySQL 通过同一数据库的命名锁串行迁移；锁跨越 DDL 的隐式提交。SQLite 测试使用写事务串行迁移。

旧版 `users.password_hash` 自动复制到 `password_credentials`，并按 `strip().casefold()` 生成 SHA-256 用户名查找键，创建唯一索引。用户 ID、角色、执行策略均保留。重复启动不会覆盖新凭据。归一化后存在重名账号时，迁移报错并阻止启动，需先处理冲突，系统不会自行合并或删除用户。

迁移为增量操作：保留旧密码列以支持旧账号回滚；新账号的密码只写新凭据表，因此旧程序不能为升级后新建的账号提供密码登录。MySQL DDL 无法由普通事务整体回滚，部署前应备份数据库；中断后重启会检查已有表和字段并继续。升级时统一更新所有 Server 进程。

旧 JWT 没有 `sid`，升级后必须重新登录。退出会撤销当前会话，其 JWT 即使以 Bearer 重放也会被拒绝；其他登录会话与机器 API Key 不受影响。会话状态保存在数据库，可跨进程校验；这不改变运行时 Scheduler/SessionStore 各自的部署要求。

启动必须配置私有的 `SAGE_SERVER_JWT_SECRET`（至少 32 字节）；不接受内置默认值及模板占位值。首次创建管理员必须设置 `SAGE_SERVER_ADMIN_PASSWORD`，不会提升同名普通用户。已有管理员时不会根据环境变量重置密码。

网页只使用 HttpOnly、SameSite=Lax 的会话 Cookie，不把 JWT 持久化在 localStorage。写请求从可读的 CSRF Cookie 取得 `X-CSRF-Token`，服务端将其与当前登录会话绑定校验；显式 Bearer 调用不需要该头。Cookie 默认 `Secure`，本地 HTTP 开发显式配置 `SAGE_SERVER_COOKIE_SECURE=false`。登录/注册的浏览器 Origin 必须匹配请求来源或 `SAGE_SERVER_PUBLIC_BASE_URL`；Vite 开发时后者填写 Vite 的实际地址。

## 后续接入 SSO

具体 OIDC/SAML 提供商适配器放在本身份模块内，通过专门路由完成跳转和回调。适配器先验证协议凭据，再通过 `identity.external.resolve()` 取得内部用户，最后调用 `identity.issue_token()` 复用同一会话体系。首次开通账号使用 `users.create(build_user_record(...))`，不创建虚构密码；绑定已有账号前必须验证用户身份与绑定授权。

当前没有对外暴露通用 claims 登录或身份绑定接口，也没有配置具体身份提供商。OIDC 适配器仍需验证签名、issuer、audience、有效期、state、nonce，以及使用 PKCE 等协议要求，不能把浏览器提交的用户资料视为已验证身份。身份稳定标识使用 [OIDC 规定的 issuer 与 subject](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability)。数据库锁依据 [MySQL GET_LOCK 文档](https://dev.mysql.com/doc/refman/8.4/en/locking-functions.html)。
