"""Opt-in real τ-bench/SAgents RSI experiment (custom method, not a submission).

Install tau2 v1.0.1 in a separate environment and run with --help. Credentials
come from the explicitly selected Desktop catalog, stay in memory, and never
enter packages or result files. Official train tasks form an expanding host
curriculum. Optional human-only test checkpoints never enter optimization;
repeated final measurement uses frozen packages.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import hashlib
import random
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from examples.v2.host.registrations import provided, runtime_for
from sagents.v2 import (
    AgentPackageBundle, AgentPackageOptimizer, ApplicationConfiguration,
    IsolatedOptimizationRunner, OptimizationAgent, OptimizationCase,
    OptimizationConstraints, OptimizationSuite,
)
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.tool.provider import ToolProvider

TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
CURRENT_BRIDGE = contextvars.ContextVar("tau_bridge", default=None)
RUBRIC = "Use the unmodified official τ-bench reward for this complete simulated task."


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def compact_training_trace(simulation):
    """Preserve all action names/arguments and conversation boundaries for diagnosis."""
    rows = []
    for message in simulation.get("messages", []):
        role = message.get("role", "")
        row = {"role": role}
        if message.get("tool_calls"):
            row["tool_calls"] = message["tool_calls"]
        content = str(message.get("content") or "")
        limit = 240 if role == "tool" else 600
        if content:
            row["content"] = content[:limit]
            if len(content) > limit:
                row["content_truncated"] = True
        rows.append(row)
    text = json.dumps(rows, ensure_ascii=False)
    if len(text) > 8192:
        text = text[:2048] + "\n[... middle omitted ...]\n" + text[-6000:]
    return text


def task_case(task_id, split):
    return OptimizationCase(
        id=f"tau-{task_id}", input=json.dumps({"tau_task_id": task_id}),
        rubric=RUBRIC, split=split, coverage_tags=("official-retail-task",),
    )


def partition_tasks(splits, *, seed, initial_count, validation_count, test_count):
    train = list(splits["train"])
    test = list(splits["test"])
    if set(train) & set(test) or len(train) != len(set(train)) or len(test) != len(set(test)):
        raise ValueError("official task splits overlap or repeat")
    if initial_count + validation_count >= len(train):
        raise ValueError("leave some training tasks for later challenges")
    random.Random(seed).shuffle(train)
    random.Random(seed).shuffle(test)
    return {
        "training": train[:initial_count],
        "validation": train[initial_count:initial_count + validation_count],
        "challenge_pool": train[initial_count + validation_count:],
        "test": test[:test_count] if test_count else test,
    }


def package(identity, instructions, tools=()):
    data = BuiltinPackageFactory.create("assistant", package_id=identity).model_dump(mode="json")
    data["agents"]["assistant"].update({
        "instructions": {"inline": instructions}, "tools": list(tools),
        "budgets": {"max_steps": 48},
    })
    return AgentPackageBundle(manifest=data)


class TauExperiment:
    def __init__(self, args):
        from app.v2.desktop.backend.catalog import DesktopModelProviderRecord, default_agent_config
        from tau2.domains.retail.environment import get_environment, get_tasks
        self.args, self.root = args, args.output.resolve()
        resuming = args.resume_test or args.resume_development
        self.replay = None
        self.journal_path = self.root / "rsi.jsonl"
        if self.root.exists() and not resuming:
            raise ValueError("output directory must be new; completed trajectories are never silently rerun")
        self.root.mkdir(parents=True, exist_ok=resuming)
        catalog = json.loads(args.catalog.expanduser().read_text())
        def select(name):
            row = next(r for r in catalog["model_providers"] if name in (r["id"], r["name"]))
            return DesktopModelProviderRecord.model_validate(row)
        self.target_provider = select(args.target_provider)
        self.teacher_provider = select(args.teacher_provider)
        self.simulator_provider = select(args.simulator_provider or args.teacher_provider)
        self.default_config = default_agent_config()
        self.native_tools = tuple(self.default_config["availableTools"])
        environment = get_environment()
        self.domain_tools = environment.get_tools()
        self.policy = environment.get_policy()
        self.tasks = {t.id: t for t in get_tasks()}
        splits = json.loads((args.tau_source / "data/tau2/domains/retail/split_tasks.json").read_text())
        self.parts = partition_tasks(splits, seed=args.seed, initial_count=args.initial_training,
                                     validation_count=args.validation_count, test_count=args.test_count)
        self.pool_offset = 0
        self.episode_slots = asyncio.Semaphore(args.concurrency)
        self.monitor_packages = set()
        self.target = package("sage.tau.target", self.default_config["systemPrefix"]
            + "\nFollow the official domain policy below. Tools operate only on a simulated business database."
            + "\n<policy>\n" + self.policy + "\n</policy>",
            (*self.native_tools, *(t.name for t in self.domain_tools)))
        self.agents = {name: OptimizationAgent(package=package("sage.tau." + name,
             "Follow the host JSON contract. Improve reusable service procedures; never include case-specific IDs, customer details, or expected answers."), agent_id="assistant")
             for name in ("evaluation", "tuner", "reviewer", "designer", "suite-review")}
        self.context = RequestContext(actor=ActorRef(principal_id="tau-experiment",
             principal_type=PrincipalType.USER, scopes=("skill.load",)))
        self.native = IsolatedOptimizationRunner(builder_factory=self.factory, authorize=self.authorize,
             max_evidence_events=2000, max_evidence_bytes=2000000, resume_user_input=True)
        self.calls = 0
        self.episodes = json.loads((self.root / "episodes.json").read_text()) if resuming else []
        self.reusable_baselines = {}
        if args.reuse_evidence:
            source = args.reuse_evidence.resolve()
            old = json.loads((source / "experiment.json").read_text())
            rows = json.loads((source / "episodes.json").read_text())
            baseline = AgentPackageBundle.model_validate_json((source / "baseline-package.json").read_text())
            if (baseline.content_hash != self.target.content_hash
                or old["target_model"] != self.target_provider.model
                or old["user_and_nl_judge_model"] != self.simulator_provider.model
                or old["seed"] != args.seed or old["max_steps"] != args.max_steps
                or old["partition"] != self.parts):
                raise ValueError("baseline evidence uses different frozen conditions")
            if any(r["phase"].startswith("test-") for r in rows) or any(
                json.loads(p.read_text())["phase"].startswith("test-")
                for p in (source / "episodes").glob("*/identity.json")):
                raise ValueError("cannot import development evidence after external test exposure")
            for row in rows:
                if row["phase"] == "rsi" and row["package_hash"] == baseline.content_hash:
                    self.reusable_baselines.setdefault(row["task"], (source, row))
        metadata = {"benchmark": "tau2", "version": "1.0.1", "commit": TAU_COMMIT,
            "domain": "retail", "method": "custom", "seed": args.seed,
            "target_model": self.target_provider.model, "teacher_model": self.teacher_provider.model,
            "user_and_nl_judge_model": self.simulator_provider.model,
            "provider_ids": [self.target_provider.id, self.teacher_provider.id, self.simulator_provider.id],
            "native_tools": self.native_tools, "domain_tools": [t.name for t in self.domain_tools],
            "max_steps": args.max_steps, "target_turn_max_steps": 48, "rounds": args.rounds,
            "test_trials": args.test_trials,
            "monitor_count": args.monitor_count,
            "reference_only": args.reference_only,
            "infrastructure_attempts": 3,
            "partition": self.parts, "challenge_batch": args.challenge_batch,
            "candidate_selection": "last accepted development candidate; human-only checkpoints excluded",
            "cost_reporting": "unknown for custom routes; LiteLLM zero-cost fallbacks are not actual costs",
            "sampling": "official user seed; target sampling uses the fixed catalog defaults",
            "reused_baseline_evidence": str(args.reuse_evidence.resolve()) if args.reuse_evidence else None,
            "selection_metric": "0.5 * training_mean + 0.5 * validation_mean",
            "notes": ["Default Sage instruction plus official domain policy at baseline; all native and domain tools fixed throughout.",
                "Native file/planning tools use per-episode workspace; process tools exposed but execution denied without OS isolation.",
                "No installed optional Skills; load_skill is present. No cross-task memory.",
                "Official orchestrator, user simulator, environment, reward logic; configured user/NL judge route differs from default.",
                "Host curriculum draws additional official train tasks; this is not synthetic task generation.",
                "Validation is drawn from official train; tuner receives anonymous scores only.",
                "Human-only checkpoints, when enabled, are read-only measurements; final repeated test follows development selection."]}
        if resuming:
            previous = json.loads((self.root / "experiment.json").read_text())
            for key in ("commit", "provider_ids", "max_steps", "rounds", "partition", "challenge_batch"):
                if previous[key] != metadata[key]:
                    raise ValueError(f"resume configuration differs: {key}")
            if previous.get("reference_only", False) != args.reference_only:
                raise ValueError("resume reference mode differs")
            if previous.get("monitor_count", 0) != args.monitor_count:
                raise ValueError("resume monitor plan differs")
            if previous.get("test_trials", 1) != args.test_trials:
                raise ValueError("resume test trial count differs from precommitted plan")
            if args.resume_test and not (self.root / "frozen.json").exists():
                raise ValueError("only frozen external measurement can resume; RSI itself cannot restart silently")
            if args.resume_development:
                if (self.root / "frozen.json").exists():
                    raise ValueError("use --resume-test after freezing")
                for key in ("target_model", "teacher_model", "user_and_nl_judge_model", "seed", "target_turn_max_steps"):
                    if previous[key] != metadata[key]:
                        raise ValueError(f"development resume configuration differs: {key}")
                baseline = AgentPackageBundle.model_validate_json((self.root / "baseline-package.json").read_text())
                if baseline.content_hash != self.target.content_hash:
                    raise ValueError("development resume baseline changed")
                from examples.v2.tau_bench_replay import DevelopmentReplay
                self.replay = DevelopmentReplay(self.root)
                self.journal_path = self.root / f"rsi-resume-{uuid4().hex}.jsonl"
                save(self.root / "development-resume.json", {
                    "journal": str(self.journal_path), "source_journal": str(self.replay.source_journal),
                    "completed_development_episodes": sum(r["phase"] == "rsi" for r in self.episodes),
                    "note": "Replay exact completed observations and matching internal requests; only unfinished disposable simulations run again. Native input-pause transport fix applies to new executions."})
        else:
            save(self.root / "experiment.json", metadata)
            save(self.root / "baseline-package.json", self.target.model_dump(mode="json"))
        # Snapshot executable experiment logic on every invocation (including
        # resumes) so later infrastructure fixes remain auditable.
        sources = ["examples/v2/optimizer_tau_bench.py", "examples/v2/tau_bench_adapter.py",
            "examples/v2/tau_bench_report.py", "sagents/v2/optimization/optimizer.py",
            "sagents/v2/optimization/contracts.py", "sagents/v2/optimization/observer.py",
            "sagents/v2/optimization/feedback.py", "sagents/v2/optimization/principles.py",
            "sagents/v2/optimization/runner.py", "examples/v2/tau_bench_replay.py"]
        snapshot = self.root / "implementation" / uuid4().hex
        repository = Path(__file__).resolve().parents[2]
        hashes = {}
        for source in sources:
            payload = (repository / source).read_bytes()
            target = snapshot / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            hashes[source] = hashlib.sha256(payload).hexdigest()
        save(snapshot / "manifest.json", {"hashes": hashes, "resume_test": args.resume_test,
            "resume_development": args.resume_development,
            "infrastructure_attempts": 3, "test_trials": args.test_trials, "monitor_count": args.monitor_count})


    async def authorize(self, action, bundle, context):
        if bundle.manifest.metadata.id == self.target.manifest.metadata.id:
            if set(bundle.manifest.agents["assistant"].tools) != set(self.target.manifest.agents["assistant"].tools):
                raise PermissionError("benchmark tool grant is frozen")
        elif bundle.manifest.agents["assistant"].tools:
            raise PermissionError("internal agents may not use tools")

    def factory(self, bundle, root, context):
        from app.v2.desktop.backend.catalog import DesktopAgentRecord
        from app.v2.desktop.backend.model_providers import DesktopModelProviders
        from sagents.v2.model.protocols import create_registered_model_provider
        from sagents.v2.runtime.credentials import CredentialMaterial
        is_target = bundle.manifest.metadata.id == self.target.manifest.metadata.id
        selected = self.target_provider if is_target else self.teacher_provider
        agent = DesktopAgentRecord(agent_id="tau", user_id="tau", name="tau",
                                  config={"deepThinking": False})
        route = DesktopModelProviders.route(selected, agent, compatibility_profile=selected.compatibility_profile)
        route = route.model_copy(update={"request": route.request.model_copy(update={"max_output_tokens": 4096})})
        provider = create_registered_model_provider(route, CredentialMaterial(
            credential_id="tau-model", secret=selected.api_key, source="explicit-catalog"),
            capability_profile=route.capability_profile)
        registrations = [provided("tau.model", lambda ctx, deps: provider, "model.provider", ownership="owned")]
        choices = {"model.provider": {"plugin": "tau.model"},
            "execution.binding": {"plugin": "sage.execution.binding.local-workspace", "config": {
                "workspace": str(root / "workspace"), "policy": {"process": {"enabled": False}}}},
            "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
            "skill.provider": {"plugin": "sage.skill.filesystem", "config": {"roots": [str(root / "skills")]}},
        }
        if is_target:
            bridge = CURRENT_BRIDGE.get()
            if bridge is None:
                raise RuntimeError("target requires official environment bridge")
            registrations.append(provided("tau.tools", lambda ctx, deps: ToolProvider(bridge, bridge), "tool.provider"))
            # The standard assembler binds load_skill to the per-agent loader;
            # selecting that Tool plugin directly precedes loader construction.
            choices["tool.provider"] = ({"plugin": "sage.tool.official"}, {"plugin": "tau.tools"})
        policy = DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
        registrations.append(provided("tau.policy", lambda ctx, deps: policy, "agent.tool-policy"))
        choices["agent.tool-policy"] = {"plugin": "tau.policy"}
        route_data = route.model_dump(mode="json")
        route_data.pop("credential", None)
        tools = choices.pop("tool.provider", None)
        runtime = runtime_for(root / "sessions", bundle.manifest.runtime, capabilities=choices)
        if tools:
            from sagents.v2.package.manifest.runtime import CapabilitySelection
            runtime = runtime.model_copy(update={"capabilities": {**runtime.capabilities,
                "tool.provider": tuple(CapabilitySelection.model_validate(t) for t in tools)}})
        return ApplicationConfiguration(tuple(registrations), runtime, {"models": {"primary": route_data}})

    def configure_official_models(self):
        import tau2.evaluator.evaluator_nl_assertions as nl
        selected = self.simulator_provider
        self.simulator_model = ("openai/responses/" if selected.protocol == "openai-responses"
                                else "openai/") + selected.model
        self.simulator_args = {"api_base": selected.base_url, "api_key": selected.api_key,
            "max_completion_tokens": 4096, "timeout": 120, "num_retries": 0}
        # Configure only the judge model/route, without changing its prompt or logic.
        nl.DEFAULT_LLM_NL_ASSERTIONS = self.simulator_model
        nl.DEFAULT_LLM_NL_ASSERTIONS_ARGS = self.simulator_args

    async def episode(self, bundle, task_id, *, phase, seed=None, trial=0):
        # Each official environment is disposable and local. Only infrastructure
        # exceptions retry, preserving every failed trajectory; a scored failure
        # is final and never retried to inflate success.
        for attempt in range(3):
            try:
                async with self.episode_slots:
                    return await self._episode(bundle, task_id, phase=phase, seed=seed, trial=trial)
            except Exception as error:
                from litellm.exceptions import APIConnectionError, BadGatewayError, InternalServerError, Timeout
                if not isinstance(error, (APIConnectionError, BadGatewayError, InternalServerError, Timeout)) or attempt == 2:
                    raise
                print(json.dumps({"infrastructure_retry": type(error).__name__, "attempt": attempt + 1,
                    "phase": phase, "task": task_id, "trial": trial}), flush=True)
                await asyncio.sleep(2 * (attempt + 1))

    async def _episode(self, bundle, task_id, *, phase, seed=None, trial=0):
        from examples.v2.tau_bench_adapter import SageTauAgent, TauToolBridge
        from tau2.domains.retail.environment import get_environment
        from tau2.orchestrator.orchestrator import Orchestrator
        from tau2.runner.build import build_user
        from tau2.runner.simulation import run_simulation
        from tau2.utils.utils import get_now
        if phase.startswith("test-"):
            frozen = json.loads((self.root / "frozen.json").read_text())
            if task_id not in self.parts["test"] or bundle.content_hash not in (frozen["baseline"], frozen["candidate"]):
                raise PermissionError("test requires precommitted task and frozen package")
        elif phase == "human-test":
            if task_id not in self.parts["test"][:self.args.monitor_count] or bundle.content_hash not in self.monitor_packages:
                raise PermissionError("human test requires a registered retained checkpoint")
        elif task_id in self.parts["test"]:
            raise PermissionError("test task is unavailable before freeze")
        if phase == "rsi" and bundle.content_hash == self.target.content_hash and task_id in self.reusable_baselines:
            # A confirmed prior baseline is consumed at most once. Fresh
            # stability confirmations cannot be replaced by a cached execution.
            source, row = self.reusable_baselines.pop(task_id)
            simulation_path = source / "episodes" / row["episode"] / "simulation.json"
            simulation = json.loads(simulation_path.read_text())
            reward = simulation["reward_info"]
            reused = {**row, "episode": "reuse_" + uuid4().hex,
                      "reused_from": str(simulation_path), "reused": True}
            self.episodes.append(reused)
            save(self.root / "episodes.json", self.episodes)
            print(json.dumps({"task": task_id, "phase": phase, "reused_confirmed_baseline": True,
                              "reward": reward["reward"]}), flush=True)
            return OptimizationObservation(state="completed", output=json.dumps({
                "conversation": simulation["messages"], "official_reward": reward,
            }), evidence={"tau_reward": reward, "tau_trajectory": str(simulation_path),
                          "reused_from": str(simulation_path)},
                elapsed_seconds=row["seconds"], input_tokens=row["input_tokens"], output_tokens=row["output_tokens"])
        episode_id = uuid4().hex
        directory = self.root / "episodes" / episode_id
        started, stamp = time.monotonic(), get_now()
        save(directory / "identity.json", {"id": episode_id, "task_id": task_id,
            "package_hash": bundle.content_hash, "phase": phase, "trial": trial,
            "seed": self.args.seed if seed is None else seed, "started": stamp})
        print(json.dumps({"episode": episode_id[:8], "task": task_id, "phase": phase,
                          "state": "started"}), flush=True)
        environment, task = get_environment(), self.tasks[task_id]
        bridge = TauToolBridge(environment.get_tools(), on_progress=lambda value:
            print(json.dumps({"episode": episode_id[:8], **value}), flush=True))
        token = CURRENT_BRIDGE.set(bridge)
        try:
            async with self.native.conversation(bundle, "assistant", self.context) as session:
                agent = SageTauAgent(bridge=bridge, session=session, loop=asyncio.get_running_loop(),
                    domain_policy=self.policy, tools=environment.get_tools())
                user = build_user("user_simulator", environment, task,
                    llm=self.simulator_model, llm_args=dict(self.simulator_args))
                orchestrator = Orchestrator(domain="retail", agent=agent, user=user,
                    environment=environment, task=task, max_steps=self.args.max_steps,
                    max_errors=10, seed=self.args.seed if seed is None else seed)
                try:
                    worker = asyncio.create_task(asyncio.to_thread(run_simulation, orchestrator))
                    try:
                        simulation = await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        await bridge.close()
                        # Let the official sync worker leave the bridge before
                        # disposing its native Application and environment.
                        from contextlib import suppress
                        with suppress(Exception):
                            await worker
                        raise
                finally:
                    await bridge.close()
            save(directory / "simulation.json", simulation.model_dump(mode="json"))
            save(directory / "sage-turns.json", [o.model_dump(mode="json") for o in bridge.observations])
            reward = simulation.reward_info.model_dump(mode="json")
            row = {"episode": episode_id, "task": task_id, "phase": phase,
                "package_hash": bundle.content_hash, "trial": trial,
                "seed": self.args.seed if seed is None else seed, "reward": reward["reward"],
                "termination": simulation.termination_reason.value,
                "seconds": time.monotonic() - started,
                "input_tokens": sum(o.input_tokens for o in bridge.observations),
                "output_tokens": sum(o.output_tokens for o in bridge.observations)}
            self.episodes.append(row)
            save(self.root / "episodes.json", self.episodes)
            print(json.dumps(row), flush=True)
            return OptimizationObservation(state="completed", output=json.dumps({
                "conversation": [m.model_dump(mode="json", exclude_none=True) for m in simulation.messages],
                "official_reward": reward,
            }), evidence={"tau_reward": reward, "tau_trajectory": str(directory / "simulation.json"),
                          "training_trace": compact_training_trace(simulation.model_dump(mode="json")) if phase == "rsi" else ""},
                elapsed_seconds=row["seconds"], input_tokens=row["input_tokens"], output_tokens=row["output_tokens"])
        except BaseException as exc:
            save(directory / "failure.json", {"error_type": type(exc).__name__, "phase": phase})
            if "orchestrator" in locals():
                save(directory / "partial-trajectory.json", [m.model_dump(mode="json")
                    for m in orchestrator.trajectory])
            raise
        finally:
            await bridge.close()
            save(directory / "sage-turns.json", [o.model_dump(mode="json") for o in bridge.observations])
            CURRENT_BRIDGE.reset(token)

    async def run(self, bundle, agent_id, content, context):
        if bundle.manifest.metadata.id == self.target.manifest.metadata.id:
            task_id = json.loads(content)["tau_task_id"]
            if task_id not in set(self.parts["training"] + self.parts["validation"] + self.parts["challenge_pool"]):
                raise PermissionError("official test task cannot enter RSI")
            if self.replay:
                replayed = self.replay.target(bundle.content_hash, content)
                if replayed is not None:
                    return replayed
            return await self.episode(bundle, task_id, phase="rsi")
        request = json.loads(content)
        role = bundle.manifest.metadata.id.rsplit(".", 1)[-1]
        data = request["data"]
        if role == "evaluation":
            reward = data["observation"]["evidence"]["tau_reward"]
            answer = {"score": reward["reward"], "passed": reward["reward"] == 1,
                      "rationale": "Official tau2 reward: " + json.dumps(reward)}
        elif role == "designer":
            # Host curriculum, not fabricated model questions. Each round adds
            # different official train fixtures in the precommitted order.
            count = min(self.args.challenge_batch, data["max_cases"])
            ids = self.parts["challenge_pool"][self.pool_offset:self.pool_offset + count]
            if len(ids) != count:
                raise ValueError("training curriculum exhausted")
            self.pool_offset += count
            answer = {"cases": [task_case(i, "training").model_dump(mode="json") for i in ids]}
        elif role == "suite-review":
            cases = data["suite"]["cases"]
            permitted = set(self.parts["training"] + self.parts["validation"] + self.parts["challenge_pool"])
            for case in cases:
                if json.loads(case["input"])["tau_task_id"] not in permitted or case["rubric"] != RUBRIC:
                    raise PermissionError("invalid official fixture")
            answer = {"approved": True, "issues": [], "rationale": "Host verifies official fixture membership and unmodified reward contract."}
        else:
            if self.replay:
                replayed = self.replay.agent(role, request)
                if replayed is not None:
                    self.calls += 1
                    return replayed
            observation = await self.native.run(bundle, agent_id, content, context)
            self.calls += 1
            save(self.root / "internal-calls" / f"{self.calls:03d}-{role}.json", {
                "role": role, "request": request, "observation": observation.model_dump(mode="json")})
            return observation
        return OptimizationObservation(state="completed", output=json.dumps(answer))

    async def execute(self):
        self.configure_official_models()
        if self.args.resume_test:
            candidate = AgentPackageBundle.model_validate_json((self.root / "candidate-package.json").read_text())
            baseline = AgentPackageBundle.model_validate_json((self.root / "baseline-package.json").read_text())
            freeze = json.loads((self.root / "frozen.json").read_text())
            if baseline.content_hash != freeze["baseline"] or candidate.content_hash != freeze["candidate"]:
                raise ValueError("frozen package changed")
            self.target = baseline
            return await self.measure_frozen(candidate, freeze)
        if self.args.reference_only:
            save(self.root / "suite.json", {"cases": []})
            freeze = {"baseline": self.target.content_hash, "candidate": self.target.content_hash,
                "goal_verified": None, "selection_rule": "default reference model; no tuning or candidate selection"}
            save(self.root / "frozen.json", freeze)
            save(self.root / "candidate-package.json", self.target.model_dump(mode="json"))
            return await self.measure_frozen(self.target, freeze)
        if self.args.smoke:
            await self.episode(self.target, self.parts["training"][0], phase="smoke")
            return
        suite = OptimizationSuite(cases=tuple(
            task_case(i, split) for split in ("training", "validation") for i in self.parts[split]))
        save(self.root / "suite.json", suite.model_dump(mode="json"))
        goal = ("Improve completion of retail customer service tasks using the official tools and policy. "
            "The host executes tau_task_id fixtures as complete multi-turn official simulations; input task IDs are opaque host routing, not user questions. "
            "Only official train fixtures are used here. Never encode task IDs, account IDs, order numbers or case answers in guidance. "
            "Use training conversation and official reward failures to improve reusable procedures. "
            "Do not alter tools, policy, models, budgets, evaluator or simulator.\n" + self.policy)
        optimizer = AgentPackageOptimizer(runner=self, evaluator=self.agents["evaluation"],
            tuner=self.agents["tuner"], reviewer=self.agents["reviewer"],
            suite_reviewer=self.agents["suite-review"], test_designer=self.agents["designer"])
        from sagents.v2.optimization.observer import HumanTestObserver
        from sagents.v2.optimization.contracts import OptimizationTestSuite
        monitor = None
        if self.args.monitor_count:
            test_suite = OptimizationTestSuite(cases=tuple(task_case(i, "test") for i in self.parts["test"][:self.args.monitor_count]))
            async def observe_test(bundle, case):
                self.monitor_packages.add(bundle.content_hash)
                observation = await self.episode(bundle, json.loads(case.input)["tau_task_id"], phase="human-test")
                reward = observation.evidence["tau_reward"]
                return {"grade": {"score": reward["reward"], "passed": reward["reward"] == 1,
                    "rationale": "Official tau2 reward"}, "trajectory": observation.evidence["tau_trajectory"]}
            monitor = HumanTestObserver(baseline=self.target, suite=test_suite, evaluate=observe_test,
                publish=lambda records: save(self.root / "human-test-checkpoints.json", records),
                concurrency=self.args.concurrency,
                completed_records=json.loads((self.root / "human-test-checkpoints.json").read_text())
                    if self.args.resume_development else ())
        def event(e):
            print(json.dumps({"rsi_stage": e["event"], "round": e["data"].get("round")}), flush=True)
            if monitor:
                monitor.observe(e)
        try:
            result = await optimizer.optimize(self.target, context=self.context, goal=goal, suite=suite,
                validation_case_count=self.args.validation_count, rounds=self.args.rounds,
                max_concurrency=self.args.concurrency, call_timeout_seconds=1200, timeout_seconds=14400,
                constraints=OptimizationConstraints(max_guidance_chars=12000),
                resume_optimization_id=self.replay.optimization_id if self.replay else None,
                optimization_scope=("instructions",), journal_path=self.journal_path, on_event=event)
            if self.replay:
                self.replay.assert_consumed()
            if monitor:
                await monitor.finish()
        finally:
            if monitor:
                await monitor.cancel()
        save(self.root / "rsi-result.json", result.model_dump(mode="json"))
        # Retain the last accepted development candidate even without convergence.
        # Human test observations never enter this selection.
        accepted = [r for r in result.report.rounds if r.accepted and r.candidate_package is not None]
        candidate = accepted[-1].candidate_package if accepted else self.target
        freeze = {"baseline": self.target.content_hash, "candidate": candidate.content_hash,
                  "goal_verified": result.report.goal_verified,
                  "selection_rule": "last accepted development candidate; human-only checkpoints excluded; frozen before repeated final measurement"}
        save(self.root / "frozen.json", freeze)
        save(self.root / "candidate-package.json", candidate.model_dump(mode="json"))
        await self.measure_frozen(candidate, freeze)

    async def measure_frozen(self, candidate, freeze):
        semaphore = asyncio.Semaphore(self.args.concurrency)
        async def measure(label, bundle, task_id, trial):
            async with semaphore:
                if any(r["phase"] == "test-" + label and r["task"] == task_id
                       and r.get("trial", 0) == trial
                       and r["package_hash"] == bundle.content_hash for r in self.episodes):
                    return  # confirmed completed trajectory; no new model call
                await self.episode(bundle, task_id, phase="test-" + label,
                    trial=trial, seed=self.args.seed + trial)
        labels = (("reference", self.target),) if self.args.reference_only else (("baseline", self.target), ("candidate", candidate))
        # Frozen packages face the exact same precommitted tasks and seeds.
        await asyncio.gather(*(measure(label, bundle, i, trial)
            for trial in range(self.args.test_trials) for i in self.parts["test"] for label, bundle in labels))
        from examples.v2.tau_bench_report import repeated_scores
        metrics = repeated_scores(self.episodes, self.parts["test"], self.args.test_trials, labels=tuple(label for label, _ in labels))
        scores = {label: [r["reward"] for r in self.episodes if r["phase"] == "test-" + label]
                  for label, _ in labels}
        summary = {**freeze, "official_test_tasks": len(self.parts["test"]),
            "full_official_test_split": len(self.parts["test"]) == 40,
            "test_scores": {k: sum(v) / len(v) for k, v in scores.items()},
            "episodes": len(self.episodes), "method": "custom", "trials": self.args.test_trials,
            "reliability": metrics,
            "warning": "Retail official test subset; custom routes and scaffold; not a leaderboard submission."}
        save(self.root / "summary.json", summary)
        print(json.dumps(summary), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true", help="authorize actual paid model calls")
    p.add_argument("--tau-source", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--target-provider", required=True)
    p.add_argument("--teacher-provider", required=True)
    p.add_argument("--simulator-provider")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=20261021)
    p.add_argument("--rounds", type=int, choices=range(1, 9), default=3)
    p.add_argument("--initial-training", type=int, choices=range(1, 25), default=4)
    p.add_argument("--validation-count", type=int, choices=range(1, 25), default=4)
    p.add_argument("--challenge-batch", type=int, choices=range(1, 7), default=2)
    p.add_argument("--test-count", type=int, choices=range(0, 41), default=0, help="0 = full official test split")
    p.add_argument("--monitor-count", type=int, choices=range(0, 41), default=0, help="human-only test tasks per retained checkpoint; no feedback to RSI")
    p.add_argument("--test-trials", type=int, choices=(1, 4), default=1, help="precommit independent trials per task; 4 reports pass^1 and pass^4")
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--concurrency", type=int, choices=range(1, 9), default=3)
    p.add_argument("--reference-only", action="store_true", help="measure the default target model without optimization as a matched reference")
    p.add_argument("--smoke", action="store_true", help="one train episode; no optimization or test data")
    p.add_argument("--resume-test", action="store_true", help="resume frozen test measurement only, preserving completed trajectories")
    p.add_argument("--resume-development", action="store_true", help="reconstruct interrupted development from exact completed evidence; requests must match")
    p.add_argument("--reuse-evidence", type=Path, help="consume confirmed identical baseline train evidence once; never replaces fresh confirmation")
    args = p.parse_args()
    if args.resume_development and (args.resume_test or args.reuse_evidence or args.reference_only or args.smoke):
        p.error("development resume cannot be combined with other run modes")
    if args.reference_only and (args.monitor_count or args.smoke or args.reuse_evidence):
        p.error("reference-only does not optimize, monitor checkpoints, or reuse training evidence")
    if not args.live:
        p.error("--live is required")
    commit = subprocess.check_output(["git", "-C", str(args.tau_source), "rev-parse", "HEAD"], text=True).strip()
    if commit != TAU_COMMIT:
        p.error("tau-source must be the pinned official v1.0.1 commit")
    import os
    import sys
    os.environ["TAU2_DATA_DIR"] = str(args.tau_source / "data")
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    sys.path.insert(0, str(args.tau_source / "src"))
    from loguru import logger
    logger.remove()
    # Avoid credential-bearing exception reprs from upstream HTTP diagnostics.
    logger.add(sys.stderr, level="ERROR", format="{level}: {message}", backtrace=False, diagnose=False,
               filter=lambda record: "This model isn't mapped yet" not in record["message"])
    asyncio.run(TauExperiment(args).execute())


if __name__ == "__main__":
    main()
