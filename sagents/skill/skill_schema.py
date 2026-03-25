from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class SkillSchema:
    name: str
    description: str
    path: str
    instructions: str = ""  # SKILL.md 内容
    file_list: str = ""  # 文件树列表，markdown 格式

    def get_content(self) -> str:
        """
        Get the full content of the skill (Level 2 loading).
        """
        return self.instructions or ""
