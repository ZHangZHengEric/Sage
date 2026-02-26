from typing import Optional

import jwt

from . import config
from .exceptions import SageHTTPException


def parse_access_token(token: str) -> Optional[dict]:
    cfg = config.get_startup_config()
    try:
        claims = jwt.decode(token, cfg.jwt_key, algorithms=["HS256"])
        return claims
    except jwt.ExpiredSignatureError:
        raise SageHTTPException(
            status_code=401, detail="登录过期", error_detail="token expired"
        )
    except Exception:
        raise SageHTTPException(
            status_code=401, detail="Token非法", error_detail="invalid token"
        )


def parse_refresh_token(token: str) -> Optional[dict]:
    cfg = config.get_startup_config()
    try:
        claims = jwt.decode(token, cfg.refresh_token_secret, algorithms=["HS256"])
        return claims
    except Exception:
        raise SageHTTPException(
            status_code=401, detail="Token非法", error_detail="invalid refresh token"
        )
