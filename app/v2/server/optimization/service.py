"""Durable RSI operations; optimization never changes the active Agent."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

from app.v2.server.catalog.packages import package_owner
from app.v2.server.optimization.contracts import RsiStart
from app.v2.server.optimization.repository import RsiRepository
from app.v2.server.optimization.runtime import RsiRuntime, binding_id, internal_roles, validate_target
from app.v2.server.observability.logging import get_logger
from app.v2.server.skills.runtime import CatalogSkillProvider
from sagents.v2 import AgentPackageOptimizer
from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.optimization.contracts import OptimizationConstraints
from sagents.v2.optimization.recovery import engine_fingerprint
from sagents.v2.optimization.observer import SharedCallPool, SharedCallLimitRunner

LOGGER = get_logger(__name__)


class ServerRsiService:
    def __init__(self, host, quota):
        self.host, self.quota = host, quota
        self.packages = host.agent_management.store
        self.store = RsiRepository(self.packages)
        self.root = host.paths.runtime_root / "rsi"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.tasks = {}
        self.leases = {}
        self.progress = {}
        self.closing = False

    async def close(self):
        self.closing = True
        tasks = tuple(self.tasks.values())
        leases = dict(self.leases)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for run, (user, agent, token) in leases.items():
            value = await self.store.get(package_owner(user), agent, run)
            if value["status"] == "running" and value.get("lease_token") == token:
                await self.store.update(package_owner(user), agent, run, token,
                    {"status": "interrupted", "stage": "interrupted", "lease_until": 0})

    async def _agent(self, user, agent):
        if await self.host.users.get_by_id(user) is None:
            raise PermissionError("RSI owner no longer exists")
        return await self.host.catalog_store.get_agent(user, agent)

    async def start(self, user, agent, request: RsiStart):
        current = await self._agent(user, agent)
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        owner = package_owner(user)
        old = await self.store.by_request(owner, agent, request.request_id, digest)
        if old is not None:
            return self._public(old)
        if self.closing or len(self.tasks) >= self.host.settings.max_pending_runs:
            raise ValueError("RSI capacity reached")
        package = current.package_bundle
        validate_target(package)
        catalog = await self.host.catalog_store.editor_catalog(user)
        if not self.host.execution.has_model(catalog):
            raise ValueError("RSI model is unavailable")
        from app.v2.server.runtime.loop import package_model_record
        if request.model_id not in (None, "default") and package_model_record(catalog, request.model_id) is None:
            raise ValueError("RSI model_id is unavailable")
        files = dict(package.files)
        records = tuple(await self.host.skill_catalog.bound_skills(owner_user_id=user, agent_id=agent))
        provider = CatalogSkillProvider(records, self.host.paths.data_root, package_files=files)
        for name in package.manifest.agents[agent].skills:
            bundle = await provider.fetch(name, run_id="rsi-admission")
            for relative, content in bundle.files.items():
                try:
                    files[f"skills/{name}/{relative}"] = content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("RSI package Skills currently require UTF-8 resources") from exc
        snapshot = package.model_copy(update={"files": files})
        if files != package.files:
            snapshot = snapshot.model_copy(update={"manifest": snapshot.manifest.model_copy(update={
                "metadata": snapshot.manifest.metadata.model_copy(update={"version": "rsi-seed-" + snapshot.content_hash[:24]})})})
        snapshot = type(package).model_validate(snapshot.model_dump(mode="json"))
        snapshot_ref = await self.packages.save(owner, snapshot)
        value = {"id": new_id("rsi"), "agent_id": agent, "status": "queued", "stage": "queued",
            "request": request.model_dump(mode="json"), "base_package_ref": package.content_hash,
            "snapshot_ref": snapshot_ref, "binding_id": binding_id(catalog, snapshot, self.host.settings),
            "engine_id": engine_fingerprint(), "created_at": utc_now().isoformat(), "journals": [], "versions": []}
        value, created = await self.store.create(owner, agent, request.request_id, digest, value)
        if created:
            value = await self._launch(user, agent, value)
        return self._public(value)

    async def _launch(self, user, agent, value):
        if self.closing or len(self.tasks) >= self.host.settings.max_pending_runs:
            raise ValueError("RSI capacity reached")
        owner = package_owner(user)
        package = await self.packages.get(owner, value["snapshot_ref"])
        catalog = await self.host.catalog_store.editor_catalog(user)
        if engine_fingerprint() != value["engine_id"] or binding_id(catalog, package, self.host.settings) != value["binding_id"]:
            raise ValueError("RSI recovery binding conflict: engine or model configuration changed")
        token = new_id("lease")
        value = await self.store.claim(owner, agent, value["id"], token)
        root = self.root / value["id"]
        root.mkdir(mode=0o700, exist_ok=True)
        previous = None
        for name in reversed(value["journals"]):
            path = root / name
            if path.is_file() and path.stat().st_size:
                previous = path
                break
        journal = f"attempt-{new_id('log')}.jsonl"
        value = await self.store.update(owner, agent, value["id"], token,
            {"journals": [*value["journals"], journal], "stage": "starting", "error_type": None,
             "error_code": None, "failure_stage": None, "finished_at": None})
        task = asyncio.create_task(self._execute(user, agent, value, package, catalog, root / journal, previous), name=value["id"])
        self.tasks[value["id"]] = task
        self.leases[value["id"]] = (user, agent, token)
        task.add_done_callback(lambda done: self._done(value["id"], done))
        return value

    def _done(self, run, task):
        if self.tasks.get(run) is task:
            self.tasks.pop(run, None)
            self.leases.pop(run, None)
            self.progress.pop(run, None)
        if not task.cancelled() and task.exception() is not None:
            LOGGER.exception("rsi.background.failed", "RSI task failed", task.exception(), run_id=run)

    async def _heartbeat(self, user, agent, value, task):
        try:
            while True:
                await asyncio.sleep(5)
                updated = await self.store.update(package_owner(user), agent, value["id"], value["lease_token"],
                    {**self.progress.get(value["id"], {}), "lease_until": time.time() + self.store.lease_seconds})
                if updated.get("cancel_requested"):
                    task.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            task.cancel()  # A lost database/lease cannot keep executing unowned work.

    async def _execute(self, user, agent, value, package, catalog, journal, previous):
        heartbeat = asyncio.create_task(self._heartbeat(user, agent, value, asyncio.current_task()))
        owner, token = package_owner(user), value["lease_token"]
        terminal = {"status": "interrupted", "stage": "interrupted"}
        try:
            request = RsiStart.model_validate(value["request"])
            roles = internal_roles(package, request.model_id)
            context = self.host.contexts.for_user(user)
            runtime = RsiRuntime(self.host, package, catalog, context, journal.parent, roles, self.quota)
            runner = SharedCallLimitRunner(runtime.runner, SharedCallPool(request.max_concurrency))
            optimizer = AgentPackageOptimizer(runner=runner, evaluator=roles["evaluator"],
                tuner=roles["tuner"], test_designer=roles["designer"], test_driver=roles["user_simulator"])
            constraints = OptimizationConstraints(allow_instruction_guidance=False,
                max_system_prompt_chars=request.max_system_prompt_chars, max_skill_chars=request.max_skill_chars,
                max_skill_count=request.max_skill_count, allow_skill_changes=True, allow_skill_creation=True,
                editable_files=tuple(name for name in package.files if name.startswith("skills/") or
                    name == package.manifest.agents[agent].instructions.path))

            def observe(event):
                self.progress[value["id"]] = {"stage": event["event"], "sequence": event["sequence"],
                    "round": event["data"].get("round", self.progress.get(value["id"], {}).get("round", 0))}

            result = await optimizer.optimize(package, context=context, goal=request.goal, agent_id=agent,
                suite=request.suite, rounds=request.rounds, constraints=constraints,
                optimization_scope=request.optimization_scope, stopping_policy=request.stopping_policy,
                validation_case_count=sum(c.split == "validation" for c in request.suite.cases) if request.suite else request.validation_case_count,
                initial_training_case_count=request.initial_training_case_count,
                training_cases_per_round=request.training_cases_per_round, grow_training=request.training_cases_per_round > 0,
                evaluation_repeats=request.evaluation_repeats, max_edit_repairs=request.max_edit_repairs,
                max_concurrency=request.max_concurrency, call_timeout_seconds=request.call_timeout_seconds,
                timeout_seconds=request.timeout_seconds, final_max_cases=0,
                journal_path=journal, resume_from=previous, recovery_binding_id=value["binding_id"],
                restart_incomplete=True, restart_readonly_roles=("evaluation", "tuning", "test_dialogue"),
                journal_start_sequence=value.get("sequence", 0), on_event=observe)
            versions = []
            for iteration in result.iterations:
                if iteration.evaluation is None:
                    continue
                ref = await self.packages.save(owner, iteration.package)
                versions.append({"version_id": f"{value['id']}.{iteration.iteration}", "iteration": iteration.iteration,
                    "package_ref": ref, "recommended": iteration.recommended, "reason": iteration.reason})
            candidate_ref = await self.packages.save(owner, result.candidate_package)
            result_name = journal.stem + "-result.json"
            await bounded_to_thread("skill-io", lambda: write_result(journal.parent / result_name, result.model_dump(mode="json")))
            terminal = {"status": "completed", "stage": "completed", "versions": versions,
                "candidate_ref": candidate_ref, "goal_verified": result.report.goal_verified,
                "improved": result.report.improved, "result_name": result_name}
        except asyncio.CancelledError:
            pass
        except Exception as error:
            terminal = {"status": "failed", "stage": "failed", "error_type": type(error).__name__,
                "error_code": getattr(getattr(error, "info", None), "code", None),
                "failure_stage": self.progress.get(value["id"], {}).get("stage")}
            LOGGER.warning("rsi.failed", "RSI experiment failed", run_id=value["id"], error_type=type(error).__name__)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await self.store.update(owner, agent, value["id"], token,
                {**self.progress.get(value["id"], {}), **terminal, "finished_at": utc_now().isoformat(), "lease_until": 0})

    async def get(self, user, agent, run, *, include_result=True):
        await self._agent(user, agent)
        value = await self.store.get(package_owner(user), agent, run)
        result = self._public(value)
        result.update(self.progress.get(run, {}))
        if value["status"] == "running" and value.get("lease_until", 0) < time.time():
            result.update(status="interrupted", stage="interrupted")
        if include_result and value["status"] == "completed":
            result["result"] = await bounded_to_thread("skill-io", lambda: json.loads((self.root / run / value["result_name"]).read_text()))
        return result

    async def list(self, user, agent, *, limit=50, offset=0):
        await self._agent(user, agent)
        values = await self.store.list(package_owner(user), agent, limit=limit, offset=offset)
        return [self._public(value) for value in values]

    async def cancel(self, user, agent, run):
        await self._agent(user, agent)
        cancelled = await self.store.cancel(package_owner(user), agent, run)
        task = self.tasks.get(run)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            value = await self.store.get(package_owner(user), agent, run)
            if value["status"] == "running" and value.get("lease_token") == cancelled.get("lease_token"):
                await self.store.update(package_owner(user), agent, run, value["lease_token"],
                    {"status": "interrupted", "stage": "interrupted", "lease_until": 0})
        return await self.get(user, agent, run, include_result=False)

    async def resume(self, user, agent, run):
        await self._agent(user, agent)
        value = await self.store.get(package_owner(user), agent, run)
        return self._public(await self._launch(user, agent, value))

    async def version(self, user, agent, run, version):
        value = await self.get(user, agent, run, include_result=False)
        selected = next((v for v in value["versions"] if v["version_id"] == version), None)
        if selected is None:
            raise ValueError("RSI version not found")
        package = await self.packages.get(package_owner(user), selected["package_ref"])
        return {**selected, "package": package.model_dump(mode="json")}

    async def apply(self, user, agent, run, version, expected_ref):
        selected = await self.version(user, agent, run, version)
        value = await self.get(user, agent, run, include_result=False)
        if value["status"] != "completed":
            raise ValueError("RSI version conflict: experiment is incomplete")
        if expected_ref != value["base_package_ref"]:
            raise ValueError("RSI base package conflict; create a new experiment for the changed Agent")
        from sagents.v2.agent.management import AgentPackageBundle
        package = AgentPackageBundle.model_validate(selected["package"])
        await self.host.catalog.apply_rsi_package(user, agent, package, expected_ref)
        return {"agent_id": agent, "package_ref": package.content_hash, "previous_ref": expected_ref}

    @staticmethod
    def _public(value):
        result = {k: v for k, v in value.items() if k not in {"lease_token", "lease_until", "binding_id", "engine_id", "journals", "result_name"}}
        if value.get("status") == "running" and value.get("lease_until", 0) < time.time():
            result.update(status="interrupted", stage="interrupted")
        return result


def write_result(path: Path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
