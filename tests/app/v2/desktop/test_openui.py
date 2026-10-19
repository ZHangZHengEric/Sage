import json

import pytest

from app.v2.desktop.backend.openui import OpenUiParser, OpenUiStore, openui_blocks
from app.v2.desktop.backend.schemas import DesktopRunRequest, RunMessage
from app.v2.desktop.backend.schemas import ModelProviderPatch
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)

CODE = 'root = Card("Trip", [Input("city", "City", "", true), Button("submit", "Continue")])'


@pytest.mark.asyncio
async def test_official_parser_streams_before_completion_and_isolates_messages():
    parser = OpenUiParser()
    try:
        partial = await parser.parse('root = Text("He', complete=False, stream_id="a")
        other = await parser.parse('root = Text("Wo', complete=False, stream_id="b")
        assert partial["props"]["content"] == "He"
        assert other["props"]["content"] == "Wo"
        assert (
            await parser.parse('root = Text("Hello")', complete=True, stream_id="a")
        )["props"]["content"] == "Hello"
        for bad in [
            'root = Text("Hi',
            'root = Unknown("Hi")',
            "root = Text($secret)",
            'root = Card("X", [Input("a", "A"), Input("a", "B"), Button("ok", "OK")])',
        ]:
            with pytest.raises(ValueError):
                await parser.parse(bad, complete=True)
    finally:
        await parser.close()
    assert parser.process is None


def test_fences_are_not_detected_inside_other_code_blocks():
    assert openui_blocks('````markdown\n```openui\nroot = Text("X")\n```\n````') == []
    blocks = openui_blocks('Before\n```openui\nroot = Text("Hi')
    assert blocks[0]["closed"] is False
    assert blocks[0]["code"] == 'root = Text("Hi'


@pytest.mark.asyncio
async def test_store_revision_owner_validation_and_durable_duplicate_protection(
    tmp_path,
):
    parser = OpenUiParser()
    try:
        tree = await parser.parse(CODE, complete=True)
    finally:
        await parser.close()
    store = OpenUiStore(tmp_path / "ui.sqlite3")
    params = dict(
        owner="owner",
        session="session",
        agent="sage",
        run="source",
        operation="publication",
        key="message:0",
        code=CODE,
        tree=tree,
        fallback="",
    )
    surface = store.publish(**params)
    assert store.publish(**params) == surface
    assert store.get("intruder", "session", surface["surface_id"]) is None
    with pytest.raises(ValueError, match="required"):
        store.claim(surface, "submit", {"city": ""})
    with pytest.raises(ValueError, match="Unknown"):
        store.claim(surface, "execute_shell_command", {"city": "Shanghai"})
    with pytest.raises(ValueError, match="Unknown"):
        store.claim(surface, "submit", {"city": "Shanghai", "hidden": "x"})
    normalized, replay = store.claim(surface, "submit", {"city": "Shanghai"})
    assert normalized == {"city": "Shanghai"} and replay is None
    with pytest.raises(ValueError, match="reconciliation"):
        store.claim(surface, "submit", normalized)
    store.accepted(surface, "action-run")
    restored = OpenUiStore(store.path)
    assert restored.claim(surface, "submit", normalized)[1] == "action-run"
    with pytest.raises(ValueError, match="already"):
        restored.claim(surface, "submit", {"city": "Beijing"})
    replaced = restored.publish(**{**params, "operation": "replacement"})
    assert replaced["revision"] == 2
    with pytest.raises(ValueError, match="replaced"):
        restored.claim(surface, "submit", normalized)


