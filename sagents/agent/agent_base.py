from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, cast
import json
import uuid
import asyncio
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.session_context import SessionContext
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.prompt_caching import add_cache_control_to_messages
from sagents.llm.sage_openai import SageAsyncOpenAI
from sagents.llm.capabilities import create_chat_completion_with_fallback
from sagents.llm.model_capabilities import is_openai_reasoning_model, resolve_reasoning_effort
from sagents.utils.llm_request_utils import (
    format_api_error_details,
    is_unsupported_input_format_error,
)
from sagents.utils.multimodal_image import (
    process_multimodal_content as _process_multimodal_content_util,
    resolve_local_sage_url as _resolve_local_sage_url_util,
    get_mime_type as _get_mime_type_util,
)
from sagents.utils.message_sanitizer import (
    remove_orphan_tool_calls as _remove_orphan_tool_calls_util,
    strip_content_when_tool_calls as _strip_content_when_tool_calls_util,
)
from sagents.utils.stream_merger import merge_chat_completion_chunks as _merge_chunks_util
from sagents.utils.stream_tag_parser import judge_delta_content_type as _judge_delta_content_type_util
from sagents.utils.agent_session_helper import (
    get_live_session as _get_live_session_util,
    get_live_session_context as _get_live_session_context_util,
    should_abort_due_to_session as _should_abort_due_to_session_util,
)
import traceback
import time
import os
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
import httpx
from openai.types.chat import chat_completion_chunk


