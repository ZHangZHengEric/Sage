from typing import List, Any, Dict, Union
from .base import BaseTraceHandler
from sagents.utils.logger import logger

class ObservabilityManager(BaseTraceHandler):
    """
    Manager that dispatches events to multiple trace handlers.
    """

    def __init__(self, handlers: List[BaseTraceHandler] = []):
        self.handlers = handlers

    def add_handler(self, handler: BaseTraceHandler):
        self.handlers.append(handler)

    def on_chain_start(self, session_id: str, input_data: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_chain_start(session_id, input_data, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_chain_start: {e}")

    def on_chain_end(self, output_data: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_chain_end(output_data, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_chain_end: {e}")

    def on_chain_error(self, error: Exception, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_chain_error(error, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_chain_error: {e}")

    def on_agent_start(self, session_id: str, agent_name: str, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_agent_start(session_id, agent_name, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_agent_start: {e}")

    def on_agent_end(self, output: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_agent_end(output, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_agent_end: {e}")

    def on_agent_error(self, error: Exception, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_agent_error(error, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_agent_error: {e}")

    def on_llm_start(self, session_id: str, model_name: str, messages: List[Any], step_name: str = None, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_llm_start(session_id, model_name, messages, step_name, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_llm_start: {e}")

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_llm_end(response, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_llm_end: {e}")

    def on_llm_error(self, error: Exception, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_llm_error(error, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_llm_error: {e}")

    def on_tool_start(self, session_id: str, tool_name: str, tool_input: Union[str, Dict], **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_tool_start(session_id, tool_name, tool_input, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_tool_start: {e}")

    def on_tool_end(self, tool_output: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_tool_end(tool_output, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_tool_end: {e}")

    def on_tool_error(self, error: Exception, **kwargs: Any) -> Any:
        for handler in self.handlers:
            try:
                handler.on_tool_error(error, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}.on_tool_error: {e}")
