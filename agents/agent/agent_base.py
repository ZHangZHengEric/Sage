from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Generator
import re,json
import uuid
from agents.utils.logger import logger
from agents.tool.tool_base import AgentToolSpec


class AgentBase(ABC):
    def __init__(self, model: Any, model_config: Dict[str, Any],system_prefix: str = ""):
        """Initialize with executable model and config"""
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.agent_description = f"{self.__class__.__name__} agent"
        logger.debug(f"Initialized {self.__class__.__name__} with model config: {model_config}")
    
    def run(self, messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None) -> List[Dict[str, Any]]:
        """
        Process messages and optionally use tools via tool_manager.
        Must be implemented by subclasses.
        """
        # 这里有可能死循环，因为两个父类的方法循环掉用
    
        result_iter = self.run_stream(messages=messages, tool_manager=tool_manager,context=context,session_id=session_id)
        result = []
        for chunk in result_iter:
            result.extend(chunk)
        # 对chunk 进行合并
        result = self._merge_chunks(result)
        return result

    def to_tool(self) -> AgentToolSpec:
        """Convert agent to tool format for tool manager"""
        # Create a tool definition with the agent's run method
        tool_spec = AgentToolSpec(
            name=self.__class__.__name__,
            description=self.agent_description+'\n\n Agent类型的工具，可以自动读取历史对话，所需不需要运行的参数',
            func=self.run,
            parameters={},
            required=[]
        )
        return tool_spec
        

    def _extract_json_from_markdown(self, content: str) -> str:
        """
        Extract JSON content from markdown code block if present.
        
        Args:
            content: Content that may contain markdown code block
            
        Returns:
            Extracted JSON content or original content if no code block found
        """
        # Try to parse directly first
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        
        # Try to extract from markdown code block
        code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
        match = re.search(code_block_pattern, content)
        if match:
            try:
                json.loads(match.group(1))
                return match.group(1)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from markdown code block in {self.__class__.__name__}")
                pass
        
        # Return original content if no valid JSON found
        return content

    def _extract_completed_actions_messages(self, messages):
        """Extract completed actions from messages."""
        logger.debug(f"{self.__class__.__name__}: Extracting completed actions from {len(messages)} messages")
        completed_actions_messages = []
        for index,msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                completed_actions_messages.extend(messages[len(messages)-index:])
                break
        
        # 除去type为task_decomposition的messages
        for msg in completed_actions_messages:
            if msg.get('type') == 'task_decomposition':
                completed_actions_messages.remove(msg)
                break

        logger.debug(f"{self.__class__.__name__}: Extracted {len(completed_actions_messages)} completed action messages")
        return completed_actions_messages

    def _extract_task_description_messages(self,messages):
        logger.debug(f"{self.__class__.__name__}: Extracting task description from {len(messages)} messages")
        task_description_messages = []
        for index,msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                task_description_messages.extend(messages[:len(messages)-index])
                break
        
        # 只保留type 为normal 以及final answer 的messages
        for msg in task_description_messages:
            if msg.get('type') not in ['normal','final_answer']:
                task_description_messages.remove(msg)

        logger.debug(f"{self.__class__.__name__}: Extracted {len(task_description_messages)} task description messages")
        return task_description_messages

    def run_stream(self, messages: List[Dict[str, Any]], 
                 tool_manager: Optional[Any] = None,
                 context: Optional[Dict[str, Any]] = None,
                 session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """Streaming version of run() that yields message chunks.
        
        Default implementation converts regular run() output to stream format.
        Subclasses should override for proper streaming support.
        
        Args:
            messages: List of messages in the conversation
            tool_manager: Tool manager instance
            context: Optional context dictionary
            
        Yields:
            List of message chunks with unique message IDs
        """
        logger.info(f"{self.__class__.__name__}.run_stream: Starting with {len(messages)} messages")
        result = self.run(messages=messages, tool_manager=tool_manager,context= context,session_id=session_id)
        logger.info(f"{self.__class__.__name__}.run_stream: Completed run with {len(result) if isinstance(result, list) else 1} result messages")
        
        # Convert regular output to streaming format with message IDs
        if isinstance(result, list):
            for msg in result:
                msg_with_id = msg.copy()
                msg_with_id['message_id'] = str(uuid.uuid4())
                logger.debug(f"{self.__class__.__name__}.run_stream: Yielding message with role={msg.get('role')}, type={msg.get('type')}")
                yield [msg_with_id]
        else:
            # Handle unexpected return types
            result['message_id'] = str(uuid.uuid4())
            logger.debug(f"{self.__class__.__name__}.run_stream: Yielding non-list result with role={result.get('role')}, type={result.get('type')}")
            yield [result]

    def clean_messages(self,messages):
        """只保留openai 需要的message 的key
        """
        clean_messages = []
        for msg in messages:
                if 'tool_calls' in msg and msg['tool_calls'] is not None:
                    clean_messages.append({
                        'role': msg['role'],
                        'tool_calls': msg['tool_calls']
                    })
                elif 'content' in msg:
                    if 'tool_call_id' in msg:
                        clean_messages.append({
                            'role': msg['role'],
                            'content': msg['content'],
                            'tool_call_id': msg['tool_call_id']
                        })
                    else:
                        clean_messages.append({
                            'role': msg['role'],
                            'content': msg['content']
                        })
        return clean_messages

    def _merge_messages(self, all_messages: List[Dict], new_messages: List[Dict]) -> List[Dict]:
        """Merge new messages into existing messages by message_id.
        
        Args:
            all_messages: Current complete message list
            new_messages: New messages to merge
            
        Returns:
            Merged message list with updated content
        """
        # logger.debug(f"Merging {len(new_messages)} new messages into {len(all_messages)} existing messages")
        merged = []
        message_map = {}
        
        # First add all existing messages
        for msg in all_messages:
            msg_copy = msg.copy()
            merged.append(msg_copy)
            message_map[msg_copy['message_id']] = msg_copy
        
        # Then merge new messages
        for msg in new_messages:
            msg_copy = msg.copy()
            if 'message_id' not in msg_copy:
                print(msg_copy)
            msg_id = msg_copy['message_id']
            if msg_id in message_map:
                # Update existing message content without modifying original
                existing = message_map[msg_id]
                if 'content' in existing:
                    existing['content'] += msg_copy.get('content', '')
                if 'show_content' in existing:                
                    existing['show_content'] += msg_copy.get('show_content', '')
            else:
                # Add new message
                merged.append(msg_copy)
                message_map[msg_id] = msg_copy
        
        # logger.debug(f"Merged message count: {len(merged)}")
        return merged
    def convert_messages_to_str(self,messages):
        """
        将messages 转换为str
        """
        messages_str_list= []
        for msg in messages:
            if msg['role'] == 'user':
                messages_str_list.append(f"User: {msg['content']}")
            elif msg['role'] == 'assistant':
                if 'content' in msg:
                    messages_str_list.append(f"Assistant: {msg['content']}")
                elif 'tool_calls' in msg:
                    messages_str_list.append(f"Assistant: Tool calls: {msg['tool_calls']}")
            elif msg['role'] == 'tool':
                messages_str_list.append(f"Tool: {msg['content']}")
        result = "\n".join(messages_str_list) or "None"
        return result