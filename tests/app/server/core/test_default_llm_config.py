from common.core import config


def test_server_does_not_configure_default_llm_without_explicit_api_key(monkeypatch):
    monkeypatch.delenv(config.ENV.DEFAULT_LLM_API_KEY, raising=False)

    cfg = config.build_startup_config("server")

    assert cfg.default_llm_api_key == ""


def test_server_ignores_explicit_default_llm_api_key(monkeypatch):
    monkeypatch.setenv(config.ENV.DEFAULT_LLM_API_KEY, "server-global-key")

    cfg = config.build_startup_config("server")

    assert cfg.default_llm_api_key == ""
