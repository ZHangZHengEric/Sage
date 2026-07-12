import asyncio
from types import SimpleNamespace

from sagents.tool.impl.image_understanding_tool import ImageUnderstandingTool


class FakeSessionContext:
    def __init__(self):
        self.pending = []

    def enqueue_user_injection(self, content, guidance_id=None, extra_metadata=None):
        self.pending.append(
            {
                "content": content,
                "guidance_id": guidance_id,
                "metadata": extra_metadata or {},
            }
        )
        return "guidance-1"


class FakeSession:
    def __init__(self, supports_multimodal=True, context=None):
        self.model = SimpleNamespace(supports_multimodal=supports_multimodal)
        self.model_config = {"supports_multimodal": supports_multimodal}
        self.context = context if context is not None else FakeSessionContext()

    def get_context(self):
        return self.context


class FakeSessionManager:
    def __init__(self, session):
        self.session = session

    def get(self, session_id):
        return self.session


def install_fake_session(monkeypatch, session):
    import sagents.session_runtime as session_runtime

    monkeypatch.setattr(
        session_runtime,
        "get_global_session_manager",
        lambda: FakeSessionManager(session),
    )


def test_analyze_image_injects_remote_url_without_extra_llm_call(monkeypatch):
    session = FakeSession(supports_multimodal=True)
    context = session.get_context()
    install_fake_session(monkeypatch, session)
    tool = ImageUnderstandingTool()

    async def fail_fetch(*args, **kwargs):
        raise AssertionError("remote URL should be injected directly, not downloaded")

    async def fail_llm(*args, **kwargs):
        raise AssertionError("native multimodal mode should not make an extra LLM call")

    monkeypatch.setattr(tool, "_fetch_url_image_to_base64", fail_fetch)
    monkeypatch.setattr(tool, "_call_llm_with_image", fail_llm)

    result = asyncio.run(
        tool.analyze_image(
            image_path="https://example.com/cat.png",
            session_id="sess-1",
            prompt="描述图片里的文字",
        )
    )

    assert result["status"] == "success"
    assert result["data"]["mode"] == "native_multimodal_context"
    assert result["data"]["image_format"] == "remote_url"
    assert len(context.pending) == 1

    content = context.pending[0]["content"]
    assert content[0]["type"] == "text"
    assert "工具注入的图片上下文" in content[0]["text"]
    assert "描述图片里的文字" in content[0]["text"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/cat.png"},
    }
    assert context.pending[0]["metadata"]["tool_source"] == "analyze_image"
    assert context.pending[0]["metadata"]["hidden_from_chat"] is True
    assert context.pending[0]["metadata"]["sse_visible"] is False
    assert context.pending[0]["metadata"]["llm_scope"] == "durable"


def test_analyze_image_rejects_text_only_model_before_image_processing(monkeypatch):
    session = FakeSession(supports_multimodal=False)
    context = session.get_context()
    install_fake_session(monkeypatch, session)
    tool = ImageUnderstandingTool()

    async def fail_encode(*args, **kwargs):
        raise AssertionError("text-only model should fail before encoding image")

    monkeypatch.setattr(tool, "_build_native_image_content", fail_encode)

    result = asyncio.run(
        tool.analyze_image(
            image_path="https://example.com/cat.png",
            session_id="sess-1",
        )
    )

    assert result["status"] == "error"
    assert "不支持图片输入" in result["message"]
    assert context.pending == []


def test_analyze_image_encodes_local_image_for_native_context(monkeypatch):
    session = FakeSession(supports_multimodal=True)
    context = session.get_context()
    install_fake_session(monkeypatch, session)
    tool = ImageUnderstandingTool()

    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: object())

    async def fake_encode(sandbox, image_path):
        return "abc123", "image/jpeg"

    monkeypatch.setattr(tool, "_encode_image_to_base64", fake_encode)

    result = asyncio.run(
        tool.analyze_image(
            image_path="/tmp/screenshot.png",
            session_id="sess-1",
        )
    )

    assert result["status"] == "success"
    assert result["data"]["image_format"] == "image/jpeg"
    content = context.pending[0]["content"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,abc123"},
    }


def test_analyze_image_errors_when_live_session_has_no_context(monkeypatch):
    session = FakeSession(supports_multimodal=True, context=None)
    session.get_context = lambda: None
    install_fake_session(monkeypatch, session)

    result = asyncio.run(
        ImageUnderstandingTool().analyze_image(
            image_path="https://example.com/cat.png",
            session_id="sess-1",
        )
    )

    assert result["status"] == "error"
    assert "会话上下文未初始化" in result["message"]


def test_analyze_image_tool_description_says_no_extra_model_call():
    spec = ImageUnderstandingTool.analyze_image._tool_spec

    assert "不会额外发起一次模型分析请求" in spec.description_i18n["zh"]
    assert "does not make an extra model analysis call" in spec.description_i18n["en"]
