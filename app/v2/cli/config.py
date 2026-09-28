"""V2 CLI configuration without legacy startup state or database setup."""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


def sage_home() -> Path:
    return Path(os.environ.get("SAGE_LOCAL_DATA_ROOT") or Path.home() / ".sage").expanduser().resolve()


def load_environment() -> None:
    load_dotenv(sage_home() / ".sage_env", override=False)
    load_dotenv(".env", override=True)


def get_default_cli_user_id() -> str:
    load_environment()
    return os.environ.get("SAGE_CLI_USER_ID") or os.environ.get("SAGE_DESKTOP_USER_ID") or "default_user"


@dataclass(frozen=True)
class CliConfig:
    default_llm_model_name: str
    default_llm_api_base_url: str


def configure_cli_logging(*, verbose: bool) -> CliConfig:
    load_environment()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO if verbose else logging.ERROR)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="INFO" if verbose else "ERROR", format="{message}")
    return CliConfig(
        default_llm_model_name=os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME", "deepseek-v4-flash"),
        default_llm_api_base_url=os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/"),
    )
