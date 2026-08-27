import importlib.util
import inspect

from app.server import routers
from common.core import config
from common.schemas.agent import AgentConfigDTO
from common.schemas.chat import StreamRequest


def test_server_knowledge_base_modules_are_removed():
    removed_modules = (
        "app.server.routers.kdb",
        "common.services.knowledge_base.kdb",
        "common.models.file",
        "common.models.kdb",
        "common.core.client.embed",
        "common.core.client.es",
        "sagents.llm.embedding",
    )

    for module_name in removed_modules:
        assert importlib.util.find_spec(module_name) is None


def test_server_contracts_do_not_expose_knowledge_base_or_embedding_settings():
    startup_config = config.StartupConfig()

    for field_name in (
        "embed_api_key",
        "embed_base_url",
        "embed_model",
        "embed_dims",
        "es_url",
        "es_api_key",
        "es_username",
        "es_password",
    ):
        assert not hasattr(startup_config, field_name)

    assert "availableKnowledgeBases" not in AgentConfigDTO.model_fields
    assert "available_knowledge_bases" not in StreamRequest.model_fields
    assert not hasattr(config.ENV, "KB_MCP_URL")
    assert not hasattr(config.ENV, "KB_MCP_API_KEY")

    from sagents import llm

    assert not hasattr(llm, "OpenAIEmbedding")


def test_server_router_registry_does_not_register_knowledge_base():
    source = inspect.getsource(routers.register_routes)

    assert "kdb" not in source.lower()
    assert "knowledge-base" not in source
