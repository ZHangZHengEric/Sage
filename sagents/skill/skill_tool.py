import os
import shutil
from typing import List, Optional, Union
from sagents.utils.sandbox.sandbox import Sandbox
from sagents.skill import SkillManager, SkillProxy
from sagents.utils.logger import logger

class SkillTools:
    def __init__(self, skill_manager: Union[SkillManager, SkillProxy], agent_workspace: Optional[str] = None, skill_workspace_path: Optional[str] = None):
        self.skill_manager = skill_manager
        self.agent_workspace = agent_workspace
        self.skill_workspace_path = skill_workspace_path

    def _resolve_resource_path(self, skill_name: str, resource_name: str) -> Optional[str]:
        if self.skill_workspace_path:
            # 在临时沙盒模式下，所有资源都在 skill_workspace_path 中
            normalized_resource_name = resource_name.replace("\\", "/")
            # 移除可能的 skill_name 前缀，因为在沙盒里是扁平的或者保持原样
            # 假设拷贝是整个 skill 目录内容拷贝到 sandbox root
            # 如果 resource_name 是 relative path, 直接 join

            # 处理可能的 "skills/skill_name/" 前缀
            if normalized_resource_name.startswith("skills/"):
                normalized_resource_name = normalized_resource_name.split("/", 2)[-1]
            elif normalized_resource_name.startswith(f"{skill_name}/"):
                normalized_resource_name = normalized_resource_name[len(f"{skill_name}/"):]

            resource_path = os.path.join(self.skill_workspace_path, normalized_resource_name)
            # 在沙盒模式下，我们允许访问沙盒内的任何文件，所以只要路径在沙盒内即可
            # 但为了兼容性，先检查存在性
            if os.path.exists(resource_path):
                return resource_path
            # 如果文件不存在，可能是新生成的文件，也返回路径
            return resource_path

        return self.skill_manager.get_skill_resource_path(
            skill_name, resource_name, agent_workspace=self.agent_workspace
        )

    def read_skill_file(self, skill_name: str, file_path: str) -> str:
        """
        读取技能目录下的文件 (Layer 3)。
        """
        path = self._resolve_resource_path(skill_name, file_path)
        if not path or (not os.path.exists(path) and self.skill_workspace_path is None):
            # 非沙盒模式下必须存在
            return f"Error: File '{file_path}' not found in skill '{skill_name}'."

        if not os.path.exists(path):
            return f"Error: File '{file_path}' not found."

        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def run_skill_script(self, skill_name: str, script_path: str, args: List[str] = [], install_cmd: str = None) -> str:
        """
        运行技能目录下的脚本 (Layer 3)。
        """
        path = self._resolve_resource_path(skill_name, script_path)
        if not path or (not os.path.exists(path) and self.skill_workspace_path is None):
            return f"Error: Script '{script_path}' not found in skill '{skill_name}'."

        if not os.path.exists(path):
            return f"Error: Script '{script_path}' not found."

        # Using Sandbox to run
        allowed = [os.path.dirname(path)]
        cwd = None

        if self.skill_workspace_path:
            allowed.append(self.skill_workspace_path)
            cwd = self.skill_workspace_path

        sandbox = Sandbox(allowed_paths=allowed)
        try:
            return sandbox.skill_run_script(path, args, install_cmd=install_cmd, cwd=cwd) or "执行成功"
        except Exception as e:
            return f"Error running script: {e}"

    def load_skill(self, skill_name: str) -> str:
        """
        加载指定技能的详细说明 (Layer 2)。
        """
        logger.info(f"Loading skill: {skill_name}")
        skill_schema = self.skill_manager.skills.get(skill_name)
        if not skill_schema:
            return f"Error: Skill '{skill_name}' not found or has no instructions."
        instructions = skill_schema.instructions
        if not instructions:
            return f"Error: Skill '{skill_name}' not found or has no instructions."
        return f"<SKILL_MD_CONTEXT>\n{instructions}\n</SKILL_MD_CONTEXT>\n"

    def write_temp_file(self, file_path: str, content: str) -> str:
        """
        在当前工作空间(沙盒)中创建或覆盖文件。
        """
        full_path = file_path
        # 优先使用 skill_workspace_path (沙盒)
        target_workspace = self.skill_workspace_path

        if target_workspace:
            if not os.path.isabs(file_path):
                full_path = os.path.join(target_workspace, file_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"成功写入文件: {full_path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def submit_skill_outputs(self, file_paths: List[str]) -> str:
        """
        确认最终产物，并将沙盒中的文件拷贝到 Agent 工作空间。
        """
        if not self.skill_workspace_path:
            return "Error: No active sandbox environment."
        if not self.agent_workspace:
            return "Error: No agent workspace defined."
        results = []
        for file_path in file_paths:
            # src is in skill_workspace_path (temp sandbox)
            # 处理相对路径
            if os.path.isabs(file_path):
                # 如果是绝对路径，检查是否在 sandbox 内
                if not file_path.startswith(self.skill_workspace_path):
                    results.append(f"Error: File {file_path} is outside of sandbox.")
                    continue
                src = file_path
                rel_path = os.path.relpath(src, self.skill_workspace_path)
            else:
                src = os.path.join(self.skill_workspace_path, file_path)
                rel_path = file_path

            # dst is in agent_workspace
            dst = os.path.join(self.agent_workspace, rel_path)

            try:
                if os.path.exists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                        results.append(f"Copied directory {rel_path}")
                    else:
                        shutil.copy2(src, dst)
                        results.append(f"Copied file {rel_path}")
                else:
                    results.append(f"File not found: {rel_path}")
            except Exception as e:
                results.append(f"Error copying {rel_path}: {e}")
        return "\n".join(results)

    def execute_command(self, command: str) -> str:
        """
        在技能工作空间(沙盒)中执行 Shell 命令。
        """
        cwd = self.skill_workspace_path

        # Using Sandbox to run
        allowed = []
        if cwd:
            allowed.append(cwd)

        sandbox = Sandbox(allowed_paths=allowed)
        try:
            return sandbox.run_shell_command(command, cwd=cwd)
        except Exception as e:
            return f"Error running command: {e}"

    @staticmethod
    def get_execute_tool_definitions() -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_skill_file",
                    "description": "读取技能相关的文件内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "技能名称"},
                            "file_path": {"type": "string", "description": "文件路径 (如果是相对路径，则基于当前工作空间)"},
                        },
                        "required": ["skill_name", "file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_temp_file",
                    "description": "在当前工作空间(沙盒)中创建或覆盖文件。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径 (如果是相对路径，则基于当前工作空间)"},
                            "content": {"type": "string", "description": "文件内容"},
                        },
                        "required": ["file_path", "content"],
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
                            "script_path": {"type": "string", "description": "工作空间内的脚本路径 (推荐使用绝对路径)"},
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
                    "name": "submit_skill_outputs",
                    "description": "确认最终产物，并将沙盒中的文件拷贝到 Agent 工作空间。任务完成后必须调用此工具。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_paths": {
                                "type": "array", 
                                "items": {"type": "string"}, 
                                "description": "需要提交的文件或目录路径列表(相对路径)"
                            },
                        },
                        "required": ["file_paths"],
                    },
                },
            },
        ]

    '''
     这个方法是假的。给llm做选择的
    '''
    @staticmethod
    def get_select_tool_definitions() -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": "加载技能的详细说明(SKILL.md)",
                    "parameters": {
                        "type": "object",
                        "properties": {"skill_name": {"type": "string", "description": "技能名称"}},
                        "required": ["skill_name"],
                    },
                },
            }            
        ]
