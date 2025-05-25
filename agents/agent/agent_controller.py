from telnetlib import LOGOUT
from typing import List, Dict, Any
from .agent_base import AgentBase
from .task_analysis_agent.task_analysis_agent import TaskAnalysisAgent
from .executor_agent.executor_agent import ExecutorAgent
from .task_summary_agent.task_summary_agent import TaskSummaryAgent
from .planning_agent.planning_agent import PlanningAgent
from .observation_agent.observation_agent import ObservationAgent
from .direct_executor_agent.direct_executor_agent import DirectExecutorAgent
from .task_decompose_agent.task_decompose_agent import TaskDecomposeAgent
from agents.utils.logger import logger
import json
import uuid
import re,os,sys
import datetime
class AgentController:
    def __init__(self, model: Any, model_config: Dict[str, Any],system_prefix:str=""):
        """Initialize with model instance and config"""
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self._init_agents()
        logger.info("AgentController initialized with model and config")
        
    def _init_agents(self):
        """Initialize all required agents with shared model"""
        self.task_analysis_agent = TaskAnalysisAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.executor_agent = ExecutorAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.task_summary_agent = TaskSummaryAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.planning_agent = PlanningAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.observation_agent = ObservationAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.direct_executor_agent = DirectExecutorAgent(self.model, self.model_config,system_prefix=self.system_prefix)
        self.task_decompose_agent = TaskDecomposeAgent(self.model, self.model_config,system_prefix=self.system_prefix)

    def run_stream(self, input_messages: List[Dict], tool_manager: Any = None, session_id=None, deep_thinking=True, summary=True,max_loop_count=10,deep_research=True):
        """Execute agent workflow with streaming output
        
        Args:
            input_messages: List of message dictionaries
            tool_manager: ToolManager instance
            session_id: Session ID
            deep_thinking: Whether to perform task analysis
            summary: Whether to generate task summary
            
        Yields:
            List[Dict]: List of new message dictionaries since last yield, each with:
            - message_id: Unique identifier for the message
            - Other standard message fields (role, content, type, etc.)
        """
        logger.info(f"Starting run_stream workflow with session_id: {session_id}")
        if session_id is None:
            session_id = str(uuid.uuid1())
            logger.info(f"Generated new session_id: {session_id}")
        
        # Initialize messages, preserving existing message_id if present
        all_messages = []
        for msg in input_messages.copy():
            if 'message_id' not in msg:
                msg = {**msg, 'message_id': str(uuid.uuid4())} 
            all_messages.append(msg)
        last_returned_ids = {m['message_id'] for m in all_messages}
        # 检测all_messages有多少的字符，如果超过10000个字符，就删除前面非role user或者非final_answer的消息，直到字符数小于10000
        start_index = 0
        while len(json.dumps(all_messages)) > 10000 and start_index < len(all_messages):
            if all_messages[start_index]['role'] == 'user' or all_messages[start_index]['type'] == 'final_answer':
                start_index += 1
                continue
            else:
                del all_messages[start_index]
                continue
        logger.info(f"Initialized messages count: {len(all_messages)}")
        
        logger.info('prepare to basic info')
        current_time_str = datetime.datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')
        file_workspace = '''/tmp/sage/{session_id}'''.format(session_id=session_id)
        logger.info(f"ExecutorAgent.run: Using file workspace: {file_workspace}")
        if os.path.exists(file_workspace):
            logger.debug(f"ExecutorAgent.run: Use existing workspace directory")
            # logger.debug(f"ExecutorAgent.run: Removing existing workspace directory")
            # os.system(f'rm -rf {file_workspace.format(session_id=session_id)}')
        os.makedirs(file_workspace, exist_ok=True)
        context = {'current_time': current_time_str, 'file_workspace': file_workspace}
        logger.info(f"ExecutorAgent.run: Using context: {context}")


        # 1. Task Analysis Phase
        if deep_thinking:
            logger.info("Starting Task Analysis Phase")
            analysis_chunks = []
            for chunk in self.task_analysis_agent.run_stream(messages=all_messages,tool_manager= tool_manager,context=context,session_id=session_id):
                analysis_chunks.append(chunk)
                all_messages = self._merge_messages(all_messages, chunk)
                yield chunk
            logger.info(f"Task Analysis Phase completed with {len(analysis_chunks)} chunks")
        
        # 2. Planning-Execution-Observation Loop
        if deep_research:
            # 执行任务分解
            logger.info("Starting Task Decomposition Phase")
            decompose_chunks = []
            for chunk in self.task_decompose_agent.run_stream(messages=all_messages,tool_manager= tool_manager,context=context,session_id=session_id):
                decompose_chunks.append(chunk)
                all_messages = self._merge_messages(all_messages, chunk)
                yield chunk
            logger.info(f"Task Decomposition Phase completed with {len(decompose_chunks)} chunks")

            loop_count = 0
            while True:
                loop_count += 1
                logger.info(f"Starting Planning-Execution-Observation Loop #{loop_count}")
                
                if loop_count > max_loop_count:
                    logger.warning("Reached maximum loop count, stopping workflow")
                    # yield [{'role': 'assistant', 'content': 'Maximum loop count reached. Stopping workflow.', 'type': 'final_answer'}]
                    break


                # Planning Phase
                logger.info("Starting Planning Phase")
                plan_chunks = []
                for chunk in self.planning_agent.run_stream(messages=all_messages, tool_manager=tool_manager,context=context,session_id=session_id):
                    plan_chunks.append(chunk)
                    all_messages = self._merge_messages(all_messages, chunk)
                    yield chunk
                logger.info(f"Planning Phase completed with {len(plan_chunks)} chunks")
                
                # Execution Phase
                logger.info("Starting Execution Phase")
                exec_chunks = []
                for chunk in self.executor_agent.run_stream(messages=all_messages,tool_manager= tool_manager, context=context,session_id=session_id):
                    exec_chunks.append(chunk)
                    all_messages = self._merge_messages(all_messages, chunk)
                    yield chunk
                logger.info(f"Execution Phase completed with {len(exec_chunks)} chunks")
                
                # Observation Phase
                logger.info("Starting Observation Phase")
                obs_chunks = []
                for chunk in self.observation_agent.run_stream(messages=all_messages,tool_manager= tool_manager,context=context,session_id=session_id):
                    obs_chunks.append(chunk)
                    all_messages = self._merge_messages(all_messages, chunk)
                    yield chunk
                logger.info(f"Observation Phase completed with {len(obs_chunks)} chunks")
                
                # Check completion
                obs_content = all_messages[-1]['content'].replace('Observation: ', '')
                try:
                    obs_result = json.loads(obs_content)
                    if obs_result.get('is_completed', False):
                        logger.info("Task completed as indicated by Observation")
                        break
                    if obs_result.get('needs_more_input', False):
                        logger.info("Task needs more input from user")
                        clarify_msg = {
                            'role': 'assistant',
                            'content': obs_result.get('user_query', ''),
                            'type': 'final_answer',
                            'message_id': str(uuid.uuid4()),
                            'show_content': obs_result.get('user_query', '') + '\n'
                        }
                        all_messages.append(clarify_msg)
                        yield [clarify_msg]
                        return
                except json.JSONDecodeError:
                    logger.warning("Failed to decode Observation result JSON, continuing loop")
                    continue
            
            # 3. Task Summary Phase
            if summary:
                logger.info("Starting Task Summary Phase")
                summary_chunks = []
                for chunk in self.task_summary_agent.run_stream(messages= all_messages,tool_manager= tool_manager,context=context ,session_id=session_id):
                    summary_chunks.append(chunk)
                    all_messages = self._merge_messages(all_messages, chunk)
                    yield chunk
                logger.info(f"Task Summary Phase completed with {len(summary_chunks)} chunks")
        else:
            # use direct executor agent to execute the task
            logger.info("Starting Direct Executor Agent")
            for chunk in self.direct_executor_agent.run_stream(messages= all_messages,tool_manager= tool_manager,context=context,session_id=session_id):
                all_messages = self._merge_messages(all_messages, chunk)
                yield chunk
            logger.info(f"Direct Executor Agent completed")
        logger.info(f"run_stream workflow completed for session_id: {session_id}")
        logger.info(f"all messages :{all_messages}")
        
    def run(self, input_messages: List[Dict], tool_manager: Any = None, session_id=None, deep_thinking=True,summary=True ) -> Dict[str, Any]:
        """Execute complete agent workflow with Planning-Observation loop
        
        Args:
            input_messages: List of message dictionaries with 'role' and 'content' keys
            tool_manager: Optional ToolManager instance for tool execution
            deep_thinking: Whether to perform initial task analysis
            
        Returns:
            Dictionary containing:
            - all_messages: Complete message history
            - new_messages: New messages generated in this run
            - final_output: Final output message
        """
        logger.info(f"Starting run workflow with session_id: {session_id}")
        if session_id is None:
            # session_id = str(uuid.uuid1())+'-'+ datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_id = str(uuid.uuid1())
            logger.info(f"Generated new session_id: {session_id}")
        # remove type is not normal message
        
        # input_messages = [msg for msg in input_messages if msg.get('type','normal') == 'normal']
        
        # 1. Initial task analysis
        all_messages = input_messages.copy()
        new_messages = []
        logger.info(f"Initialized with {len(all_messages)} input messages")
        
        if deep_thinking:
            logger.info('Starting initial task analysis')
            analysis_messages = self.task_analysis_agent.run(input_messages, tool_manager)
            logger.info(f'Task analysis completed with {len(analysis_messages)} messages')
            print('Analysis结果:', json.dumps(analysis_messages, ensure_ascii=False, indent=2))
            all_messages.extend(analysis_messages)
            new_messages.extend(analysis_messages)
        
        # 2. Planning-Execution-Observation loop
        loop_count = 0
        while True:
            loop_count += 1
            logger.info(f"Starting Planning-Execution-Observation Loop #{loop_count}")
            
            # Planning phase - get next steps
            logger.info('Starting planning phase')
            plan_messages = self.planning_agent.run(all_messages,tool_manager)
            logger.info(f'Planning phase completed with {len(plan_messages)} messages')
            print('Planning结果:', json.dumps(plan_messages, ensure_ascii=False, indent=2))
            all_messages.extend(plan_messages)
            new_messages.extend(plan_messages)
            
            # Execution phase
            logger.info('Starting execution phase')
            exec_messages = self.executor_agent.run(all_messages, tool_manager,session_id=session_id)
            logger.info(f'Execution phase completed with {len(exec_messages)} messages')
            print('Execution结果:', json.dumps(exec_messages, ensure_ascii=False, indent=2))
            all_messages.extend(exec_messages)
            new_messages.extend(exec_messages)
            
            # Observation phase - check progress
            logger.info('Starting observation phase')
            obs_messages = self.observation_agent.run(all_messages)
            logger.info(f'Observation phase completed with {len(obs_messages)} messages')
            print('Observation结果:', json.dumps(obs_messages, ensure_ascii=False, indent=2))
            all_messages.extend(obs_messages)
            new_messages.extend(obs_messages)
            
            # Check if task is completed
            obs_result_content = obs_messages[-1]['content'].replace('Observation: ', '')
            try:
                obs_result_json = json.loads(obs_result_content)
                print('obs_result_json:', obs_result_json)
                if obs_result_json.get('is_completed', False):
                    logger.info("Task completed as indicated by Observation")
                    break
                if obs_result_json.get('needs_more_input', False):
                    logger.info("Task needs more input from user")
                    print('需要更多输入')
                    # 需要返回询问用户的message
                    clrify_message = {
                        'role': 'assistant',
                        'content': obs_result_json.get('user_query', ''),
                        'type': 'normal'
                    }
                    all_messages.append(clrify_message)
                    new_messages.append(clrify_message)
                    return {
                        'all_messages': all_messages,
                        'new_messages': new_messages,
                        'final_output': clrify_message,
                        "session_id": session_id
                    }
                    
            except json.JSONDecodeError:
                logger.warning("Failed to decode Observation result JSON, continuing loop")
                print('Observation结果解析失败，继续执行')
                continue
        
        # 3. Task summary
        if summary:
            logger.info('Starting task summary phase')
            summary_result = self.task_summary_agent.run(all_messages, tool_manager)
            logger.info(f'Task summary completed with {len(summary_result)} messages')
            print('总结结果:', json.dumps(summary_result, ensure_ascii=False, indent=2))
            all_messages.extend(summary_result)
            new_messages.extend(summary_result)
            
        # Get final output (last normal message)
        final_output = next(
            (m for m in reversed(summary_result) if m.get('type') == 'normal'),
            summary_result[-1]
        )
        
        logger.info(f"run workflow completed for session_id: {session_id}")
        return {
            'all_messages': all_messages,
            'new_messages': new_messages,
            'final_output': final_output,
            "session_id": session_id,
        }

    def _merge_messages(self, all_messages: List[Dict], new_messages: List[Dict]) -> List[Dict]:
        """Merge new messages into existing messages by message_id.
        
        Args:
            all_messages: Current complete message list
            new_messages: New messages to merge
            
        Returns:
            Merged message list with updated content
        """
        merged = self.task_analysis_agent._merge_messages(all_messages, new_messages)
        return merged

    def _is_task_complete(self, messages: List[Dict[str, Any]]) -> bool:
        """Check if task is complete based on evaluation output"""
        # Find the tool response message
        tool_response = next(
            (msg for msg in messages 
             if msg.get('role') == 'tool' and 
                msg.get('tool_call_id', '').startswith('decision_')),
            None
        )
        
        if not tool_response or not tool_response.get('content'):
            return False
            
        content = tool_response['content']
        
        try:
            # Try to parse as JSON directly
            result = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
            match = re.search(code_block_pattern, content)
            if match:
                try:
                    result = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return False
            else:
                return False
                
        return result.get('task_status', '') == 'completed'