class AgentBase(ABC):
    """
    智能体基类

    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    def __init__(self, model: Optional[AsyncOpenAI] = None, model_config: Optional[Dict[str, Any]] = None, system_prefix: str = ""):
        """
        初始化智能体基类

        Args:
            model: 可执行的语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        self.model = model
        self.model_config = model_config if model_config is not None else {}
        self.system_prefix = system_prefix
        self.agent_description = f"{self.__class__.__name__} agent"
        self.agent_name = self.__class__.__name__

        # 设置最大输入长度（用于安全检查，防止消息过长）
        # 实际的上下文长度由 SessionContext 中的 context_budget_manager 动态管理
        # 这里只是作为兜底的安全阈值

        self.max_model_input_len = 1000000

        logger.debug(f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {model_config}, 最大输入长度（安全阈值）: {self.max_model_input_len}")

    def _get_live_session(self, session_id: Optional[str]):
        return _get_live_session_util(session_id, log_prefix=self.__class__.__name__)

    def _get_live_session_context(self, session_id: Optional[str]):
        return _get_live_session_context_util(session_id, log_prefix=self.__class__.__name__)

    @abstractmethod
    async def run_stream(self,
                         session_context: SessionContext,
                         ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        流式处理消息的抽象方法

        Args:
            session_context: 会话上下文
            tool_manager: 可选的工具管理器
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 流式输出的消息块
        """
        if False:
            yield []

    def _remove_tool_call_without_id(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """移除 tool_calls 没有对应 tool 回复的 assistant 消息。详见
        ``sagents.utils.message_sanitizer.remove_orphan_tool_calls``。
        """
        return _remove_orphan_tool_calls_util(messages)

    def _remove_content_if_tool_calls(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """assistant 消息带 tool_calls 时移除 content 字段。详见
        ``sagents.utils.message_sanitizer.strip_content_when_tool_calls``。
        """
        return _strip_content_when_tool_calls_util(messages)

    async def _process_multimodal_content(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """处理多模态消息内容（本地图片转 base64、压缩到最大 512x512）。详见
        ``sagents.utils.multimodal_image.process_multimodal_content``。
        """
        return await _process_multimodal_content_util(msg)

    @staticmethod
    def _maybe_resolve_local_sage_url(url: str) -> Optional[str]:
        """桌面端 sidecar 的 ``http://127.0.0.1/api/oss/file/...`` 反解为本地路径。详见
        ``sagents.utils.multimodal_image.resolve_local_sage_url``。
        """
        return _resolve_local_sage_url_util(url)

    def _get_mime_type(self, file_extension: str) -> str:
        """根据文件扩展名获取 MIME 类型。详见
        ``sagents.utils.multimodal_image.get_mime_type``。
        """
        return _get_mime_type_util(file_extension)

    async def _call_llm_streaming(self, messages: List[Union[MessageChunk, Dict[str, Any]]], session_id: Optional[str] = None, step_name: str = "llm_call", model_config_override: Optional[Dict[str, Any]] = None, enable_thinking: Optional[bool] = None):
        """
        通用的流式模型调用方法，有这个封装，主要是为了将
        模型调用和日志记录等功能统一起来，以及token 的记录等，方便后续的维护和扩展。

        Args:
            messages: 输入消息列表
            session_id: 会话ID（用于请求记录）
            step_name: 步骤名称（用于请求记录）
            model_config_override: 覆盖模型配置（用于工具调用等），可包含response_format等参数
            enable_thinking: 是否启用思考模式，优先使用此参数，为None时使用deep_thinking配置。
                           对于OpenAI推理模型(o3-mini, GPT-5.2等)，会转换为reasoning_effort参数

        Returns:
            Generator: 语言模型的流式响应
        """
        logger.debug(f"{self.__class__.__name__}: 调用语言模型进行流式生成, session_id={session_id}")

        if session_id:
            session = self._get_live_session(session_id)
            if session is None:
                logger.warning(f"{self.__class__.__name__}: session is None for session_id={session_id}")
            elif session.is_interrupted():
                logger.info(f"{self.__class__.__name__}: 跳过模型调用，session已中断，会话ID: {session_id}")
                return
        # 确定最终的模型配置
        final_config = {**self.model_config}
        if model_config_override:
            final_config.update(model_config_override)

        model_name = cast(str, final_config.pop('model')) if 'model' in final_config else "gpt-3.5-turbo"
        # 移除不是OpenAI API标准参数的配置项
        final_config.pop('max_model_len', None)
        final_config.pop('api_key', None)
        final_config.pop('maxTokens', None)
        final_config.pop('base_url', None)
        # 移除快速模型相关配置（这些是我们内部使用的参数）
        final_config.pop('fast_api_key', None)
        final_config.pop('fast_base_url', None)
        final_config.pop('fast_model_name', None)
        # 只有当 model 不是 SageAsyncOpenAI 类型时，才移除 model_type
        # SageAsyncOpenAI 需要 model_type 来选择使用哪个客户端
        if not isinstance(self.model, SageAsyncOpenAI):
            final_config.pop('model_type', None)
        all_chunks = []

        # 重试配置 - 增加重试次数以应对网络不稳定情况
        max_retries = 8
        retry_count = 0
        last_exception = None
        structured_output_fallback_used = False

        while retry_count < max_retries:
            try:
                if self.model is None:
                    raise ValueError("Model is not initialized")

                # 纯 MessageChunk 列表：与 convert_messages_to_dict_for_request 一致，剔除 turn_status 协议对
                if messages and all(isinstance(m, MessageChunk) for m in messages):
                    messages = MessageManager.strip_turn_status_from_llm_context(list(messages))

                # 发起LLM请求
                # 将 MessageChunk 对象转换为字典，以便进行 JSON 序列化
                start_request_time = time.time()
                first_token_time = None
                serializable_messages = []
                cache_segments: List[Optional[str]] = []

                for msg in messages:
                    if isinstance(msg, MessageChunk):
                        msg_dict = msg.to_dict()
                        msg_dict = await self._process_multimodal_content(msg_dict)
                        serializable_messages.append(msg_dict)
                        seg = None
                        if isinstance(getattr(msg, 'metadata', None), dict):
                            seg = msg.metadata.get('cache_segment')
                        cache_segments.append(seg)
                    else:
                        msg_copy = msg.copy()
                        msg_copy = await self._process_multimodal_content(msg_copy)
                        serializable_messages.append(msg_copy)
                        cache_segments.append(None)
                # 只保留model.chat.completions.create 需要的messages的key，移除掉不不要的
                serializable_messages = [{k: v for k, v in msg.items() if k in ['role', 'content', 'tool_calls', 'tool_call_id']} for msg in serializable_messages]

                # === 注入 shell completion 事件作为 <system_reminder> 消息 ===
                # 后台 shell 命令完成后，watcher 会把事件写入 ExecuteCommandTool._COMPLETION_EVENTS。
                # 这里在每次 LLM 请求前 flush 一次，作为 role=user + <system_reminder> 文本注入。
                # 选 role=user 而非 system 的原因：
                #   1) Anthropic 不允许中段 system 消息；
                #   2) 不破坏 OpenAI tool_call 严格交替序列；
                #   3) 不污染 system prompt cache。
                # await_shell 显式拿到 completed 时会 consume 对应 task_id 的事件，
                # 因此被显式消费过的不会在这里重复出现。
                if session_id:
                    try:
                        from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
                        completion_events = ExecuteCommandTool.pop_completion_events(session_id)
                    except Exception as _e:
                        logger.warning(f"flush shell completion events 失败: {_e}")
                        completion_events = []
                    if completion_events:
                        # 取 session 语言，用于 reminder 文本国际化
                        _reminder_lang = "en"
                        try:
                            _sc = self._get_live_session_context(session_id)
                            if _sc is not None:
                                _reminder_lang = _sc.get_language()
                        except Exception:
                            pass
                        _is_zh = str(_reminder_lang).lower().startswith("zh")

                    for ev in completion_events:
                        tail = ev.get('tail', '') or ''
                        if _is_zh:
                            tail_section = (
                                f"最后几行输出:\n{tail}" if tail else "（无输出）"
                            )
                            note = (
                                f"注意：这只是完成通知，输出已截断。"
                                f"如需完整 stdout，请调用 await_shell(task_id=\"{ev.get('task_id')}\")。"
                            )
                        else:
                            tail_section = (
                                f"tail (last few lines):\n{tail}" if tail
                                else "(no output captured)"
                            )
                            note = (
                                f"Note: This is a brief notification only. "
                                f"Call await_shell(task_id=\"{ev.get('task_id')}\") to retrieve the full stdout if needed."
                            )
                        reminder_text = (
                            "<system_reminder>\n"
                            f"[shell completion] task_id={ev.get('task_id')} "
                            f"exit_code={ev.get('exit_code')} elapsed_ms={ev.get('elapsed_ms')}\n"
                            f"command: {ev.get('command', '')}\n"
                            f"{tail_section}\n"
                            f"{note}\n"
                            "</system_reminder>"
                        )
                        serializable_messages.append({"role": "user", "content": reminder_text})
                        cache_segments.append(None)
                    if completion_events:
                        logger.info(
                            f"{self.__class__.__name__}: 注入 {len(completion_events)} 条 shell completion reminder"
                        )

                # 为消息添加 prompt caching 支持（Anthropic 格式）
                # 多段 system 时按 cache_segments 打多个断点；老路径保持单断点回退
                if serializable_messages:
                    add_cache_control_to_messages(serializable_messages, cache_segments=cache_segments)

                # 统计图片数量
                image_count = 0
                for msg in serializable_messages:
                    content = msg.get('content')
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get('type') == 'image_url':
                                image_count += 1
                if image_count > 0:
                    logger.info(f"[LLM请求] 包含 {image_count} 张图片")

                # print("serializable_messages:",serializable_messages)
                # 确保所有的messages 中都包含role 和 content
                for msg in serializable_messages:
                    if 'role' not in msg:
                        msg['role'] = MessageRole.USER.value
                    if 'content' not in msg:
                        msg['content'] = ''

                # 需要处理 serializable_messages 中，如果有tool call ，但是没有后续的tool call id,需要去掉这条消息
                serializable_messages = self._remove_tool_call_without_id(serializable_messages)
                # 如果针对带有 tool_calls 的assistant 的消息，要删除content 这个字段
                serializable_messages = self._remove_content_if_tool_calls(serializable_messages)
                # 提取tools 的value
                logger_final_config = {k: v for k, v in final_config.items() if k != 'tools'}
                logger.debug(f"{self.__class__.__name__} | {step_name}: 调用语言模型进行流式生成 (尝试 {retry_count + 1}/{max_retries}) |final_config={logger_final_config}")
                final_config = {k: v for k, v in final_config.items() if v is not None}
                response_format = final_config.pop("response_format", None)

                # 根据 enable_thinking 参数或 deep_thinking 配置决定是否启用思考模式
                # 优先使用传入的 enable_thinking 参数
                final_enable_thinking = False
                if enable_thinking is not None:
                    final_enable_thinking = enable_thinking
                elif session is not None:
                    deep_thinking = session.session_context.agent_config.get("deep_thinking", False)
                    # 处理字符串 "auto" 的情况，默认为 False
                    if isinstance(deep_thinking, str):
                        final_enable_thinking = deep_thinking.lower() == "true"
                    else:
                        final_enable_thinking = bool(deep_thinking)

                # 构建 extra_body，根据模型类型使用不同的参数
                # 对于 OpenAI 推理模型 (o3-mini, GPT-5.2等) 使用 reasoning_effort
                # 对于其他模型使用 enable_thinking/thinking 参数
                extra_body = {
                    "_step_name": step_name # 观察用，记录下当前是哪个步骤的调用
                }

                # 判断是否为 OpenAI / 兼容三方 reasoning 模型（白名单前缀，避免误伤 gpt-4o 等）
                is_reasoning_model = is_openai_reasoning_model(model_name)

                if is_reasoning_model:
                    # OpenAI 推理模型使用 reasoning_effort 参数
                    # low = 最小化推理，medium = 平衡，high = 最大化推理
                    # 注：OpenAI Chat Completions 接口对 o-/gpt-5 系不回传 reasoning content，
                    # 仅在 usage.reasoning_tokens 上报 token 消耗，无法通过该参数关闭。
                    # SAGE_REASONING_EFFORT_OFF 仅在思考关闭时生效，可切换到 minimal/medium/high。
                    effort = resolve_reasoning_effort(
                        enable_thinking=final_enable_thinking,
                        env_value=os.environ.get("SAGE_REASONING_EFFORT_OFF"),
                        default_off="low",
                    )
                    extra_body["reasoning_effort"] = effort
                    logger.debug(
                        f"{self.__class__.__name__} | {step_name}: OpenAI推理模型，reasoning_effort={effort}"
                    )
                else:
                    # 其他模型使用 enable_thinking/thinking 参数
                    extra_body["chat_template_kwargs"] = {"enable_thinking": final_enable_thinking}
                    extra_body["enable_thinking"] = final_enable_thinking
                    extra_body["thinking"] = {'type': "enabled" if final_enable_thinking else "disabled"}
                    logger.debug(f"{self.__class__.__name__} | {step_name}: 思考模式={final_enable_thinking}")
                
                stream = await create_chat_completion_with_fallback(
                    self.model,
                    model=model_name,
                    messages=cast(List[Any], serializable_messages),
                    model_config=final_config,
                    response_format=response_format,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=extra_body,
                    **final_config,
                )
                async for chunk in stream:
                    # print(chunk)
                    # 记录首token时间
                    if first_token_time is None:
                        first_token_time = time.time()
                    all_chunks.append(chunk)
                    
                    # 显式让出控制权，确保在高吞吐量时不会饿死事件循环（如心跳检测）
                    await asyncio.sleep(0)
                    
                    yield chunk

                # 成功完成，跳出重试循环
                break

            except (RateLimitError, APIError, APIConnectionError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError) as e:
                if (
                    response_format is not None
                    and not structured_output_fallback_used
                    and is_unsupported_input_format_error(e)
                ):
                    structured_output_fallback_used = True
                    response_format = None
                    retry_count += 1
                    last_exception = e
                    logger.warning(
                        f"{self.__class__.__name__}: structured output not supported in this runtime shape, retrying without response_format: {e}"
                    )
                    await asyncio.sleep(0)
                    continue
                retry_count += 1
                last_exception = e
                error_message = str(e).lower()

                # 检查是否是限流错误
                is_rate_limit = isinstance(e, RateLimitError) or "rate limit" in error_message or "too many requests" in error_message
                # 检查是否是网络连接错误（包括连接中断、超时等）
                is_connection_error = isinstance(e, APIConnectionError) or "connection" in error_message or "incomplete chunked read" in error_message
                # 检查是否是超时错误
                is_timeout = isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout)) or "timeout" in error_message or "read timeout" in error_message
                # 检查是否是读取错误
                is_read_error = isinstance(e, httpx.ReadError) or "read error" in error_message
                # 检查是否是 token 超限错误
                is_token_limit_error = "range of input length" in error_message or "token" in error_message and "exceed" in error_message

                if retry_count < max_retries and (is_rate_limit or is_connection_error or is_timeout or is_read_error):
                    wait_time = 2 ** retry_count  # 指数退避: 2, 4, 8 秒
                    if is_rate_limit:
                        error_type = "限流"
                    elif is_timeout:
                        error_type = "超时"
                        wait_time = min(wait_time, 10)  # 超时错误最多等待10秒
                    else:
                        error_type = "网络连接"
                    logger.warning(f"{self.__class__.__name__}: 遇到{error_type}错误，等待 {wait_time} 秒后重试 ({retry_count}/{max_retries}): {e}")
                    await asyncio.sleep(wait_time)
                elif is_token_limit_error:
                    # token 超限错误，直接抛出，由上层处理压缩逻辑
                    logger.error(f"{self.__class__.__name__}: Token 超限错误，需要压缩消息: {e}")
                    raise
                else:
                    # 非可重试错误或已达到最大重试次数
                    if isinstance(e, APIError):
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {format_api_error_details(e)}\n{traceback.format_exc()}"
                        )
                    else:
                        logger.error(f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}")
                    all_chunks.append(
                        chat_completion_chunk.ChatCompletionChunk(
                            id="",
                            object="chat.completion.chunk",
                            created=0,
                            model="",
                            choices=[
                                chat_completion_chunk.Choice(
                                    index=0,
                                    delta=chat_completion_chunk.ChoiceDelta(
                                        content=traceback.format_exc(),
                                        tool_calls=None,
                                    ),
                                    finish_reason="stop",
                                )
                            ],
                            usage=None,
                        )
                    )
                    raise e

            except Exception as e:
                # 其他非API错误，检查是否是网络相关错误
                retry_count += 1
                last_exception = e
                error_message = str(e).lower()

                # 检查是否是网络相关错误（如 httpx.RemoteProtocolError, httpx.ReadTimeout 等）
                is_network_error = any(keyword in error_message for keyword in [
                    "connection", "incomplete chunked read", "peer closed", "remoteprotocolerror",
                    "timeout", "read timeout", "connect timeout", "read error"
                ])
                # 检查是否是 httpx 特定的超时或读取错误
                is_httpx_error = isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError, httpx.ConnectError))

                if (is_network_error or is_httpx_error) and retry_count < max_retries:
                    # 使用指数退避 + 随机抖动，避免同时重试
                    import random
                    wait_time = min(2 ** retry_count + random.uniform(0, 1), 30)  # 最大30秒
                    error_type = "HTTP超时" if is_httpx_error else "网络"
                    logger.warning(f"{self.__class__.__name__}: 遇到{error_type}错误，等待 {wait_time:.1f} 秒后重试 ({retry_count}/{max_retries}): {e}")
                    await asyncio.sleep(wait_time)
                    continue  # 继续重试循环
                else:
                    # 非网络错误或已达到最大重试次数
                    if isinstance(e, APIError):
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {format_api_error_details(e)}\n{traceback.format_exc()}"
                        )
                    else:
                        logger.error(f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}")
                    all_chunks.append(
                        chat_completion_chunk.ChatCompletionChunk(
                            id="",
                            object="chat.completion.chunk",
                            created=0,
                            model="",
                            choices=[
                                chat_completion_chunk.Choice(
                                    index=0,
                                    delta=chat_completion_chunk.ChoiceDelta(
                                        content=traceback.format_exc(),
                                        tool_calls=None,
                                    ),
                                    finish_reason="stop",
                                )
                            ],
                            usage=None,
                        )
                    )
                    raise e
            finally:
                # 只有在成功完成或最终失败时才记录
                if retry_count == 0 or retry_count >= max_retries or (last_exception and not isinstance(last_exception, (RateLimitError, APIError))):
                    # 将次请求记录在session context 中的llm调用记录中
                    total_time = time.time() - start_request_time
                    first_token_latency = first_token_time - start_request_time if first_token_time else None
                    first_token_str = f"{first_token_latency:.3f}s" if first_token_latency else "N/A"
                    logger.info(f"{self.__class__.__name__} | {step_name}: 调用语言模型进行流式生成，总耗时: {total_time:.3f}s, 首token延迟: {first_token_str}, 返回{len(all_chunks)}个chunk")
                    if session_id:
                        session_context = self._get_live_session_context(session_id)

                        # final_config 在前面已经把 'model' pop 走了，这里把模型名补回，
                        # 让 SessionContext 的 per-request tokens 统计能拿到 model 字段。
                        model_config_for_record = {**final_config, "model": model_name}
                        llm_request = {
                            "step_name": step_name,
                            "model_config": model_config_for_record,
                            "model": model_name,
                            "messages": serializable_messages,
                            "started_at": start_request_time,
                            "first_token_time": first_token_time,
                            "ttfb_sec": (first_token_time - start_request_time) if first_token_time else None,
                            "duration_sec": total_time,
                        }
                        # 将流式的chunk，进行合并成非流式的response，保存下chunk所有的记录
                        try:
                            llm_response = self.merge_stream_response_to_non_stream_response(all_chunks)
                        except Exception:
                            logger.error(f"{self.__class__.__name__}: 合并流式响应失败: {traceback.format_exc()}")
                            logger.error(f"{self.__class__.__name__}: 合并流式响应失败: {all_chunks}")
                            llm_response = None
                        if session_context:
                            session_context.add_llm_request(llm_request, llm_response)

                            # 更新动态 token 比例
                            logger.debug(f"{self.__class__.__name__}: 检查 token 比例更新条件: llm_response={llm_response is not None}, usage={llm_response.usage if llm_response else None}")
                            if llm_response and llm_response.usage:
                                # 计算总字符数（输入+输出）
                                # 处理 MessageChunk 对象和字典两种类型
                                def get_content_length(m):
                                    if isinstance(m, MessageChunk):
                                        content = m.content
                                        if isinstance(content, str):
                                            return len(content)
                                        elif isinstance(content, list):
                                            return len(str(content))
                                        return 0
                                    else:
                                        # 字典类型
                                        content = m.get('content', '')
                                        return len(str(content))
                                
                                input_chars = sum(get_content_length(m) for m in messages)
                                output_content = llm_response.choices[0].message.content or ''
                                output_chars = len(output_content)
                                total_chars = input_chars + output_chars

                                # 获取实际 token 数
                                actual_tokens = llm_response.usage.total_tokens

                                # 更新 token 比例（message_manager 内部会处理中英文比例）
                                session_context.message_manager.update_token_ratio(total_chars, actual_tokens)
                                logger.debug(f"{self.__class__.__name__}: 更新 token 比例，字符数={total_chars}，token数={actual_tokens}，比例={actual_tokens/total_chars:.4f}")
                        else:
                            logger.warning(f"{self.__class__.__name__}: session_context is None for session_id={session_id}, skip add_llm_request")

    async def _build_system_segments(self,
                                     session_id: Optional[str] = None,
                                     custom_prefix: Optional[str] = None,
                                     language: Optional[str] = None,
                                     system_prefix_override: Optional[str] = None,
                                     include_sections: Optional[List[str]] = None) -> Dict[str, str]:
        """构建按缓存稳定度切分的 system 文本段。

        返回 dict 形如 ``{"stable": str, "semi_stable": str, "volatile": str}``。
        命名按"自上而下越来越易变"排列，便于上层在多段 system message + Anthropic
        cache_control 多断点策略下保持高 cache 命中率：

        - ``stable``：role_definition + IDENTITY/AGENT/SOUL/USER/MEMORY md（按会话生命周期基本不变）
        - ``semi_stable``：available_skills 列表 + active_skills 内容 + skills_usage_hint
        - ``volatile``：system_context（含时间戳等动态字段）+ workspace_files + external_paths
        """
        if include_sections is None:
            include_sections = ['role_definition', 'system_context', 'active_skill', 'workspace_files', 'available_skills', 'AGENT.MD']

        stable_buf = ""
        semi_buf = ""
        volatile_buf = ""

        session_context = None
        if session_id:
            session_context = self._get_live_session_context(session_id)
        # 兼容旧逻辑使用的局部变量名
        system_prefix = ""

        # 1. Role Definition  → stable
        use_identity = False
        if 'role_definition' in include_sections:
            role_content = ""
            if system_prefix_override:
                role_content = system_prefix_override
            elif hasattr(self, 'SYSTEM_PREFIX_FIXED'):
                role_content = self.SYSTEM_PREFIX_FIXED
            elif self.system_prefix:
                role_content = self.system_prefix
            else:
                if session_context and session_context.sandbox:
                    identity_path = os.path.join(session_context.sandbox_agent_workspace, 'IDENTITY.md')
                    try:
                        if await session_context.sandbox.file_exists(identity_path):
                            role_content = await session_context.sandbox.read_file(identity_path)
                            use_identity = True
                    except Exception as e:
                        logger.warning(f"AgentBase: Failed to read IDENTITY.md: {e}")

                if not role_content:
                    role_content = prompt_manager.get_prompt(
                        'agent_intro_template',
                        agent='common',
                        language=language)

            if custom_prefix:
                role_content += f"\n\n{custom_prefix}"

            stable_buf += f"<role_definition>\n{role_content}\n</role_definition>\n"

            # system_reminder 标签语义说明：注入到 stable 段以保持高 cache 命中率
            if language and str(language).lower().startswith("zh"):
                reminder_hint = (
                    "当对话中出现 <system_reminder>...</system_reminder> 包裹的内容时，"
                    "请视为系统级状态通知（非用户输入），仅作为参考信息推进任务即可，"
                    "不需要回复或感谢这条提醒。典型场景：后台 shell 命令完成事件。"
                )
            else:
                reminder_hint = (
                    "When you see content wrapped in <system_reminder>...</system_reminder>, "
                    "treat it as a system-level status notification (not user input). "
                    "Use it as context to drive the next step; do not reply to or acknowledge the reminder itself. "
                    "A common case is background shell command completion events."
                )
            stable_buf += f"<system_reminder_hint>\n{reminder_hint}\n</system_reminder_hint>\n"

        if session_context:
            system_context_info = session_context.system_context.copy()
            logger.debug(f"{self.__class__.__name__}: 添加运行时system_context到系统消息")
            use_claw_mode = os.environ.get("SAGE_USE_CLAW_MODE", "true").lower() == "true"
            if 'use_claw_mode' in system_context_info:
                use_claw_mode = system_context_info.get("use_claw_mode", use_claw_mode)
                if isinstance(use_claw_mode, str):
                    use_claw_mode = use_claw_mode.lower() == "true"
            logger.debug(f"{self.__class__.__name__}: use_claw_mode: {use_claw_mode}")
            if "AGENT.MD" in include_sections and use_claw_mode and session_context.sandbox:
                # 各种 .md 文件 → stable
                workspace = session_context.sandbox_agent_workspace

                try:
                    agent_md_content = await session_context.sandbox.read_file(os.path.join(workspace, 'AGENT.md'))
                    if agent_md_content:
                        stable_buf += f"<agent_md>\n{agent_md_content}\n</agent_md>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: AGENT.md not found or error reading: {e}")

                try:
                    soul_content = await session_context.sandbox.read_file(os.path.join(workspace, 'SOUL.md'))
                    if soul_content:
                        if len(soul_content) > 300:
                            soul_content = soul_content[:300]+"……"
                        stable_buf += f"<soul>\n{soul_content}\n</soul>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: SOUL.md not found or error reading: {e}")

                try:
                    user_content = await session_context.sandbox.read_file(os.path.join(workspace, 'USER.md'))
                    if user_content:
                        if len(user_content) > 300:
                            user_content = user_content[:300]+"……"
                        stable_buf += f"<user>\n{user_content}\n</user>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: USER.md not found or error reading: {e}")

                try:
                    memory_content = await session_context.sandbox.read_file(os.path.join(workspace, 'MEMORY.md'))
                    if memory_content:
                        if len(memory_content) > 500:
                            memory_content = memory_content[:500]+"……"
                        stable_buf += f"<memory>\n{memory_content}\n</memory>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: MEMORY.md not found or error reading: {e}")

                if not use_identity:
                    try:
                        identity_content = await session_context.sandbox.read_file(os.path.join(workspace, 'IDENTITY.md'))
                        if identity_content:
                            if len(identity_content) > 300:
                                identity_content = identity_content[:300]+"……"
                            stable_buf += f"<identity>\n{identity_content}\n</identity>\n"
                    except Exception as e:
                        logger.debug(f"AgentBase: IDENTITY.md not found or error reading: {e}")

            active_skills = None
            if 'active_skills' in system_context_info:
                active_skills = system_context_info.pop('active_skills')

            # 2. System Context  → volatile（含时间戳/动态字段）
            if 'system_context' in include_sections:
                volatile_buf += "<system_context>\n"
                excluded_keys = {'active_skills', 'active_skill_instruction', '可以访问的其他路径文件夹', 'external_paths'}
                for key, value in system_context_info.items():
                    if key in excluded_keys:
                        continue
                    if isinstance(value, (dict, list, tuple)):
                        if isinstance(value, tuple):
                            value = list(value)
                        formatted_val = json.dumps(value, ensure_ascii=False, indent=2)
                        volatile_buf += f"  <{key}>\n{formatted_val}\n  </{key}>\n"
                    else:
                        volatile_buf += f"  <{key}>{str(value)}</{key}>\n"
                volatile_buf += "</system_context>\n"

            # 3. Active Skills  → semi_stable
            if 'active_skill' in include_sections and active_skills:
                semi_buf += "<active_skills>\n"
                for skill in active_skills:
                    skill_name = skill.get('skill_name', 'unknown')
                    skill_content = skill.get('skill_content', '')
                    skill_content_escaped = str(skill_content).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    semi_buf += f"  <{skill_name}>\n{skill_content_escaped}\n  </{skill_name}>\n"
                semi_buf += "</active_skills>\n"

            # 4. Workspace Files  → volatile
            if 'workspace_files' in include_sections:
                if hasattr(session_context, 'sandbox') and session_context.sandbox:
                    workspace_name = session_context.system_context.get('private_workspace', '')
                    volatile_buf += "<workspace_files>\n"
                    workspace_files = prompt_manager.get_prompt(
                        'workspace_files_label',
                        agent='common',
                        language=language,
                    )
                    volatile_buf += workspace_files.format(workspace=workspace_name)

                    try:
                        file_tree = await session_context.sandbox.get_file_tree(
                            include_hidden=True,
                            max_depth=2,
                            max_items_per_dir=5
                        )
                        if not file_tree:
                            no_files = prompt_manager.get_prompt(
                                'no_files_message',
                                agent='common',
                                language=language,
                            )
                            volatile_buf += no_files
                        else:
                            volatile_buf += file_tree
                    except Exception as e:
                        logger.error(f"AgentBase: 获取工作空间文件树时出错: {e}")
                        no_files = prompt_manager.get_prompt(
                            'no_files_message',
                            agent='common',
                            language=language,
                        )
                        volatile_buf += no_files

                    volatile_buf += "</workspace_files>\n"

                external_paths = session_context.system_context.get('external_paths')
                if external_paths and isinstance(external_paths, list) and hasattr(session_context, 'sandbox') and session_context.sandbox:
                    volatile_buf += "<external_paths>\n"
                    ext_paths_intro = prompt_manager.get_prompt(
                        'external_paths_intro',
                        agent='common',
                        language=language,
                    )
                    volatile_buf += ext_paths_intro
                    for ext_path in external_paths:
                        if isinstance(ext_path, str):
                            volatile_buf += f"Path: {ext_path}\n"
                            try:
                                ext_tree = await session_context.sandbox.get_file_tree(
                                    root_path=ext_path,
                                    include_hidden=True,
                                    max_depth=2,
                                    max_items_per_dir=5
                                )
                                if ext_tree:
                                    volatile_buf += ext_tree
                                else:
                                    volatile_buf += "(Empty)\n"
                            except Exception as e:
                                volatile_buf += f"(Error listing files: {e})\n"
                            volatile_buf += "\n"
                    volatile_buf += "</external_paths>\n"

            # 5. Available Skills  → semi_stable
            if 'available_skills' in include_sections:
                sm = session_context.effective_skill_manager
                if sm:
                    if hasattr(sm, "load_new_skills"):
                        try:
                            sm.load_new_skills()
                        except Exception as e:
                            logger.warning(f"Failed to load new skills: {e}")

                    skill_infos = sm.list_skill_info()
                    if skill_infos:
                        semi_buf += "<available_skills>\n"
                        for skill in skill_infos:
                            semi_buf += f"<skill>\n<skill_name>{skill.name}</skill_name>\n<skill_description>{skill.description[:50]+'...' if len(skill.description) > 50 else skill.description}</skill_description>\n</skill>\n"
                        semi_buf += "</available_skills>\n"

                        skills_hint = prompt_manager.get_prompt(
                            'skills_usage_hint',
                            agent='common',
                            language=language,
                            default=""
                        )
                        if skills_hint:
                            semi_buf += f"<skill_usage>\n{skills_hint}\n</skill_usage>\n"

        # 兼容已有局部变量名（避免上游 logger 行依赖）
        system_prefix = stable_buf + semi_buf + volatile_buf
        logger.debug(f"{self.__class__.__name__}: 系统消息生成完成，总长度: {len(system_prefix)}")

        return {
            "stable": stable_buf,
            "semi_stable": semi_buf,
            "volatile": volatile_buf,
        }

    async def prepare_unified_system_message(self,
                                       session_id: Optional[str] = None,
                                       custom_prefix: Optional[str] = None,
                                       language: Optional[str] = None,
                                       system_prefix_override: Optional[str] = None,
                                       include_sections: Optional[List[str]] = None) -> MessageChunk:
        """单条 system message（向后兼容）。

        内部调用 ``_build_system_segments`` 后把三段顺序拼接成一条 system，保持
        和旧版完全一致的行为；新接入方应优先使用 ``prepare_unified_system_messages``
        以拿到分段结构、配合多断点 prompt cache。
        """
        segments = await self._build_system_segments(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=include_sections,
        )
        merged = segments["stable"] + segments["semi_stable"] + segments["volatile"]
        return MessageChunk(
            role=MessageRole.SYSTEM.value,
            content=merged,
            type=MessageType.SYSTEM.value,
            agent_name=self.agent_name,
        )

    async def prepare_unified_system_messages(self,
                                              session_id: Optional[str] = None,
                                              custom_prefix: Optional[str] = None,
                                              language: Optional[str] = None,
                                              system_prefix_override: Optional[str] = None,
                                              include_sections: Optional[List[str]] = None) -> List[MessageChunk]:
        """按 cache 稳定度切分的多段 system message。

        - 返回顺序固定为 ``[stable, semi_stable, volatile]``，空段会被过滤掉
        - 每条 ``MessageChunk.metadata["cache_segment"]`` 标注所属段，便于
          ``add_cache_control_to_messages`` 在前两段末尾打 cache 断点
        - 兜底：当环境变量 ``SAGE_SPLIT_SYSTEM=false`` 时，等价于
          ``prepare_unified_system_message``，把所有段合并为单条 system
        """
        segments = await self._build_system_segments(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=include_sections,
        )

        if os.environ.get("SAGE_SPLIT_SYSTEM", "true").lower() == "false":
            merged = segments["stable"] + segments["semi_stable"] + segments["volatile"]
            return [MessageChunk(
                role=MessageRole.SYSTEM.value,
                content=merged,
                type=MessageType.SYSTEM.value,
                agent_name=self.agent_name,
                metadata={"cache_segment": "stable"},
            )]

        out: List[MessageChunk] = []
        for seg_name in ("stable", "semi_stable", "volatile"):
            seg_text = segments.get(seg_name) or ""
            if not seg_text.strip():
                continue
            out.append(MessageChunk(
                role=MessageRole.SYSTEM.value,
                content=seg_text,
                type=MessageType.SYSTEM.value,
                agent_name=self.agent_name,
                metadata={"cache_segment": seg_name},
            ))
        # 至少保留一条空 stable，避免下游 history 为空时 LLM 直接拒绝
        if not out:
            out.append(MessageChunk(
                role=MessageRole.SYSTEM.value,
                content="",
                type=MessageType.SYSTEM.value,
                agent_name=self.agent_name,
                metadata={"cache_segment": "stable"},
            ))
        return out

    def _judge_delta_content_type(self,
                                  delta_content: str,
                                  all_tokens_str: str,
                                  tag_type: Optional[List[str]] = None) -> str:
        """根据已累积的输出，判断当前 delta 所属的 tag 类型。详见
        ``sagents.utils.stream_tag_parser.judge_delta_content_type``。
        """
        return _judge_delta_content_type_util(delta_content, all_tokens_str, tag_type)

    def _handle_tool_calls_chunk(self,
                                 chunk,
                                 tool_calls: Dict[str, Any],
                                 last_tool_call_id: str) -> None:
        """
        处理工具调用数据块

        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典
            last_tool_call_id: 最后的工具调用ID
        """
        if not chunk.choices or not chunk.choices[0].delta.tool_calls:
            return

        for tool_call in chunk.choices[0].delta.tool_calls:
            tc_id = tool_call.id if tool_call.id is not None and len(tool_call.id) > 0 else ""
            tc_index = getattr(tool_call, "index", None)
            temp_key = f"__tool_call_index_{tc_index}" if tc_index is not None else None

            target_key = None
            if tc_id and tc_id in tool_calls:
                target_key = tc_id
            elif tc_index is not None:
                # 优先按 index 复用已有的 tool_call，避免多 tool 场景下串台
                for existing_key, existing_value in tool_calls.items():
                    if isinstance(existing_value, dict) and existing_value.get("index") == tc_index:
                        target_key = existing_key
                        break
                if target_key is None and temp_key and temp_key in tool_calls:
                    target_key = temp_key
                if target_key is None and tc_id:
                    target_key = tc_id
                if target_key is None and temp_key:
                    target_key = temp_key
                if target_key is None and last_tool_call_id and last_tool_call_id in tool_calls:
                    target_key = last_tool_call_id
                if target_key is None and tool_calls:
                    target_key = next(reversed(tool_calls))
            elif last_tool_call_id and last_tool_call_id in tool_calls:
                target_key = last_tool_call_id
            elif tc_id:
                target_key = tc_id
            elif tool_calls:
                target_key = next(reversed(tool_calls))

            if target_key is None:
                continue

            entry = tool_calls.get(target_key)
            if entry is None:
                logger.info(
                    f"{self.agent_name}: 检测到新工具调用: "
                    f"{tc_id or target_key}, index={tc_index}, 工具名称: {tool_call.function.name}"
                )
                entry = {
                    'id': tc_id or "",
                    'index': tc_index,
                    'type': tool_call.type or 'function',
                    'function': {
                        'name': tool_call.function.name or "",
                        'arguments': tool_call.function.arguments or ""
                    }
                }
                tool_calls[target_key] = entry
            else:
                if tc_id and not entry.get('id'):
                    entry['id'] = tc_id
                    if target_key != tc_id:
                        tool_calls[tc_id] = entry
                        del tool_calls[target_key]
                        target_key = tc_id
                if tc_index is not None and entry.get('index') is None:
                    entry['index'] = tc_index
                if tool_call.function.name:
                    logger.info(
                        f"{self.agent_name}: 更新工具调用: {entry.get('id') or target_key}, "
                        f"index={tc_index}, 工具名称: {tool_call.function.name}"
                    )
                    entry['function']['name'] = tool_call.function.name
                if tool_call.function.arguments:
                    entry['function']['arguments'] += tool_call.function.arguments

    def _create_tool_call_error_message(self,
                                        tool_name: str,
                                        raw_arguments: str,
                                        error_reason: str) -> MessageChunk:
        """
        创建工具调用错误消息，当JSON解析失败时返回给用户

        Args:
            tool_name: 工具名称
            raw_arguments: 原始参数字符串
            error_reason: 错误原因

        Returns:
            MessageChunk: 错误消息块
        """
        # 分析参数长度，给出优化建议
        param_length = len(raw_arguments)
        suggestions = []

        if param_length > 2000:
            suggestions.append("• 参数内容过长（超过2000字符），建议将任务拆分为多次工具调用")
            suggestions.append("• 或者将大段内容保存到文件，然后传递文件路径")

        if '{' in raw_arguments and raw_arguments.count('{') != raw_arguments.count('}'):
            suggestions.append("• JSON括号不匹配，请检查花括号是否成对闭合")

        if '"' in raw_arguments:
            quote_count = raw_arguments.count('"')
            if quote_count % 2 != 0:
                suggestions.append("• 引号未正确闭合，请检查字符串引号是否成对")

        if '\\' in raw_arguments:
            suggestions.append("• 包含反斜杠字符，请确保特殊字符已正确转义")

        if not suggestions:
            suggestions.append("• 请检查JSON格式是否正确")
            suggestions.append("• 确保所有字符串使用双引号包裹")
            suggestions.append("• 确保没有多余的逗号或缺少逗号")

        # 截断过长的参数显示
        display_args = raw_arguments[:200] + "..." if len(raw_arguments) > 200 else raw_arguments

        content = f"""我尝试调用工具 `{tool_name}`，但参数解析失败。

**错误原因**: {error_reason}

**原始参数**:
```
{display_args}
```

**优化建议**:
{chr(10).join(suggestions)}

我需要重新优化我的工具调用方式和参数，确保工具参数格式正确。"""

        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=content,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.DO_SUBTASK_RESULT.value,
            agent_name=self.agent_name
        )

    def _create_tool_call_message(self, tool_call: Dict[str, Any]) -> List[MessageChunk]:
        """
        创建工具调用消息

        Args:
            tool_call: 工具调用信息

        Returns:
            List[MessageChunk]: 工具调用消息列表
        """
        # 格式化工具参数显示
        # 兼容两种分隔符
        args = tool_call['function']['arguments']
        if '```<｜tool▁call▁end｜>' in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(▁): {args}")
            tool_call['function']['arguments'] = args.split('```<｜tool▁call▁end｜>')[0]
        elif '```<｜tool call end｜>' in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(space): {args}")
            tool_call['function']['arguments'] = args.split('```<｜tool call end｜>')[0]

        function_params = tool_call['function']['arguments']
        if len(function_params) > 0:
            try:
                function_params = json.loads(function_params)
            except json.JSONDecodeError:
                try:
                    # 尝试使用 eval 解析，并注入 JSON 常量
                    function_params = eval(function_params, {"__builtins__": None}, {'true': True, 'false': False, 'null': None})
                except Exception:
                    logger.error(f"{self.agent_name}: 第一次参数解析报错，再次进行参数解析失败")
                    logger.error(f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}")

            if isinstance(function_params, str):
                try:
                    function_params = json.loads(function_params)
                except json.JSONDecodeError:
                    try:
                        # 再次尝试使用 eval 解析
                        function_params = eval(function_params, {"__builtins__": None}, {'true': True, 'false': False, 'null': None})
                    except Exception:
                        logger.error(f"{self.agent_name}: 解析完参数化依旧后是str，再次进行参数解析失败")
                        logger.error(f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}")
                        logger.error(f"{self.agent_name}: 工具参数格式错误: {function_params}")
                        logger.error(f"{self.agent_name}: 工具参数类型: {type(function_params)}")

            formatted_params = ''
            if isinstance(function_params, dict):
                tool_call['function']['arguments'] = json.dumps(function_params, ensure_ascii=False)
                for param, value in function_params.items():
                    formatted_params += f"{param} = {json.dumps(value, ensure_ascii=False)}, "
                formatted_params = formatted_params.rstrip(', ')
            else:
                # 只有当非空且非字典时才记录错误（SimpleAgent逻辑兼容）
                if function_params: 
                    logger.warning(f"{self.agent_name}: 参数解析结果不是字典: {type(function_params)}")
                formatted_params = str(function_params)
        else:
            formatted_params = ""

        tool_name = tool_call['function']['name']

        # 将content 整理成函数调用的形式
        return [MessageChunk(
            role='assistant',
            tool_calls=[{
                'id': tool_call['id'],
                'type': tool_call['type'],
                'function': {
                    'name': tool_call['function']['name'],
                    'arguments': tool_call['function']['arguments']
                }
            }],
            message_type=MessageType.TOOL_CALL.value,
            message_id=str(uuid.uuid4()),
            # content=f"{tool_name}({formatted_params})",
            content = None,
            agent_name=self.agent_name
        )]

    async def _execute_tool(self,
                            tool_call: Dict[str, Any],
                            tool_manager: Optional[ToolManager],
                            messages_input: List[Any],
                            session_id: str,
                            session_context: Optional[SessionContext] = None) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行工具

        Args:
            tool_call: 工具调用信息
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 消息块列表
        """
        tool_name = tool_call['function']['name']
        if session_context is None and session_id:
            try:
                session_context = self._get_live_session_context(session_id)
            except Exception as e:
                logger.debug(f"{self.agent_name}: 无法通过 session_id 获取 session_context: {e}")

        try:
            # 解析并执行工具调用
            if len(tool_call['function']['arguments']) > 0:
                arguments = json.loads(tool_call['function']['arguments'])
            else:
                arguments = {}

            if not isinstance(arguments, dict):
                async for chunk in self._handle_tool_error(tool_call['id'], tool_name, Exception("工具参数格式错误: 参数必须是JSON对象")):
                    yield chunk
                return

            if not tool_manager:
                raise ValueError("Tool manager is not provided")

            # 构造调用参数，确保 session_id 正确传递且不重复
            call_kwargs = arguments.copy()
            # 如果 arguments 中有 session_id，移除它（因为会作为显式参数传递）
            call_kwargs.pop('session_id', None)

            tool_response = await tool_manager.run_tool_async(
                tool_name,
                session_id=session_id,
                **call_kwargs
            )

            # 检查是否为流式响应
            if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
                # 处理流式响应
                logger.debug(f"{self.agent_name}: 收到流式工具响应")
                try:
                    for chunk in tool_response:
                        # 普通工具：添加必要的元数据
                        if isinstance(chunk, list):
                            # 转化成message chunk
                            message_chunks = []
                            for message in chunk:
                                if isinstance(message, dict):
                                    message_chunks.append(MessageChunk(
                                        role=MessageRole.TOOL.value,
                                        content=message['content'],
                                        tool_call_id=tool_call['id'],
                                        message_id=str(uuid.uuid4()),
                                        message_type=MessageType.TOOL_CALL_RESULT.value,
                                        agent_name=self.agent_name
                                    ))
                            yield message_chunks
                        else:
                            # 单个消息
                            if isinstance(chunk, dict):
                                message_chunk_ = MessageChunk(
                                    role=MessageRole.TOOL.value,
                                    content=chunk['content'],
                                    tool_call_id=tool_call['id'],
                                    message_id=str(uuid.uuid4()),
                                    message_type=MessageType.TOOL_CALL_RESULT.value,
                                    agent_name=self.agent_name
                                )
                                yield [message_chunk_]
                except Exception as e:
                    logger.error(f"{self.agent_name}: 处理流式工具响应时发生错误: {str(e)}")
                    async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                        yield chunk
            else:
                # 处理非流式响应
                logger.debug(f"{self.agent_name}: 收到非流式工具响应，正在处理")
                logger.info(f"{self.agent_name}: 工具响应 {tool_response}")
                processed_response = self.process_tool_response(tool_response, tool_call['id'])
                yield processed_response

        except Exception as e:
            logger.error(f"{self.agent_name}: 执行工具 {tool_name} 时发生错误: {str(e)}")
            logger.error(f"{self.agent_name}: 堆栈: {traceback.format_exc()}")
            async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                yield chunk

    async def _handle_tool_error(self, tool_call_id: str, tool_name: str, error: Exception) -> AsyncGenerator[List[MessageChunk], None]:
        """
        处理工具执行错误

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 错误信息

        Yields:
            List[MessageChunk]: 错误消息块列表
        """
        error_message = f"工具 {tool_name} 执行失败: {str(error)}"
        logger.error(f"{self.agent_name}: {error_message}")

        error_chunk = MessageChunk(
            role='tool',
            content=json.dumps({"error": error_message}, ensure_ascii=False),
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )

        yield [error_chunk]

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[MessageChunk]:
        """
        处理工具执行响应

        Args:
            tool_response: 工具执行响应
            tool_call_id: 工具调用ID

        Returns:
            List[MessageChunk]: 处理后的结果消息
        """
        logger.debug(f"{self.agent_name}: 处理工具响应，工具调用ID: {tool_call_id}")

        try:
            tool_response_dict = json.loads(tool_response)

            if "content" in tool_response_dict:
                content = tool_response_dict["content"]
            else:
                content = tool_response
        except (json.JSONDecodeError, TypeError):
            content = tool_response

        # 如果 content 还是 dict/list，转成 json string
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        else:
            content = str(content)

        return [MessageChunk(
            role=MessageRole.TOOL.value,
            content=content,
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
            agent_name=self.agent_name
        )]

    def merge_stream_response_to_non_stream_response(self, chunks):
        """将流式的 chunk 合并成非流式的 response。详见
        ``sagents.utils.stream_merger.merge_chat_completion_chunks``。
        """
        return _merge_chunks_util(chunks)

    async def _handle_tool_calls(self,
                                 tool_calls: Dict[str, Any],
                                 tool_manager: Optional[ToolManager],
                                 messages_input: List[Any],
                                 session_id: str,
                                 handle_complete_task: bool = False,
                                 emit_tool_call_message: bool = True) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        """
        处理工具调用

        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            handle_complete_task: 是否处理complete_task工具（TaskExecutorAgent需要）

        Yields:
            tuple[List[MessageChunk], bool]: (消息块列表, 是否完成任务)
        """
        logger.info(f"{self.agent_name}: LLM响应包含 {len(tool_calls)} 个工具调用")

        for tool_call_id, tool_call in tool_calls.items():
            # 增加让出主线程逻辑，防止工具循环处理导致卡死
            await asyncio.sleep(0)
            
            tool_name = tool_call['function']['name']
            raw_arguments = tool_call['function']['arguments']
            logger.info(f"{self.agent_name}: 执行工具 {tool_name}")
            logger.info(f"{self.agent_name}: 参数 {raw_arguments}")

            # 验证工具参数是否为有效的JSON
            # 将复杂的解析逻辑放到线程池中执行
            is_valid_json = False
            parsed_arguments = None
            
            try:
                # 使用线程池执行同步的解析逻辑
                parsed_arguments, is_valid_json = await asyncio.to_thread(self._parse_and_validate_json, raw_arguments)
            except Exception as e:
                logger.error(f"{self.agent_name}: JSON解析异常: {e}")
                is_valid_json = False

            # 如果JSON解析失败，将工具调用转换为普通消息返回
            if not is_valid_json:
                logger.warning(f"{self.agent_name}: 工具参数JSON解析失败，转换为普通消息")
                error_message = self._create_tool_call_error_message(
                    tool_name=tool_name,
                    raw_arguments=raw_arguments,
                    error_reason="JSON格式无效或结构不完整"
                )
                yield ([error_message], False)
                continue

            # 更新解析后的参数
            tool_call['function']['arguments'] = json.dumps(parsed_arguments, ensure_ascii=False)

            # 检查是否为complete_task（仅TaskExecutorAgent需要处理）
            if handle_complete_task and tool_name == 'complete_task':
                logger.info(f"{self.agent_name}: complete_task，停止执行")
                yield ([MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content='已经完成了满足用户的所有要求',
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.DO_SUBTASK_RESULT.value
                )], True)
                return

            # 如果上游已经把 tool_call 以流式消息发出来了，这里就不要重复发卡片了。
            if emit_tool_call_message:
                output_messages = self._create_tool_call_message(tool_call)
                yield (output_messages, False)

            # 执行工具
            async for message_chunk_list in self._execute_tool(
                tool_call=tool_call,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
            ):
                yield (message_chunk_list, False)
    def _parse_and_validate_json(self, raw_arguments: str) -> tuple[Any, bool]:
        """
        在线程池中运行的同步JSON解析逻辑
        使用安全的 ast.literal_eval 替代 eval，避免代码注入风险
        """
        import ast

        try:
            parsed = json.loads(raw_arguments)
            return parsed, True
        except json.JSONDecodeError:
            # 尝试使用 ast.literal_eval 安全解析
            # 仅支持基本数据类型：字符串、数字、元组、列表、字典、集合、布尔值、None
            try:
                parsed = ast.literal_eval(raw_arguments)
                # 验证解析结果是否为字典（工具参数必须是字典）
                if not isinstance(parsed, dict):
                    return None, False
                # 验证解析结果是否可以序列化为JSON
                json.dumps(parsed)
                return parsed, True
            except (ValueError, SyntaxError, TypeError):
                return None, False

    def _should_abort_due_to_session(self, session_context: SessionContext, session_id: Optional[str] = None) -> bool:
        """检查会话/父会话状态，命中即返回 True。详见
        ``sagents.utils.agent_session_helper.should_abort_due_to_session``。
        """
        return _should_abort_due_to_session_util(
            session_context,
            log_prefix=self.__class__.__name__,
        )
