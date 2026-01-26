from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class SkillSchema:
    """
    Complete schema for a Skill directory.
    """
    name: str
    description: str
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    instructions: str = ""  # Content of SKILL.md
    
    # Files in the skill directory
    files: Dict[str, str] = field(default_factory=dict)  # relative_path -> absolute_path
    
    # Specific categorized resources
    scripts: Dict[str, str] = field(default_factory=dict)  # name -> absolute_path
    references: Dict[str, str] = field(default_factory=dict)  # name -> absolute_path
    resources: Dict[str, str] = field(default_factory=dict)  # name -> absolute_path
    
    version: str = "latest"
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    requirements: List[str] = field(default_factory=list)

    def get_content(self) -> str:
        """
        Get the full content of the skill (Level 2 loading).
        """
        return self.instructions or ""

    def to_tool_definition(self) -> Dict[str, Any]:
        """
        Convert skill to OpenAI tool definition.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.metadata.get("parameters", {"type": "object", "properties": {}})
            }
        }
