"""Desktop-owned, durable RSI jobs and immutable package/configuration versions.

Tasks belong to the sidecar, never an HTTP request. Interrupted jobs are retained
without replay. Applying a version is a separate, confirmed compare-and-swap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from app.v2.desktop.backend.service import DesktopV2Service

import asyncio
import base64
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from .rsi_evaluation import EvaluationPlan, ScorerImport, ScorerSelection, McpExecutionScorer, scorer_binding

from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.optimization.scoring import ScorerDescriptor
from sagents.v2.optimization.builtin_scoring import BuiltinScoring, BuiltinScoringUnavailable
from sagents.v2.optimization.python_scorer import PythonExecutionScorer

from sagents.v2 import AgentPackageOptimizer, IsolatedOptimizationRunner
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.common import StrictModel, new_id, utc_now
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization import (
    OptimizationAgent,
    OptimizationConstraints,
    OptimizationSuite,
)
from sagents.v2.optimization.contracts import (
    OptimizationPart,
    OptimizationTestSuite,
    OptimizationStoppingPolicy,
)
from sagents.v2.optimization.recovery import OptimizationTransientFailure, engine_fingerprint
from sagents.v2.optimization.generator import AgentPackageTestGenerator
from sagents.v2.optimization.observer import HumanTestObserver, IsolatedTestEvaluator, SharedCallLimitRunner
from sagents.v2.package.manifest.agents import Instructions
from sagents.v2.skill import FilesystemSkillProvider
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.agent.policy.tool_policy import (
    ToolOperationAssessment,
    ToolPolicyAction,
)
from sagents.v2.tool.generated import generated_tools, generated_tool_provider
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


def rsi_binding(agent, provider, internal_provider):
    return hashlib.sha256(json.dumps({"agent": fingerprint(agent), "user": agent.user_id,
        "target": provider.model_dump(mode="json"), "internal": internal_provider.model_dump(mode="json"),
        "grant": "desktop.rsi.local-workspace/v7-phased-evaluation"}, sort_keys=True).encode()).hexdigest()


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())


def rsi_journal(root, value, *, existing=False):
    name = value.get("journal_name", "audit.jsonl")
    if Path(name).name != name or not name.startswith("audit") or not name.endswith(".jsonl"):
        raise ValueError("invalid RSI journal identity")
    path = root / name
    if existing and not path.exists() and value.get("recovery_journal_name"):
        return rsi_journal(root, {"journal_name": value["recovery_journal_name"]})
    return path


class RsiStart(StrictModel):
    goal: str = Field(min_length=1, max_length=16000)
    rounds: int = Field(default=8, ge=1, le=100)
    optimization_scope: tuple[OptimizationPart, ...] = ("instructions", "skills")
    model_provider_id: str | None = None
    suite: OptimizationSuite | None = None
    evaluation_plan_id: str | None = None
    scorer: ScorerSelection | None = None
    scorer_id: str | None = None
    builtin_scoring: BuiltinScoring = Field(default_factory=BuiltinScoring)
    dataset: OptimizationDataset | None = None
    human_test_count: int = Field(default=0, ge=0, le=100)
    human_test_suite: OptimizationTestSuite | None = None
    evaluation_repeats: int = Field(default=1, ge=1, le=10)
    human_test_repeats: int = Field(default=1, ge=1, le=10)
    evaluation_aggregation: Literal["minimum", "mean"] = "minimum"
    initial_training_case_count: int = Field(default=6, ge=1, le=100)
    training_cases_per_round: int = Field(default=6, ge=0, le=100)
    max_system_prompt_chars: int = Field(default=64000, ge=1, le=1000000)
    max_skill_chars: int = Field(default=32000, ge=1, le=1000000)
    max_skill_count: int = Field(default=16, ge=0, le=256)
    max_edit_repairs: int = Field(default=3, ge=0, le=10)
    grow_training: bool = True
    refresh_incumbent: bool = False
    validation_case_count: int = Field(
        default=24,
        ge=1,
        le=100,
        validation_alias=AliasChoices("validation_case_count", "test_case_count"),
    )
    max_concurrency: int = Field(default=3, ge=1, le=16)
    stopping_policy: OptimizationStoppingPolicy = Field(
        default_factory=OptimizationStoppingPolicy
    )
    request_id: str = Field(min_length=1, max_length=128)


def rsi_timeout_seconds(request: RsiStart) -> int:
    """Budget larger batches without increasing their authorized model-call count."""
    count = max(request.validation_case_count + request.initial_training_case_count + request.training_cases_per_round * request.rounds,
                len(request.suite.cases) if request.suite else 0)
    batches = (count + request.max_concurrency - 1) // request.max_concurrency
    test_count = len(request.human_test_suite.cases) if request.human_test_suite else request.human_test_count
    test_batches = (test_count + request.max_concurrency - 1) // request.max_concurrency
    test_budget = (request.rounds + 1) * test_batches * 480 * request.human_test_repeats
    # Target + evaluator can each consume the 240-second per-call budget.
    # Include the growing training set and stability passes; retain a bounded deadline.
    return min(
        86400,
        max(3600, (request.rounds * (2 if request.refresh_incumbent else 1) + 2) * batches * 480 * request.evaluation_repeats + test_budget),
    )


def builtin_scoring_failure_code(error: BaseException) -> str | None:
    """Keep a uniform typed scoring failure through concurrent teardown groups."""
    pending, codes = [error], set()
    while pending:
        current = pending.pop()
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        elif isinstance(current, BuiltinScoringUnavailable):
            codes.add(current.code)
        else:
            return None
    return next(iter(codes)) if len(codes) == 1 else None


class RsiApply(StrictModel):
    confirmed: Literal[True]
    expected_fingerprint: str = Field(min_length=64, max_length=64)


class RsiStore:
    def __init__(self, path: Path, *, recover_interrupted: bool = True):
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
            ).fetchall() if recover_interrupted else ():
                value = json.loads(row[1])
                if self.external_alive(value):
                    continue
                if value["status"] in {"queued", "running"}:
                    value.update(
                        status="interrupted", finished_at=utc_now().isoformat()
                    )
                    db.execute(
                        "UPDATE records SET body=?, summary=? WHERE id=?",
                        (json.dumps(value), json.dumps(self.metadata(value)), row[0]),
                    )
        os.chmod(path, 0o600)

    def external_alive(self, value):
        if not value.get("external_host"):
            return False
        identity = value.get("id", "")
        if not identity or not all(c.isalnum() or c in "_-" for c in identity):
            return False
        try:
            marker = json.loads((self.path.parent / "rsi" / identity / "external-host.json").read_text())
            pid = marker["pid"]
            if type(pid) is not int or pid <= 1 or marker.get("run_id") != identity:
                return False
            os.kill(pid, 0)
            return True
        except (OSError, ValueError, KeyError):
            return False

    def external_active(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE kind='run' AND json_extract(body, '$.external_host')=1 AND json_extract(body, '$.status')='running'").fetchall()
        return any(self.external_alive(json.loads(row[0])) for row in rows)

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
    async def import_rsi_scorer(self, agent_id, scorer: ScorerImport, user_id):
        await self._agent(agent_id, user_id)
        source_hash = hashlib.sha256(scorer.source.encode()).hexdigest()
        identity = "rsi_scorer_" + hashlib.sha256((source_hash + scorer.name).encode()).hexdigest()[:24]
        scope = hashlib.sha256(f"{user_id}\0{agent_id}".encode()).hexdigest()
        directory = self.runtime_root / "rsi-scorers" / scope / source_hash
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "scorer.py"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != source_hash:
                raise ValueError("frozen scorer source changed")
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(scorer.source)
        descriptor = ScorerDescriptor(id=identity, name=scorer.name, version=source_hash)
        try:
            validation = await PythonExecutionScorer(path=path, source_hash=source_hash,
                descriptor=descriptor, timeout=10).validate()
        except (TimeoutError, RuntimeError, ValueError) as exc:
            raise ValueError(f"scorer validation failed: {str(exc) or '10-second validation timeout'}") from exc
        descriptor = descriptor.model_copy(update={"contract": validation.get("scoring_contract")})
        value = {"validation": validation, "id": identity, "name": scorer.name, "source_hash": source_hash,
                 "path": str(path), "descriptor": descriptor.model_dump(mode="json")}
        self.rsi_store.put(value, user_id, agent_id, "scorer")
        return {k: value[k] for k in ("id", "name", "source_hash", "descriptor", "validation")}

    async def import_rsi_evaluation_plan(self, agent_id, plan: EvaluationPlan, user_id):
        await self._agent(agent_id, user_id)
        data = plan.model_dump(mode="json")
        identity = "rsi_plan_" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]
        value = {"id": identity, "name": plan.name, "plan": data}
        training_suite, test_suite = plan.training_suite(), plan.test_suite()
        value["validation_case_count"] = sum(c.split == "validation" for c in training_suite.cases) if training_suite else None
        value["human_test_count"] = len(test_suite.cases) if test_suite else None
        self.rsi_store.put(value, user_id, agent_id, "evaluation_plan")
        return {"id": identity, "name": plan.name,
                "scorer": plan.scorer.model_dump(mode="json"), "goal": plan.goal,
                "builtin_scoring": plan.builtin_scoring.model_dump(mode="json"),
                "validation_case_count": value["validation_case_count"],
                "human_test_count": value["human_test_count"]}

    async def _rsi_scorer_selection(self, request, user_id, agent_id):
        selection = request.scorer
        if selection is None or selection.mode == "eval_agent":
            return None
        if selection.mode == "python":
            stored = self.rsi_store.get(selection.module_id, user_id, agent_id, "scorer")
            if stored.get("validation", {}).get("status") != "passed":
                raise ValueError("scorer has not passed validation")
            digest = hashlib.sha256(Path(stored["path"]).read_bytes()).hexdigest()
            if digest != stored["source_hash"] or selection.descriptor.model_dump(mode="json") != stored["descriptor"]:
                raise ValueError("frozen scorer source changed")
            if selection.binding_id is not None and selection.binding_id != digest:
                raise ValueError("RSI scorer binding changed since this experiment")
            return selection.model_copy(update={"binding_id": digest})
        plugin = await self._mcp_plugin(user_id)
        definition = await plugin.get_tool(selection.tool, run_id="rsi-scorer-admission")
        binding = scorer_binding(selection, plugin, definition)
        if selection.binding_id is not None and selection.binding_id != binding:
            raise ValueError("RSI scorer binding changed since this experiment")
        return selection.model_copy(update={"binding_id": binding})

    def _initialize_rsi(self):
        self = cast("DesktopV2Service", self)
        self.rsi_store = RsiStore(self.runtime_root / "rsi.sqlite3")
        self._rsi_tasks = {}
        self._rsi_cursors = {}

    @property
    def rsi_active(self):
        self = cast("DesktopV2Service", self)
        return any(not task.done() for task in self._rsi_tasks.values()) or self.rsi_store.external_active()

    async def _close_rsi(self):
        self = cast("DesktopV2Service", self)
        tasks = tuple(self._rsi_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _agent_bundle(self, agent):
        self = cast("DesktopV2Service", self)
        return (await self._agent_snapshot(agent))[0]

    async def _agent_snapshot(self, agent):
        self = cast("DesktopV2Service", self)
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
        self = cast("DesktopV2Service", self)
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
        self = cast("DesktopV2Service", self)
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
            "scorers": [{k: p[k] for k in ("id", "name", "source_hash", "descriptor", "validation")}
                        for p in self.rsi_store.list(user_id, agent_id, "scorer")],
            "evaluation_plans": [{"id": p["id"], "name": p["name"],
                "scorer": p["plan"]["scorer"], "goal": p["plan"].get("goal"),
                "builtin_scoring": p["plan"].get("builtin_scoring", {"mode": "quality"}),
                "validation_case_count": p.get("validation_case_count"),
                "human_test_count": p.get("human_test_count")}
                for p in self.rsi_store.list(user_id, agent_id, "evaluation_plan")],
        }

    async def rsi_version(self, agent_id, version_id, user_id):
        self = cast("DesktopV2Service", self)
        await self._agent(agent_id, user_id)
        return self.rsi_store.get(version_id, user_id, agent_id, "version")

    async def rsi_run(self, agent_id, run_id, user_id, *, after_sequence=0, compact=False):
        self = cast("DesktopV2Service", self)
        await self._agent(agent_id, user_id)
        value = self.rsi_store.get(run_id, user_id, agent_id, "run")
        path = rsi_journal(self.runtime_root / "rsi" / run_id, value, existing=True)
        events = []
        if after_sequence < 0:
            raise ValueError("after_sequence must be nonnegative")
        if path.exists():
            with path.open(encoding="utf-8") as journal:
                journal.seek(self._rsi_cursors.get((run_id, path.name, after_sequence), 0))
                while line := journal.readline():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    if event["sequence"] > after_sequence:
                        events.append(event)
                        self._rsi_cursors[(run_id, path.name, event["sequence"])] = journal.tell()
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
        if compact:
            from app.v2.desktop.backend.rsi_presentation import compact_rsi_payload
            return compact_rsi_payload(value)
        return value

    async def start_rsi(self, agent_id, request: RsiStart, user_id):
        self = cast("DesktopV2Service", self)
        if request.evaluation_plan_id:
            stored = self.rsi_store.get(request.evaluation_plan_id, user_id, agent_id, "evaluation_plan")
            plan = EvaluationPlan.model_validate(stored["plan"])
            if request.suite is not None or request.human_test_suite is not None or request.scorer is not None:
                raise ValueError("selected evaluation plan is the single source of suites and scorer")
            training_suite, test_suite = plan.training_suite(), plan.test_suite()
            request = request.model_copy(update={"suite": training_suite, "human_test_suite": test_suite,
                "validation_case_count": sum(c.split == "validation" for c in training_suite.cases) if training_suite else request.validation_case_count,
                "human_test_count": len(test_suite.cases) if test_suite else request.human_test_count,
                "scorer": plan.scorer, "builtin_scoring": plan.builtin_scoring})
        if request.dataset is not None:
            if request.suite is not None or request.human_test_suite is not None:
                raise ValueError("dataset is the single source of imported cases")
            training_suite, test_suite = request.dataset.optimization_suite(), request.dataset.human_test_suite()
            request = request.model_copy(update={"suite": training_suite, "human_test_suite": test_suite,
                "validation_case_count": sum(c.split == "validation" for c in training_suite.cases),
                "human_test_count": len(test_suite.cases) if test_suite else 0})
        if request.scorer_id is not None:
            if request.scorer is not None:
                raise ValueError("select one scorer")
            stored = self.rsi_store.get(request.scorer_id, user_id, agent_id, "scorer")
            request = request.model_copy(update={"scorer": ScorerSelection(mode="python",
                module_id=stored["id"], descriptor=stored["descriptor"])})
        selection = await self._rsi_scorer_selection(request, user_id, agent_id)
        if selection is not None:
            request = request.model_copy(update={"scorer": selection})
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
            native_tools.update(generated_tools(package.files))
            environment = await self._rsi_case_environment(request, user_id)
            if environment is not None:
                native_tools.update(d.name for d in await environment.definitions())
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
                "evaluation_plan_id": request.evaluation_plan_id,
                "scorer": request.scorer.model_dump(mode="json") if request.scorer else None,
                "scorer_id": request.scorer_id,
                "builtin_scoring": request.builtin_scoring.model_dump(mode="json"),
                "environment_fingerprint": environment.fingerprint if environment else None,
                "initial_training_case_count": request.initial_training_case_count,
                "training_cases_per_round": request.training_cases_per_round,
                "max_system_prompt_chars": request.max_system_prompt_chars,
                "max_skill_chars": request.max_skill_chars,
                "max_skill_count": request.max_skill_count,
                "max_edit_repairs": request.max_edit_repairs,
                "evaluation_repeats": request.evaluation_repeats,
                "human_test_repeats": request.human_test_repeats,
                "evaluation_aggregation": request.evaluation_aggregation,
                "rounds": request.rounds,
                "validation_case_count": request.validation_case_count,
                "human_test_count": len(request.human_test_suite.cases) if request.human_test_suite else request.human_test_count,
                "max_concurrency": request.max_concurrency,
                "stopping_policy": request.stopping_policy.model_dump(mode="json"),
                "generated_tool_audit_required": "tools" in request.optimization_scope,
                "timeout_seconds": rsi_timeout_seconds(request),
                "optimization_scope": request.optimization_scope,
                "model_provider_id": internal_provider.id,
                "created_at": utc_now().isoformat(),
                "base_fingerprint": fingerprint(agent),
                "stage": "queued",
                "iteration": 0,
                "resumable": True,
                "recovery_engine_id": engine_fingerprint(),
                "recovery_binding_id": rsi_binding(agent, provider, internal_provider),
            }
            root = self.runtime_root / "rsi" / run_id
            root.mkdir(parents=True, mode=0o700)
            from .rsi_artifacts import write_directory_index
            write_directory_index(root)
            private_json(root / "resume-context.json", {"request": request.model_dump(mode="json"),
                "package": package.model_dump(mode="json"), "assets": assets})
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

    async def _rsi_case_environment(self, request, user_id):
        from sagents.v2.optimization.environment import McpCaseEnvironment
        binding = request.dataset.environment if request.dataset else None
        if binding is None:
            return None
        records = {r.name: r for r in await self.catalog.list_mcp(user_id) if not r.disabled}
        if any(name not in records for name in binding.mcp_servers):
            raise ValueError('dataset requires an unavailable MCP server')
        return McpCaseEnvironment(tuple(self._mcp_config(records[name]) for name in binding.mcp_servers))

    async def resume_rsi(self, agent_id, run_id, user_id):
        self = cast("DesktopV2Service", self)
        async with self._agent_update_lock:
            agent = await self._agent(agent_id, user_id)
            value = self.rsi_store.get(run_id, user_id, agent_id, "run")
            if value.get("external_host"):
                raise ValueError("External experiments resume through their owning host")
            if value["status"] not in {"interrupted", "cancelled", "failed"} or not value.get("resumable"):
                raise ValueError("This RSI run cannot resume")
            if any(r["status"] in {"queued", "running"} for r in self.rsi_store.list(user_id, agent_id, "run")):
                raise ValueError("This Agent already has an active RSI run")
            if value.get("recovery_engine_id") != engine_fingerprint():
                raise ValueError("RSI engine changed since this experiment; use the original engine to resume")
            if fingerprint(agent) != value["base_fingerprint"]:
                raise ValueError("Agent configuration changed since this experiment")
            root = self.runtime_root / "rsi" / run_id
            frozen = json.loads((root / "resume-context.json").read_text())
            request = RsiStart.model_validate(frozen["request"])
            await self._rsi_scorer_selection(request, user_id, agent_id)
            provider = await self._provider(agent, user_id)
            internal_provider = provider
            if request.model_provider_id:
                internal_provider = await self.catalog.get_model_provider(request.model_provider_id, user_id)
                if internal_provider is None or not internal_provider.api_key:
                    raise ValueError("RSI model is not configured")
            if rsi_binding(agent, provider, internal_provider) != value["recovery_binding_id"]:
                raise ValueError("RSI model configuration changed since this experiment")
            source = rsi_journal(root, value, existing=True)
            if not source.exists():
                if value.get("sequence", 0):
                    raise ValueError("RSI journal is unavailable for recovery")
                source = None
            value.update(status="queued", recovery_journal_name=source.name if source else None, journal_name=f"audit-resume-{new_id('part')}.jsonl",
                         resumed_at=utc_now().isoformat(), resume_count=value.get("resume_count", 0) + 1)
            value.pop("finished_at", None)
            value.pop("error_type", None)
            self._rsi_cursors = {key: offset for key, offset in self._rsi_cursors.items() if key[0] != run_id}
            self.rsi_store.put(value, user_id, agent_id, "run")
            task = asyncio.create_task(self._execute_rsi(agent,
                AgentPackageBundle.model_validate(frozen["package"]), provider, internal_provider,
                request, value, frozen["assets"], resume_from=source), name=run_id)
            self._rsi_tasks[run_id] = task
            task.add_done_callback(lambda _: self._rsi_tasks.pop(run_id, None))
            return value.copy()

    async def _execute_rsi(
        self, agent, package, provider, internal_provider, request, value, assets, *, resume_from=None
    ):
        self = cast("DesktopV2Service", self)
        root = self.runtime_root / "rsi" / value["id"]
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        user, identity = agent.user_id, agent.agent_id
        value = dict(value)
        test_observer = None
        scorer_gateway = None

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
            if test_observer is not None:
                test_observer.observe(event)
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
                value["activity"] = data.get("activity", data["role"])
            if event["event"] == "optimization_stopped":
                value["termination"] = data
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
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
            project = await self.add_project(f"RSI · {agent.name} · {value['id'][-8:]}", str(workspace))
            value.update(workspace_id=project.id, workspace_path=project.path)
            value["status"] = "running"
            save()
            manifest_data = package.manifest.model_dump(mode="json")
            manifest_data["runtime"]["capabilities"]["tool.provider"] = {
                "plugin": OfficialToolPlugin.plugin_id
            }
            package = AgentPackageBundle(manifest=manifest_data, files=package.files)
            roles = {}
            role_provider = {}
            continuation = package.manifest.runtime.capabilities.get("agent.continuation-policy")
            continuation_plugin = (getattr(continuation, "plugin", "unknown") if continuation is not None
                else "sage.agent.continuation.deterministic")
            target_execution_context = {"continuation_policy": continuation_plugin}
            if continuation_plugin == "sage.agent.continuation.deterministic":
                target_execution_context.update(
                    text_without_tool_calls="ends the current run unless an earlier explicit status or host rule overrides completion",
                    tool_steps="pending tool calls continue before the final response; separate tool/model steps are not separate user turns")
            # Describe the host's actual default/explicit selection to internal
            # roles only. The selected target package and its baseline stay intact.
            execution_guidance = "\nHost target execution semantics: " + json.dumps(target_execution_context, ensure_ascii=False)
            for role in (
                "evaluator",
                "tuner",
                "designer",
                "reviewer",
                "suite_reviewer",
            ):
                manifest = self._manifest(agent, internal_provider,
                                          ("file_read", "file_write", "file_update") if role == "tuner" else ("file_read", "file_write") if role == "evaluator" else (), ())
                definition = manifest.agents[identity].model_copy(
                    update={
                        "instructions": Instructions(
                            inline=f"You are the independent RSI {role}. Follow the supplied JSON schema. Preserve the original agent goal. Use reusable improvements; never memorize test answers." + execution_guidance
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
            environment = await self._rsi_case_environment(request, user)
            if (environment.fingerprint if environment else None) != value.get('environment_fingerprint'):
                raise ValueError('RSI case environment changed since experiment admission')
            environment_definitions = await environment.definitions() if environment else ()
            environment_tools = {d.name for d in environment_definitions}
            definitions = (*definitions, *environment_definitions)
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
            tool_scopes.update(scope for definition in definitions if definition.name in {"file_read", "file_write", "file_update"}
                               for scope in definition.required_scopes)
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
                    else {"file_read", "file_write", "file_update"} if bundle.manifest.metadata.id == "desktop.rsi.tuner"
                    else {"file_read", "file_write"} if bundle.manifest.metadata.id == "desktop.rsi.evaluator" else set()
                )
                created = generated_tools(bundle.files)
                if bundle.manifest.metadata.id == package.manifest.metadata.id:
                    if "tools" in request.optimization_scope:
                        permitted = permitted | set(created)
                    else:
                        if created != generated_tools(package.files):
                            raise PermissionError(
                                "Generated tools changed outside tools scope"
                            )
                        permitted = permitted | set(created)
                elif created:
                    raise PermissionError("RSI roles cannot acquire generated tools")
                if set(bundle.manifest.agents[identity].tools) - permitted:
                    raise PermissionError("Tools exceed the frozen RSI grant")

            async def factory(bundle, workspace, context):
                tuner_workspace = None
                editor_workspace = None
                evaluation_workspace = workspace / "evaluation" if bundle.manifest.metadata.id == "desktop.rsi.evaluator" else None
                if evaluation_workspace is not None:
                    evaluation_workspace.mkdir(parents=True, exist_ok=True)
                if bundle.manifest.metadata.id == "desktop.rsi.tuner":
                    from sagents.v2.optimization.package_workspace import editor_binding
                    editor_workspace = editor_binding(bundle, root / "workspace")
                    from sagents.v2.optimization.evidence import materialize_tuner_workspace
                    tuner_workspace = editor_workspace or materialize_tuner_workspace(root / "workspace", bundle.files)
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
                    if bundle.manifest.metadata.id == package.manifest.metadata.id and call.definition.name in environment_tools:
                        return ToolOperationAssessment(action=ToolPolicyAction.ALLOW,
                            reason='Explicit per-case simulated MCP environment')
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
                    CapabilityOffer,
                    ExtensionDescriptor,
                    ExtensionRegistration,
                    ExtensionScope,
                )

                registrations = []
                generated = generated_tool_provider(bundle.files)
                generated_plugin = "com.sage.desktop.rsi.generated-tools"
                if generated.definitions:
                    registrations.append(
                        ExtensionRegistration(
                            descriptor=ExtensionDescriptor(
                                plugin_id=generated_plugin,
                                name="Generated pure tools",
                                version="2",
                                provides=(
                                    CapabilityOffer(
                                        capability="tool.provider", api_version="2"
                                    ),
                                ),
                                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                                config_schema={
                                    "type": "object",
                                    "additionalProperties": False,
                                },
                            ),
                            factory=lambda context, deps: generated,
                            ownership="borrowed",
                        )
                    )
                choices = dict(bundle.manifest.runtime.capabilities)
                if environment is not None and bundle.manifest.metadata.id == package.manifest.metadata.id:
                    from sagents.v2.optimization.runner import OPTIMIZATION_CASE
                    from sagents.v2.tool.provider import ToolProvider
                    case_plugin = environment.for_workspace(workspace, OPTIMIZATION_CASE.get())
                    registrations.append(ExtensionRegistration(
                        descriptor=ExtensionDescriptor(plugin_id='sage.rsi.case-mcp', name='Isolated case tools', version='1',
                            provides=(CapabilityOffer(capability='tool.provider', api_version='2'),),
                            supported_scopes=frozenset({ExtensionScope.PROCESS}),
                            config_schema={'type': 'object', 'additionalProperties': False}),
                        factory=lambda context, deps: ToolProvider(case_plugin, case_plugin), ownership='borrowed'))
                policy = DefaultToolPolicy(
                    operation_assessor=assess,
                    operation_assessor_id="desktop.rsi.local-workspace/v4-package-editor",
                )
                for capability, value in (
                    ("model.provider", model),
                    ("execution.model-budget", self.model_budget),
                    ("skill.provider", skills),
                    ("agent.tool-policy", policy),
                ):
                    plugin = "com.sage.desktop.rsi." + capability.replace(".", "-")
                    registrations.append(
                        ExtensionRegistration(
                            descriptor=ExtensionDescriptor(
                                plugin_id=plugin,
                                name=capability,
                                version="2",
                                provides=(
                                    CapabilityOffer(
                                        capability=capability, api_version="2"
                                    ),
                                ),
                                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                                config_schema={
                                    "type": "object",
                                    "additionalProperties": False,
                                },
                            ),
                            factory=lambda context, deps, value=value: value,
                            ownership="borrowed",
                        )
                    )
                    choices[capability] = CapabilitySelection(plugin=plugin)
                choices["session.store"] = CapabilitySelection(
                    plugin="sage.session.filesystem",
                    config={"root": str(workspace / "sessions")},
                )
                choices["execution.binding"] = CapabilitySelection(
                    plugin="sage.execution.binding.local-workspace",
                    config={
                        "workspace": str(evaluation_workspace if evaluation_workspace is not None else tuner_workspace if tuner_workspace is not None else workspace / "work"),
                        "policy": {"process": {"enabled": False},
                                   **({"filesystem": {"allowed_operations": ["read", "list", "write", "create"], "protected_paths": ["inputs", "control.json"]}} if evaluation_workspace is not None else {}),
                                   **({"filesystem": {"allowed_operations": ["read", "list", "write", "create"], "protected_paths": ["evidence"]}} if editor_workspace else {})},
                    },
                )
                choices.setdefault(
                    "tool.provider", CapabilitySelection(plugin="sage.tool.official")
                )
                if generated.definitions:
                    choices["tool.provider"] = (
                        CapabilitySelection(plugin="sage.tool.official"),
                        CapabilitySelection(plugin=generated_plugin),
                    )
                if environment is not None and bundle.manifest.metadata.id == package.manifest.metadata.id:
                    providers = choices['tool.provider']
                    choices['tool.provider'] = (*(providers if isinstance(providers, tuple) else (providers,)),
                        CapabilitySelection(plugin='sage.rsi.case-mcp'))
                # RSI roles have their own structured evaluator. Select tools
                # directly unless the frozen package explicitly chooses another
                # policy, so default discovery cannot become another model task.
                choices.setdefault(
                    "tool.selection-policy",
                    CapabilitySelection(plugin="sage.tool-selection.direct"),
                )
                choices.setdefault(
                    "agent.continuation-policy",
                    CapabilitySelection(plugin="sage.agent.continuation.deterministic"),
                )
                runtime = bundle.manifest.runtime.model_copy(
                    update={
                        "capabilities": choices,
                        "state_root": str(workspace / "sessions"),
                    }
                )
                return ApplicationConfiguration(
                    tuple(registrations), runtime, self._model_catalog(agent, selected)
                )

            constraints = OptimizationConstraints(
                allow_instruction_guidance=False,
                max_system_prompt_chars=request.max_system_prompt_chars,
                max_skill_chars=request.max_skill_chars,
                max_skill_count=request.max_skill_count,
                editable_files=tuple(
                    name for name in package.files if name != "desktop/context.json"
                ),
                creatable_files=("skills/rsi-guidance/SKILL.md",),
                allow_skill_changes=True,
                allow_skill_creation=True,
                skill_candidates={
                    "rsi-guidance": "Reusable methods for the original goal"
                },
                allow_tool_changes=True,
                allow_tool_creation=True,
                require_clean_generated_tools="tools" in request.optimization_scope,
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
            shared_calls = asyncio.Semaphore(request.max_concurrency)
            optimizer.runner = SharedCallLimitRunner(optimizer.runner, shared_calls)
            context = RequestContext(actor=ActorRef(
                principal_id=user, principal_type=PrincipalType.USER,
                scopes=tuple(sorted(tool_scopes)),
            ))
            scorer = None
            if request.scorer is not None and request.scorer.mode == "python":
                selection = await self._rsi_scorer_selection(request, user, identity)
                stored = self.rsi_store.get(selection.module_id, user, identity, "scorer")
                from .scorer_model_api import ScorerModelGateway
                model = await self._model_provider(internal_provider, agent, enable_thinking=False)
                def audit_scorer_model(record):
                    # Separate metadata-only audit, never merged into tuning evidence.
                    path = root / "scorer-model-calls.jsonl"
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stats = value.setdefault("scorer_model_usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
                    stats["calls"] += 1
                    for key in ("input_tokens", "output_tokens"):
                        stats[key] += record.get("usage", {}).get(key, 0)
                    save()
                scorer_gateway = ScorerModelGateway(provider=model, model=internal_provider.model,
                    model_binding=internal_provider.id, run_id=value["id"], concurrency=shared_calls,
                    model_budget=self.model_budget, max_output_tokens=internal_provider.max_tokens,
                    audit=audit_scorer_model, redact=(internal_provider.api_key,))
                await scorer_gateway.start()
                value["scorer_model_transport"] = "sage-model-provider"
                scorer = PythonExecutionScorer(path=stored["path"], source_hash=stored["source_hash"],
                    descriptor=selection.descriptor, model_api_factory=scorer_gateway.bind)
            elif request.scorer is not None and request.scorer.mode == "mcp":
                selection = await self._rsi_scorer_selection(request, user, identity)
                scorer = McpExecutionScorer(selection, await self._mcp_plugin(user), context, value["id"])
            if request.human_test_count or request.human_test_suite:
                # Separate runner, fresh Applications/Sessions and private evidence.
                # This sink never supplies data to optimizer.optimize().
                test_root = root / "human-test"
                test_runner = IsolatedOptimizationRunner(
                    builder_factory=factory, authorize=authorize, root=test_root,
                    run_metadata=optimizer.runner.run_metadata,
                )
                test_runner = SharedCallLimitRunner(test_runner, shared_calls)
                def publish_test(records):
                    value["test_observations"] = records
                    save()
                try:
                    test_suite = request.human_test_suite
                    if test_suite is None and value.get("human_test_suite"):
                        test_suite = OptimizationTestSuite.model_validate(value["human_test_suite"])
                    if test_suite is None:
                        generation = await AgentPackageTestGenerator(
                            runner=test_runner, designer=roles["designer"],
                        ).generate_split_with_record(
                            package, context=context, goal=request.goal, split="test",
                            case_count=request.human_test_count, max_cases=request.human_test_count,
                            timeout_seconds=240,
                        )
                        test_suite = OptimizationTestSuite(cases=generation.suite.cases)
                    (test_root / "suite.json").write_text(test_suite.model_dump_json())
                    value["human_test_suite"] = test_suite.model_dump(mode="json")
                    test_observer = HumanTestObserver(
                        baseline=package, suite=test_suite, publish=publish_test,
                        completed_records=value.get("test_observations", ()),
                        concurrency=request.max_concurrency,
                        repeats=request.human_test_repeats,
                        evaluate=IsolatedTestEvaluator(
                            runner=test_runner, evaluator=roles["evaluator"], driver=roles["designer"],
                            evidence_directory=test_root / "evaluations",
                            retry_local_evaluations=True, restart_incomplete_dialogues=True,
                            context=context, goal=request.goal,
                            scorer=scorer,
                            require_clean_generated_tools=constraints.require_clean_generated_tools,
                        ),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    value["human_test_error"] = type(error).__name__
                    save()
            async def run_optimizer(source):
                return await optimizer.optimize(
                    package,
                    context=context,
                    goal=request.goal,
                    rounds=request.rounds,
                    stopping_policy=request.stopping_policy,
                    require_diverse_suite=request.suite is None,
                    constraints=constraints,
                    scorer=scorer,
                    optimization_scope=request.optimization_scope,
                    builtin_scoring=request.builtin_scoring,
                    suite=request.suite,
                    final_max_cases=0,
                    evaluation_repeats=request.evaluation_repeats,
                    evaluation_aggregation=request.evaluation_aggregation,
                    max_edit_repairs=request.max_edit_repairs,
                    initial_training_case_count=request.initial_training_case_count,
                    training_cases_per_round=request.training_cases_per_round,
                    grow_training=request.grow_training,
                    refresh_incumbent=request.refresh_incumbent,
                    validation_case_count=request.validation_case_count,
                    max_concurrency=request.max_concurrency,
                    call_timeout_seconds=240,
                    timeout_seconds=rsi_timeout_seconds(request),
                    journal_path=rsi_journal(root, value),
                    evidence_directory=root / "workspace" / "iterations",
                    tuner_workspace=root / "workspace",
                    edit_package_files=True,
                    resume_from=source,
                    recovery_binding_id=value.get("recovery_binding_id"),
                    restart_incomplete=True,
                    restart_package_editor=True,
                    restart_file_evaluator=True,
                    journal_start_sequence=value.get("sequence", 0) if source else 0,
                    on_event=observe,
                )
            source = resume_from
            for failure in range(13):
                try:
                    result = await run_optimizer(source)
                    break
                except OptimizationTransientFailure:
                    if failure == 12:
                        raise
                    source = rsi_journal(root, value)
                    delay = min(60, 2 ** min(failure + 1, 6))
                    value.update(recovery_journal_name=source.name, journal_name=f"audit-retry-{new_id('part')}.jsonl",
                                 stage="infrastructure_retry",
                                 infrastructure_retry={"attempt": failure + 1, "wait_seconds": delay},
                                 automatic_recoveries=value.get("automatic_recoveries", 0) + 1)
                    save()
                    await self._rsi_retry_wait(delay)

            if test_observer is not None:
                value["stage"] = "human_test_pending"
                save()
                await test_observer.finish()
            result_path = root / "result.json"
            result_path.write_text(result.model_dump_json(), encoding="utf-8")
            os.chmod(result_path, 0o600)
            for item in result.iterations:
                stored = self.rsi_store.get(
                    f"{value['id']}.{item.iteration}", user, identity, "version"
                )
                stored["evaluation_protocol"] = "adaptive_validation"
                stored.update(
                    record=item.model_dump(mode="json"),
                    ready=True,
                    review=item.review.model_dump(mode="json") if item.review else None,
                )
                self.rsi_store.put(stored, user, identity, "version")
            value.update(
                status="completed",
                recommended_hash=(result.candidate_package.content_hash
                                  if result.report.goal_verified else None),
                retained_hash=result.candidate_package.content_hash,
                termination=result.report.termination.model_dump(mode="json"),
                goal_verified=result.report.goal_verified,
                recommendation_block_reason=result.report.recommendation_block_reason,
            )
        except asyncio.CancelledError:
            value["status"] = "interrupted"
            raise
        except Exception as error:
            # Provider errors can contain secrets. Persist only the exception type.
            if (code := builtin_scoring_failure_code(error)) is not None:
                value["error_code"] = code
            value.update(
                status="failed",
                error_type=type(error).__name__,
                exit_reason="timeout" if isinstance(error, TimeoutError) else "error",
            )
        finally:
            if test_observer is not None:
                await test_observer.cancel()
                (root / "human-test" / "evidence.json").write_text(
                    json.dumps(test_observer.evidence, ensure_ascii=False), encoding="utf-8",
                )
            if scorer_gateway is not None:
                await scorer_gateway.close()
            value["finished_at"] = utc_now().isoformat()
            save()

    async def _rsi_retry_wait(self, seconds):
        await asyncio.sleep(seconds)

    async def cancel_rsi(self, agent_id, run_id, user_id):
        self = cast("DesktopV2Service", self)
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
        self = cast("DesktopV2Service", self)
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
