"""Human-facing mirror of an externally hosted optimizer into local Desktop.

The trusted host supplies the owning catalog Agent and runtime directory.
Nothing in this sink returns observations to the optimizer. Versions are
read-only because an external runner may depend on unavailable host bindings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from app.v2.desktop.backend.rsi import RsiStore, fingerprint
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.common import utc_now


class DesktopOptimizationMirror:
    def __init__(self, runtime_root: Path, agent, *, goal, rounds,
                 validation_count, repeats, concurrency, scope, test_count,
                 input_visibility="message"):
        if input_visibility not in {"message", "opaque_fixture"}:
            raise ValueError("unknown input visibility")
        self.agent = agent
        self.store = RsiStore(runtime_root / "rsi.sqlite3", recover_interrupted=False)
        self.run_id = "rsi_external_" + uuid4().hex
        self.root = runtime_root / "rsi" / self.run_id
        self.root.mkdir(parents=True, mode=0o700)
        marker = self.root / "external-host.json"
        marker.write_text(json.dumps({"pid": os.getpid(), "run_id": self.run_id}))
        os.chmod(marker, 0o600)
        self.journal = self.root / "audit.jsonl"
        self.value = {"id": self.run_id, "request_id": self.run_id,
            "status": "running", "goal": goal, "rounds": rounds,
            "validation_case_count": validation_count, "evaluation_repeats": repeats,
            "evaluation_aggregation": "mean", "max_concurrency": concurrency,
            "optimization_scope": list(scope), "human_test_count": test_count,
            "created_at": utc_now().isoformat(), "base_fingerprint": fingerprint(agent),
            "stage": "queued", "iteration": 0, "sequence": 0,
            "external_host": True, "evaluation_protocol": "adaptive_validation",
            "input_visibility": input_visibility}
        self.save()

    def save(self):
        self.store.put(self.value, self.agent.user_id, self.agent.agent_id, "run")

    @classmethod
    def for_resume(cls, runtime_root, agent, run_id, baseline_hash):
        self = cls.__new__(cls)
        self.agent = agent
        self.store = RsiStore(runtime_root / "rsi.sqlite3", recover_interrupted=False)
        self.value = self.store.get(run_id, agent.user_id, agent.agent_id, "run")
        if not self.value.get("external_host") or self.value["status"] not in {"failed", "interrupted"}:
            raise ValueError("only failed/interrupted external experiments can resume")
        baseline = self.store.get(f"{run_id}.0", agent.user_id, agent.agent_id, "version")
        if baseline["package_hash"] != baseline_hash:
            raise ValueError("resumed baseline package changed")
        self.run_id = run_id
        self.root = runtime_root / "rsi" / run_id
        self.journal = self.root / "audit.jsonl"
        self.sequence_offset = self.value.get("sequence", 0)
        self.value.setdefault("resume_history", []).append({"resumed_at": utc_now().isoformat(),
            "previous_status": self.value["status"], "previous_error": self.value.get("error")})
        self.value.update(status="running", stage="resuming")
        self.value.pop("error", None)
        self.value.pop("finished_at", None)
        marker = self.root / "external-host.json"
        marker.write_text(json.dumps({"pid": os.getpid(), "run_id": run_id}))
        os.chmod(marker, 0o600)
        self.save()
        return self

    @classmethod
    def for_completed_tests(cls, runtime_root, agent, run_id, count):
        """Attach human measurements without replacing development or versions."""
        self = cls.__new__(cls)
        self.agent = agent
        self.store = RsiStore(runtime_root / "rsi.sqlite3", recover_interrupted=False)
        self.value = self.store.get(run_id, agent.user_id, agent.agent_id, "run")
        if self.value["status"] != "completed" or self.value.get("test_observations"):
            raise ValueError("backfill needs a completed run without existing test observations")
        self.run_id = run_id
        self.root = runtime_root / "rsi" / run_id
        self.journal = self.root / "audit.jsonl"
        self.value.update(human_test_count=count, human_test_measurement_status="running")
        self.save()
        return self

    async def register_workspace(self, path):
        """Register only the public training workspace through Desktop's API.

        Desktop availability must not abort an otherwise valid experiment. The
        archive path remains recorded if its project cannot be registered yet.
        """
        import httpx

        path = Path(path).resolve()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.value["workspace_path"] = str(path)
        try:
            registry = json.loads((self.root.parent.parent / "desktop-v2-sidecar.json").read_text())
            endpoint = f"http://{registry['host']}:{registry['port']}"
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                response = await client.post(endpoint + "/api/v2/projects",
                    headers={"Authorization": "Bearer " + registry["auth_token"]},
                    json={"name": f"RSI · {self.agent.name} · {self.run_id[-8:]}", "path": str(path)})
                response.raise_for_status()
                project = response.json()["data"]
                if Path(project["path"]).resolve() != path:
                    raise ValueError("Desktop registered a different workspace")
                self.value["workspace_id"] = project["id"]
                self.value.pop("workspace_registration_error", None)
        except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
            self.value["workspace_registration_error"] = type(error).__name__
        self.save()

    def version(self, index, package_data, record=None):
        package = AgentPackageBundle.model_validate(package_data)
        self.store.put({"id": f"{self.run_id}.{index}", "run_id": self.run_id,
            "iteration": index, "created_at": utc_now().isoformat(), "source": "rsi",
            "fingerprint": fingerprint(self.agent), "config": self.agent.config,
            "name": self.agent.name, "package": package_data,
            "package_hash": package.content_hash, "assets": {},
            "record": record or {}, "review": (record or {}).get("review"),
            "ready": False, "external_host": True},
            self.agent.user_id, self.agent.agent_id, "version")

    def observe(self, event):
        event = {**event, "sequence": event["sequence"] + getattr(self, "sequence_offset", 0)}
        with self.journal.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event, ensure_ascii=False) + "\n")
        os.chmod(self.journal, 0o600)
        data, name = event["data"], event["event"]
        record = data.get("record") or {}
        self.value.update(stage=name, sequence=event["sequence"],
            iteration=max(self.value["iteration"], data.get("round", record.get("round", 0))))
        if "role" in data:
            self.value.update(role=data["role"], activity=data.get("activity", data["role"]))
        if name == "operation_started":
            self.version(0, data["package"])
        elif name == "candidate_created":
            self.version(data["round"], data["package"])
        elif name == "round_completed" and record.get("candidate_package"):
            self.version(record["round"], record["candidate_package"], record)
        elif name == "optimization_stopped":
            self.value["termination"] = data
        self.save()

    def tests(self, records):
        self.value["test_observations"] = records
        self.save()

    def optimized(self, result):
        path = self.root / "result.json"
        path.write_text(result.model_dump_json(), encoding="utf-8")
        os.chmod(path, 0o600)
        self.value.update(retained_hash=result.candidate_package.content_hash,
            goal_verified=result.report.goal_verified, stage="human_test_pending")
        self.save()

    def finish(self, summary=None, *, error=None):
        self.value.update(status="failed" if error else "completed",
            stage="failed" if error else "result_completed", finished_at=utc_now().isoformat())
        if error:
            self.value["error"] = type(error).__name__
        if summary:
            self.value["benchmark_measurement"] = summary
        self.save()
