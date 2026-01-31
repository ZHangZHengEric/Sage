from typing import List, Dict, Any, Optional, AsyncGenerator, Union, cast
import json
import uuid
import asyncio
from copy import deepcopy
import tempfile
import shutil
import os

import re
from sagents.agent.agent_base import AgentBase
from sagents.context.session_context import SessionContext
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager
from sagents.skill.skill_tool import SkillTools


class SkillExecutorAgent(AgentBase):

    def __init__(self, model: Any = None, model_config: Dict[str, Any] = {}, system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "SkillExecutorAgent"
        self.agent_description = "SkillExecutorAgent: 负责按需加载和执行技能。"

    def _get_active_skill_from_history(self, messages: List[MessageChunk]) -> Optional[str]:
        # 倒序遍历，找到最近的一次状态变更
        for msg in reversed(messages):
            if not msg.tool_calls:
                continue

            tool_calls = msg.tool_calls
            if isinstance(tool_calls, list):
                # 同一条消息可能有多个 tool call，通常按顺序执行，倒序遍历时应注意
                # 这里假设一条消息里的 tool calls 顺序是从前到后的，
                # 但我们是倒序遍历消息。对于同一条消息内的 tool calls，
                # 如果我们想找“最后生效”的，应该看最后一个 tool call。
                # 所以我们也倒序遍历 tool calls
                for tc in reversed(tool_calls):
                    func_name = ""
                    args_str = ""
                    if isinstance(tc, dict):
                        func_name = tc.get("function", {}).get("name", "")
                        args_str = tc.get("function", {}).get("arguments", "")
                    else:
                        try:
                            func = getattr(tc, "function", None)
                            if func:
                                func_name = getattr(func, "name", "")
                                args_str = getattr(func, "arguments", "")
                        except Exception:
                            pass

                    if func_name == "load_skill":
                        args = self._safe_parse_args(args_str)
                        return args.get("skill_name")
                    elif func_name == "unload_skill":
                        return None
        return None

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[Any] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        logger.info(f"SkillExecutorAgent: 全部消息长度：{MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], message_manager.messages))}")
        
        # 使用全量消息检查技能状态，避免因上下文截断导致状态丢失
        active_skill_name = self._get_active_skill_from_history(message_manager.messages)
        
        history_messages = message_manager.extract_all_context_messages(recent_turns=20, last_turn_user_only=True)
        logger.info(
            f"SkillExecutorAgent: 获取历史消息的条数:{len(history_messages)}，历史消息的content长度：{MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], history_messages))}"
        )

        # 检查是否有活跃的技能
        if active_skill_name:
            logger.info(f"SkillExecutorAgent: 检测到活跃技能 {active_skill_name}，跳过选择阶段，直接执行。")
            # 阶段二：技能执行 (跳过规划)
            async for chunk in self._execute_skill(
                session_id=session_id,
                history_messages=history_messages,
                session_context=session_context,
                selected_skill_name=active_skill_name,
                skip_planning=True,
            ):
                yield chunk
            return

        prompt_template = PromptManager().get_agent_prompt_auto("SKILL_EXECUTOR_SELECT_PROMPT", language=session_context.get_language())
        # 补充全部可选择的技能列表到system prompt
        select_system_prompt = prompt_template.format(available_skills="\n".join(session_context.skill_manager.get_skill_description_lines()))

        select_system_message = MessageChunk(role=MessageRole.SYSTEM.value, content=select_system_prompt, message_id=str(uuid.uuid4()), message_type=MessageType.SYSTEM.value)
        # 拷贝一个新的列表，避免修改原列表（使用浅拷贝替代 deepcopy 以防递归错误）
        history_messages_for_select = list(history_messages)
        history_messages_for_select.insert(0, select_system_message)
        # 阶段一：技能意图识别选择
        selection_result = {}
        async for chunk in self._select_skill(
            session_id=session_id,
            history_messages=history_messages_for_select,
            session_context=session_context,
            selection_result=selection_result,
        ):
            yield chunk

        selected_skill_name = selection_result.get("skill_name")
        if not selected_skill_name:
            logger.warning(f"SkillExecutorAgent: 未选择任何技能。")
            return
        # 阶段二：技能执行
        async for chunk in self._execute_skill(
            session_id=session_id,
            history_messages=history_messages,
            session_context=session_context,
            selected_skill_name=selected_skill_name,
        ):
            yield chunk
        return

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

    async def _stream_llm_and_collect(
        self,
        *,
        messages: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str],
        step_name: str,
        model_config_override: Dict[str, Any],
        content_message_type: str,
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
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
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

    async def _invoke_tool(
        self,
        func_name: str,
        args: Dict[str, Any],
        tool_map: Dict[str, Any],
    ) -> str:
        if func_name in tool_map:
            try:
                if asyncio.iscoroutinefunction(tool_map[func_name]):
                    return await tool_map[func_name](**args)
                return await asyncio.to_thread(tool_map[func_name], **args)
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
            type=MessageType.SKILL_EXEC_TOOL_CALL_RESULT.value,
            message_type=MessageType.SKILL_EXEC_TOOL_CALL_RESULT.value,
            show_content=str(result),
        )

    async def _select_skill(
        self, session_id: Optional[str], history_messages: List[MessageChunk], session_context: SessionContext, selection_result: Dict[str, Any]
    ) -> AsyncGenerator[List[MessageChunk], None]:
        step_tool_calls: Dict[str, Any] = {}
        select_tool_defs = SkillTools.get_select_tool_definitions()

        async for chunk in self._stream_llm_and_collect(
            messages=history_messages,
            session_id=session_id,
            step_name="skill_executor_select",
            model_config_override={
                "tools": select_tool_defs,
            },
            content_message_type=MessageType.SKILL_SELECT_RESULT.value,
            tool_calls=step_tool_calls,
        ):
            yield chunk

        if not step_tool_calls:
            logger.info("SkillExecutorAgent: 没有找到合适的技能，返回原逻辑")
            return

        selected_skill_name = None
        tool_call = list(step_tool_calls.values())[0]
        output_messages = self._create_tool_call_message(tool_call)
        yield output_messages
        func_name = tool_call["function"]["name"]
        args = self._safe_parse_args(tool_call["function"]["arguments"])
        if func_name == "load_skill":
            try:
                selected_skill_name = args.get("skill_name")
                # 验证技能存在
                instructions = session_context.skill_manager.get_skill_instructions(selected_skill_name)
                if not selected_skill_name or not instructions:
                    logger.info("SkillExecutorAgent: 技能 %s 不存在或没有指令", selected_skill_name)
                    return
            except Exception as e:
                yield [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=str(f"执行技能选择工具错误 {func_name}: {e}"),
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.ERROR.value,
                        show_content=str(f"执行技能选择工具错误 {func_name}: {e}"),
                    )
                ]
            msg_chunk = MessageChunk(
                role=MessageRole.TOOL.value,
                content=f"启动技能: {selected_skill_name} 处理中...",
                tool_call_id=tool_call["id"],
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value,
                type=MessageType.TOOL_CALL_RESULT.value,
                show_content=f"启动技能: {selected_skill_name} 处理中...",
            )
            yield [msg_chunk]
            selection_result["skill_name"] = selected_skill_name

    async def _check_task_status(
        self,
        messages_input: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str],
        session_context: SessionContext,
    ) -> str:
        if not messages_input:
            return "WAIT_USER"
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
            return "WAIT_USER"

        last_user_index = None
        for i, message in enumerate(message_chunks):
            if message.role == MessageRole.USER.value and (message.type == MessageType.NORMAL.value or message.message_type == MessageType.NORMAL.value):
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = message_chunks[last_user_index:]
        else:
            messages_for_complete = message_chunks
        clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_for_complete)

        status_prompt_template = PromptManager().get_agent_prompt_auto("task_complete_template", language=session_context.get_language())
        messages_input = [
            {"role": "system", "content": status_prompt_template.format(messages=json.dumps(clean_messages, ensure_ascii=False, indent=2))},
        ]
        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            session_id=session_id,
            step_name="skill_task_status_check",
            model_config_override={"response_format": {"type": "json_object"}}
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
            return result.get("status", "WAIT_USER")
        except Exception:
            logger.warning("SkillExecutorAgent: 解析任务状态判断响应时出错")
            return "WAIT_USER"

    def _parse_plan_xml(self, xml_content: str) -> List[Dict[str, str]]:
        try:
            # Attempt to find <plan>...</plan>
            match = re.search(r"<plan>(.*?)</plan>", xml_content, re.DOTALL)
            if match:
                xml_content = match.group(1)

            steps = []
            # Naive regex parsing for <step>...</step>
            step_pattern = re.compile(r"<step>(.*?)</step>", re.DOTALL)
            for step_match in step_pattern.finditer(xml_content):
                step_content = step_match.group(1)
                step_info = {}

                id_match = re.search(r"<id>(.*?)</id>", step_content)
                if id_match:
                    step_info["id"] = id_match.group(1).strip()

                instruction_match = re.search(r"<instruction>(.*?)</instruction>", step_content, re.DOTALL)
                if instruction_match:
                    step_info["instruction"] = instruction_match.group(1).strip()

                intent_match = re.search(r"<intent>(.*?)</intent>", step_content, re.DOTALL)
                if intent_match:
                    step_info["intent"] = intent_match.group(1).strip()

                if step_info.get("instruction"):
                    steps.append(step_info)
            return steps
        except Exception as e:
            logger.error(f"Failed to parse plan XML: {e}")
            return []

    async def _generate_execution_plan(
        self,
        session_context: SessionContext,
        sandbox_skill_info: Dict[str, Any],
        history_messages: List[MessageChunk],
        plan_output: List[Any],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        prompt_template = PromptManager().get_agent_prompt_auto("SKILL_GENERATION_PLAN_PROMPT", language=session_context.get_language())
        system_prompt = prompt_template.format(
            skill_name=sandbox_skill_info.get("name"),
            skill_description=sandbox_skill_info.get("description"),
            skill_path=sandbox_skill_info.get("path"),
            instructions=sandbox_skill_info.get("instructions"),
            messages=history_messages,
        )
        system_msg = MessageChunk(role=MessageRole.SYSTEM.value, content=system_prompt, message_id=str(uuid.uuid4()), message_type=MessageType.SYSTEM.value)
        messages = [system_msg]

        full_content = ""
        step_tool_calls: Dict[str, Any] = {}
        async for chunk in self._stream_llm_and_collect(
            messages=messages,
            session_id=session_context.session_id,
            step_name="skill_plan_generation",
            model_config_override={"temperature": 0.2},
            content_message_type=MessageType.SKILL_EXEC_PLAN.value,
            tool_calls=step_tool_calls,
        ):
            yield chunk
            if chunk and chunk[0].content:
                full_content += chunk[0].content

        plan_steps = self._parse_plan_xml(full_content)
        
        # 强制添加提取产物的步骤
        try:
            next_id = 1
            if plan_steps:
                try:
                    next_id = int(plan_steps[-1].get("id", "0")) + 1
                except ValueError:
                    next_id = len(plan_steps) + 1
            
            artifact_step = {
                "id": str(next_id),
                "instruction": "技能执行完毕。评估上文中的最终输出产物，并输出到用户工作空间(使用 submit_skill_outputs)。",
                "intent": "确保产物提交"
            }
            plan_steps.append(artifact_step)
            logger.info("SkillExecutorAgent：已强制添加产物提取步骤。")
        except Exception as e:
            logger.warning(f"SkillExecutorAgent：强制添加产物提取步骤失败: {e}")

        plan_output.extend(plan_steps)
        if len(plan_steps) == 0:
            logger.warning("SkillExecutorAgent：技能执行计划为空。尝试使用兜底策略执行。")
            plan_steps.append({"id": "1", "instruction": "基于用户请求执行技能指令。", "intent": "兜底策略"})
            # 保存计划步骤到沙盒目录里的文件
        try:
            sandbox_path = sandbox_skill_info.get("path", session_context.agent_workspace)
            plan_file_path = os.path.join(sandbox_path, "plan_steps.json")
            with open(plan_file_path, "w", encoding="utf-8") as f:
                json.dump(plan_steps, f, ensure_ascii=False, indent=4)
            logger.info(f"SkillExecutorAgent：技能执行计划已保存到 {plan_file_path}")
        except Exception as e:
            logger.error(f"SkillExecutorAgent：技能执行计划保存失败: {e}")

    async def _execute_skill(
        self, session_id: Optional[str], history_messages: List[MessageChunk], session_context: SessionContext, selected_skill_name: str, skip_planning: bool = False
    ) -> AsyncGenerator[List[MessageChunk], None]:
        skill_manager = session_context.skill_manager
        skill_metadata = skill_manager.get_skill_metadata(selected_skill_name) or {}

        # 创建独立环境的临时沙盒 (使用固定路径以支持多轮对话)
        temp_sandbox_path = os.path.join(session_context.agent_workspace, f"skill_sandbox_{selected_skill_name}")
        logger.info(f"SkillExecutorAgent： 使用沙盒目录 {temp_sandbox_path}")

        try:
            if not os.path.exists(temp_sandbox_path):
                os.makedirs(temp_sandbox_path, exist_ok=True)
                # 将skills的文件拷贝过去
                skill_source_path = skill_metadata.get("path")
                if skill_source_path and os.path.exists(skill_source_path):
                    try:
                        # 递归拷贝所有内容到沙盒根目录
                        shutil.copytree(skill_source_path, temp_sandbox_path, dirs_exist_ok=True)
                        logger.info(f"拷贝技能 {selected_skill_name} 的文件到沙盒目录 {temp_sandbox_path}")
                    except Exception as e:
                        logger.error(f"拷贝技能 {selected_skill_name} 的文件到沙盒目录 {temp_sandbox_path} 失败: {e}")
                        return
            else:
                logger.info(f"使用已存在的沙盒目录 {temp_sandbox_path}")

            sandbox_skill_info = {**skill_metadata, "path": temp_sandbox_path, "instructions": skill_manager.get_skill_instructions(selected_skill_name)+"\n技能相关文件的相对路径地址：\n".join(skill_manager.get_skill_file_list(selected_skill_name))}
            skill_tools = SkillTools(skill_manager, agent_workspace=session_context.agent_workspace, skill_workspace_path=temp_sandbox_path)
            tool_map = {
                 "read_skill_file": skill_tools.read_skill_file,
                 "write_temp_file": skill_tools.write_temp_file,
                 "run_skill_script": skill_tools.run_skill_script,
                 "submit_skill_outputs": skill_tools.submit_skill_outputs,
            }
            task_finished = False

            # plan_steps = []
            # if not skip_planning:
            #     async for chunk in self._generate_execution_plan(session_context, sandbox_skill_info, history_messages, plan_steps):
            #         yield chunk
            # else:
            #     # 尝试加载已有的计划
            #     try:
            #         plan_file_path = os.path.join(temp_sandbox_path, "plan_steps.json")
            #         if os.path.exists(plan_file_path):
            #             with open(plan_file_path, "r", encoding="utf-8") as f:
            #                 plan_steps = json.load(f)
            #             logger.info(f"SkillExecutorAgent：加载已有计划 {len(plan_steps)} 步")
            #         else:
            #             logger.warning("SkillExecutorAgent：跳过规划且无已有计划文件，使用默认空计划。")
            #     except Exception as e:
            #         logger.error(f"SkillExecutorAgent：加载已有计划失败: {e}")

            execute_system_prompt_prefix = (PromptManager().get_agent_prompt_auto("INSTRUCTION_SKILL_EXECUTION_PROMPT", language=session_context.get_language())
                .format(
                    skill_name=sandbox_skill_info.get("name", ""),
                    skill_description=sandbox_skill_info.get("description", ""),
                    skill_path=sandbox_skill_info.get("path", ""),
                    instructions=sandbox_skill_info.get("instructions", ""),
                    # plan_steps=plan_steps,
                )
            )
            # 将system 加入到到messages中
            execute_system = self.prepare_unified_system_message(
                session_id,
                custom_prefix=execute_system_prompt_prefix,
                language=session_context.get_language(),
            )
            tool_definitions_for_llm = skill_tools.get_execute_tool_definitions()
            # 执行的system message
            history_messages.insert(0, execute_system)
            all_new_response_chunks: List[MessageChunk] = []

            loop_count = 0
            while loop_count < 20:
                loop_count += 1

                # 合并消息
                history_messages = MessageManager.merge_new_messages_to_old_messages(
                    cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks), cast(List[Union[MessageChunk, Dict[str, Any]]], history_messages)
                )
                all_new_response_chunks = []
                step_tool_calls = {}
                async for chunks in self._stream_llm_and_collect(
                    messages=history_messages,
                    session_id=session_id,
                    step_name=f"skill_executor_step_{loop_count}",
                    model_config_override={
                        "tools": tool_definitions_for_llm,
                        "temperature": 0.2,
                        "tool_choice": "auto",
                    },
                    content_message_type=MessageType.SKILL_EXEC_RESULT.value,
                    tool_calls=step_tool_calls,
                ):
                    non_empty_chunks = [c for c in chunks if (c.message_type != MessageType.EMPTY.value)]
                    if len(non_empty_chunks) > 0:
                        all_new_response_chunks.extend(deepcopy(non_empty_chunks))
                    yield chunks

                if step_tool_calls:
                    for tool_call in list(step_tool_calls.values()):
                        output_messages = self._create_tool_call_message(tool_call)
                        # skill的tool call 不存储
                        output_messages[0].message_type = MessageType.SKILL_EXEC_TOOL_CALL.value
                        output_messages[0].type = MessageType.SKILL_EXEC_TOOL_CALL.value
                        yield output_messages
                        all_new_response_chunks.extend(deepcopy(output_messages))
                        func_name = tool_call["function"]["name"]
                        args = self._safe_parse_args(tool_call["function"]["arguments"])

                        result = await self._invoke_tool(func_name, args, tool_map)
                        msg_chunk = self._build_tool_result_chunk(tool_call["id"], result)
                        yield [msg_chunk]
                        all_new_response_chunks.append(deepcopy(msg_chunk))
                else:
                    # 合并消息以进行状态检查
                    history_messages = MessageManager.merge_new_messages_to_old_messages(
                        cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks), cast(List[Union[MessageChunk, Dict[str, Any]]], history_messages)
                    )
                    all_new_response_chunks = []

                    status = await self._check_task_status(history_messages, session_id, session_context)
                    if status == "COMPLETED":
                        task_finished = True
                        break
                    elif status == "WAIT_USER":
                        task_finished = False
                        break

            if task_finished:
                final_summary = history_messages[len(history_messages) - 1].content
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=final_summary, message_id=str(uuid.uuid4()), message_type=MessageType.SKILL_OBSERVATION.value)]
                mock_message_id = str(uuid.uuid4())
                # 任务完成，卸载技能
                unload_msg1 = MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    tool_calls=[{
                        "id": mock_message_id,
                        "type": "function",
                        "function": {
                            "name": "unload_skill",
                            "arguments": "{}"
                        }
                    }],
                    message_type=MessageType.TOOL_CALL.value
                )
                yield [unload_msg1]
                # 任务完成，卸载技能
                unload_msg2 = MessageChunk(
                    tool_call_id=mock_message_id,
                    role=MessageRole.TOOL.value,
                    content="卸载完成",
                    message_type=MessageType.TOOL_CALL_RESULT.value
                )
                yield [unload_msg2]
                 
                try:
                    shutil.rmtree(temp_sandbox_path)
                    logger.info(f"Removed temp sandbox {temp_sandbox_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temp sandbox: {e}")

        finally:
            pass
            pass