@pytest.mark.asyncio
@pytest.mark.parametrize("ui_preference", ["auto", "interactive"])
async def test_desktop_stream_and_action_replay_use_no_ui_tool(
    tmp_path, monkeypatch, ui_preference
):
    from tests.app.v2.desktop.sdk_fixture import desktop
    text = "Choose a city.\n```openui\n" + CODE + "\n```"
    requests = []
    steps = []
    for answer in (text, "Received your city."):
        events = tuple(ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta=char) for char in answer)
        steps.append(ScriptedModelStep(events=(*events, ModelStreamEvent(kind=ModelEventKind.COMPLETED,
            response=ModelResponse(response_id="answer", text=answer, finish_reason="stop"))), assertion=requests.append))
    service, _, _ = desktop(tmp_path, model=ScriptedModelProvider(tuple(steps)))
    await service.list_agents("owner")
    await service.patch_model_provider("model_main", ModelProviderPatch(api_keys=["fake"]), "owner")
    try:
        frames = [
            json.loads(line)
            async for line in service.run_events(
                DesktopRunRequest(
                    agent_id="sage",
                    messages=[RunMessage(role="user", text="Trip")],
                    ui_preference=ui_preference,
                    preferred_skills=["sage-openui"]
                    if ui_preference == "interactive"
                    else [],
                    idempotency_key="first",
                ),
                "owner",
            )
        ]
        assert frames[-1]["type"] == "run.completed", frames[-1]
        updates = [
            frame["surface"]
            for frame in frames
            if frame.get("kind") == "openui.updated"
        ]
        assert any(surface["tree"] and not surface["complete"] for surface in updates)
        surface = next(surface for surface in reversed(updates) if surface["complete"])
        assert not any(frame.get("type", "").startswith("tool.") for frame in frames)
        assert "fenced Markdown block" in "\n".join(
            block.text
            for message in requests[0].messages
            if message.role == "system"
            for block in message.content
            if block.kind == "text"
        )
        system_text = "\n".join(
            block.text
            for message in requests[0].messages
            if message.role == "system"
            for block in message.content
            if block.kind == "text"
        )
        assert ("# Sage OpenUI" in system_text) == (ui_preference == "interactive")
        assert "built-in answer format" in system_text
        assert "Rendering has no tool-loading prerequisite" in system_text
        assert "operations independently required" in system_text
        assert ("preloaded by the standard Sage Skill loader" in system_text) == (
            ui_preference == "interactive"
        )
        if ui_preference == "interactive":
            assert "They are not loaded. Call load_skill" not in system_text
        else:
            assert "Choose the presentation automatically" in system_text
        hydrated = await service.openui_surfaces(surface["session_id"], "owner")
        assert hydrated[0]["surface_id"] == surface["surface_id"]
        request = DesktopRunRequest(
            agent_id="sage",
            session_id=surface["session_id"],
            messages=[],
            openui_action=dict(
                surface_id=surface["surface_id"],
                revision=1,
                action="submit",
                values={"city": "Shanghai"},
            ),
        )
        action_frames = [
            json.loads(line) async for line in service.run_events(request, "owner")
        ]
        assert action_frames[-1]["type"] == "run.completed", action_frames[-1]
        replay = [
            json.loads(line) async for line in service.run_events(request, "owner")
        ]
        assert replay[0]["handle"]["run_id"] == action_frames[0]["handle"]["run_id"]
        assert len(requests) == 2
        assert (await service.openui_surfaces(surface["session_id"], "owner"))[0][
            "submitted"
        ] is True
        with pytest.raises(Exception):
            await service.openui_surfaces(surface["session_id"], "intruder")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_expanded_gallery_and_typed_submission_validation(tmp_path):
    from pathlib import Path
    from app.v2.desktop.backend.openui import validate_tree, validate_field_value

    fixtures = json.loads(
        Path("app/v2/desktop/test/fixtures/openui_gallery.json").read_text()
    )
    parser = OpenUiParser()
    try:
        for fixture in fixtures:
            tree = await parser.parse(fixture["code"], complete=True)
            fields, _ = validate_tree(tree)
            assert tree == fixture["surface"]["tree"]
            if fixture["name"] == "calculator":
                for value in [True, float("nan"), float("inf"), -1, 1000001, "100"]:
                    with pytest.raises(ValueError):
                        validate_field_value(fields["principal"], value)
                validate_field_value(fields["principal"], 12000.5)
            if fixture["name"] == "form":
                for value in [[], ["unknown"], ["艺术", "艺术"], "艺术"]:
                    with pytest.raises(ValueError):
                        validate_field_value(fields["interests"], value)
                for value in ["2026-02-30", "2026-1-1", "not-a-date"]:
                    with pytest.raises(ValueError):
                        validate_field_value(fields["date"], value)
        bad_sources = [
            'root = Tabs([Text("bad")])',
            'root = Accordion([Text("bad")])',
            'root = Chart("X", "line", ["A"], [{name: "X", values: [1, 2]}])',
            'root = Chart("X", "pie", ["A"], [{name: "X", values: [-1]}])',
            'root = Chart("X", "line", ["A"], [{name: "X", values: ["missing"]}])',
            'root = Computed("X", "sum", ["missing"])',
            'root = Computed("X", "divide", [1])',
            'root = Image("http://example.com/image.png", "X")',
            'root = Image("https://127.0.0.1/image.png", "X")',
            'root = Image("https://host.internal/image.png", "X")',
            'root = Card("X", [Slider("n", "N", 10, 0, 5, 1), Button("ok", "OK")])',
            'root = Diagram("X", [{id: "a", label: "A"}], [["a", "b"]])',
        ]
        for code in bad_sources:
            with pytest.raises(ValueError):
                await parser.parse(code, complete=True)
        code = 'root = Card("X", [NumberInput("amount", "Amount", 10, 0, 100, 1), Chart("Live", "bar", ["Chosen"], [{name: "Amount", values: ["amount"]}]), Button("ok", "OK")])'
        await parser.parse(code, complete=True)
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_expanded_fields_claim_and_replay_preserve_types(tmp_path):
    code = 'root = Card("Settings", [NumberInput("amount", "Amount", 10, 0, 100, 1), CheckboxGroup("tags", "Tags", ["A", "B"], ["A"], true), DateInput("date", "Date", "2026-11-01", true), Button("save", "Save")])'
    parser = OpenUiParser()
    try:
        tree = await parser.parse(code, complete=True)
    finally:
        await parser.close()
    store = OpenUiStore(tmp_path / "expanded.sqlite3")
    surface = store.publish(
        owner="owner",
        session="session",
        agent="sage",
        run="source",
        operation="publish",
        key="message:0",
        code=code,
        tree=tree,
        fallback="",
    )
    normalized, replay = store.claim(
        surface, "save", {"amount": 12.5, "tags": ["B", "A"], "date": "2026-11-07"}
    )
    assert replay is None
    assert normalized == {"amount": 12.5, "tags": ["A", "B"], "date": "2026-11-07"}
    store.accepted(surface, "accepted")
    assert (
        store.claim(
            surface, "save", {"amount": 12.5, "tags": ["A", "B"], "date": "2026-11-07"}
        )[1]
        == "accepted"
    )


