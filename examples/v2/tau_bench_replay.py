"""Fail-closed reconstruction of interrupted development from saved evidence.

Only completed development calls are replayed. Human test observations never
enter this cache, and each saved execution is consumed at most once.
"""
from collections import defaultdict, deque
from copy import deepcopy
import json
import re
from pathlib import Path

from sagents.v2.optimization.contracts import OptimizationObservation


class DevelopmentReplay:
    def __init__(self, root):
        self.targets = defaultdict(deque)
        self.internal = deque()
        started = {}
        completed_ids = set()
        identities = set()
        self.source_journal = root / "rsi.jsonl"
        if (root / "development-resume.json").exists():
            previous = json.loads((root / "development-resume.json").read_text())
            journal = Path(previous["journal"]).resolve()
            if journal.parent != root.resolve():
                raise ValueError("resume journal must remain in the experiment directory")
            if journal.exists():
                self.source_journal = journal
        for line in self.source_journal.read_text().splitlines():
            event = json.loads(line)
            data = event["data"]
            if event["event"] == "candidate_created":
                version = data["package"]["manifest"]["metadata"]["version"]
                match = re.search(r"\.opt\.([0-9a-f]{32})\.\d+$", version)
                if not match:
                    raise ValueError("saved candidate has no optimization identity")
                identities.add(match[1])
            if event["event"] == "target_call_started":
                started[data["call_id"]] = data
            elif event["event"] == "target_call_completed":
                call = started[data["call_id"]]
                observation = OptimizationObservation.model_validate(data["observation"])
                if observation.state != "completed":
                    raise ValueError("cannot replay an incomplete target observation")
                self.targets[(call["package_hash"], call["input"])].append(observation)
                trajectory = observation.evidence.get("tau_trajectory")
                if trajectory:
                    completed_ids.add(Path(trajectory).parent.name)
        episodes = json.loads((root / "episodes.json").read_text())
        if any(row["phase"].startswith("test-") for row in episodes):
            raise ValueError("development replay cannot follow frozen test measurement")
        expected = {row["episode"] for row in episodes if row["phase"] == "rsi"}
        if completed_ids != expected:
            raise ValueError("development journal and completed episodes disagree")
        if len(identities) != 1:
            raise ValueError("development replay needs one recorded optimization identity")
        self.optimization_id = identities.pop()
        for path in sorted((root / "internal-calls").glob("*.json")):
            self.internal.append((path, json.loads(path.read_text())))
        self.replayed_targets = 0
        self.replayed_internal = 0

    def target(self, package_hash, content):
        queue = self.targets.get((package_hash, content))
        if not queue:
            if self.internal:
                raise ValueError("target replay differs before saved internal decisions")
            return None
        self.replayed_targets += 1
        return queue.popleft().model_copy(deep=True)

    def agent(self, role, request):
        if not self.internal:
            if any(self.targets.values()):
                raise ValueError("unconsumed development evidence before a new agent call")
            return None
        path, saved = self.internal[0]
        if saved["role"] != role or saved["request"] != request:
            raise ValueError(f"development replay request differs: {path.name}")
        self.internal.popleft()
        self.replayed_internal += 1
        return OptimizationObservation.model_validate(deepcopy(saved["observation"]))

    def assert_consumed(self):
        if self.internal or any(self.targets.values()):
            raise ValueError("development replay did not consume all saved evidence")
