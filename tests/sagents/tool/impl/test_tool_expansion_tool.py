import asyncio
from types import SimpleNamespace

from sagents.tool.impl.tool_expansion_tool import ToolExpansionTool


class _AllowedToolManager:
    def __init__(self, names):
        self._names = list(names)

    def list_all_tools_name(self):
        return list(self._names)


def _ctx(allowed, suggested):
    return SimpleNamespace(
        tool_manager=_AllowedToolManager(allowed),
        audit_status={"suggested_tools": list(suggested)},
    )


def _patch_ctx(monkeypatch, ctx):
    import sagents.utils.agent_session_helper as helper

    monkeypatch.setattr(helper, "get_live_session_context", lambda *args, **kwargs: ctx)


def test_expands_tool_within_current_agent_allowed_boundary(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "beta_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools(["beta_tool"], session_id="s1")
    )

    assert out["success"] is True
    assert out["expanded_tools"] == ["beta_tool"]
    assert out["invalid_tools"] == []
    assert out["already_selected_tools"] == []
    assert out["available_expandable_tools"] == []
    assert ctx.audit_status["suggested_tools"] == ["alpha_tool", "beta_tool"]
    assert ctx.audit_status["tools_expanded"] is True


def test_invalid_tool_name_returns_available_expandable_tools(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "beta_tool", "gamma_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools(["missing_tool"], session_id="s1")
    )

    assert out["success"] is False
    assert out["expanded_tools"] == []
    assert out["invalid_tools"] == ["missing_tool"]
    assert out["already_selected_tools"] == []
    assert out["available_expandable_tools"] == ["beta_tool", "gamma_tool"]
    assert ctx.audit_status["suggested_tools"] == ["alpha_tool"]
    assert "tools_expanded" not in ctx.audit_status


def test_rejects_tool_outside_current_agent_allowed_boundary(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools(["beta_tool"], session_id="s1")
    )

    assert out["success"] is False
    assert out["expanded_tools"] == []
    assert out["invalid_tools"] == ["beta_tool"]
    assert out["available_expandable_tools"] == []
    assert ctx.audit_status["suggested_tools"] == ["alpha_tool"]
    assert "tools_expanded" not in ctx.audit_status


def test_reports_already_selected_tool_without_setting_refresh(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools(["alpha_tool"], session_id="s1")
    )

    assert out["success"] is False
    assert out["already_selected_tools"] == ["alpha_tool"]
    assert out["available_expandable_tools"] == []
    assert ctx.audit_status["suggested_tools"] == ["alpha_tool"]
    assert "tools_expanded" not in ctx.audit_status


def test_accepts_single_string_tool_name(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "beta_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools("beta_tool", session_id="s1")  # pyright: ignore[reportArgumentType]
    )

    assert out["success"] is True
    assert out["expanded_tools"] == ["beta_tool"]


def test_mixed_valid_invalid_and_already_selected_names(monkeypatch):
    ctx = _ctx(
        allowed=["alpha_tool", "beta_tool", "gamma_tool", "tool_expand_tools"],
        suggested=["alpha_tool"],
    )
    _patch_ctx(monkeypatch, ctx)

    out = asyncio.run(
        ToolExpansionTool().tool_expand_tools(
            ["alpha_tool", "beta_tool", "missing_tool"],
            session_id="s1",
        )
    )

    assert out["success"] is True
    assert out["expanded_tools"] == ["beta_tool"]
    assert out["invalid_tools"] == ["missing_tool"]
    assert out["already_selected_tools"] == ["alpha_tool"]
    assert out["available_expandable_tools"] == ["gamma_tool"]
    assert ctx.audit_status["suggested_tools"] == ["alpha_tool", "beta_tool"]
    assert ctx.audit_status["tools_expanded"] is True
