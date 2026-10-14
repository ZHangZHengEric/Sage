"""Agent-owned approval preferences, independent of execution grants."""

from typing import Literal
from pydantic import Field
from sagents.v2.contracts.common import StrictModel


class ToolApprovalConfig(StrictModel):
    default: Literal["ask", "auto_approve"] = "auto_approve"
    tools: dict[str, Literal["inherit", "ask", "auto_approve"]] = Field(
        default_factory=dict
    )

    def mode_for(self, tool_id: str) -> str:
        mode = self.tools.get(tool_id, "inherit")
        return self.default if mode == "inherit" else mode
