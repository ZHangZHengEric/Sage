"""
Agent Definition Module

Defines the AgentDefinition class - pure configuration without session info.
"""
from typing import List, Optional, Dict, Any


class AgentDefinition:
    """
    Agent definition - configuration only, no session info.

    This class represents the "blueprint" for an agent that can be instantiated
    multiple times across different sessions.

    支持后端持久化存储或内存存储
    """

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        name: str = "",
        description: str = "",
        available_tools: Optional[List[str]] = None,
        available_skills: Optional[List[str]] = None,
        available_workflows: Optional[List[str]] = None,
        system_context: Optional[Dict[str, Any]] = None,
        backend_stored: bool = False
    ):
        """
        Initialize agent definition.

        Args:
            agent_id: Unique agent ID
            system_prompt: The system prompt defining agent's persona and capabilities
            name: Human-readable nickname for display (defaults to agent_id)
            description: Short description of the agent's role
            available_tools: List of tool names available to this agent
            available_skills: List of skill names available to this agent
            available_workflows: List of workflow names available to this agent
            system_context: Additional system context/configuration
            backend_stored: Whether this agent is stored in backend (persisted)
        """
        if not str(name or "").strip():
            raise ValueError(f"AgentDefinition.name is required for agent_id={agent_id}")
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.description = description
        self.available_tools = available_tools or []
        self.available_skills = available_skills or []
        self.available_workflows = available_workflows or []
        self.system_context = system_context or {}
        self.backend_stored = backend_stored

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "available_tools": self.available_tools,
            "available_skills": self.available_skills,
            "available_workflows": self.available_workflows,
            "system_context": self.system_context,
            "backend_stored": self.backend_stored
        }

    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentDefinition":
        """Create from dictionary representation."""
        return cls(
            agent_id=data.get("agent_id") or data.get("name"),
            name=data.get("name", ""),
            system_prompt=data["system_prompt"],
            description=data.get("description", ""),
            available_tools=data.get("available_tools"),
            available_skills=data.get("available_skills"),
            available_workflows=data.get("available_workflows"),
            system_context=data.get("system_context"),
            backend_stored=data.get("backend_stored", False)
        )
