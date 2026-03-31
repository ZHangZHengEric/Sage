---
layout: default
title: OAuth2 对接指南（Lage）
nav_order: 10
description: "Sage Server 作为 OAuth2 授权服务器对接 Lage 的接入说明"
lang: zh
ref: oauth2-lage-integration
---

{% include lang_switcher.html %}


{: .note }
> 本文档以 `lage` 为示例，说明 Sage Server 作为 OAuth2 授权服务器时的对接方式。当前推荐使用授权码模式（Authorization Code）并配合 `refresh_token`。

# OAuth2 对接指南（Lage）

## 适用场景

当 `lage` 需要复用 Sage 的登录能力时，Sage 可以作为 OAuth2 授权服务器，对外提供标准的：

- 授权端点 `authorize`
- 令牌端点 `token`
- 用户信息端点 `userinfo`
- 授权服务器元数据端点

`lage` 作为 OAuth2 Client，只需要按标准授权码流程接入即可。

## 推荐接口路径

假设 Sage Server 对外地址为：

```text
https://sage.example.com
```

推荐使用以下标准路径：

- 授权服务器元数据：`GET https://sage.example.com/.well-known/oauth-authorization-server`
- 授权端点：`GET https://sage.example.com/oauth2/authorize`
- 令牌端点：`POST https://sage.example.com/oauth2/token`
- 用户信息端点：`GET https://sage.example.com/oauth2/userinfo`

说明：

- Sage 仍保留了旧兼容路径 `/api/oauth2/*`，但新接入建议直接使用 `/oauth2/*`
- Sage 内部自己的登录与上游身份接入走 `/api/auth/*`
- 即使 Sage 自己还接了上游 OIDC，`lage` 侧也不需要感知，仍然只面对 Sage 的 OAuth2 接口

## 1. 服务端准备

### 1.1 配置 `lage` client

Sage Server 通过环境变量 `SAGE_OAUTH2_CLIENTS` 预注册 OAuth2 Client。推荐给 `lage` 配置一个 confidential client：

```json
[
  {
    "client_id": "lage",
    "name": "Lage",
    "description": "Lage Web OAuth2 Login",
    "client_secret": "replace-with-a-strong-secret",
    "redirect_uris": [
      "https://lage.example.com/oauth/callback"
    ],
    "grant_types": [
      "authorization_code",
      "refresh_token"
    ],
    "response_types": [
      "code"
    ],
    "scope": "openid profile email",
    "token_endpoint_auth_method": "client_secret_basic",
    "skip_consent": true,
    "enabled": true
  }
]
```

建议：

- `client_id` 固定为 `lage`
- `token_endpoint_auth_method` 推荐 `client_secret_basic`
- `redirect_uris` 必须是 `lage` 实际回调地址，且需要和 Sage 端配置完全一致
- `scope` 推荐先使用 `openid profile email`
- 如果 `lage` 不能安全保存 `client_secret`，可以改成 public client，并使用 `token_endpoint_auth_method=none` + PKCE

### 1.2 可选配置

如果希望对外暴露固定 issuer，可以配置：

```bash
export SAGE_OAUTH2_ISSUER="https://sage.example.com/oauth2"
```

如果希望调整 access token 有效期，可以配置：

```bash
export SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN=3600
```

### 1.3 启动后校验

启动 Sage Server 后，可以先检查元数据接口：

```bash
curl https://sage.example.com/.well-known/oauth-authorization-server
```

期望返回类似：

```json
{
  "issuer": "https://sage.example.com/oauth2",
  "authorization_endpoint": "https://sage.example.com/oauth2/authorize",
  "token_endpoint": "https://sage.example.com/oauth2/token",
  "userinfo_endpoint": "https://sage.example.com/oauth2/userinfo",
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "response_types_supported": ["code"],
  "scopes_supported": ["openid", "profile", "email"]
}
```

## 2. Lage 侧需要保存的配置

`lage` 侧至少需要以下参数：

- `client_id`: `lage`
- `client_secret`: `replace-with-a-strong-secret`
- `authorization_url`: `https://sage.example.com/oauth2/authorize`
- `token_url`: `https://sage.example.com/oauth2/token`
- `userinfo_url`: `https://sage.example.com/oauth2/userinfo`
- `redirect_uri`: `https://lage.example.com/oauth/callback`
- `scope`: `openid profile email`

如果 `lage` 支持从元数据自动发现，也可以只配置：

- metadata url: `https://sage.example.com/.well-known/oauth-authorization-server`

## 3. 标准授权码流程

### 第一步：跳转到 Sage 授权端点

浏览器跳转到：

```text
GET https://sage.example.com/oauth2/authorize
  ?response_type=code
  &client_id=lage
  &redirect_uri=https%3A%2F%2Flage.example.com%2Foauth%2Fcallback
  &scope=openid%20profile%20email
  &state=lage-random-state
```

如果 `lage` 使用 PKCE，再追加：

```text
&code_challenge=YOUR_CODE_CHALLENGE
&code_challenge_method=S256
```

说明：

- 如果用户当前没有登录 Sage，Sage 会先把浏览器重定向到自己的登录页
- 用户登录成功后，Sage 会自动回到 `/oauth2/authorize` 继续完成授权
- 当前默认 `skip_consent=true` 时，不展示授权确认页，直接签发 code

### 第二步：Sage 回跳到 Lage

成功后，Sage 会把浏览器重定向到：

```text
https://lage.example.com/oauth/callback?code=AUTH_CODE&state=lage-random-state
```

