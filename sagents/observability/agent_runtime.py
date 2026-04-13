import asyncio
from typing import Any, Dict, List, Optional, Union
from sagents.observability.manager import ObservabilityManager
from sagents.tool import tool_manager
from sagents.tool.tool_manager import ToolManager
from sagents.context.session_context import SessionContext
from sagents.utils.logger import logger


def _get_current_observability_session_id() -> Optional[str]:
    from sagents.session_runtime import get_current_session_id
    return get_current_session_id()

class ObservableToolManager:
    """
    Wraps ToolManager to provide observability hooks.
    This uses Composition to add behavior without modifying ToolManager or AgentBase.
    """
    def __init__(self, tool_manager: ToolManager, observability_manager: ObservabilityManager, session_id: str):
        self._tool_manager = tool_manager
        self.observability_manager = observability_manager
        self.session_id = session_id

    def __getattr__(self, name):
        # Delegate all other calls to the original tool manager
        return getattr(self._tool_manager, name)

    async def run_tool_async(
        self,
        tool_name: str,
        session_id: str,
        user_id=None,
        **kwargs,
    ) -> Any:
        """
        Intercepts tool execution to log start/end events.
        """
        # Note: The agent might pass session_id, but we also have self.session_id.
        # We use the passed one if available, else ours.
        sid = session_id or self.session_id

        self.observability_manager.on_tool_start(sid, tool_name, kwargs)

        try:
            result = await self._tool_manager.run_tool_async(
                tool_name,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )
            
            # Check for streaming response
            output_to_log = result
            if hasattr(result, '__iter__') and not isinstance(result, (str, bytes)):
                 output_to_log = "<streaming_response>"
            
            self.observability_manager.on_tool_end(output_to_log, session_id=sid)
            return result
        except Exception as e:
            # Use on_tool_error if available, or log error in on_tool_end
            if hasattr(self.observability_manager, 'on_tool_error'):
                self.observability_manager.on_tool_error(e, session_id=sid)
            else:
                self.observability_manager.on_tool_end(f"Error: {str(e)}", session_id=sid)
            raise e

class ObservableAsyncOpenAI:
    """
    Wraps AsyncOpenAI client (or similar model object) to provide observability hooks.
    """
    def __init__(self, model: Any, observability_manager: ObservabilityManager):
        self._model = model
        self.observability_manager = observability_manager
        self.chat = ObservableChat(model.chat, observability_manager)
    
    def __getattr__(self, name):
        return getattr(self._model, name)

class ObservableChat:
    def __init__(self, chat: Any, observability_manager: ObservabilityManager):
        self._chat = chat
        self.observability_manager = observability_manager
        self.completions = ObservableCompletions(chat.completions, observability_manager)

    def __getattr__(self, name):
        return getattr(self._chat, name)

class ObservableCompletions:
    def __init__(self, completions: Any, observability_manager: ObservabilityManager):
        self._completions = completions
        self.observability_manager = observability_manager

    def __getattr__(self, name):
        return getattr(self._completions, name)

    async def create(self, **kwargs) -> Any:
        """
        Intercepts LLM creation.
        """
        session_id = _get_current_observability_session_id()
        model_name = kwargs.get('model', 'unknown')
        messages = kwargs.get('messages', [])
        
        # Extract step_name from extra_body if present to avoid sending it to API
        step_name = None
        if 'extra_body' in kwargs and isinstance(kwargs['extra_body'], dict):
            step_name = kwargs['extra_body'].pop('_step_name', None)

        # We try to get base_url if possible, otherwise default
        try:
            llm_system = str(self._completions._client.base_url)
        except Exception:
            llm_system = "default_endpoint"
        
        if session_id:
            self.observability_manager.on_llm_start(session_id, model_name, messages, llm_system=llm_system, step_name=step_name)
        
        try:
            response = await self._completions.create(**kwargs)
            
            if session_id:
                if kwargs.get('stream', False):
                    return self._wrap_stream(response, session_id)
                else:
                    self.observability_manager.on_llm_end(response, session_id=session_id)
                    return response
            else:
                return response
                
        except Exception as e:
            if session_id:
                self.observability_manager.on_llm_error(e, session_id=session_id)
            raise e

    async def _wrap_stream(self, stream, session_id):
        collected_content = []
        try:
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        collected_content.append(delta.content)
                yield chunk
        finally:
            # When stream ends (or error occurs during iteration which raises out)
            # If successful completion:
            # We construct a minimal response object or just log a marker
            # Since we can't easily reconstruct the full ChatCompletion object without duplicating AgentBase logic,
            # we will log the accumulated content.
            full_content = "".join(collected_content)
            self.observability_manager.on_llm_end(full_content, session_id=session_id)

class AgentRuntime:
    """
    Runtime wrapper that executes an agent with observability injection.
    """
    def __init__(self, agent: Any, observability_manager: ObservabilityManager):
        self.agent = agent
        self.observability_manager = observability_manager

    def __getattr__(self, name):
        # Delegate attribute access to the underlying agent
        return getattr(self.agent, name)

    async def run_stream(self, 
                         session_context: SessionContext):
        session_id = session_context.session_id
        input_messages = session_context.message_manager.messages
        tool_manager = session_context.tool_manager
        # 2. Start Chain Span
        # We use agent name as the chain name
        agent_name = getattr(self.agent, 'agent_name', self.agent.__class__.__name__)

        # Extract input info for logging
        log_input = input_messages
        agent_end_status: Dict[str, Any] = {"status": "finished"}
        
        self.observability_manager.on_agent_start(session_id, agent_name, input=log_input)
        
        original_tool_manager = tool_manager
        try:
            # 3. Wrap Dependencies (ToolManager)
            wrapped_tm = tool_manager
            if tool_manager:
                wrapped_tm = ObservableToolManager(tool_manager, self.observability_manager, session_id)
                session_context.tool_manager = wrapped_tm
            
            # 4. Execute Agent
            async for chunk in self.agent.run_stream(session_context):
                yield chunk
        except (GeneratorExit, asyncio.CancelledError):
            agent_end_status = {"status": "cancelled"}
            raise
        except Exception as e:
            agent_end_status = {"status": "error", "error": str(e)}
            self.observability_manager.on_agent_error(e, session_id=session_id)
            raise e
        finally:
            session_context.tool_manager = original_tool_manager
            self.observability_manager.on_agent_end(agent_end_status, session_id=session_id)
