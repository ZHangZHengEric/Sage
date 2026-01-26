import os
import json
from typing import List, Optional
from sagents.utils.sandbox.sandbox import Sandbox
from sagents.skills.skill_manager import SkillManager
from sagents.utils.logger import logger

class SkillTools:
    def __init__(self, skill_manager: SkillManager, agent_workspace: Optional[str] = None):
        self.skill_manager = skill_manager
        self.agent_workspace = agent_workspace

    def read_skill_file(self, skill_name: str, file_path: str) -> str:
        """
        读取技能目录下的文件 (Layer 3)。
        """
        path = self.skill_manager.get_skill_resource_path(skill_name, file_path, agent_workspace=self.agent_workspace)
        if not path:
            return f"Error: File '{file_path}' not found in skill '{skill_name}'."
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def load_skill(self, skill_name: str) -> str:
        """
        加载指定技能的详细说明 (Layer 2)。
        """
        logger.info(f"Loading skill: {skill_name}")
        skill_schema = self.skill_manager.skills.get(skill_name)
        if not skill_schema:
            return f"Error: Skill '{skill_name}' not found or has no instructions."

        # Prepare skill in workspace if workspace is set
        if self.agent_workspace:
            self.skill_manager.prepare_skill_in_workspace(skill_name, self.agent_workspace)

        instructions = skill_schema.instructions
        if not instructions:
            return f"Error: Skill '{skill_name}' not found or has no instructions."

        # Append available resources for visibility
        res_summary = ""
        
        # Helper to sanitize paths (avoid absolute paths)
        def sanitize_resources(resources):
            if not resources:
                return {}
            # Return {rel_path: "skills/<skill_name>/<rel_path>"}
            return {k: f"skills/{skill_name}/{k}" for k in resources.keys()}

        # Use XML format as defined in the prompt
        if skill_schema.scripts or skill_schema.references or skill_schema.resources:
            if skill_schema.scripts:
                scripts_safe = sanitize_resources(skill_schema.scripts)
                scripts_json = json.dumps(scripts_safe, ensure_ascii=False, indent=2)
                res_summary += f"\n<SCRIPT_CONTEXT>\n{scripts_json}\n</SCRIPT_CONTEXT>\n"
            
            if skill_schema.references:
                refs_safe = sanitize_resources(skill_schema.references)
                refs_json = json.dumps(refs_safe, ensure_ascii=False, indent=2)
                res_summary += f"\n<REFERENCE_CONTEXT>\n{refs_json}\n</REFERENCE_CONTEXT>\n"
                
            if skill_schema.resources:
                resources_safe = sanitize_resources(skill_schema.resources)
                resources_json = json.dumps(resources_safe, ensure_ascii=False, indent=2)
                # Note: prompt doesn't explicitly have RESOURCE_CONTEXT in the main block but it is good to provide
                res_summary += f"\n<RESOURCE_CONTEXT>\n{resources_json}\n</RESOURCE_CONTEXT>\n"
            
        return f"<SKILL_MD_CONTEXT>\n{instructions}\n</SKILL_MD_CONTEXT>\n{res_summary}"

    def run_skill_script(self, skill_name: str, script_path: str, args: List[str] = [], install_cmd: str = None) -> str:
        """
        运行技能目录下的脚本 (Layer 3)。
        """
        path = self.skill_manager.get_skill_resource_path(skill_name, script_path, agent_workspace=self.agent_workspace)
        if not path:
            return f"Error: Script '{script_path}' not found in skill '{skill_name}'."

        # Using Sandbox to run
        allowed = [os.path.dirname(path)]
        cwd = None
        if self.agent_workspace:
            allowed.append(self.agent_workspace)
            cwd = self.agent_workspace

        sandbox = Sandbox(allowed_paths=allowed)
        try:
            return sandbox.skill_run_script(path, args, install_cmd=install_cmd, cwd=cwd)
        except Exception as e:
            return f"Error running script: {e}"

    def write_temp_file(self, file_path: str, content: str) -> str:
        """
        在指定路径创建或覆盖临时文件。
        """
        full_path = file_path
        if self.agent_workspace:
            if os.path.isabs(file_path):
                return f"Error: Absolute paths are not allowed. Please use a path relative to the workspace."
            full_path = os.path.join(self.agent_workspace, file_path)
        
        try:
            # Create directories if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: File '{file_path}' written."
        except Exception as e:
            return f"Error writing file: {e}"

    def edit_temp_file(self, file_path: str, old_str: str, new_str: str) -> str:
        """
        编辑指定路径的临时文件内容 (Search & Replace)。
        """
        full_path = file_path
        if self.agent_workspace:
            if os.path.isabs(file_path):
                return f"Error: Absolute paths are not allowed. Please use a path relative to the workspace."
            full_path = os.path.join(self.agent_workspace, file_path)
        
        path = full_path
        
        if not os.path.exists(path):
            return f"Error: File '{file_path}' not found."
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if old_str not in content:
                return f"Error: old_str not found in file '{file_path}'."
                
            # Perform replacement (replace one occurrence to be safe/precise)
            new_content = content.replace(old_str, new_str, 1)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            return f"Success: File '{file_path}' updated."
        except Exception as e:
            return f"Error editing file: {e}"

    @staticmethod
    def get_tool_definitions() -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": "加载技能的详细说明(SKILL.md)和资源列表。",
                    "parameters": {
                        "type": "object",
                        "properties": {"skill_name": {"type": "string", "description": "技能名称"}},
                        "required": ["skill_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_skill_file",
                    "description": "读取技能相关的文件内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "技能名称"},
                            "file_path": {"type": "string", "description": "文件相对路径 (如 'forms.md')"},
                        },
                        "required": ["skill_name", "file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_skill_script",
                    "description": "运行技能相关的各类脚本。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "技能名称"},
                            "script_path": {"type": "string", "description": "工作空间内的脚本相对路径"},
                            "args": {"type": "array", "items": {"type": "string"}, "description": "脚本参数列表"},
                            "install_cmd": {"type": "string", "description": "运行脚本前需要执行的依赖安装命令 (例如 'pip install pandas' 或 'npm install')"},
                        },
                        "required": ["skill_name", "script_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_temp_file",
                    "description": "在指定路径创建或覆盖临时文件（请使用相对路径）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径 (请使用相对路径)"},
                            "content": {"type": "string", "description": "文件内容"},
                        },
                        "required": ["file_path", "content"],
                    },
                },
            },
        ]