`lage` 需要：

- 校验 `state`
- 取出 `code`
- 由服务端调用 token 接口换取 token

### 第三步：用 code 换 token

推荐 `client_secret_basic`：

```bash
curl -X POST https://sage.example.com/oauth2/token \
  -u "lage:replace-with-a-strong-secret" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=AUTH_CODE" \
  -d "redirect_uri=https://lage.example.com/oauth/callback"
```

如果使用 PKCE，再加上：

```bash
-d "code_verifier=YOUR_CODE_VERIFIER"
```

成功响应示例：

```json
{
  "token_type": "Bearer",
  "access_token": "ACCESS_TOKEN",
  "expires_in": 3600,
  "refresh_token": "REFRESH_TOKEN",
  "scope": "openid profile email"
}
```

### 第四步：读取用户信息

```bash
curl https://sage.example.com/oauth2/userinfo \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

示例响应：

```json
{
  "sub": "user_xxx",
  "iss": "https://sage.example.com/oauth2",
  "preferred_username": "alice",
  "role": "user",
  "name": "Alice",
  "email": "alice@example.com",
  "email_verified": true,
  "picture": "https://sage.example.com/avatar/alice.png"
}
```

字段说明：

- `sub`: Sage 内部用户唯一标识，推荐作为 `lage` 侧稳定用户主键
- `preferred_username`: 用户登录名
- `name`: 展示名称
- `email`: 在请求了 `email` scope 且用户存在邮箱时返回
- `role`: Sage 侧角色，可选用于 `lage` 的授权映射

## 4. Refresh Token 流程

当 access token 过期后，`lage` 可以继续用 refresh token 刷新：

```bash
curl -X POST https://sage.example.com/oauth2/token \
  -u "lage:replace-with-a-strong-secret" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=REFRESH_TOKEN"
```

响应仍然是新的：

- `access_token`
- `refresh_token`
- `expires_in`

说明：

- Sage 当前会轮换 refresh token
- `lage` 收到新的 refresh token 后，应覆盖保存旧值

## 5. Lage 示例配置

下面给一个通用的服务端配置示意。字段名请以 `lage` 实际实现为准，但可以按这个语义映射：

```yaml
oauth2:
  issuer: https://sage.example.com/oauth2
  client_id: lage
  client_secret: replace-with-a-strong-secret
  authorization_url: https://sage.example.com/oauth2/authorize
  token_url: https://sage.example.com/oauth2/token
  userinfo_url: https://sage.example.com/oauth2/userinfo
  redirect_uri: https://lage.example.com/oauth/callback
  scope: openid profile email
```

如果 `lage` 支持自动发现：

```yaml
oauth2:
  metadata_url: https://sage.example.com/.well-known/oauth-authorization-server
  client_id: lage
  client_secret: replace-with-a-strong-secret
  redirect_uri: https://lage.example.com/oauth/callback
  scope: openid profile email
```

## 6. PKCE 场景

如果 `lage` 是纯前端应用、桌面端应用，或者不能安全保存 `client_secret`，建议改成 public client：

```json
{
  "client_id": "lage",
  "name": "Lage",
  "redirect_uris": ["https://lage.example.com/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "scope": "openid profile email",
  "token_endpoint_auth_method": "none",
  "skip_consent": true,
  "enabled": true
}
```

此时要求：

- `/oauth2/authorize` 必须带 `code_challenge`
- `/oauth2/token` 必须带 `code_verifier`

## 7. 常见错误排查

### `invalid_request: redirect_uri is invalid`

原因：

- `lage` 请求里的 `redirect_uri` 和 `SAGE_OAUTH2_CLIENTS` 中配置的不完全一致

检查项：

- 协议是否一致
- 域名是否一致
- 路径是否一致
- 是否多了 `/`

### `invalid_client`

原因：

- `client_id` 不存在
- `client_secret` 错误
- `client_secret_basic` / `client_secret_post` 使用方式和 Sage 配置不一致

### `invalid_grant: invalid authorization code`

原因：

- code 已使用
- code 已过期
- code 和 `client_id` 不匹配
- token 请求时带的 `redirect_uri` 和 authorize 时不一致

### `invalid_grant: code_verifier mismatch`

原因：

- PKCE 的 `code_verifier` 与最初生成 `code_challenge` 的原文不一致

### `invalid_scope`

原因：

- `lage` 请求了 Sage client 未授权的 scope

## 8. 对接建议

- 如果 `lage` 是服务端应用，优先使用 confidential client + `client_secret_basic`
- 如果 `lage` 是浏览器或桌面应用，优先使用 public client + PKCE
- `lage` 本地应以 `sub` 作为稳定用户 ID，不建议只依赖 `preferred_username`
- 新接入统一使用 `/oauth2/*` 和 `/.well-known/oauth-authorization-server`
- Sage 自己内部登录相关接口统一使用 `/api/auth/*`

## 9. 当前实现边界

当前 Sage OAuth2 Provider 的实现特点如下：

- 已支持 `authorization_code`
- 已支持 `refresh_token`
- 已支持 `userinfo`
- 已支持 metadata discovery
- 当前默认预注册 client，不支持动态 client registration
- 当前默认 `skip_consent=true` 时不展示单独的授权确认页

如果后续 `lage` 需要：

- 动态注册 client
- 更细粒度 scope
- 单独 consent 页面
- ID Token / 完整 OIDC

可以在现有基础上继续扩展。
