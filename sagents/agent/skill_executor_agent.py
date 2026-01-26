from typing import List, Dict, Any, Optional, AsyncGenerator, Union, cast
import json
import uuid
from sagents.agent.agent_base import AgentBase
from sagents.context.session_context import SessionContext
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.skills import SkillProxy, SkillManager
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager
from sagents.skills.skill_tool import SkillTools


class SkillExecutorAgent(AgentBase):

    def __init__(self, model: Any = None, model_config: Dict[str, Any] = {}, system_prefix: str = ""):
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
                logger.warning(f"SkillExecutorAgent: Tool arguments parsed to non-dict ({type(args)}). args_str={args_str}")
                return {}
            return args
        except Exception as e:
            logger.warning(f"SkillExecutorAgent: Failed to parse tool arguments: {e}. args_str={args_str}")
            return {}

    async def _select_skill(
        self,
        session_id: Optional[str],
        chain_step: int,
        chain_messages: List[Dict[str, Any]],
        all_skill_tool_defs: List[Dict[str, Any]],
        tool_map: Dict[str, Any],
        selection_result: Dict[str, Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        logger.info(f"SkillExecutorAgent: Chain Step {chain_step+1} - Selection")
        step1_chunks = []
        step1_tool_calls: Dict[str, Any] = {}
        step1_last_tool_call_id: Optional[str] = None

        load_skill_def = next((t for t in all_skill_tool_defs if t["function"]["name"] == "load_skill"), None)

        async for chunk in self._call_llm_streaming(
            messages=chain_messages,
            session_id=session_id,
            step_name=f"skill_executor_select_{chain_step}",
            model_config_override={"tools": [load_skill_def] if load_skill_def else [], "tool_choice": "auto"},
        ):
            if chunk is None: continue
            if chunk.choices is None or len(chunk.choices) == 0: continue

            step1_chunks.append(chunk)
            delta = chunk.choices[0].delta

            if delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, step1_tool_calls, step1_last_tool_call_id or "")
                for tc in delta.tool_calls:
                    if tc.id: step1_last_tool_call_id = tc.id
                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_type=MessageType.EMPTY.value,
                        type=MessageType.EMPTY.value,
                        message_id=str(uuid.uuid4()),
                        show_content="",
                    )
                ]

            if delta.content:
                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=delta.content,
                        message_type=MessageType.SKILL_SELECT_RESULT.value,
                        type=MessageType.SKILL_SELECT_RESULT.value,
                        message_id=str(uuid.uuid4()),
                        show_content=delta.content,
                    )
                ]

        step1_response = self.merge_stream_response_to_non_stream_response(step1_chunks)
        if not step1_response or not step1_response.choices:
            return

        step1_assistant_msg = step1_response.choices[0].message
        chain_messages.append(step1_assistant_msg.model_dump())

        if not step1_tool_calls:
            logger.info("SkillExecutorAgent: No skill selected.")
            return

        # Handle Tool Calls
        tool_calls_dicts = list(step1_tool_calls.values())
        yield [
            MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=step1_assistant_msg.content,
                tool_calls=tool_calls_dicts,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL.value,
            )
        ]

        selected_skill_name = None
        skill_instructions = None

        for tool_call in tool_calls_dicts:
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

                confirmation_content = f"启动技能: {selected_skill_name}"
                yield [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content=confirmation_content,
                        tool_call_id=tool_call["id"],
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                        type=MessageType.TOOL_CALL_RESULT.value,
                        show_content=confirmation_content,
                    )
                ]
                skill_instructions = result
                chain_messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": confirmation_content})
        
        selection_result["skill_name"] = selected_skill_name
        selection_result["instructions"] = skill_instructions

    async def _is_skill_complete(
        self,
        messages_input: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str],
        language: str
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
            if message.role == MessageRole.USER.value and (message.type == MessageType.NORMAL.value or message.message_type == MessageType.NORMAL.value):
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = message_chunks[last_user_index:]
        else:
            messages_for_complete = message_chunks
        clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_for_complete)

        task_complete_template = PromptManager().get_agent_prompt_auto('task_complete_template', language=language)
        prompt = task_complete_template.format(
            session_id=session_id or "",
            messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
        )
        messages_input = [{'role': 'user', 'content': prompt}]
        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            session_id=session_id,
            step_name="skill_task_complete_judge"
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
            return result.get('task_interrupted', False)
        except json.JSONDecodeError:
            logger.warning("SkillExecutorAgent: 解析任务完成判断响应时JSON解码错误")
            return False

    async def _execute_skill(
        self,
        session_id: Optional[str],
        chain_step: int,
        skill_name: str,
        skill_instructions: str,
        chain_messages: List[Dict[str, Any]],
        skill_manager: Union[SkillManager, SkillProxy],
        language: str,
        all_skill_tool_defs: List[Dict[str, Any]],
        tool_map: Dict[str, Any],
        execution_result: Dict[str, Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:

        skill_metadata = skill_manager.get_skill_metadata(skill_name) or {}

        # Use relative path for skill_path in prompt to avoid leaking absolute paths
        skill_path = f"skills/{skill_name}"

        instruction_prompt_template = PromptManager().get_agent_prompt_auto(
            "INSTRUCTION_SKILL_EXECUTION_PROMPT", language=language
        )
        execution_system_prompt = instruction_prompt_template.format(
            skill_name=skill_metadata.get("name", skill_name),
            skill_description=skill_metadata.get("description", ""),
            skill_path=skill_path,
            instructions=skill_instructions,
        )
        execution_system_message = self.prepare_unified_system_message(session_id=session_id, language=language, system_prefix_override=execution_system_prompt)

        exec_messages = [execution_system_message]
        if len(chain_messages) > 1:
            exec_messages.extend(chain_messages[1:])

        tool_definitions_for_llm = [t for t in all_skill_tool_defs if t["function"]["name"] != "load_skill"]

        max_steps = 10
        skill_completed = False
        final_summary = None
        for step in range(max_steps):
            content_message_id = str(uuid.uuid4())
            chunks = []
            tool_calls: Dict[str, Any] = {}
            last_tool_call_id: Optional[str] = None

            async for chunk in self._call_llm_streaming(
                messages=exec_messages,
                session_id=session_id,
                step_name=f"skill_executor_step_{chain_step}_{step}",
                model_config_override={"tools": tool_definitions_for_llm, "tool_choice": "auto"},
            ):
                chunks.append(chunk)
                if chunk is None or chunk.choices is None or len(chunk.choices) == 0: continue

                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
                    for tc in delta.tool_calls:
                        if tc.id: last_tool_call_id = tc.id
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
                    yield [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=delta.content,
                            message_type=MessageType.SKILL_OBSERVATION.value,
                            type=MessageType.SKILL_OBSERVATION.value,
                            message_id=content_message_id,
                            show_content=delta.content,
                        )
                    ]

            response = self.merge_stream_response_to_non_stream_response(chunks)
            if not response or not response.choices:
                break

            assistant_msg = response.choices[0].message
            exec_messages.append(assistant_msg.model_dump())
            chain_messages.append(assistant_msg.model_dump())

            if assistant_msg.tool_calls:
                tool_calls_dicts = []
                for tc in assistant_msg.tool_calls:
                    tool_calls_dicts.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })

                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=assistant_msg.content,
                        tool_calls=tool_calls_dicts,
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.TOOL_CALL.value,
                    )
                ]

                for tool_call in assistant_msg.tool_calls:
                    func_name = tool_call.function.name
                    args = self._safe_parse_args(tool_call.function.arguments)

                    result = ""
                    if func_name in tool_map:
                        try:
                            result = tool_map[func_name](**args)
                        except Exception as e:
                            result = f"Error executing {func_name}: {e}"
                    else:
                        result = f"Error: Tool '{func_name}' not found"

                    yield [
                        MessageChunk(
                            role=MessageRole.TOOL.value,
                            content=str(result),
                            tool_call_id=tool_call.id,
                            message_id=str(uuid.uuid4()),
                            type=MessageType.TOOL_CALL_RESULT.value,
                            message_type=MessageType.TOOL_CALL_RESULT.value,
                            show_content=str(result),
                        )
                    ]

                    tool_msg = {"role": "tool", "tool_call_id": tool_call.id, "content": str(result)}
                    exec_messages.append(tool_msg)
                    chain_messages.append(tool_msg)

            skill_completed = await self._is_skill_complete(exec_messages, session_id, language)
            if skill_completed:
                if assistant_msg.content:
                    final_summary = assistant_msg.content
                logger.info(f"SkillExecutorAgent: Skill '{skill_name}' completed.")
                break

        execution_result["summary"] = final_summary

    async def run_stream(
        self,
        session_context: SessionContext,
        tool_manager: Optional[Any] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:

        skill_manager = session_context.skill_manager
        language = session_context.get_language()
        if not skill_manager:
            logger.warning("SkillExecutorAgent: 未找到 SkillManager")
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

        skill_tools = SkillTools(skill_manager, agent_workspace=session_context.agent_workspace)
        all_skill_tool_defs = SkillTools.get_tool_definitions()

        tool_map = {
            "load_skill": skill_tools.load_skill,
            "read_skill_file": skill_tools.read_skill_file,
            "run_skill_script": skill_tools.run_skill_script,
            "write_temp_file": skill_tools.write_temp_file,
            "edit_temp_file": skill_tools.edit_temp_file,
        }
        prompt_template = PromptManager().get_agent_prompt_auto("SKILL_EXECUTOR_SELECT_PROMPT", language=session_context.get_language())
        system_prompt = prompt_template.format(available_skills="\n".join(skill_manager.get_skill_description_lines(style="planner")))
        # 3.
        chain_messages = [{"role": "system", "content": system_prompt}]
        # Add Context
        context_messages = session_context.message_manager.extract_all_context_messages(recent_turns=10, last_turn_user_only=False)
        chain_messages.extend([msg.to_dict() for msg in context_messages])

        # --- Outer Loop: 多技能支持，最多执行 max_chain_steps 步 ---
        max_chain_steps = 5
        final_summary = None

        for chain_step in range(max_chain_steps):
            logger.info(f"SkillExecutorAgent: 链式执行第 {chain_step+1}/{max_chain_steps} 步")

            # 阶段一：技能意图识别选择 (Skill Selection)
            selection_result = {}
            async for chunk in self._select_skill(
                session_id=session_id, 
                chain_step=chain_step, 
                chain_messages=chain_messages, 
                all_skill_tool_defs=all_skill_tool_defs, 
                tool_map=tool_map, 
                selection_result=selection_result
            ):
                yield chunk

            selected_skill_name = selection_result.get("skill_name")
            skill_instructions = selection_result.get("instructions")

            # If NO tool call, it means the agent decided to finish (or just talk)
            if not selected_skill_name:
                logger.info("SkillExecutorAgent: No skill selected, finishing chain.")
                return

            if not skill_instructions or str(skill_instructions).startswith("Error"):
                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="未能成功加载技能指令，无法继续执行。",
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.ERROR.value,
                        show_content="未能成功加载技能指令，无法继续执行。",
                    )
                ]
                # Break chain on error
                break

            # Phase 2: Execution Loop for Selected Skill
            execution_result = {}
            async for chunk in self._execute_skill(
                session_id=session_id,
                chain_step=chain_step,
                skill_name=selected_skill_name,
                skill_instructions=skill_instructions,
                chain_messages=chain_messages,
                skill_manager=skill_manager,
                language=language,
                all_skill_tool_defs=all_skill_tool_defs,
                tool_map=tool_map,
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
