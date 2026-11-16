"""Persistent overrides for process-local Server run concurrency."""

import os
import tempfile
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.v2.server.config.settings import ServerSettings


class RunConcurrency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrent_runs: Annotated[int, Field(strict=True, ge=1)]
    max_concurrent_runs_per_user: Annotated[int, Field(strict=True, ge=1)]

    @classmethod
    def from_settings(cls, settings: ServerSettings):
        return cls(
            max_concurrent_runs=settings.max_concurrent_runs,
            max_concurrent_runs_per_user=settings.max_concurrent_runs_per_user,
        )


class RunConcurrencyConfig:
    def __init__(self, data_root: Path):
        self.path = data_root / "config" / "run-concurrency.json"

    def read(self, defaults: RunConcurrency) -> RunConcurrency:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return defaults
        return RunConcurrency.model_validate_json(data)

    def save(self, limits: RunConcurrency) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".run-concurrency-")
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(limits.model_dump_json().encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
