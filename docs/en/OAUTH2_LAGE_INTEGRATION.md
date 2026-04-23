---
layout: default
title: OAuth2 Lage Integration Guide
nav_order: 11
description: "How to connect Lage to Sage Server as an OAuth2 authorization server"
lang: en
ref: oauth2-lage-integration
---

{% include lang_switcher.html %}

{: .note }
> This guide uses `lage` as the example client. Sage Server acts as an OAuth2 authorization server and exposes the standard authorization code flow with `refresh_token` support.

# OAuth2 Lage Integration Guide

## Scope

When `lage` needs to reuse Sage sign-in, Sage can act as an OAuth2 authorization server and expose:

- authorization endpoint
- token endpoint
- userinfo endpoint
- authorization server metadata

`lage` only needs to follow the standard authorization code flow.

## Recommended Endpoints

Assuming Sage Server is exposed at:

```text
https://sage.example.com
```

Use these paths:

- metadata: `GET https://sage.example.com/.well-known/oauth-authorization-server`
- authorization: `GET https://sage.example.com/oauth2/authorize`
- token: `POST https://sage.example.com/oauth2/token`
- userinfo: `GET https://sage.example.com/oauth2/userinfo`

Notes:

- Sage still keeps legacy compatibility routes under `/api/oauth2/*`, but new integrations should use `/oauth2/*`
- Sage’s own login and upstream identity integration still use `/api/auth/*`
- If Sage also sits behind an upstream OIDC provider, `lage` does not need to know; it still talks only to Sage’s OAuth2 endpoints

## 1. Server Setup

### 1.1 Register the `lage` client

Register the client through `SAGE_OAUTH2_CLIENTS`:

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

Recommended defaults:

- keep `client_id` as `lage`
- use `client_secret_basic` when the secret can be stored safely
- make sure `redirect_uris` exactly match the client callback URL
- start with `openid profile email`
- if `lage` cannot store a secret safely, use PKCE with a public client

### 1.2 Optional settings

```bash
export SAGE_OAUTH2_ISSUER="https://sage.example.com/oauth2"
export SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN=3600
```

### 1.3 Validate the metadata endpoint

```bash
curl https://sage.example.com/.well-known/oauth-authorization-server
```

Expected fields include:

- issuer
- authorization_endpoint
- token_endpoint
- userinfo_endpoint
- grant_types_supported
- response_types_supported
- scopes_supported

## 2. Client-Side Configuration

`lage` needs at least:

- `client_id`
- `client_secret`
- `authorization_url`
- `token_url`
- `userinfo_url`
- `redirect_uri`
- `scope`

If metadata discovery is supported, the metadata URL can be used directly.

## 3. Authorization Code Flow

### Step 1: Redirect to authorization

```text
GET https://sage.example.com/oauth2/authorize
  ?response_type=code
  &client_id=lage
  &redirect_uri=https%3A%2F%2Flage.example.com%2Foauth%2Fcallback
  &scope=openid%20profile%20email
  &state=lage-random-state
```

If PKCE is enabled, add:

```text
&code_challenge=YOUR_CODE_CHALLENGE
&code_challenge_method=S256
```

### Step 2: Callback to Lage

After login, Sage redirects to the callback with `code` and `state`.

### Step 3: Exchange code for token

```bash
curl -X POST https://sage.example.com/oauth2/token \
  -u "lage:replace-with-a-strong-secret" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=AUTH_CODE" \
  -d "redirect_uri=https://lage.example.com/oauth/callback"
```

Add `code_verifier` when using PKCE.

### Step 4: Read user info

```bash
curl https://sage.example.com/oauth2/userinfo \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

## 4. Security Notes

- Prefer HTTPS everywhere.
- Keep the client secret on the server side only.
- Use PKCE whenever the client cannot protect a secret.
- Keep redirect URIs exact and bounded.

## 5. Common Failure Points

- metadata endpoint unreachable
- redirect URI mismatch
- client secret mismatch
- authorization code expired
- token request missing PKCE verifier
- user has not logged in to Sage yet