@pytest.mark.asyncio
async def test_interactive_skill_preload_uses_frozen_installer_layout(tmp_path, monkeypatch):
    from app.v2.desktop.backend import openui, workspace_service
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    runtime = tmp_path / "_internal/app/v2/desktop/backend/openui_runtime"
    runtime.mkdir(parents=True)
    (runtime / "prompt.txt").write_text("component protocol")
    skill = tmp_path / "_internal/skills/sage-openui/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: sage-openui\ndescription: Frozen skill\n---\nfrozen builtin skill instructions")
    monkeypatch.setattr(openui, "RUNTIME", runtime)
    monkeypatch.setattr(workspace_service, "__file__", str(runtime.parent / "workspace_service.py"))
    service, model, _ = desktop(tmp_path / "service")
    try:
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Render")], ui_preference="interactive"))
        assert run.state.value == "completed"
        assert "frozen builtin skill instructions" in str(model.requests[0].messages)
        accepted = await service.application.run_configuration(run.run_id, service._context("user_1"))
        assert accepted["agent"]["preload_skills"] == ["sage-openui"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_chained_calculations_validate_dependencies_and_preserve_failed_preview():
    from types import SimpleNamespace
    from pathlib import Path
    from app.v2.desktop.backend.openui import OpenUiProjector, validate_tree

    fixtures = json.loads(
        Path("app/v2/desktop/test/fixtures/openui_gallery.json").read_text()
    )
    sample = next(item for item in fixtures if item["name"] == "chained-calculator")
    parser = OpenUiParser()
    try:
        tree = await parser.parse(sample["code"], complete=True)
        fields, _ = validate_tree(tree)
        assert set(fields) == {"people", "days", "hotel", "meal"}
        for source in [
            'root = Computed("A", "sum", ["root"])',
            'root = Stack([a, b])\na = Computed("A", "sum", ["b"])\nb = Computed("B", "sum", ["a"])',
            'root = Computed("A", "sum", [Text("bad")])',
            'root = Computed("A", "sum", [NumberInput("hidden", "Hidden", 1)])',
            'root = Computed("A", "sum", ["missing"])',
        ]:
            with pytest.raises(ValueError):
                await parser.parse(source, complete=True)

        projector = OpenUiProjector(SimpleNamespace(openui_parser=parser), "owner")
        text = '```openui\nroot = Computed("Result", "sum", ["missing"])\n```'
        event = SimpleNamespace(
            type="message.delta",
            item_id="m",
            run_id="r",
            session_id="s",
            run_sequence=1,
            data=SimpleNamespace(delta=text),
        )
        partial = (await projector.project(event))[0]["surface"]
        assert partial["tree"] is not None
        event.type = "message.completed"
        event.data = SimpleNamespace(
            item=SimpleNamespace(
                item_id="m",
                data=SimpleNamespace(
                    kind="message",
                    role="assistant",
                    content=[SimpleNamespace(kind="text", text=text)],
                ),
            )
        )
        failed = (await projector.project(event))[0]["surface"]
        assert failed["error"]
        assert failed["tree"] == partial["tree"]
        assert not failed["complete"]
        assert "surface_id" not in failed  # Invalid previews can never submit.
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_local_calculator_needs_no_submit_action(tmp_path):
    from app.v2.desktop.backend.openui import validate_tree

    code = """root = Stack([cups, income, cost, profit, chart])
cups = NumberInput("cups", "每天销量", 100, 0, 2000, 1)
income = Computed("月收入", "product", [cups, 25, 30])
cost = Computed("月成本", "sum", [variable, 20000])
variable = Computed("变动成本", "product", [cups, 8, 30])
profit = Computed("月利润", "difference", [income, cost])
chart = Chart("经营测算", "bar", ["收入", "成本", "利润"], [{name: "金额", values: [income, cost, profit]}])"""
    parser = OpenUiParser()
    try:
        tree = await parser.parse(code, complete=True)
    finally:
        await parser.close()
    fields, actions = validate_tree(tree)
    assert set(fields) == {"cups"}
    assert actions == {}
    store = OpenUiStore(tmp_path / "local-ui.sqlite3")
    surface = store.publish(
        owner="owner",
        session="session",
        agent="sage",
        run="run",
        operation="local",
        key="message:0",
        code=code,
        tree=tree,
        fallback="",
    )
    assert store.get("owner", "session", surface["surface_id"])["tree"] == tree
    with pytest.raises(ValueError, match="Unknown"):
        store.claim(surface, "submit", {"cups": 200})


@pytest.mark.asyncio
async def test_real_running_plan_still_rejects_implicit_selection_arithmetic():
    from pathlib import Path

    source = Path(
        "app/v2/desktop/test/fixtures/openui_invalid_running_plan.openui"
    ).read_text()
    parser = OpenUiParser()
    try:
        with pytest.raises(ValueError, match="numeric"):
            await parser.parse(source, complete=True)
        # Isolate the second defect, so fixing Progress alone cannot hide it.
        with pytest.raises(ValueError):
            await parser.parse(
                'root = Stack([checks, total])\nchecks = CheckboxGroup("done", "Done", ["A"], [])\ntotal = Computed("Count", "sum", [checks])',
                complete=True,
            )
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_selection_count_ratio_and_progress_share_validated_bindings():
    from pathlib import Path
    from app.v2.desktop.backend.openui import validate_tree

    parser = OpenUiParser()
    try:
        source = Path(
            "app/v2/desktop/test/fixtures/openui_running_tracker.openui"
        ).read_text()
        tree = await parser.parse(source, complete=True)
        fields, _ = validate_tree(tree)
        assert (
            len([f for f in fields.values() if f["component"] == "CheckboxGroup"]) == 4
        )
        code = """root = Stack([checks, Progress("Done", rate)])
checks = CheckboxGroup("done", "Done", ["A", "B"], [])
count = Computed("Count", "count", [checks])
rate = Computed("Rate", "ratioPercent", [count, 2])"""
        await parser.parse(code, complete=True)
        for bad in [
            code.replace('"count", [checks]', '"sum", [checks]'),
            code.replace('"count", [checks]', '"count", [1]'),
            code.replace('"ratioPercent", [count, 2]', '"ratioPercent", [checks, 2]'),
            code.replace("[checks, Progress", "[Progress"),
            code.replace('Progress("Done", rate)', 'Progress("Done", 101)'),
        ]:
            with pytest.raises(ValueError):
                await parser.parse(bad, complete=True)
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_generated_child_slots_match_validated_component_contract():
    from pathlib import Path

    prompt = Path("app/v2/desktop/backend/openui_runtime/prompt.txt").read_text()
    assert "children: Slide[]" in prompt
    assert "children: (Text | Metric | Table | Chart)[]" in prompt
    assert "Tabs(children: Tab[])" in prompt
    assert "Accordion(children: Section[])" in prompt
    assert "Always write the root = Stack" not in prompt
    assert "root = Stack(...) is the FIRST line" not in prompt
    assert "Computed is itself a visible result card" in prompt
    parser = OpenUiParser()
    try:
        for source in [
            'root = Deck("Bad", [Text("Not a slide")])',
            'root = Deck("Bad", [Slide("Page", [Button("submit", "Send")])])',
            'root = Tabs([Card("Bad", [Text("Not a tab")])])',
            'root = Accordion([Tab("Bad", [Text("Not a section")])])',
        ]:
            with pytest.raises(ValueError):
                await parser.parse(source, complete=True)
    finally:
        await parser.close()
