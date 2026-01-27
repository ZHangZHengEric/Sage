from typing import List, Dict, Any, Optional, AsyncGenerator, Union, cast
import json
import uuid
from copy import deepcopy
import tempfile
import shutil
import os

from sagents.agent.agent_base import AgentBase
from sagents.context.session_context import SessionContext
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.skills import SkillProxy, SkillManager
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager
from sagents.skills.skill_tool import SkillTools


class SkillExecutorAgent(AgentBase):

    def __init__(
        self,
        model: Any = None,
        model_config: Dict[str, Any] = {},
        system_prefix: str = "",
    ):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "SkillExecutorAgent"
        self.agent_description = "SkillExecutorAgent: 负责按需加载和执行技能。"
        logger.debug("SkillExecutorAgent 初始化完成")

    def _safe_parse_args(self, args_str: str) -> Dict[str, Any]:
        try:
            args = json.loads(args_str)
            # Handle double-encoded JSON or string output
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    pass

            if not isinstance(args, dict):
                logger.warning(
                    f"SkillExecutorAgent: Tool arguments parsed to non-dict ({type(args)}). args_str={args_str}"
                )
                return {}
            return args
        except Exception as e:
            logger.warning(
                f"SkillExecutorAgent: Failed to parse tool arguments: {e}. args_str={args_str}"
            )
            return {}

    def _merge_messages_in_place(
        self,
        base_messages: List[Union[MessageChunk, Dict[str, Any]]],
        new_chunks: List[MessageChunk],
    ) -> None:
        merged_messages = MessageManager.merge_new_messages_to_old_messages(
            cast(List[Union[MessageChunk, Dict[str, Any]]], new_chunks),
            cast(List[Union[MessageChunk, Dict[str, Any]]], base_messages),
        )
        base_messages.clear()
        base_messages.extend(merged_messages)

    def _build_selection_messages(
        self,
        session_context: SessionContext,
        skill_manager: Union[SkillManager, SkillProxy],
    ) -> List[Dict[str, Any]]:
        prompt_template = PromptManager().get_agent_prompt_auto(
            "SKILL_EXECUTOR_SELECT_PROMPT", language=session_context.get_language()
        )
        system_prompt = prompt_template.format(
            available_skills="\n".join(skill_manager.get_skill_description_lines())
        )
        select_messages = [{"role": "system", "content": system_prompt}]
        context_messages = session_context.message_manager.extract_all_context_messages(
            recent_turns=10, last_turn_user_only=False
        )
        select_messages.extend([msg.to_dict() for msg in context_messages])
        return select_messages

    def _build_execution_system_prompt(
        self,
        session_context: SessionContext,
        skill_metadata: Dict[str, Any],
        selection_result: Dict[str, Any],
    ) -> str:
        instruction_prompt_template = PromptManager().get_agent_prompt_auto(
            "INSTRUCTION_SKILL_EXECUTION_PROMPT",
            language=session_context.get_language(),
        )
        return instruction_prompt_template.format(
            skill_name=skill_metadata.get("name", selection_result.get("skill_name")),
            skill_description=skill_metadata.get("description", ""),
            skill_path=skill_metadata.get("path", ""),
            instructions=selection_result.get("instructions", ""),
        )

    def _build_execution_messages(
        self,
        execution_system_prompt: str,
        chain_messages: List[Dict[str, Any]],
    ) -> List[Union[MessageChunk, Dict[str, Any]]]:
        exec_messages: List[Union[MessageChunk, Dict[str, Any]]] = [
            MessageChunk(role=MessageRole.SYSTEM.value, content=execution_system_prompt)
        ]
        if len(chain_messages) > 1:
            for msg in chain_messages[1:]:
                if isinstance(msg, dict):
                    exec_messages.append(MessageChunk.from_dict(msg))
                else:
                    exec_messages.append(msg)
        return exec_messages

    def _get_tool_definitions(
        self,
        all_skill_tool_defs: List[Dict[str, Any]],
        include_load_skill: bool,
    ) -> List[Dict[str, Any]]:
        if include_load_skill:
            return all_skill_tool_defs
        return [t for t in all_skill_tool_defs if t["function"]["name"] != "load_skill"]

    async def _stream_llm_and_collect(
        self,
        *,
        messages: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str],
        step_name: str,
        model_config_override: Dict[str, Any],
        content_message_type: str,
        step_chunks: List[MessageChunk],
        tool_calls: Dict[str, Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        content_message_id = str(uuid.uuid4())
        last_tool_call_id: Optional[str] = None
        async for chunk in self._call_llm_streaming(
            messages=messages,
            session_id=session_id,
            step_name=step_name,
            model_config_override=model_config_override,
        ):
            if chunk is None:
                continue
            if chunk.choices is None or len(chunk.choices) == 0:
                continue
            delta = chunk.choices[0].delta
            if delta.tool_calls:
                self._handle_tool_calls_chunk(
                    chunk, tool_calls, last_tool_call_id or ""
                )
                for tc in delta.tool_calls:
                    if tc.id:
                        last_tool_call_id = tc.id
                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_type=MessageType.EMPTY.value,
                        type=MessageType.EMPTY.value,
                        message_id=content_message_id,
                        show_content="",
                    )
                ]
            if delta.content:
                msg_chunk = MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=delta.content,
                    message_type=content_message_type,
                    type=content_message_type,
                    message_id=content_message_id,
                    show_content=delta.content,
                )
                yield [msg_chunk]
                step_chunks.append(deepcopy(msg_chunk))

    def _invoke_tool(
        self,
        func_name: str,
        args: Dict[str, Any],
        tool_map: Dict[str, Any],
    ) -> str:
        if func_name in tool_map:
            try:
                return tool_map[func_name](**args)
            except Exception as e:
                return f"Error executing {func_name}: {e}"
        return f"Error: Tool '{func_name}' not found"

    def _build_tool_result_chunk(
        self,
        tool_call_id: str,
        result: Any,
    ) -> MessageChunk:
        return MessageChunk(
            role=MessageRole.TOOL.value,
            content=str(result),
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            type=MessageType.TOOL_CALL_RESULT.value,
            message_type=MessageType.TOOL_CALL_RESULT.value,
            show_content=str(result),
        )

    def _create_tool_map(
        self,
        skill_tools: SkillTools,
        session_context: SessionContext,
    ) -> Dict[str, Any]:
        def load_skill_with_workspace(**args: Any) -> str:
            return skill_tools.load_skill(
                agent_workspace=session_context.agent_workspace, **args
            )

        return {
            "load_skill": load_skill_with_workspace,
            "read_skill_file": skill_tools.read_skill_file,
            "write_temp_file": skill_tools.write_temp_file,
            "run_skill_script": skill_tools.run_skill_script,
            "submit_skill_outputs": skill_tools.submit_skill_outputs,
        }

    async def _select_skill(
        self,
        session_id: Optional[str],
        select_messages: List[Dict[str, Any]],
        all_skill_tool_defs: List[Dict[str, Any]],
        tool_map: Dict[str, Any],
        selection_result: Dict[str, Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        step_chunks: List[MessageChunk] = []
        step_tool_calls: Dict[str, Any] = {}

        load_skill_def = next(
            (t for t in all_skill_tool_defs if t["function"]["name"] == "load_skill"),
            None,
        )
        async for chunk in self._stream_llm_and_collect(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], select_messages),
            session_id=session_id,
            step_name="skill_executor_select",
            model_config_override={
                "tools": [load_skill_def] if load_skill_def else [],
                "tool_choice": "auto",
            },
            content_message_type=MessageType.SKILL_SELECT_RESULT.value,
            step_chunks=step_chunks,
            tool_calls=step_tool_calls,
        ):
            yield chunk

        self._merge_messages_in_place(
            cast(List[Union[MessageChunk, Dict[str, Any]]], select_messages), step_chunks
        )

        if not step_tool_calls:
            logger.info("SkillExecutorAgent: No skill selected.")
            return

        selected_skill_name = None
        for tool_call in list(step_tool_calls.values()):
            output_messages = self._create_tool_call_message(tool_call)
            yield output_messages
            select_messages.extend(deepcopy(output_messages))

            func_name = tool_call["function"]["name"]
            args = self._safe_parse_args(tool_call["function"]["arguments"])

            if func_name == "load_skill":
                selected_skill_name = args.get("skill_name")
                try:
                    result = tool_map[func_name](**args)
                except Exception as e:
                    result = f"执行技能选择工具错误 {func_name}: {e}"
                    yield [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=str(result),
                            message_id=str(uuid.uuid4()),
                            message_type=MessageType.ERROR.value,
                            show_content=str(result),
                        )
                    ]
                msg_chunk = MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=f"启动技能: {selected_skill_name} 来完成用户需求",
                    tool_call_id=tool_call["id"],
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    type=MessageType.TOOL_CALL_RESULT.value,
                    show_content=f"启动技能: {selected_skill_name} 来完成用户需求",
                )
                yield [msg_chunk]
                select_messages.append(deepcopy(msg_chunk))
                selection_result["instructions"] = result
                selection_result["skill_name"] = selected_skill_name

    async def _is_skill_complete(
        self,
        messages_input: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str],
        language: str,
    ) -> bool:
        if not messages_input:
            return False
        message_chunks: List[MessageChunk] = []
        for msg in messages_input:
            if isinstance(msg, MessageChunk):
                message_chunks.append(msg)
            else:
                try:
                    message_chunks.append(MessageChunk.from_dict(msg))
                except Exception:
                    continue
        if not message_chunks:
            return False
        if message_chunks[-1].role == MessageRole.TOOL.value:
            logger.info("messages_input[-1].role是 tool 调用结果，不是任务完成")
            return False

        last_user_index = None
        for i, message in enumerate(message_chunks):
            if message.role == MessageRole.USER.value and (
                message.type == MessageType.NORMAL.value
                or message.message_type == MessageType.NORMAL.value
            ):
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = message_chunks[last_user_index:]
        else:
            messages_for_complete = message_chunks
        clean_messages = MessageManager.convert_messages_to_dict_for_request(
            messages_for_complete
        )

        task_complete_template = PromptManager().get_agent_prompt_auto(
            "task_complete_template", language=language
        )
        prompt = task_complete_template.format(
            session_id=session_id or "",
            messages=json.dumps(clean_messages, ensure_ascii=False, indent=2),
        )
        messages_input = [{"role": "user", "content": prompt}]
        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            session_id=session_id,
            step_name="skill_task_complete_judge",
        )
        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            return result.get("task_interrupted", False)
        except json.JSONDecodeError:
            logger.warning("SkillExecutorAgent: 解析任务完成判断响应时JSON解码错误")
            return False

    async def _execute_skill(
        self,
        session_id: Optional[str],
        selection_result: Dict[str, Any],
        chain_messages: List[Dict[str, Any]],
        skill_manager: Union[SkillManager, SkillProxy],
        session_context: SessionContext,
        all_skill_tool_defs: List[Dict[str, Any]],
        tool_map: Dict[str, Any],
        skill_tools: SkillTools,
        execution_result: Dict[str, Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        skill_metadata = skill_manager.get_skill_metadata(selection_result.get("skill_name")) or {}
        
        # 创建独立环境的临时沙盒
        temp_sandbox_path = tempfile.mkdtemp(prefix=f"skill_sandbox_{selection_result.get('skill_name')}_")
        logger.info(f"Created temp sandbox at {temp_sandbox_path}")

        try:
            # 将skills的文件拷贝过去
            skill_source_path = skill_metadata.get("path")
            if skill_source_path and os.path.exists(skill_source_path):
                try:
                    # 递归拷贝所有内容到沙盒根目录
                    shutil.copytree(skill_source_path, temp_sandbox_path, dirs_exist_ok=True)
                    logger.info(f"Copied skill files from {skill_source_path} to {temp_sandbox_path}")
                except Exception as e:
                    logger.error(f"Failed to copy skill files: {e}")

            # 设置工作路径为这个沙盒目录
            skill_tools.agent_workspace = session_context.agent_workspace
            skill_tools.skill_workspace_path = temp_sandbox_path
            
            # 使用沙盒路径作为 prompt 中的 skill_path
            execution_system_prompt = self._build_execution_system_prompt(
                session_context, 
                {**skill_metadata, "path": temp_sandbox_path}, 
                selection_result
            )
            
            exec_messages = self._build_execution_messages(
                execution_system_prompt, chain_messages
            )

            tool_definitions_for_llm = self._get_tool_definitions(
                all_skill_tool_defs, include_load_skill=False
            )

            loop_count = 0
            skill_completed = False
            while not skill_completed and loop_count < 20:
                loop_count += 1
                step_chunks: List[MessageChunk] = []
                step_tool_calls: Dict[str, Any] = {}

                async for chunk in self._stream_llm_and_collect(
                    messages=cast(List[Union[MessageChunk, Dict[str, Any]]], exec_messages),
                    session_id=session_id,
                    step_name=f"skill_executor_step_{loop_count}",
                    model_config_override={
                        "tools": tool_definitions_for_llm,
                        "temperature": 0.2,
                        "tool_choice": "auto",
                    },
                    content_message_type=MessageType.GUIDE.value,
                    step_chunks=step_chunks,
                    tool_calls=step_tool_calls,
                ):
                    yield chunk

                self._merge_messages_in_place(
                    cast(List[Union[MessageChunk, Dict[str, Any]]], exec_messages),
                    step_chunks,
                )

                for tool_call in list(step_tool_calls.values()):
                    output_messages = self._create_tool_call_message(tool_call)
                    yield output_messages
                    exec_messages.extend(deepcopy(output_messages))

                    func_name = tool_call["function"]["name"]
                    args = self._safe_parse_args(tool_call["function"]["arguments"])

                    result = self._invoke_tool(func_name, args, tool_map)
                    msg_chunk = self._build_tool_result_chunk(tool_call["id"], result)
                    yield [msg_chunk]
                    exec_messages.append(deepcopy(msg_chunk))
                skill_completed = await self._is_skill_complete(
                    exec_messages, session_id, session_context.get_language()
                )
                if skill_completed:
                    break
            final_summary = exec_messages[len(exec_messages) - 1].content
            execution_result["summary"] = final_summary
        finally:
            # 执行完成的时候，会删除这个沙盒下的所有东西
            try:
                shutil.rmtree(temp_sandbox_path)
                logger.info(f"Removed temp sandbox {temp_sandbox_path}")
            except Exception as e:
                logger.warning(f"Failed to remove temp sandbox: {e}")

    async def run_stream(
        self,
        session_context: SessionContext,
        tool_manager: Optional[Any] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:

        skill_manager = session_context.skill_manager
        if not skill_manager:
            logger.error("SkillExecutorAgent: 未找到 SkillManager")
            yield [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="系统错误：未初始化技能管理器。",
                    message_type=MessageType.ERROR.value,
                    type=MessageType.ERROR.value,
                    message_id=str(uuid.uuid4()),
                    show_content="系统错误：未初始化技能管理器。",
                )
            ]
            return

        skill_tools = SkillTools(
            skill_manager
        )
        all_skill_tool_defs = SkillTools.get_tool_definitions()
        tool_map = self._create_tool_map(skill_tools, session_context)
        select_messages = self._build_selection_messages(session_context, skill_manager)

        final_summary = None
        # 阶段一：技能意图识别选择 (Skill Selection)
        selection_result = {}
        async for chunk in self._select_skill(
            session_id=session_id,
            select_messages=select_messages,
            all_skill_tool_defs=all_skill_tool_defs,
            tool_map=tool_map,
            selection_result=selection_result,
        ):
            yield chunk

        selected_skill_name = selection_result.get("skill_name")
        if not selected_skill_name:
            logger.info("SkillExecutorAgent: No skill selected, finishing chain.")
            return
        # 阶段二：技能执行 (Skill Execution)
        execution_result = {}
        async for chunk in self._execute_skill(
            session_id=session_id,
            selection_result=selection_result,
            chain_messages=select_messages,
            skill_manager=skill_manager,
            session_context=session_context,
            all_skill_tool_defs=all_skill_tool_defs,
            tool_map=tool_map,
            skill_tools=skill_tools,
            execution_result=execution_result,
        ):
            yield chunk
        final_summary = execution_result.get("summary")
        summary_content = final_summary
        if not summary_content:
            summary_content = "执行完成。"
        yield [
            MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=summary_content,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.SKILL_OBSERVATION.value,
                show_content=summary_content,
            )
        ]
        return
