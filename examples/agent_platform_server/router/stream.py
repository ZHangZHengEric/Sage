"""
流式聊天接口路由模块
"""
import json
import uuid
import asyncio
import traceback
import time
from typing import Dict, Any, Optional, List, Union
from fastapi import APIRouter
from entities.entities import SageHTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sagents.utils.logger import logger
import globals.variables as global_vars

# 创建路由器
stream_router = APIRouter()

class Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

class StreamRequest(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    deep_thinking: Optional[bool] = None
    max_loop_count: Optional[int] = None
    multi_agent: Optional[bool] = None
    more_suggest: Optional[bool] = None
    system_context: Optional[Dict[str, Any]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None
    force_summary: Optional[bool] = False
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        # 确保 messages 中的每个消息都有 role 和 content
        if self.messages:
            for i, msg in enumerate(self.messages):
                if isinstance(msg, dict):
                    # 如果是字典，转换为 Message 对象
                    self.messages[i] = Message(**msg)
                elif not hasattr(msg, 'role') or not hasattr(msg, 'content'):
                    raise ValueError(f"消息 {i} 缺少必要的 'role' 或 'content' 字段")



def _clean_llm_model_config(llm_model_config: dict) -> dict:
    """清理LLM模型配置，移除空值"""
    if not llm_model_config:
        return {}
    return {k: v for k, v in llm_model_config.items() if v is not None and v != ''}


def _build_llm_model_config(request_config: dict, server_args) -> dict:
    """构建LLM模型配置"""
    llm_model_config = {
        'model': request_config.get('model', server_args.default_llm_model_name)
    }
    
    # 只有在有有效的max_tokens值时才添加该键，避免None值导致错误
    max_tokens_value = request_config.get('max_tokens', server_args.default_llm_max_tokens)
    if max_tokens_value is not None:
        llm_model_config['max_tokens'] = int(max_tokens_value)
        
    # 只有在有有效的temperature值时才添加该键，避免None值导致错误
    temperature_value = request_config.get('temperature', server_args.default_llm_temperature)
    if temperature_value is not None:
        llm_model_config['temperature'] = float(temperature_value)
    
    return llm_model_config


def _create_model_client(request_config: dict, server_args):
    """创建模型客户端"""
    from openai import OpenAI
    
    api_key = request_config.get('api_key', server_args.default_llm_api_key)
    base_url = request_config.get('base_url', server_args.default_llm_api_base_url)
    
    logger.info(f"初始化新的模型客户端，模型配置api_key: {api_key}")
    logger.info(f"初始化新的模型客户端，模型配置base_url: {base_url}")
    logger.info(f"初始化新的模型客户端，模型配置model: {request_config.get('model', server_args.default_llm_model_name)}")
    
    return OpenAI(api_key=api_key, base_url=base_url)


def _create_tool_proxy(request, global_vars):
    """创建工具代理"""
    if not request.available_tools:
        return global_vars.get_tool_manager()
    
    logger.info(f"初始化工具代理，可用工具: {request.available_tools}")
    
    # 如果request.multi_agent 是true，要确保request.available_tools没有 complete_task 这个工具
    if request.multi_agent and 'complete_task' in request.available_tools:
        request.available_tools.remove('complete_task')
    
    from sagents.tool.tool_proxy import ToolProxy
    tool_proxy = ToolProxy(global_vars.get_tool_manager(), request.available_tools)
        
    return tool_proxy


def _create_stream_service(model_client, llm_model_config, tool_proxy, request, server_args, max_model_len):
    """创建流式服务"""    
    from handler import SageStreamService
    stream_service = SageStreamService(
        model=model_client,
        model_config=llm_model_config,
        tool_manager=tool_proxy,
        preset_running_config={
            "system_prefix": request.system_prefix
        },
        workspace=server_args.workspace,
        memory_root=server_args.memory_root,
        max_model_len=max_model_len
    )
    return stream_service


def _setup_stream_service(request: StreamRequest):
    """设置流式服务，返回(stream_service, session_id)"""
    session_id = request.session_id or str(uuid.uuid4())
    
    # 判断是否要初始化新的 sage service 还是使用默认的
    if request.llm_model_config or request.system_prefix or request.available_tools:
        # 根据model config 初始化新的模型客户端
        server_args = global_vars.get_server_args()
        
        model_client = _create_model_client(request.llm_model_config, server_args)
        llm_model_config = _build_llm_model_config(request.llm_model_config, server_args)
        max_model_len = request.llm_model_config.get('max_model_len', server_args.default_llm_max_model_len)
        
        logger.info(f"初始化模型客户端，模型配置: {llm_model_config}")
        
        tool_proxy = _create_tool_proxy(request, global_vars)
        stream_service = _create_stream_service(model_client, llm_model_config, tool_proxy, request, server_args, max_model_len)
        
        all_active_sessions_service_map = global_vars.get_all_active_sessions_service_map()
        all_active_sessions_service_map[session_id] = {
            'stream_service': stream_service,
            'session_id': session_id,
            "is_default": False
        }
    else:
        logger.info(f"使用默认的流式服务，会话ID: {session_id}")
        # 使用默认的 sage service
        stream_service = global_vars.get_default_stream_service()
        # 记录会话ID
        all_active_sessions_service_map = global_vars.get_all_active_sessions_service_map()
        all_active_sessions_service_map[session_id] = {
            'stream_service': stream_service,
            'session_id': session_id,
            "is_default": True
        }
    
    return stream_service, session_id


def _prepare_messages(request_messages):
    """准备和格式化消息"""
    messages = []
    for msg in request_messages:
        # 保持原始消息的所有字段
        message_dict = msg.model_dump()
        # 先判断原消息是否存在message_id字段， 不存在则初始化一个
        if 'message_id' not in message_dict or not message_dict['message_id']:
            message_dict['message_id'] = str(uuid.uuid4())  # 为每个消息生成唯一ID
        # 如果有content 一定要转化成str
        if message_dict.get('content'):
            message_dict['content'] = str(message_dict['content'])
        messages.append(message_dict)
    return messages


def _initialize_message_collector(messages):
    """初始化消息收集器"""
    message_collector = {}  # {message_id: merged_message}
    message_order = []  # 保持消息的原始顺序
    
    # 将请求的messages添加到初始化中
    for msg in messages:
        msg_id = msg['message_id']
        message_collector[msg_id] = msg
        message_order.append(msg_id)
    
    return message_collector, message_order


def _update_message_collector(message_collector, message_order, result):
    """更新消息收集器"""
    if not isinstance(result, dict) or not result.get('message_id'):
        return
    
    message_id = result['message_id']
    # 如果是新消息，初始化
    if message_id not in message_collector:
        message_collector[message_id] = result
        message_order.append(message_id)
    else:
        # 对于工具调用结果消息，完整替换而不是合并
        if result.get('role') != 'tool':
            # 合并content和show_content字段（追加）
            if result.get('content'):
                message_collector[message_id]['content'] += str(result['content'])
            if result.get('show_content'):
                message_collector[message_id]['show_content'] += str(result['show_content'])


async def _send_chunked_json(result):
    """发送分块JSON数据"""
    json_str = json.dumps(result, ensure_ascii=False)
    json_size = len(json_str)
    
    # 对于超大JSON，使用分块发送确保完整性
    if json_size > 32768:  # 32KB以上使用分块发送
        logger.info(f"🔄 大JSON分块发送: {json_size} 字符")
        
        # 分块发送大JSON
        chunk_size = 8192  # 8KB per chunk
        total_chunks = (json_size + chunk_size - 1) // chunk_size
        
        # 发送分块开始标记
        start_marker = {
            'type': 'chunk_start',
            'message_id': result.get('message_id', 'unknown'),
            'total_size': json_size,
            'total_chunks': total_chunks,
            'chunk_size': chunk_size,
            'original_type': result.get('type', 'unknown')
        }
        yield json.dumps(start_marker, ensure_ascii=False) + "\n"
        await asyncio.sleep(0.01)  # 延迟确保前端准备好
        
        for i in range(total_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, json_size)
            chunk_data = json_str[start:end]
            
            # 创建分块消息
            chunk_message = {
                'type': 'json_chunk',
                'message_id': result.get('message_id', 'unknown'),  # 添加message_id字段
                'chunk_id': f"{result.get('message_id', 'unknown')}_{i}",
                'chunk_index': i,
                'total_chunks': total_chunks,
                'chunk_data': chunk_data,
                'chunk_size': len(chunk_data),
                'is_final': i == total_chunks - 1,
                'checksum': hash(chunk_data) % 1000000
            }
            
            yield json.dumps(chunk_message, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.005)  # 适中延迟确保顺序
        
        # 发送分块结束标记
        end_marker = {
            'type': 'chunk_end',
            'message_id': result.get('message_id', 'unknown'),
            'total_chunks': total_chunks,
            'expected_size': json_size,
            'original_type': result.get('type', 'unknown')
        }
        yield json.dumps(end_marker, ensure_ascii=False) + "\n"
        
        logger.info(f"✅ 完成分块发送: {total_chunks} 块")
    else:
        # 小JSON直接发送
        yield json.dumps(result, ensure_ascii=False) + "\n"


async def _create_conversation_title(request):
    """创建会话标题"""
    if not request.messages or len(request.messages) == 0:
        return "新会话"
    
    # 使用第一条用户消息的前50个字符作为标题
    first_message = request.messages[0].content
    if isinstance(first_message, str):
        conversation_title = first_message[:50] + "..." if len(first_message) > 50 else first_message
    elif isinstance(first_message, list) and len(first_message) > 0:
        # 如果是多模态消息，尝试提取文本内容
        for item in first_message:
            if isinstance(item, dict) and item.get('type') == 'text':
                text_content = item.get('text', '')
                conversation_title = text_content[:50] + "..." if len(text_content) > 50 else text_content
                break
        else:
            conversation_title = "多模态消息"
    else:
        conversation_title = "新会话"
    
    return conversation_title


async def _save_conversation_if_needed(db_manager, session_id, request):
    """如果需要，保存新会话"""
    existing_conversation = await db_manager.get_conversation(session_id)
    if not existing_conversation:
        conversation_title = await _create_conversation_title(request)
        await db_manager.save_conversation(
            user_id=request.user_id or "default_user",
            agent_id=request.agent_id or "default_agent",
            agent_name=request.agent_name or "Sage Assistant",
            messages=[],
            session_id=session_id,
            title=conversation_title
        )
        logger.info(f"创建新会话: {session_id}, 标题: {conversation_title}")


async def _save_messages_to_db(db_manager, session_id, message_collector, message_order):
    """保存消息到数据库"""
    try:
        # 按照原始顺序将合并的消息添加到现有conversation
        for message_id in message_order:
            if message_id in message_collector:
                merged_message = message_collector[message_id]
                # 添加消息到conversation
                await db_manager.add_message_to_conversation(session_id, merged_message)
        logger.info(f"成功按顺序保存 {len(message_collector)} 条消息到现有conversation {session_id}")
    except Exception as e:
        logger.error(f"保存消息到数据库失败: {e}")
        logger.error(f"错误详情: {traceback.format_exc()}")


@stream_router.post("/api/stream")
async def stream_chat(request: StreamRequest):
    """流式聊天接口"""
    if not global_vars.get_default_stream_service():
        raise SageHTTPException(status_code=503, detail="服务未配置或不可用", error_detail="Stream service is not configured or unavailable")
    
    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        raise SageHTTPException(status_code=400, detail="消息列表不能为空")
    
    logger.info(f"Server: 请求参数: {request}")
    
    # 清理LLM模型配置
    if request.llm_model_config:
        request.llm_model_config = _clean_llm_model_config(request.llm_model_config)

    # 设置流式服务
    stream_service, session_id = _setup_stream_service(request)
    
    # 初始化数据库管理器
    db_manager = global_vars.get_database_manager()
    # 生成流式响应
    async def generate_stream():
        """生成SSE流"""
        try:
            # 准备和格式化消息
            messages = _prepare_messages(request.messages)
            
            logger.info(f"开始流式处理，会话ID: {session_id}")
            
            # 添加流处理计数器和连接状态跟踪
            stream_counter = 0
            last_activity_time = time.time()
            
            # 初始化消息收集器
            message_collector, message_order = _initialize_message_collector(messages)
            
            # 处理流式响应，传递所有参数
            async for result in stream_service.process_stream(
                messages=messages, 
                session_id=session_id,
                user_id=request.user_id,
                deep_thinking=request.deep_thinking,
                max_loop_count=request.max_loop_count,
                multi_agent=request.multi_agent,
                more_suggest=request.more_suggest,
                system_context=request.system_context,
                available_workflows=request.available_workflows,
                force_summary=request.force_summary
            ):
                # 更新流处理计数器和活动时间
                stream_counter += 1
                current_time = time.time()
                time_since_last = current_time - last_activity_time
                last_activity_time = current_time
                
                # 每100个结果记录一次连接状态
                if stream_counter % 100 == 0:
                    logger.info(f"📊 流处理状态 - 会话: {session_id}, 计数: {stream_counter}, 间隔: {time_since_last:.3f}s")

                # 更新消息收集器
                _update_message_collector(message_collector,message_order, result)
                
                # 处理JSON传输（分块或直接发送）
                try:
                    async for chunk in _send_chunked_json(result):
                        yield chunk
                except Exception as e:
                    logger.error(f"JSON序列化失败: {e}")
                    # 创建错误响应
                    error_data = {
                        'type': 'error',
                        'message_id': result.get('message_id', 'error'),
                        'content': f'数据处理错误: {str(e)}',
                        'original_size': len(str(result)),
                        'error': True
                    }
                    yield json.dumps(error_data, ensure_ascii=False) + "\n"
                    
                await asyncio.sleep(0.01)  # 避免过快发送
            
            # 发送流结束标记
            end_data = {
                'type': 'stream_end',
                'session_id': session_id,
                'timestamp': time.time(),
                'total_stream_count': stream_counter
            }
            total_duration = time.time() - (last_activity_time - time_since_last if 'time_since_last' in locals() else last_activity_time)
            logger.info(f"✅ 完成流式处理: 会话 {session_id}, 总计 {stream_counter} 个流结果, 耗时 {total_duration:.3f}s")
            yield json.dumps(end_data, ensure_ascii=False) + "\n"
            
            # 保存会话和消息到数据库
            await _save_conversation_if_needed(db_manager, session_id, request)
            await _save_messages_to_db(db_manager, session_id, message_collector, message_order)
                
        except GeneratorExit as ge:
            import sys
            disconnect_msg = f"🔌 [GENERATOR_EXIT] 客户端断开连接，生成器被关闭 - 会话ID: {session_id}, 时间: {time.time()}"
            logger.error(disconnect_msg)
            logger.error(f"📊 [GENERATOR_EXIT] 流处理统计: 已处理 {stream_counter if 'stream_counter' in locals() else 0} 个流结果")
            # 强制刷新日志缓冲区
            sys.stderr.flush()
            
        except Exception as e:
            logger.error(f"流式处理异常: {e}")
            logger.error(traceback.format_exc())
            error_data = {
                'type': 'error',
                'message': str(e),
                'session_id': session_id
            }
            yield json.dumps(error_data, ensure_ascii=False) + "\n"
        finally:
            logger.info('流处理结束，清理会话资源')
            # 清理会话资源
            all_active_sessions_service_map = global_vars.get_all_active_sessions_service_map()
            if session_id in all_active_sessions_service_map:
                del all_active_sessions_service_map[session_id]
            logger.info(f"会话 {session_id} 资源已清理")
               
    return StreamingResponse(
        generate_stream(),
        media_type="text/plain"
    )