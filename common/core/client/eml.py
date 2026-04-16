from __future__ import annotations

from typing import Optional

from loguru import logger

from common.core import config
from common.core.exceptions import SageHTTPException

EML_CLIENT: Optional["Dm20151123Client"] = None # type: ignore


def _has_eml_credentials(cfg: config.StartupConfig) -> bool:
    return bool((cfg.eml_access_key_id or "").strip() and (cfg.eml_access_key_secret or "").strip())


async def init_eml_client(
    cfg: Optional[config.StartupConfig] = None,
) -> Optional["Dm20151123Client"]: # pyright: ignore[reportUndefinedVariable]
    global EML_CLIENT
    if EML_CLIENT is not None:
        return EML_CLIENT

    try:
        from alibabacloud_dm20151123.client import Client as Dm20151123Client
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError:
        logger.warning("阿里云邮件 SDK 未安装，跳过初始化")
        return None

    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize EML client")

    if not _has_eml_credentials(cfg):
        logger.info("未配置邮件 Access Key，跳过邮件客户端初始化")
        return None

    try:
        access_key_id = (cfg.eml_access_key_id or "").strip()
        access_key_secret = (cfg.eml_access_key_secret or "").strip()
        security_token = (cfg.eml_security_token or "").strip()
        client_config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token,
        )
        client_config.endpoint = cfg.eml_endpoint or "dm.aliyuncs.com"
        EML_CLIENT = Dm20151123Client(client_config)
        logger.debug(f"邮件客户端初始化成功: {client_config.endpoint}")
        return EML_CLIENT
    except Exception as e:
        logger.error(f"邮件客户端初始化失败: {e}")
        return None


def get_eml_client() -> "Dm20151123Client": # type: ignore
    global EML_CLIENT
    if EML_CLIENT is None:
        raise SageHTTPException(detail="邮件客户端未初始化", error_detail="eml client not initialized")
    return EML_CLIENT


async def send_register_verification_mail(to_address: str, code: str) -> None:
    try:
        from alibabacloud_dm20151123 import models as dm_20151123_models
        from alibabacloud_tea_util import models as util_models
    except ImportError as exc:
        raise SageHTTPException(detail="阿里云邮件 SDK 未安装", error_detail=str(exc))

    cfg = config.get_startup_config()
    account_name = (cfg.eml_account_name or "").strip()
    template_id = (cfg.eml_template_id or "").strip()
    subject = (cfg.eml_register_subject or "Sage 安全验证，请确认您的邮箱").strip()

    if not account_name or not template_id:
        raise SageHTTPException(
            detail="邮件服务未配置完整",
            error_detail="missing eml account name or template id",
        )
    if not _has_eml_credentials(cfg):
        raise SageHTTPException(
            detail="邮件服务未配置",
            error_detail="missing eml access key configuration",
        )

    client = EML_CLIENT or await init_eml_client(cfg)
    if client is None:
        raise SageHTTPException(detail="邮件客户端不可用", error_detail="eml client unavailable")

    template = dm_20151123_models.SingleSendMailRequestTemplate(
        template_data={"code": code},
        template_id=template_id,
    )
    mail_request = dm_20151123_models.SingleSendMailRequest(
        template=template,
        account_name=account_name,
        address_type=int(cfg.eml_address_type or 1),
        reply_to_address=bool(cfg.eml_reply_to_address),
        to_address=to_address,
        subject=subject,
    )
    runtime = util_models.RuntimeOptions()

    try:
        await client.single_send_mail_with_options_async(mail_request, runtime)
        logger.info(f"注册验证码邮件发送成功: {to_address}")
    except Exception as error:
        message = getattr(error, "message", "") or str(error)
        recommend = ""
        data = getattr(error, "data", None)
        if isinstance(data, dict):
            recommend = str(data.get("Recommend") or "")
        logger.error(f"注册验证码邮件发送失败: {to_address}, error={message}, recommend={recommend}")
        if "unable to load credentials" in message.lower() or "credentialexception" in message.lower():
            raise SageHTTPException(
                detail="邮件凭据未配置，请在 .env 中设置 SAGE_EML_ACCESS_KEY_ID 和 SAGE_EML_ACCESS_KEY_SECRET",
                error_detail=recommend or message,
            )
        raise SageHTTPException(
            detail="验证码邮件发送失败",
            error_detail=recommend or message,
        )


async def close_eml_client() -> None:
    global EML_CLIENT
    EML_CLIENT = None
    logger.info("邮件客户端已关闭")
