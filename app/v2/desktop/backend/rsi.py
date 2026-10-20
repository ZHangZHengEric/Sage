"""Desktop-owned, durable RSI jobs and immutable package/configuration versions.

Tasks belong to the sidecar, never an HTTP request. Interrupted jobs are retained
without replay. Applying a version is a separate, confirmed compare-and-swap.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from sagents.v2 import AgentPackageOptimizer, IsolatedOptimizationRunner
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.common import StrictModel, new_id, utc_now
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization import (
    OptimizationAgent,
    OptimizationConstraints,
    OptimizationFinalSuite,
    OptimizationSuite,
)
from sagents.v2.optimization.contracts import OptimizationPart
from sagents.v2.package.manifest.agents import Instructions
from sagents.v2.skill import FilesystemSkillProvider
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.agent.policy.tool_policy import ToolOperationAssessment, ToolPolicyAction
from sagents.v2.tool import SideEffectLevel
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    official_tool_definitions,
)
from app.v2.desktop.backend.runtime_config import _TOOL_NAME, _SKILL_NAME


def fingerprint(agent):
    return hashlib.sha256(
        json.dumps(
            {"name": agent.name, "config": agent.config},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


class RsiStart(StrictModel):
    goal: str = Field(min_length=1, max_length=16000)
    rounds: int = Field(default=3, ge=1, le=100)
    optimization_scope: tuple[OptimizationPart, ...] = ("instructions", "skills")
    model_provider_id: str | None = None
    suite: OptimizationSuite | None = None
    final_suite: OptimizationFinalSuite | None = None
    evaluation_repeats: int = Field(default=1, ge=1, le=10)
    request_id: str = Field(min_length=1, max_length=128)


class RsiApply(StrictModel):
    confirmed: Literal[True]
    expected_fingerprint: str = Field(min_length=64, max_length=64)


class RsiStore:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, user TEXT, agent TEXT, kind TEXT, body TEXT, summary TEXT)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(records)")}
            if "summary" not in columns:
                db.execute("ALTER TABLE records ADD COLUMN summary TEXT")
            for identity, body in db.execute(
                "SELECT id, body FROM records WHERE summary IS NULL"
            ).fetchall():
                db.execute(
                    "UPDATE records SET summary=? WHERE id=?",
                    (json.dumps(self.metadata(json.loads(body))), identity),
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS record_owner ON records(user, agent, kind)"
            )
            # There is deliberately no replay of calls with unknown outcomes.
            for row in db.execute(
                "SELECT id, body FROM records WHERE kind='run'"
            ).fetchall():
                value = json.loads(row[1])
                if value["status"] in {"queued", "running"}:
                    value.update(
                        status="interrupted", finished_at=utc_now().isoformat()
                    )
                    db.execute(
                        "UPDATE records SET body=?, summary=? WHERE id=?",
                        (json.dumps(value), json.dumps(self.metadata(value)), row[0]),
                    )
        os.chmod(path, 0o600)

    @staticmethod
    def metadata(value):
        return {
            k: v
            for k, v in value.items()
            if k not in {"config", "package", "assets", "record"}
        }

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, value, user, agent, kind):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO records (id, user, agent, kind, body, summary) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    value["id"],
                    user,
                    agent,
                    kind,
                    json.dumps(value, ensure_ascii=False),
                    json.dumps(self.metadata(value), ensure_ascii=False),
                ),
            )

    def list(self, user, agent, kind):
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT body FROM records WHERE user=? AND agent=? AND kind=? ORDER BY rowid DESC",
                    (user, agent, kind),
                ).fetchall()
            ]

    def summaries(self, user, agent, kind):
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT summary FROM records WHERE user=? AND agent=? AND kind=? ORDER BY json_extract(summary, '$.created_at') DESC",
                    (user, agent, kind),
                ).fetchall()
            ]

    def iterations(self, user, agent, run_id):
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT json_remove(body, '$.config', '$.package', '$.assets', '$.record.package', '$.record.candidate_package') FROM records WHERE user=? AND agent=? AND kind='version' AND json_extract(summary, '$.run_id')=?",
                    (user, agent, run_id),
                ).fetchall()
            ]

    def get(self, identity, user, agent, kind):
        with self.connect() as db:
            row = db.execute(
                "SELECT body FROM records WHERE id=? AND user=? AND agent=? AND kind=?",
                (identity, user, agent, kind),
            ).fetchone()
        if row is None:
            raise ValueError("RSI record not found")
        return json.loads(row[0])



class DesktopRsiMixin:
    def _initialize_rsi(self):
        self.rsi_store = RsiStore(self.runtime_root / "rsi.sqlite3")
        self._rsi_tasks = {}
        self._rsi_cursors = {}

    @property
    def rsi_active(self):
        return any(not task.done() for task in self._rsi_tasks.values())

    async def _close_rsi(self):
        tasks = tuple(self._rsi_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _agent_bundle(self, agent):
        return (await self._agent_snapshot(agent))[0]

    async def _agent_snapshot(self, agent):
        providers = await self.catalog.list_model_providers(agent.user_id)
        provider = next(
            (p for p in providers if p.id == agent.config.get("llm_provider_id")), None
        )
        provider = provider or next((p for p in providers if p.is_default), None)
        if provider is None:
            raise ValueError("Agent has no configured model")
        configured_tools = agent.config.get("availableTools")
        if configured_tools is None:
            mcp = await self._mcp_plugin(agent.user_id)
            mcp_definitions = await mcp.list_tools(run_id="rsi-snapshot")
            configured_tools = tuple(
                definition.name
                for definition in (*self._native_tool_definitions(), *mcp_definitions)
            )
        # Match normal Desktop composition: stale internal operation names are
        # not callable tools. Preserve the raw configuration in version records,
        # but snapshot the executable allowlist without renaming or new grants.
        tools = tuple(
            name
            for name in configured_tools
            if isinstance(name, str) and _TOOL_NAME.fullmatch(name)
        )
        skills = tuple(
            name
            for name in (agent.config.get("availableSkills") or ())
            if isinstance(name, str) and _SKILL_NAME.fullmatch(name)
        )
        if skills and "load_skill" not in tools:
            tools = (*tools, "load_skill")
        manifest = self._manifest(agent, provider, tools, skills)
        files = dict((agent.config.get("rsiPackage") or {}).get("files") or {})
        assets = dict(agent.config.get("rsiAssets") or {})
        configured_context = (
            agent.config.get("systemContext")
            or agent.config.get("system_context")
            or {}
        )
        files["desktop/context.json"] = json.dumps(
            {"system_context": configured_context}, ensure_ascii=False
        )
        source = self._skill_provider(agent)
        for name in skills:
            bundle = await source.fetch(name, run_id="rsi-snapshot")
            for path, content in bundle.files.items():
                name_in_package = f"skills/{name}/{path}"
                try:
                    files[name_in_package] = content.decode("utf-8")
                    assets.pop(name_in_package, None)
                except UnicodeDecodeError:
                    files.pop(name_in_package, None)
                    assets[name_in_package] = base64.b64encode(content).decode("ascii")
        return AgentPackageBundle(manifest=manifest, files=files), assets

    async def _record_agent_version(
        self,
        agent,
        *,
        source="settings",
        package=None,
        run_id=None,
        iteration=None,
        review=None,
    ):
        snapshot, assets = await self._agent_snapshot(agent)
        package = package or snapshot
        value = {
            "id": f"{run_id}.{iteration}" if run_id else new_id("version"),
            "created_at": utc_now().isoformat(),
            "source": source,
            "fingerprint": fingerprint(agent),
            "config": agent.config,
            "name": agent.name,
            "package": package.model_dump(mode="json"),
            "package_hash": package.content_hash,
            "assets": assets,
            "assets_hash": hashlib.sha256(
                json.dumps(assets, sort_keys=True).encode()
            ).hexdigest(),
            "run_id": run_id,
            "iteration": iteration,
            "review": review,
        }
        values = self.rsi_store.summaries(agent.user_id, agent.agent_id, "version")
        latest_settings = next((v for v in values if v["source"] == "settings"), None)
        if (
            source == "settings"
            and latest_settings
            and latest_settings["fingerprint"] == value["fingerprint"]
            and latest_settings["package_hash"] == value["package_hash"]
            and latest_settings.get("assets_hash") == value["assets_hash"]
        ):
            return latest_settings
        self.rsi_store.put(value, agent.user_id, agent.agent_id, "version")
        return value

    async def rsi_history(self, agent_id, user_id):
        agent = await self._agent(agent_id, user_id)
        async with self._agent_update_lock:
            agent = await self._agent(agent_id, user_id)
            await self._record_agent_version(agent)
        versions = self.rsi_store.summaries(user_id, agent_id, "version")
        return {
            "current_fingerprint": fingerprint(agent),
            "runs": self.rsi_store.list(user_id, agent_id, "run"),
            "versions": [
                {k: v for k, v in item.items() if k != "record"} for item in versions
            ],
        }

    async def rsi_version(self, agent_id, version_id, user_id):
        await self._agent(agent_id, user_id)
        return self.rsi_store.get(version_id, user_id, agent_id, "version")

    async def rsi_run(self, agent_id, run_id, user_id, *, after_sequence=0):
        await self._agent(agent_id, user_id)
        value = self.rsi_store.get(run_id, user_id, agent_id, "run")
        path = self.runtime_root / "rsi" / run_id / "audit.jsonl"
        events = []
        if after_sequence < 0:
            raise ValueError("after_sequence must be nonnegative")
        if path.exists():
            with path.open(encoding="utf-8") as journal:
                journal.seek(self._rsi_cursors.get((run_id, after_sequence), 0))
                while line := journal.readline():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    if event["sequence"] > after_sequence:
                        events.append(event)
                        self._rsi_cursors[(run_id, event["sequence"])] = journal.tell()
                        if len(events) == 200:
                            break
            while len(self._rsi_cursors) > 512:
                self._rsi_cursors.pop(next(iter(self._rsi_cursors)))
        value["events"] = events
        versions = self.rsi_store.iterations(user_id, agent_id, run_id)
        value["iterations"] = sorted(
            [
                {
                    **v.get("record", {}),
                    "iteration": v["iteration"],
                    "review": v.get("review"),
                    "reason": v.get("record", {}).get("reason", "Pending evaluation"),
                }
                for v in versions
                if v["run_id"] == run_id
            ],
            key=lambda v: v["iteration"],
        )
        result = path.parent / "result.json"
        if result.exists():
            value["result"] = json.loads(result.read_text())
        return value

    async def start_rsi(self, agent_id, request: RsiStart, user_id):
        if (
            not request.goal.strip()
            or not request.optimization_scope
            or len(set(request.optimization_scope)) != len(request.optimization_scope)
        ):
            raise ValueError("Goal and distinct optimization parts are required")
        async with self._agent_update_lock:
            agent = await self._agent(agent_id, user_id)
            runs = self.rsi_store.list(user_id, agent_id, "run")
            existing = next(
                (r for r in runs if r["request_id"] == request.request_id), None
            )
            request_hash = hashlib.sha256(
                request.model_dump_json(exclude={"request_id"}).encode()
            ).hexdigest()
            if existing is not None:
                if existing.get("request_hash") != request_hash:
                    raise ValueError(
                        "Request identity already belongs to different RSI options"
                    )
                return existing  # HTTP retry never duplicates model calls.
            if any(r["status"] in {"queued", "running"} for r in runs):
                raise ValueError("This Agent already has an active RSI run")
            if agent.config.get("agentMode", "simple") != "simple":
                raise ValueError("Desktop RSI currently requires a simple Agent")
            package, assets = await self._agent_snapshot(agent)
            native_tools = {d.name for d in official_tool_definitions()} | {
                "load_skill"
            }
            if set(package.manifest.agents[agent_id].tools) - native_tools:
                raise ValueError(
                    "RSI requires native tools; external MCP tools need isolated test bindings"
                )
            provider = await self._provider(agent, user_id)
            internal_provider = provider
            if request.model_provider_id:
                internal_provider = await self.catalog.get_model_provider(
                    request.model_provider_id, user_id
                )
                if internal_provider is None or not internal_provider.api_key:
                    raise ValueError("RSI model is not configured")
            await self._record_agent_version(agent, package=package)
            run_id = new_id("rsi")
            value = {
                "id": run_id,
                "request_id": request.request_id,
                "request_hash": request_hash,
                "status": "queued",
                "goal": request.goal,
                "rounds": request.rounds,
                "optimization_scope": request.optimization_scope,
                "model_provider_id": internal_provider.id,
                "created_at": utc_now().isoformat(),
                "base_fingerprint": fingerprint(agent),
                "stage": "queued",
                "iteration": 0,
            }
            self.rsi_store.put(value, user_id, agent_id, "run")
            task = asyncio.create_task(
                self._execute_rsi(
                    agent, package, provider, internal_provider, request, value, assets
                ),
                name=run_id,
            )
            self._rsi_tasks[run_id] = task
            task.add_done_callback(lambda _: self._rsi_tasks.pop(run_id, None))
            return value.copy()

    async def _execute_rsi(
        self, agent, package, provider, internal_provider, request, value, assets
    ):
        root = self.runtime_root / "rsi" / value["id"]
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        user, identity = agent.user_id, agent.agent_id
        value = dict(value)

        def save():
            self.rsi_store.put(value, user, identity, "run")

        def version_event(index, bundle_data, record=None):
            bundle = AgentPackageBundle.model_validate(bundle_data)
            item = {
                "id": f"{value['id']}.{index}",
                "created_at": utc_now().isoformat(),
                "source": "rsi",
                "fingerprint": fingerprint(agent),
                "config": agent.config,
                "name": agent.name,
                "package": bundle_data,
                "package_hash": bundle.content_hash,
                "assets": assets,
                "run_id": value["id"],
                "iteration": index,
                "review": (record or {}).get("review"),
                "record": record or {},
                "ready": bool((record or {}).get("evaluation")),
            }
            self.rsi_store.put(item, user, identity, "version")

        def observe(event):
            value["stage"] = event["event"]
            data = event["data"]
            record = data.get("record") or {}
            value["iteration"] = max(
                value["iteration"],
                data.get("round", record.get("round", value["iteration"])),
            )
            value["sequence"] = event["sequence"]
            if "role" in data:
                value["role"] = data["role"]
            if event["event"] == "operation_started":
                version_event(0, data["package"])
            elif event["event"] == "suite_review_completed":
                value["suite_review"] = data["review"]
            elif event["event"] == "candidate_created":
                version_event(data["round"], data["package"])
            elif event["event"] in {
                "semantic_review_completed",
                "evaluation_completed",
            }:
                item = self.rsi_store.get(
                    f"{value['id']}.{data['round']}", user, identity, "version"
                )
                if "review" in data:
                    item["review"] = data["review"]
                else:
                    item["record"]["evaluation"] = data["evaluation"]
                    if data["round"] == 0:
                        item["ready"] = True
                self.rsi_store.put(item, user, identity, "version")
            elif event["event"] == "round_completed" and record.get(
                "candidate_package"
            ):
                version_event(record["round"], record["candidate_package"], record)
            save()

        try:
            value["status"] = "running"
            save()
            manifest_data = package.manifest.model_dump(mode="json")
            manifest_data["runtime"]["capabilities"]["tool.catalog"] = {
                "plugin": OfficialToolPlugin.plugin_id
            }
            package = AgentPackageBundle(manifest=manifest_data, files=package.files)
            roles = {}
            role_provider = {}
            for role in (
                "evaluator",
                "tuner",
                "designer",
                "reviewer",
                "suite_reviewer",
            ):
                manifest = self._manifest(agent, internal_provider, (), ())
                definition = manifest.agents[identity].model_copy(
                    update={
                        "instructions": Instructions(
                            inline=f"You are the independent RSI {role}. Follow the supplied JSON schema. Preserve the original agent goal. Use reusable improvements; never memorize test answers."
                        ),
                    }
                )
                manifest = manifest.model_copy(
                    update={
                        "metadata": manifest.metadata.model_copy(
                            update={"id": f"desktop.rsi.{role}"}
                        ),
                        "agents": {identity: definition},
                    }
                )
                roles[role] = OptimizationAgent(
                    package=AgentPackageBundle(manifest=manifest), agent_id=identity
                )
                role_provider[manifest.metadata.id] = internal_provider
            allowed_ids = {package.manifest.metadata.id, *role_provider}
            definitions = official_tool_definitions()
            allowed_tools = (
                {d.name for d in definitions} | {"load_skill"}
                if "tools" in request.optimization_scope
                else set(package.manifest.agents[identity].tools)
            )
            tool_scopes = {
                scope
                for definition in definitions
                if definition.name in allowed_tools
                for scope in definition.required_scopes
            }
            if "load_skill" in allowed_tools:
                tool_scopes.add("skill.load")

            async def authorize(action, bundle, context):
                if (
                    action != "optimize_run"
                    or bundle.manifest.metadata.id not in allowed_ids
                    or context.actor.principal_id != user
                ):
                    raise PermissionError("Outside RSI host grant")
                permitted = (
                    allowed_tools
                    if bundle.manifest.metadata.id == package.manifest.metadata.id
                    else set()
                )
                if set(bundle.manifest.agents[identity].tools) - permitted:
                    raise PermissionError("Tools exceed the frozen RSI grant")

            async def factory(bundle, workspace, context):
                for name, content in (
                    assets.items()
                    if bundle.manifest.metadata.id == package.manifest.metadata.id
                    else ()
                ):
                    target = workspace / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(base64.b64decode(content, validate=True))
                selected = role_provider.get(bundle.manifest.metadata.id, provider)
                model = await self._model_provider(selected, agent)
                skills = FilesystemSkillProvider((workspace / "skills",))

                def assess(call):
                    local_writes = {
                        "load_skill",
                        "file_write",
                        "file_update",
                        "apply_patch",
                        "todo_write",
                    }
                    if call.definition.name in local_writes:
                        return ToolOperationAssessment(
                            action=ToolPolicyAction.ALLOW,
                            reason="RSI-local workspace operation",
                        )
                    if (
                        call.definition.side_effect_level
                        not in {SideEffectLevel.NONE, SideEffectLevel.READ}
                        or call.definition.requires_approval
                    ):
                        return ToolOperationAssessment(
                            action=ToolPolicyAction.DENY,
                            reason="Operation is unsupported in unattended RSI",
                        )
                    return None

                from sagents.v2 import ApplicationConfiguration
                from sagents.v2.package.manifest.runtime import CapabilitySelection
                from sagents.v2.runtime.extensions import (
                    CapabilityKey,
                    CapabilityOffer,
                    ExtensionDescriptor,
                    ExtensionRegistration,
                    ExtensionScope,
                )
                registrations = []
                choices = dict(bundle.manifest.runtime.capabilities)
                policy = DefaultToolPolicy(operation_assessor=assess,
                    operation_assessor_id="desktop.rsi.local-workspace/v1")
                for capability, value, extras in (
                    ("model.provider", model, ()),
                    ("execution.model-budget", self.model_budget, ()),
                    ("skill.catalog", skills, ("skill.source",)),
                    ("agent.tool-policy", policy, ()),
                ):
                    plugin = "com.sage.desktop.rsi." + capability.replace(".", "-")
                    names = (capability, *extras)
                    registrations.append(ExtensionRegistration(
                        descriptor=ExtensionDescriptor(plugin_id=plugin, name=capability, version="2",
                            provides=tuple(CapabilityOffer(capability=name, api_version="2") for name in names),
                            supported_scopes=frozenset({ExtensionScope.PROCESS}),
                            config_schema={"type": "object", "additionalProperties": False}),
                        factory=lambda context, deps, value=value: value, ownership="borrowed",
                        start=(lambda instance, context, deps, names=names: {
                            CapabilityKey(capability=name): instance for name in names
                        }) if extras else None,
                    ))
                    choices[capability] = CapabilitySelection(plugin=plugin)
                choices["session.store"] = CapabilitySelection(plugin="sage.session.filesystem", config={"root": str(workspace / "sessions")})
                choices["execution.binding"] = CapabilitySelection(plugin="sage.execution.binding.local-workspace", config={
                    "workspace": str(workspace / "work"), "policy": {"process": {"enabled": False}},
                })
                choices.setdefault("tool.catalog", CapabilitySelection(plugin="sage.tool.official"))
                # RSI roles have their own structured evaluator. Select tools
                # directly unless the frozen package explicitly chooses another
                # policy, so default discovery cannot become another model task.
                choices.setdefault("tool.selection-policy", CapabilitySelection(plugin="sage.tool-selection.direct"))
                choices.setdefault("agent.continuation-policy", CapabilitySelection(plugin="sage.agent.continuation.deterministic"))
                runtime = bundle.manifest.runtime.model_copy(update={"capabilities": choices, "state_root": str(workspace / "sessions")})
                return ApplicationConfiguration(tuple(registrations), runtime, self._model_catalog(agent, selected))


            constraints = OptimizationConstraints(
                editable_files=tuple(
                    name for name in package.files if name != "desktop/context.json"
                ),
                creatable_files=("skills/rsi-guidance/SKILL.md",),
                allow_skill_changes=True,
                skill_candidates={
                    "rsi-guidance": "Reusable methods for the original goal"
                },
                allow_tool_changes=True,
                tool_candidates={
                    **{d.name: d.description for d in definitions},
                    "load_skill": "Load an enabled skill into the isolated workspace",
                },
                editable_budget_fields=("max_steps",),
            )
            optimizer = AgentPackageOptimizer(
                runner=IsolatedOptimizationRunner(
                    builder_factory=factory,
                    authorize=authorize,
                    root=root,
                    run_metadata=lambda bundle: (
                        json.loads(package.files["desktop/context.json"])
                        if bundle.manifest.metadata.id == package.manifest.metadata.id
                        else {}
                    ),
                ),
                evaluator=roles["evaluator"],
                tuner=roles["tuner"],
                test_designer=roles["designer"],
                reviewer=roles["reviewer"],
                suite_reviewer=roles["suite_reviewer"],
            )
            result = await optimizer.optimize(
                package,
                context=RequestContext(
                    actor=ActorRef(
                        principal_id=user,
                        principal_type=PrincipalType.USER,
                        scopes=tuple(sorted(tool_scopes)),
                    )
                ),
                goal=request.goal,
                rounds=request.rounds,
                constraints=constraints,
                optimization_scope=request.optimization_scope,
                suite=request.suite,
                final_suite=request.final_suite,
                evaluation_repeats=request.evaluation_repeats,
                journal_path=root / "audit.jsonl",
                on_event=observe,
            )
            result_path = root / "result.json"
            result_path.write_text(result.model_dump_json(), encoding="utf-8")
            os.chmod(result_path, 0o600)
            for item in result.iterations:
                stored = self.rsi_store.get(
                    f"{value['id']}.{item.iteration}", user, identity, "version"
                )
                verification = result.report.final_verification
                stored["final_test"] = {
                    "tested": verification is not None
                    and item.iteration in {0, verification.candidate_iteration},
                    "passed": verification.passed
                    if verification
                    and item.iteration == verification.candidate_iteration
                    else None,
                }
                stored.update(
                    record=item.model_dump(mode="json"),
                    ready=True,
                    review=item.review.model_dump(mode="json") if item.review else None,
                )
                self.rsi_store.put(stored, user, identity, "version")
            value.update(
                status="completed",
                recommended_hash=result.candidate_package.content_hash,
            )
        except asyncio.CancelledError:
            value["status"] = "interrupted"
            raise
        except Exception as error:
            # Provider errors can contain secrets. Persist only the exception type.
            value.update(status="failed", error_type=type(error).__name__)
        finally:
            value["finished_at"] = utc_now().isoformat()
            save()

    async def cancel_rsi(self, agent_id, run_id, user_id):
        await self._agent(agent_id, user_id)
        value = self.rsi_store.get(run_id, user_id, agent_id, "run")
        task = self._rsi_tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            value = self.rsi_store.get(run_id, user_id, agent_id, "run")
            value["status"] = "cancelled"
            self.rsi_store.put(value, user_id, agent_id, "run")
        return value

    async def apply_rsi_version(self, agent_id, version_id, request: RsiApply, user_id):
        async with self._agent_update_lock:
            agent = await self._agent(agent_id, user_id)
            if fingerprint(agent) != request.expected_fingerprint:
                raise ValueError(
                    "Agent configuration changed; reload before confirming the version"
                )
            version = self.rsi_store.get(version_id, user_id, agent_id, "version")
            if version["source"] == "rsi" and not version.get("ready"):
                raise ValueError(
                    "This iteration is not complete; inspect its retained evidence first"
                )
            if version.get("review") and not version["review"]["approved"]:
                raise ValueError("Semantic review rejected this version")
            package = AgentPackageBundle.model_validate(version["package"])
            definition = package.resolved_manifest().agents[agent_id]
            await self._record_agent_version(agent)
            config = dict(version["config"])
            if version["source"] == "rsi":
                config.update(
                    systemPrefix=definition.instructions.inline,
                    availableTools=list(definition.tools),
                    availableSkills=list(definition.skills),
                    maxLoopCount=definition.budgets.max_steps,
                    rsiPackage=version["package"],
                )
            config["rsiPackage"] = version["package"]
            config["rsiAssets"] = version.get("assets", {})
            updated = agent.model_copy(
                update={
                    "name": version["name"],
                    "config": config,
                    "updated_at": utc_now(),
                }
            )
            await self._record_agent_version(
                updated, source="activation", package=package
            )
            await self.catalog.save_agent(updated)
        return await self.get_agent_settings(agent_id, user_id)
