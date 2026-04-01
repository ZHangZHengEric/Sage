# Sage Repository Remediation Status

Last updated: 2026-04-01

## Summary

The original P0 security work is complete. The repository has already closed the highest-risk trust-boundary issues around forged internal identity headers, default bootstrap admin credentials, and production-like default secrets. The auth model has also been narrowed and documented into three supported deployment modes:

- `native`: end users register and log in with Sage username/password
- `oauth`: end users log in through upstream OAuth/OIDC
- `trusted_proxy`: requests from trusted IP/CIDR ranges bypass Sage end-user auth, optional `X-Sage-Internal-UserId` may carry user context, and built-in username/password login remains available for admins only

The next work should focus on runtime stability, startup/shutdown correctness, and engineering reliability.

## Completed Work

### Closed P0 Items

- Hardened `X-Sage-Internal-UserId` handling in [app/server/core/middleware.py](/Users/caoke/Desktop/Huami/Sage/app/server/core/middleware.py)
  - untrusted public requests can no longer forge the header
  - `trusted_proxy` semantics are now explicit and IP/CIDR allowlist-based
- Removed weak default bootstrap admin behavior in [app/server/bootstrap.py](/Users/caoke/Desktop/Huami/Sage/app/server/bootstrap.py)
  - bootstrap admin creation now requires explicit `SAGE_BOOTSTRAP_ADMIN_USERNAME` and `SAGE_BOOTSTRAP_ADMIN_PASSWORD`
  - sensitive values are masked in logs
- Enforced non-default production-like secrets in [app/server/core/config.py](/Users/caoke/Desktop/Huami/Sage/app/server/core/config.py)
  - production and staging reject default JWT, refresh-token, and session secrets
  - secure session cookies are forced in production-like environments

### Auth Mode Consolidation

- Narrowed supported auth modes to `trusted_proxy`, `oauth`, and `native`
- Updated provider exposure logic in [app/server/services/auth/external_oauth.py](/Users/caoke/Desktop/Huami/Sage/app/server/services/auth/external_oauth.py)
- Updated auth router behavior in [app/server/routers/auth.py](/Users/caoke/Desktop/Huami/Sage/app/server/routers/auth.py) and [app/server/routers/user.py](/Users/caoke/Desktop/Huami/Sage/app/server/routers/user.py)
- Updated login UX in [app/server/web/src/components/LoginModal.vue](/Users/caoke/Desktop/Huami/Sage/app/server/web/src/components/LoginModal.vue)
- Synced Chinese and English auth docs

### Tests Added

- Backend regression coverage for:
  - auth mode behavior
  - middleware trust checks
  - bootstrap admin config
  - config security
  - lifecycle fail-fast and shutdown behavior
  - credentialed CORS configuration
- Frontend Vitest coverage for login modal auth-mode rendering

### Closed P1 Items

- Repaired shutdown and startup failure semantics in [app/server/bootstrap.py](/Users/caoke/Desktop/Huami/Sage/app/server/bootstrap.py) and [app/server/lifecycle.py](/Users/caoke/Desktop/Huami/Sage/app/server/lifecycle.py)
  - removed undefined shutdown calls
  - aligned scheduler shutdown with the actual sync API
  - required initializers now fail fast instead of silently returning degraded startup
- Corrected credentialed CORS defaults in [app/server/core/middleware.py](/Users/caoke/Desktop/Huami/Sage/app/server/core/middleware.py) and [app/server/core/config.py](/Users/caoke/Desktop/Huami/Sage/app/server/core/config.py)
  - wildcard origins are no longer used with credentials
  - added `SAGE_CORS_ALLOWED_ORIGINS`
  - preflight `OPTIONS` requests are no longer blocked by auth middleware

## Remaining Issues By Priority

### P2

#### 1. Add CI for backend and frontend verification

Risk:
- the new regression tests still rely on local discipline because there is no dedicated workflow enforcing them on push/PR

Expected work:
- add GitHub Actions workflow for backend pytest
- optionally include the scoped frontend Vitest job
- cache Python and Node dependencies

#### 2. Align version metadata across runtime and packaging

Risk:
- repository version sources still drift between runtime files, docs, and package metadata

Known targets:
- [setup.py](/Users/caoke/Desktop/Huami/Sage/setup.py)
- [README.md](/Users/caoke/Desktop/Huami/Sage/README.md)
- runtime version declarations under `app/server` and desktop code

Expected work:
- choose one version source of truth
- add a consistency check
- remove manual drift points

### P3

#### 3. Deduplicate docs deployment workflows

Risk:
- duplicate docs workflows increase maintenance cost and can diverge further

Known targets:
- [.github/workflows/docs.yml](/Users/caoke/Desktop/Huami/Sage/.github/workflows/docs.yml)
- [.github/workflows/deploy-docs.yml](/Users/caoke/Desktop/Huami/Sage/.github/workflows/deploy-docs.yml)

#### 4. Reconcile dependency and packaging ownership

Risk:
- `setup.py` and `requirements.txt` still appear to serve overlapping purposes with drift

Known targets:
- [setup.py](/Users/caoke/Desktop/Huami/Sage/setup.py)
- [requirements.txt](/Users/caoke/Desktop/Huami/Sage/requirements.txt)
- development docs

Expected work:
- define ownership of installable package metadata vs runtime env vs dev env
- document the supported install paths

## Recommended Next Execution Order

1. Add CI for backend and frontend verification
2. Align version metadata across runtime and packaging
3. Deduplicate docs deployment workflows
4. Reconcile dependency and packaging ownership

## Verification Gate For The Next Phase

At minimum, the next round should be considered complete only after these pass:

```bash
.venv/bin/python -m pytest tests/app/server/core/test_auth_modes.py tests/app/server/core/test_middleware_auth.py tests/app/server/core/test_bootstrap_admin.py tests/app/server/core/test_config_security.py -v
```

```bash
.venv/bin/python -m pytest tests/app/server/core/test_auth_modes.py tests/app/server/core/test_middleware_auth.py tests/app/server/core/test_bootstrap_admin.py tests/app/server/core/test_config_security.py tests/app/server/core/test_lifecycle_runtime.py tests/app/server/core/test_cors_config.py -v
```

If frontend auth behavior changes, rerun:

```bash
source ~/.nvm/nvm.sh && nvm use 20.19.0 >/dev/null && npm test -- --run src/components/__tests__/LoginModal.spec.js
```

## Reference Commits

- `dc70c134` `fix: close P0 auth and bootstrap security gaps`
- `d1bf707f` `feat: narrow enterprise auth modes and add login modal tests`
- `5b5374f1` `refactor: rename built-in auth mode to native`
- `174ad5b5` `feat: refine trusted proxy auth behavior`
