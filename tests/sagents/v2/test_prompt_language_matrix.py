"""Run metadata controls all built-in prompt locales; Tool locales are separate."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sagents.v2.agent.multi_agent.context import AgentRosterContextProvider
from sagents.v2.agent.multi_agent.contracts import AgentMode
from sagents.v2.agent.policy import LLMContinuationJudge
from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
from sagents.v2.context import RunMetadataContextProvider
from sagents.v2.context.contracts import ContextReductionScope
from sagents.v2.context.plugins.summarizer_extractive import (
    ExtractiveConversationSummarizer,
)
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.memory import LLMMemoryRecallQueryGenerator
from sagents.v2.model import (
    ModelEventKind,
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.prompt_i18n import _TEXT, prompt_language
from sagents.v2.skill.context import AvailableSkillsContextProvider
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
from tests.sagents.v2.test_continuation_judge_matrix import _context


LOCALES = [
    (None, "en"),
    ("", "en"),
    ("  ", "en"),
    ("zh", "zh"),
    (" ZH_hant_TW ", "zh"),
    ("zh-CN", "zh"),
    ("en-US", "en"),
    ("pt-BR", "en"),
    ("fr", "en"),
    ("es", "en"),
    ("de", "en"),
    ("ja", "en"),
    ("ko", "en"),
    ("ru", "en"),
    ("zhfake", "en"),
    ("system", "en"),
]


def command(language):
    return StartRun(
        input=(),
        agent_id="a",
        resolved_spec_hash="sha256:a",
        idempotency_key="start",
        config={
            "metadata": {} if language is None else {"response_language": language}
        },
    )


def model_with(*texts):
    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id=f"r{i}", text=text, finish_reason="stop"
                        ),
                    ),
                )
            )
            for i, text in enumerate(texts)
        )
    )


@pytest.mark.parametrize("language,expected", LOCALES)
async def test_runtime_and_auxiliary_requests_share_locale_and_fallback(
    language, expected
):
    assert prompt_language(language) == expected
    segments = await RunMetadataContextProvider().segments(command(language))
    text = "\n".join(segment.content for segment in segments)
    assert (
        "当前回复语言为 zh。" if expected == "zh" else "The response language is en."
    ) in text
    assert _TEXT[expected]["runtime_hint"] in text
    assert _TEXT[expected]["reminder_hint"] in text
    # Judge must normalize regional variants instead of falling back from zh-CN to en.
    judge_model = model_with('{"decision":"completed","reason":"done"}')
    await LLMContinuationJudge(judge_model).decide(_context(language=language or "en"))
    judge_request = judge_model.requests[0]
    assert judge_request.metadata["response_language"] == expected
    judge_text = judge_request.messages[0].content[0].text
    assert (
        "先应用 Todo 硬约束" if expected == "zh" else "Apply the Todo invariant first"
    ) in judge_text
    assert _TEXT[expected]["judge_reference"] in judge_text
    # A per-request locale must override the generator's independent host setting.
    memory_model = model_with('{"query":"project file.py"}')
    await LLMMemoryRecallQueryGenerator(memory_model, language="zh").generate(
        "inspect file.py", run_id="run", language=expected
    )
    assert memory_model.requests[0].metadata["response_language"] == expected
    assert (
        memory_model.requests[0].messages[0].content[0].text
        == _TEXT[expected]["memory_system"]
    )
    assert "inspect file.py" in memory_model.requests[0].messages[1].content[0].text


@pytest.mark.parametrize(
    "language,expected", [("zh-CN", "zh"), ("pt-BR", "en"), ("", "en")]
)
async def test_summary_initial_retry_and_extractive_fallback_share_locale(
    language, expected
):
    payload = {
        "summary": "result",
        **{
            key: []
            for key in (
                "decisions",
                "open_tasks",
                "files_touched",
                "commands_run",
                "important_errors",
                "user_requirements",
            )
        },
    }
    model = model_with("invalid JSON", json.dumps(payload))
    request = SummarizationRequest(
        scope=ContextReductionScope(
            context_key="c", session_id="s", run_id="r", response_language=language
        ),
        messages=(
            ModelMessage(
                role="user", content=(TextBlock(text="keep /project/file.py"),)
            ),
        ),
        previous_summary="old evidence",
        target_tokens=512,
    )
    assert (
        json.loads(await ModelConversationSummarizer(model).summarize(request))
        == payload
    )
    assert len(model.requests) == 2
    for model_request in model.requests:
        assert model_request.metadata["response_language"] == expected
        system = model_request.messages[0].content[0].text
        assert _TEXT[expected]["summary_system"] in system
        assert _TEXT[expected]["summary_language"] in system
        assert "/project/file.py" in model_request.messages[1].content[0].text
    assert (
        _TEXT[expected]["summary_retry"]
        in model.requests[1].messages[0].content[0].text
    )
    value = await ExtractiveConversationSummarizer().summarize(request)
    snapshot = json.loads(value)
    assert snapshot["summary"] == "old evidence"
    assert "/project/file.py" in " ".join(snapshot["user_requirements"])
    assert "Previous summary" not in value



@pytest.mark.parametrize(
    "language,expected", [("zh-TW", "zh"), ("pt", "en"), (None, "en")]
)
async def test_runtime_context_wrappers_use_run_locale_and_preserve_authored_text(
    language, expected
):
    cmd = command(language)
    cmd = cmd.model_copy(update={"invocation_mode": "plan"})
    segments = await RunMetadataContextProvider().segments(cmd)
    assert _TEXT[expected]["plan"] in next(
        s.content for s in segments if s.segment_id == "plan_mode"
    )
    guidance = DefaultAgentStepRequestBuilder._continuation_message(
        "KEEP exact reason", expected
    )
    assert "KEEP exact reason" in guidance.content[0].text
    assert _TEXT[expected]["continuation"].split("\n")[0] in guidance.content[0].text

    class Catalog:
        async def list_skills(self, *, run_id):
            return (
                SimpleNamespace(
                    name="custom_skill", description="KEEP authored description"
                ),
            )

    skills = await AvailableSkillsContextProvider(Catalog()).segments(cmd)
    assert _TEXT[expected]["skills"] in skills[0].content
    assert "KEEP authored description" in skills[0].content
    leaf = await AgentRosterContextProvider(
        None, AgentMode.SIMPLE, allow_delegation=False
    ).segments(cmd, run_id="r")
    assert _TEXT[expected]["leaf"] in leaf[0].content


def test_builtin_catalog_has_exactly_two_complete_locales():
    assert set(_TEXT) == {"en", "zh"}
    assert _TEXT["en"].keys() == _TEXT["zh"].keys()


@pytest.mark.parametrize(
    "language,expected", [(None, "en"), ("zh-CN", "zh"), ("pt-BR", "en")]
)
async def test_engine_overrides_memory_host_locale_per_run(language, expected):
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, setup_loop

    query_model = model_with('{"query":""}')
    generator = LLMMemoryRecallQueryGenerator(query_model, language="zh")
    _, handle, loop, _ = await setup_loop(
        model_with("done"),
        response_language=language,
        automatic_memory_recall=True,
        memory_recall_query_generator=generator,
        actor_context=CONTEXT.model_copy(update={"language": "pt"}),
    )
    await loop.execute(handle.run_id, CONTEXT.model_copy(update={"language": "pt"}))
    assert query_model.requests[0].metadata["response_language"] == expected
    # The shared generator is never mutated by a Run's language choice.
    assert generator.language == "zh"


@pytest.mark.parametrize(
    "language,expected", [("zh-CN", "zh"), ("pt-BR", "en"), (None, "en")]
)
async def test_goal_plan_and_self_configuration_context_follow_run(
    language, expected, tmp_path
):
    from sagents.v2.goal.context import GoalContextProvider
    from sagents.v2.plan.context import PlanContextProvider
    from sagents.v2.i18n import tr
    from tests.sagents.v2.test_self_configuration import service

    class Goals:
        async def get(self, run_id):
            return None

    cmd = command(language).model_copy(update={"invocation_mode": "goal"})
    goal = await GoalContextProvider(Goals()).segments(cmd, run_id="r")
    assert tr("goal.create_instruction", expected) in goal[0].content

    class Plan:
        async def get(self, run_id):
            return SimpleNamespace(content="KEEP approved plan")

    plan = await PlanContextProvider(Plan()).segments(
        cmd.model_copy(update={"invocation_mode": "plan"}), run_id="r"
    )
    assert tr("plan.submitted_instruction", expected) in plan[0].content
    assert "KEEP approved plan" in plan[0].content
    controller = service(tmp_path)
    controller.system_prompt = "KEEP authored instructions"
    config = await controller.segments(cmd)
    assert (
        _TEXT[expected]["self_configuration"].split("{revision}")[0]
        in config[0].content
    )
    assert _TEXT[expected]["self_instructions"] in config[1].content
    assert "KEEP authored instructions" in config[1].content
