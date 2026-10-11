"""V2 CLI configuration without legacy startup state or database setup."""
from dataclasses import dataclass
import logging
import json
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
    use_app_model: bool = False


def app_default_model(user_id: str) -> dict | None:
    """Read the Desktop v2 catalog without importing or starting Desktop services."""
    from app.v2.cli.errors import CLIError

    root = Path(os.environ.get("SAGE_DESKTOP_DATA_ROOT") or Path.home() / "sage").expanduser()
    path = root / "runtime" / "desktop-catalog.json"
    if not path.exists():
        return None
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if catalog.get("format_version") != "sage.desktop-catalog/v2":
            raise ValueError("unsupported catalog format")
        providers = [p for p in catalog["model_providers"] if p["user_id"] == user_id]
        provider = next((p for p in providers if p.get("is_default")), None)
        # Match Desktop's fallback when no explicit default exists.
        if provider is None and providers:
            provider = providers[0]
        if provider is not None and not all(provider.get(k) for k in ("model", "base_url", "api_key")):
            raise ValueError("the selected model is incomplete")
        return provider
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Never include catalog contents or credential-bearing validation details.
        raise CLIError(
            f"Cannot load the APP v2 model configuration from {path}.",
            next_steps=["Check the default model in APP settings, or configure SAGE_DEFAULT_LLM_* explicitly."],
        ) from exc


def configure_cli_logging(*, verbose: bool) -> CliConfig:
    load_environment()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO if verbose else logging.ERROR)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="INFO" if verbose else "ERROR", format="{message}")
    return CliConfig(
        default_llm_model_name=os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME", "deepseek-v4-flash"),
        default_llm_api_base_url=os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/"),
        use_app_model=not any(os.environ.get(key) for key in (
            "SAGE_DEFAULT_LLM_API_BASE_URL", "SAGE_DEFAULT_LLM_API_KEY",
        )),
    )
