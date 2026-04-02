from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from common.models.user import UserDao
from common.services.oauth.provider import (
    OAuth2ProtocolError,
    authenticate_access_token,
    authenticate_token_endpoint_client,
    build_authorization_context,
    build_authorization_error_redirect,
    build_authorization_success_redirect,
    build_oauth2_error_body,
    build_oauth2_metadata,
    build_userinfo_payload,
    build_web_login_redirect_path,
    create_authorization_code,
    exchange_authorization_code_for_token,
    parse_token_endpoint_params,
    refresh_oauth2_access_token,
)

oauth2_router = APIRouter(tags=["OAuth2"])


def _token_success_response(payload: dict) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=payload,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


def _token_error_response(error: OAuth2ProtocolError) -> JSONResponse:
    headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    }
    if error.error == "invalid_client":
        headers["WWW-Authenticate"] = 'Basic realm="sage"'
    if error.error == "invalid_token":
        headers["WWW-Authenticate"] = 'Bearer realm="sage"'
    return JSONResponse(
        status_code=error.status_code,
        content=build_oauth2_error_body(error.error, error.description),
        headers=headers,
    )


@oauth2_router.get("/.well-known/oauth-authorization-server")
async def oauth2_well_known(request: Request):
    return build_oauth2_metadata(request)


@oauth2_router.get("/api/oauth2/metadata")
@oauth2_router.get("/oauth2/metadata")
async def oauth2_metadata(request: Request):
    return build_oauth2_metadata(request)


@oauth2_router.get("/api/oauth2/authorize")
@oauth2_router.get("/oauth2/authorize")
async def oauth2_authorize(request: Request):
    try:
        context = await build_authorization_context(request.query_params)
    except OAuth2ProtocolError as error:
        return JSONResponse(
            status_code=error.status_code,
            content=build_oauth2_error_body(error.error, error.description),
        )

    claims = getattr(request.state, "user_claims", None) or {}
    user_id = str(claims.get("userid") or "").strip()
    if not user_id:
        return RedirectResponse(url=build_web_login_redirect_path(request), status_code=302)

    user = await UserDao().get_by_id(user_id)
    if not user:
        return RedirectResponse(url=build_web_login_redirect_path(request), status_code=302)

    if not context.client.skip_consent:
        error_url = build_authorization_error_redirect(
            context.redirect_uri,
            "access_denied",
            "interactive consent page is not implemented",
            context.state,
        )
        return RedirectResponse(url=error_url, status_code=302)

    code = await create_authorization_code(context, user)
    redirect_url = build_authorization_success_redirect(
        context.redirect_uri,
        code,
        context.state,
    )
    return RedirectResponse(url=redirect_url, status_code=302)


@oauth2_router.post("/api/oauth2/token")
@oauth2_router.post("/oauth2/token")
async def oauth2_token(request: Request):
    try:
        params = await parse_token_endpoint_params(request)
        grant_type = str(params.get("grant_type") or "").strip()
        if not grant_type:
            raise OAuth2ProtocolError("invalid_request", "missing grant_type")

        client, _ = await authenticate_token_endpoint_client(request.headers, params)
        if grant_type == "authorization_code":
            token_payload, _ = await exchange_authorization_code_for_token(client, params)
            return _token_success_response(token_payload)
        if grant_type == "refresh_token":
            token_payload, _ = await refresh_oauth2_access_token(client, params)
            return _token_success_response(token_payload)
        raise OAuth2ProtocolError("unsupported_grant_type", f"unsupported grant_type: {grant_type}")
    except OAuth2ProtocolError as error:
        return _token_error_response(error)


@oauth2_router.api_route("/api/oauth2/userinfo", methods=["GET", "POST"])
@oauth2_router.api_route("/oauth2/userinfo", methods=["GET", "POST"])
async def oauth2_userinfo(request: Request):
    try:
        token, user, _ = await authenticate_access_token(request)
        return build_userinfo_payload(request, user, token)
    except OAuth2ProtocolError as error:
        return _token_error_response(error)
