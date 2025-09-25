
import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.tasks.task_base import TaskBase, TaskStatus
import json
import uuid
from copy import deepcopy

class TaskObservationAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.OBSERVATION_PROMPT_TEMPLATE = """# 任务执行分析指南
通过用户的历史对话，来观察用户的需求或者任务

## 用户历史对话
{task_description}

## 任务管理器状态（未更新的状态，需要本次分析去更新）
{task_manager_status}

## 近期完成动作详情
{execution_results}

## 分析要求
1. 评估当前执行是否满足任务要求
2. 确定任务完成状态：
   - in_progress: 任务正在进行中，需要继续执行
   - completed: 任务已完成，无需进一步操作
   - need_user_input: 需要用户输入才能继续
   - failed: 任务执行失败，无法继续
3. 评估任务整体完成百分比，范围0-100
4. 根据近期完成动作详情，判断哪些任务已经完成，不要仅仅依赖任务管理器状态

## completion_status设置为completed，即任务已完成，满足以下条件其中一个即可，与任务整体完成百分比不冲突：
1. 当前已经执行的动作的结果，可以满足对于用户任务回复的数据支持。
2. 当前在执行重复的动作，且动作的结果没有发生变化。
3. 当前完成对用户任务的理解，需要等待用户进一步的反馈，以便进一步满足他们的需求。
4. 当子任务全部完成时

## 子任务完成判断规则
1. **基于执行结果判断**：仔细分析近期完成动作详情，如果某个子任务的核心要求已经通过执行动作完成，即使任务管理器状态显示为pending，也应该标记为已完成
2. **子任务内容匹配**：将执行结果与子任务描述进行匹配，如果执行结果已经覆盖了子任务的核心要求，则认为子任务完成
3. **数据完整性**：如果子任务要求收集特定信息，且执行结果显示已经收集到这些信息，则认为子任务完成
4. **不要过度保守**：如果执行结果显示已经完成了子任务的核心目标，不要因为任务管理器状态而犹豫标记为完成
5. **灵活调整子任务**：如果执行过程中，发现子任务是不必要或者可以跳过的，则认为子任务完成

## 子任务失败判断规则
1. 当子任务执行失败，且失败次数**超过2次**时，认为子任务失败

## 特殊规则
1. 上一步完成了数据搜索，后续还需要对搜索结果进行进一步的理解和处理，不能认为是任务完成
2. analysis中不要带有工具的真实名称，以及不要输出任务的序号，只需要输出任务的描述。
3. 只输出以下格式的XML，不要输出其他内容，不要输出```
4. 任务状态更新基于实际执行结果，不要随意标记为完成
5. 尽可能减少用户输入，不要打扰用户，按照你对事情的完整理解，尽可能全面的完成事情
6. 针对**多次**尝试确定了无法完成或者失败的子任务，不要再次尝试，跳过该任务。
7. analysis 部分不要超过100字。
8. 如果基于当前的工具和能力，发现无法完成任务，将 finish_percent 设置为100，completion_status 设置为failed。
9. 对于一次没有成功的子任务，要积极尝试使用其他工具或者方法，以增加成功的机会。

## 输出格式
```
<analysis>
分析近期完成动作详情的执行情况进行总结，指导接下来的方向要详细一些，一段话不要有换行。
</analysis>
<finish_percent>
40
</finish_percent>
<completion_status>
in_progress
</completion_status>
<completed_task_ids>
["1","2"]
</completed_task_ids>
<pending_task_ids>
["3","4"]
</pending_task_ids>
<failed_task_ids>
["5"]
</failed_task_ids>
```
## 输出字段描述：
finish_percent：子任务完成数量的百分比数字，格式：30，范围0-100，100表示所有的子任务都完成
completion_status：任务完成状态，in_progress（进行中）、completed（已完成）、need_user_input（需要用户输入）、failed（失败）
completed_task_ids：已完成的子任务ID列表，格式：["1", "2"]，通过近期完成动作详情以及任务管理器状态，判定已完成的子任务ID列表
pending_task_ids：未完成的子任务ID列表，格式：["3", "4"]，通过近期完成动作详情以及任务管理器状态，判定未完成的子任务ID列表
failed_task_ids：无法完成的子任务ID列表，格式：["5"]，通过近期完成动作详情以及任务管理器状态，经过3次尝试执行后，判定无法完成的子任务ID列表
"""  
        self.agent_name = "ObservationAgent"
        self.agent_description = "观测智能体，专门负责基于当前状态生成下一步执行计划"
        logger.info("TaskObservationAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'

        recent_execution_results_messages = message_manager.extract_after_last_observation_messages()
        recent_execution_results_messages_str = MessageManager.convert_messages_to_str(recent_execution_results_messages)

        prompt = self.OBSERVATION_PROMPT_TEMPLATE.format(
            task_description=task_description_messages_str,
            task_manager_status=task_manager_status,
            execution_results=recent_execution_results_messages_str
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.OBSERVATION.value
            )
        ]
        message_id = str(uuid.uuid4())
        unknown_content = ''
        all_content = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="observation"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content + delta_content_char
                    # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all, all_content, tag_type=['finish_percent','completion_status','analysis','completed_task_ids','pending_task_ids','failed_task_ids'])
                    all_content += delta_content_char
                    
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['analysis']:
                            if tag_type != last_tag_type:
                                yield [MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    content='',
                                    message_id=message_id,
                                    show_content='\n\n',
                                    message_type=MessageType.OBSERVATION.value
                                )]
                            
                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content='',
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type=MessageType.OBSERVATION.value
                            )]
                        last_tag_type = tag_type
        yield from self._finalize_observation_result(
            session_context=session_context,
            all_content=all_content, 
            message_id=message_id,
            task_manager = task_manager
        )
    def _finalize_observation_result(self,session_context:SessionContext,all_content:str,message_id:str,task_manager:TaskManager):
        """
        最终化观测结果
        """
        try:
            response_json = self.convert_xlm_to_json(all_content)
            logger.info(f"ObservationAgent: 观察分析结果: {response_json}")
            if "all_observations" not in session_context.audit_status:
                session_context.audit_status["all_observations"] = []
            session_context.audit_status["all_observations"].append(response_json)

            # 更新TaskManager中的任务状态
            if task_manager:
                self._update_task_manager_status(task_manager, response_json)
            
            # 创建最终结果消息（不需要usage信息，因为这是转换过程）
            result_message = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='执行评估: ' + json.dumps(response_json, ensure_ascii=False),
                message_id=message_id,
                show_content='\n',
                message_type=MessageType.OBSERVATION.value
            )
            
            yield [result_message]
            
        except Exception as e:
            logger.error(f"ObservationAgent: 解析观察结果时发生错误: {str(e)}")
            logger.error(f"ObservationAgent: 原始XML内容: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"任务观测失败: {str(e)}",
                message_id=str(uuid.uuid4()),
                show_content=f"任务观测失败: {str(e)}",
                message_type=MessageType.OBSERVATION.value
            )]
    def convert_xlm_to_json(self, xlm_content: str) -> Dict[str, Any]:
        
        logger.debug("ObservationAgent: 转换XML内容为JSON格式")
        try:
            # 提取finish_percent并转换为int类型
            finish_percent = xlm_content.split('<finish_percent>')[1].split('</finish_percent>')[0].strip()
            finish_percent = int(finish_percent)
            
            # 提取completion_status
            completion_status = xlm_content.split('<completion_status>')[1].split('</completion_status>')[0].strip()
            
            # 提取analysis
            analysis = xlm_content.split('<analysis>')[1].split('</analysis>')[0].strip()
            
            # 提取completed_task_ids
            completed_task_ids = []
            if '<completed_task_ids>' in xlm_content and '</completed_task_ids>' in xlm_content:
                completed_task_ids_str = xlm_content.split('<completed_task_ids>')[1].split('</completed_task_ids>')[0].strip()
                try:
                    completed_task_ids = json.loads(completed_task_ids_str) if completed_task_ids_str else []
                except:
                    completed_task_ids = []
            
            # 提取pending_task_ids
            pending_task_ids = []
            if '<pending_task_ids>' in xlm_content and '</pending_task_ids>' in xlm_content:
                pending_task_ids_str = xlm_content.split('<pending_task_ids>')[1].split('</pending_task_ids>')[0].strip()
                try:
                    pending_task_ids = json.loads(pending_task_ids_str) if pending_task_ids_str else []
                except:
                    pending_task_ids = []
            
            # 提取failed_task_ids
            failed_task_ids = []
            if '<failed_task_ids>' in xlm_content and '</failed_task_ids>' in xlm_content:
                failed_task_ids_str = xlm_content.split('<failed_task_ids>')[1].split('</failed_task_ids>')[0].strip()
                try:
                    failed_task_ids = json.loads(failed_task_ids_str) if failed_task_ids_str else []
                except:
                    failed_task_ids = []
            
            # 构建响应JSON - 只保留简化后的字段
            response_json = {
                "finish_percent": finish_percent,
                "completion_status": completion_status,
                "analysis": analysis,
                "completed_task_ids": completed_task_ids,
                "pending_task_ids": pending_task_ids,
                "failed_task_ids": failed_task_ids
            }
            
            # 为了兼容性，添加derived字段
            response_json["needs_more_input"] = completion_status == "need_user_input"
            response_json["is_completed"] = completion_status in ["completed", "failed"]
            
            logger.debug(f"ObservationAgent: XML转JSON完成: {response_json}")
            return response_json
            
        except Exception as e:
            logger.error(f"ObservationAgent: XML转JSON失败: {str(e)}")
            raise

    def _update_task_manager_status(self, task_manager: TaskManager, observation_result: Dict[str, Any]) -> None:
        try:
            # 获取任务状态信息
            completed_task_ids = observation_result['completed_task_ids'] if 'completed_task_ids' in observation_result else []
            failed_task_ids = observation_result['failed_task_ids'] if 'failed_task_ids' in observation_result else []
            logger.info(f"ObservationAgent: 观察分析结果中完成任务: {completed_task_ids}，失败任务: {failed_task_ids}")
            # 更新已完成的任务状态
            for task_id in completed_task_ids:
                try:
                    if hasattr(task_manager, 'update_task_status'):
                        task_manager.update_task_status(task_id, TaskStatus.COMPLETED)
                        logger.info(f"ObservationAgent: 已将任务 {task_id} 标记为完成")
                        
                        # 尝试更新任务的执行结果
                        task = task_manager.get_task(task_id)
                        if task and hasattr(task_manager, 'complete_task'):
                            # 使用观察结果的分析作为任务结果
                            analysis = observation_result['analysis'] if 'analysis' in observation_result else ''
                            if analysis:
                                task_manager.complete_task(
                                    task_id=task_id,
                                    result=analysis,
                                    execution_details={
                                        'observation_analysis': analysis,
                                        'completion_detected_by': 'ObservationAgent'
                                    }
                                )
                                logger.info(f"ObservationAgent: 已更新任务 {task_id} 的执行结果")
                    else:
                        logger.warning(f"ObservationAgent: TaskManager没有update_task_status方法")
                except Exception as e:
                    logger.warning(f"ObservationAgent: 更新任务 {task_id} 状态为完成时出错: {str(e)}")
            
            # 更新失败的任务状态
            for task_id in failed_task_ids:
                try:
                    if hasattr(task_manager, 'update_task_status'):
                        task_manager.update_task_status(task_id, TaskStatus.FAILED)
                        logger.info(f"ObservationAgent: 已将任务 {task_id} 标记为失败")
                    else:
                        logger.warning(f"ObservationAgent: TaskManager没有update_task_status方法")
                except Exception as e:
                    logger.warning(f"ObservationAgent: 更新任务 {task_id} 状态为失败时出错: {str(e)}")
            
            logger.info(f"ObservationAgent: 任务状态更新完成，完成任务: {completed_task_ids}，失败任务: {failed_task_ids}")
            # 从任务管理器当前的最新状态，如果完成的任务数与失败的任务数之和等于总任务数，将 observation_result 的completion_status 设为 completed
            completed_tasks = task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
            failed_tasks = task_manager.get_tasks_by_status(TaskStatus.FAILED)
            if len(completed_tasks) + len(failed_tasks) == len(task_manager.get_all_tasks()):
                observation_result['completion_status'] = 'completed'
        except Exception as e:
            logger.error(f"ObservationAgent: 更新TaskManager任务状态时发生错误: {str(e)}")