from typing import Dict, Any, List, Union, Optional
import contextvars
import json
import random
import hashlib
import dataclasses
from opentelemetry import trace, context
from opentelemetry.trace import Status, StatusCode

from .base import BaseTraceHandler
from sagents.utils.logger import logger

# ContextVar to hold the stack of (span, token) for the current task.
# We use an immutable tuple to ensure safety across async tasks (copy-on-write).
# Each element is a tuple: (span, token)
_span_token_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar("span_token_stack", default=())

class OpenTelemetryTraceHandler(BaseTraceHandler):
    """
    Handler that creates OpenTelemetry spans for agent execution.
    Uses ContextVars for proper async context propagation.
    """

    def __init__(self, service_name: str = "sagents", export_to_console: bool = False):
        self.service_name = service_name
        self.tracer = trace.get_tracer(service_name)
        # No longer using self.span_stacks for concurrency safety

    def _push_span(self, span: trace.Span):
        """Helper to activate span and push to stack"""
        # Activate span in OTel context
        ctx = trace.set_span_in_context(span)
        token = context.attach(ctx)

        # Update stack (immutable tuple)
        current_stack = _span_token_stack.get()
        _span_token_stack.set(current_stack + ((span, token),))

    def _end_span_on_error(self, error: Exception):
        """Helper to safely end span on error and mark as detached in stack"""
        current_stack = _span_token_stack.get()
        if not current_stack:
            return

        span, token = current_stack[-1]

        # Record exception
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))

        # If we have a valid token, it means we haven't detached/ended yet.
        # We end it now to prevent leaks if finally block is missed.
        if token is not None:
            span.end()
            context.detach(token)

            # Update stack to replace token with None (marking as ended/detached)
            # This ensures subsequent _pop_span (in finally) won't try to end/detach again.
            _span_token_stack.set(current_stack[:-1] + ((span, None),))

    def _pop_span(self) -> Optional[trace.Span]:
        """Helper to pop span, end it (if not already), and detach context"""
        current_stack = _span_token_stack.get()
        if not current_stack:
            return None

        span, token = current_stack[-1]

        # Only end/detach if token exists (not already handled by error handler)
        if token is not None:
            span.end()
            context.detach(token)

        # Always remove from stack
        _span_token_stack.set(current_stack[:-1])
        return span

    def _get_current_span(self) -> Optional[trace.Span]:
        """Get current active span without popping"""
        current_stack = _span_token_stack.get()
        if not current_stack:
            return None
        return current_stack[-1][0]

    def on_chain_start(
        self, session_id: str, input_data: Union[str, Any], **kwargs: Any
    ) -> Any:
        # Check for leaked spans from previous executions in this context (thread/task)
        # This prevents memory leaks and context pollution if a previous run crashed or failed to cleanup.
        current_stack = _span_token_stack.get()
        if current_stack:
            try:
                # Iterate in reverse to properly detach contexts (LIFO)
                for span, token in reversed(current_stack):
                    if token is not None:
                        try:
                            context.detach(token)
                        except Exception as e:
                            logger.warning(f"Failed to detach leaked token: {e}")
                    
                    # Optionally end the span if it's still recording
                    try:
                        if span.is_recording():
                            span.end()
                    except Exception as e:
                        logger.warning(f"Failed to end leaked span: {e}")
            except Exception as e:
                logger.error(f"Error during leaked span cleanup: {e}")
            finally:
                # Always reset the stack
                _span_token_stack.set(())

        # Start a new span. OTel will automatically pick up parent from context if it exists.
        # We don't manually generate trace_id or parent context anymore.
        
        # 1. Generate consistent trace_id from session_id
        # We use MD5 hash of session_id to get a 128-bit integer
        trace_id = int(hashlib.md5(session_id.encode('utf-8')).hexdigest(), 16)

        # 2. Create a parent context that forces this trace_id
        # We simulate a parent span so that this new span belongs to the same trace.
        span_id = random.getrandbits(64)
        trace_flags = trace.TraceFlags(trace.TraceFlags.SAMPLED)
        
        span_context = trace.SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=trace_flags
        )
        
        # Wrap in NonRecordingSpan to create a Context
        parent_ctx = trace.set_span_in_context(trace.NonRecordingSpan(span_context))
        
        # 3. Start the span representing this "User Input" turn
        span = self.tracer.start_span(
            name="用户输入", 
            context=parent_ctx, 
            kind=trace.SpanKind.SERVER
        )

        # Use specific attributes instead of SERVICE_NAME (which is Resource-level)
        span.set_attribute("session_id", session_id)

        try:
            if isinstance(input_data, (dict, list)):
                def default_serializer(obj):
                    if dataclasses.is_dataclass(obj):
                        return dataclasses.asdict(obj)
                    if hasattr(obj, 'to_dict'):
                        return obj.to_dict()
                    if hasattr(obj, '__dict__'):
                        return obj.__dict__
                    return str(obj)
                    
                input_str = json.dumps(input_data, ensure_ascii=False, default=default_serializer)
            else:
                input_str = str(input_data)
            span.set_attribute("input", input_str)
        except Exception as e:
            logger.error(f"Error setting input attribute: {e}")
            pass

        self._push_span(span)

    def on_chain_end(self, output_data: Union[str, Any], **kwargs: Any) -> Any:
        span = self._get_current_span()
        if not span:
            return

        try:
            if isinstance(output_data, (dict, list)):
                def default_serializer(obj):
                    if dataclasses.is_dataclass(obj):
                        return dataclasses.asdict(obj)
                    if hasattr(obj, 'to_dict'):
                        return obj.to_dict()
                    if hasattr(obj, '__dict__'):
                        return obj.__dict__
                    return str(obj)

                output_str = json.dumps(output_data, ensure_ascii=False, default=default_serializer)
            else:
                output_str = str(output_data)
            span.set_attribute("output", str(output_str))
        except Exception as e:
            logger.error(f"Error setting output attribute: {e}")
            pass
        span.set_status(Status(StatusCode.OK))
        self._pop_span()

    def on_chain_error(self, error: Exception, **kwargs: Any) -> Any:
        self._end_span_on_error(error)

    def on_agent_start(self, session_id: str, agent_name: str, **kwargs: Any) -> Any:
        span = self.tracer.start_span(
            name=f"Agent运行:{agent_name}",
            kind=trace.SpanKind.INTERNAL
        )
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("session_id", session_id)
        self._push_span(span)

    def on_agent_end(self, output: Any, **kwargs: Any) -> Any:
        span = self._get_current_span()
        if not span:
            return
        span.set_status(Status(StatusCode.OK))
        self._pop_span()

    def on_agent_error(self, error: Exception, **kwargs: Any) -> Any:
        self._end_span_on_error(error)

    def on_llm_start(self, session_id: str, model_name: str, messages: List[Any], **kwargs: Any) -> Any:
        span = self.tracer.start_span(
            name=f"LLM调用:{model_name}",
            kind=trace.SpanKind.CLIENT
        )
        llm_system = kwargs.get("llm_system", "openai")
        span.set_attribute("llm.system", llm_system)
        span.set_attribute("llm.model", model_name)
        try:
            messages_str = json.dumps(messages, ensure_ascii=False)
            span.set_attribute("llm.messages", messages_str)
        except Exception as e:
            logger.error(f"Error setting llm.messages attribute: {e}")
            pass
        span.set_attribute("session_id", session_id)
        self._push_span(span)

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        span = self._get_current_span()
        if not span:
            return

        try:
            span.set_attribute("llm.response", json.dumps(response, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Error setting llm.response attribute: {e}")
            pass
        
        span.set_status(Status(StatusCode.OK))
        self._pop_span()

    def on_llm_error(self, error: Exception, **kwargs: Any) -> Any:
        self._end_span_on_error(error)

    def on_tool_start(self, session_id: str, tool_name: str, tool_input: Union[str, Dict], **kwargs: Any) -> Any:
        span = self.tracer.start_span(
            name=f"工具执行:{tool_name}",
            kind=trace.SpanKind.INTERNAL
        )
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("session_id", session_id)
        try:
            if isinstance(tool_input, (dict, list)):
                input_str = json.dumps(tool_input, ensure_ascii=False)
            else:
                input_str = str(tool_input)
            span.set_attribute("tool.input", input_str)
        except Exception as e:
            logger.error(f"Error setting tool input attribute: {e}")
            pass
        self._push_span(span)

    def on_tool_end(self, tool_output: Any, **kwargs: Any) -> Any:
        span = self._get_current_span()
        if not span:
            return
        try:
            if isinstance(tool_output, (dict, list)):
                output_str = json.dumps(tool_output, ensure_ascii=False)
            else:
                output_str = str(tool_output)
            span.set_attribute("tool.output", str(output_str))
        except Exception as e:
            logger.error(f"Error setting tool output attribute: {e}")
            pass
        span.set_status(Status(StatusCode.OK))
        self._pop_span()

    def on_tool_error(self, error: Exception, **kwargs: Any) -> Any:
        self._end_span_on_error(error)
