from typing import Any, Dict, List, Optional, Union
import contextvars
from sagents.observability.manager import ObservabilityManager
from sagents.tool.tool_manager import ToolManager

# ContextVar to hold the current session_id for the ObservableModel
session_id_var = contextvars.ContextVar("session_id", default=None)

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

    async def run_tool_async(self, tool_name: str, session_context: Any, session_id: str, **kwargs) -> Any:
        """
        Intercepts tool execution to log start/end events.
        """
        # Note: The agent might pass session_id, but we also have self.session_id.
        # We use the passed one if available, else ours.
        sid = session_id or self.session_id
        
        self.observability_manager.on_tool_start(sid, tool_name, kwargs)
        
        try:
            result = await self._tool_manager.run_tool_async(tool_name, session_context, session_id=session_id, **kwargs)
            
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
        session_id = session_id_var.get()
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
                         input_messages: Optional[Union[List[Dict[str, Any]], Any]] = None, 
                         tool_manager: Optional[ToolManager] = None, 
                         session_id: str = None, 
                         **kwargs):
        # 1. Set ContextVar for Model Observability
        token = session_id_var.set(session_id)
        
        # 2. Start Chain Span
        # We use agent name as the chain name
        agent_name = getattr(self.agent, 'agent_name', self.agent.__class__.__name__)

        # Extract input info for logging
        log_input = input_messages
        if log_input is None and 'session_context' in kwargs:
             # Try to extract something meaningful from session_context
             try:
                 sc = kwargs['session_context']
                 if hasattr(sc, 'message_manager') and hasattr(sc.message_manager, 'messages'):
                     msgs = sc.message_manager.messages
                     if msgs:
                         # Log the last message or a summary
                         log_input = f"SessionContext (last msg: {str(msgs[-1])[:200]})"
                     else:
                         log_input = "SessionContext (empty messages)"
                 else:
                     log_input = "SessionContext (opaque)"
             except Exception:
                 log_input = "SessionContext (extraction failed)"
        
        self.observability_manager.on_agent_start(session_id, agent_name, input=log_input)
        
        try:
            # 3. Wrap Dependencies (ToolManager)
            wrapped_tm = tool_manager
            if tool_manager:
                wrapped_tm = ObservableToolManager(tool_manager, self.observability_manager, session_id)
            
            # 4. Execute Agent
            # We call the original run_stream
            # Note: We pass 'input_messages' if it was passed, otherwise it might be in kwargs or different sig
            
            # Construct args
            call_kwargs = kwargs.copy()
            if input_messages is not None:
                call_kwargs['input_messages'] = input_messages
                
            async for chunk in self.agent.run_stream(
                tool_manager=wrapped_tm,
                session_id=session_id,
                **call_kwargs
            ):
                yield chunk
                
        except Exception as e:
            self.observability_manager.on_agent_error(e, session_id=session_id)
            raise e
        finally:
            self.observability_manager.on_agent_end({"status": "finished"}, session_id=session_id)
            session_id_var.reset(token)
