from abc import ABC, abstractmethod
from typing import Dict, Any, List, Union

class BaseTraceHandler(ABC):
    """
    Base interface for observability handlers (tracers).
    """

    @abstractmethod
    def on_chain_start(self, session_id: str, input_data: Any, **kwargs: Any) -> Any:
        """Run when the main chain (workflow) starts."""
        pass

    @abstractmethod
    def on_chain_end(self, output_data: Any, **kwargs: Any) -> Any:
        """Run when the main chain ends."""
        pass

    @abstractmethod
    def on_chain_error(self, error: Exception, **kwargs: Any) -> Any:
        """Run when chain errors."""
        pass

    @abstractmethod
    def on_agent_start(self, session_id: str, agent_name: str, **kwargs: Any) -> Any:
        """Run when an agent starts."""
        pass

    @abstractmethod
    def on_agent_end(self, output: Any, **kwargs: Any) -> Any:
        """Run when an agent ends."""
        pass

    @abstractmethod
    def on_agent_error(self, error: Exception, **kwargs: Any) -> Any:
        """Run when an agent errors."""
        pass

    @abstractmethod
    def on_llm_start(
        self, 
        session_id: str, 
        model_name: str, 
        messages: List[Any], 
        **kwargs: Any
    ) -> Any:
        """Run when LLM starts."""
        pass

    @abstractmethod
    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        """Run when LLM ends."""
        pass

    @abstractmethod
    def on_llm_error(self, error: Exception, **kwargs: Any) -> Any:
        """Run when LLM errors."""
        pass

    @abstractmethod
    def on_tool_start(
        self, 
        session_id: str, 
        tool_name: str, 
        tool_input: Union[str, Dict], 
        **kwargs: Any
    ) -> Any:
        """Run when a tool starts."""
        pass

    @abstractmethod
    def on_tool_end(self, tool_output: Any, **kwargs: Any) -> Any:
        """Run when a tool ends."""
        pass

    @abstractmethod
    def on_tool_error(self, error: Exception, **kwargs: Any) -> Any:
        """Run when a tool errors."""
        pass
