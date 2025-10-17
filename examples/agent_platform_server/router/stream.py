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
from openai import OpenAI

from sagents.tool.tool_proxy import ToolProxy
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



@stream_router.post("/api/stream")
async def stream_chat(request: StreamRequest):
    """流式聊天接口"""
    if not global_vars.get_default_stream_service():
        raise SageHTTPException(status_code=503, detail="服务未配置或不可用", error_detail="Stream service is not configured or unavailable")
    
    logger.info(f"Server: 请求参数: {request}")
    # 生成会话ID
    # llm_model_config={'model': '', 'maxTokens': '', 'temperature': ''}
    # 如果是value 是空，删除key
    if request.llm_model_config:
        request.llm_model_config = {k: v for k, v in request.llm_model_config.items() if v is not None and v != ''}

    session_id = request.session_id or str(uuid.uuid4())
    
    # 初始化会话服务
    db_manager = global_vars.get_database_manager()

    # 检查会话是否存在
    existing_conversation = await db_manager.get_conversation(session_id)
    if not existing_conversation:
        # 创建新会话
        if request.messages and len(request.messages) > 0:
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
        
        await db_manager.save_conversation(
            user_id=request.user_id or "default_user",
            agent_id=request.agent_id or "default_agent",
            agent_name=request.agent_name or "Sage Assistant",
            messages=[msg.model_dump() for msg in request.messages],
            session_id=session_id,
            title=conversation_title
        )
        logger.info(f"创建新会话: {session_id}, 标题: {conversation_title}")
    else:
        # 更新现有会话的消息
        new_messages = [msg.model_dump() for msg in request.messages]
        for msg in new_messages:
            await db_manager.add_message_to_conversation(session_id, msg)
        logger.info(f"更新现有会话: {session_id}")
    
    # 判断是否要初始化新的 sage service 还是使用默认的
    # 取决于是否需要自定义模型以及 agent 的system prefix ，以及对tool 的工具是否有限制
    if request.llm_model_config or request.system_prefix or request.available_tools:
        # 根据model config 初始化新的模型客户端
        server_args = global_vars.get_server_args()
        logger.info(f"初始化新的模型客户端，模型配置api_key :{request.llm_model_config.get('api_key', server_args.default_llm_api_key)}")
        logger.info(f"初始化新的模型客户端，模型配置base_url :{request.llm_model_config.get('base_url', server_args.default_llm_api_base_url)}")
        logger.info(f"初始化新的模型客户端，模型配置model :{request.llm_model_config.get('model', server_args.default_llm_model_name)}")
        model_client = OpenAI(
            api_key=request.llm_model_config.get('api_key', server_args.default_llm_api_key),
            base_url=request.llm_model_config.get('base_url', server_args.default_llm_api_base_url),
        )
        llm_model_config = {
            'model': request.llm_model_config.get('model', server_args.default_llm_model_name)
        }
        
        # 只有在有有效的max_tokens值时才添加该键，避免None值导致错误
        max_tokens_value = request.llm_model_config.get('max_tokens', server_args.default_llm_max_tokens)
        max_model_len = request.llm_model_config.get('max_model_len', server_args.default_llm_max_model_len)
        if max_tokens_value is not None:
            llm_model_config['max_tokens'] = int(max_tokens_value)
            
        # 只有在有有效的temperature值时才添加该键，避免None值导致错误
        temperature_value = request.llm_model_config.get('temperature', server_args.default_llm_temperature)
        if temperature_value is not None:
            llm_model_config['temperature'] = float(temperature_value)
        logger.info(f"初始化模型客户端，模型配置: {llm_model_config}")

        if request.available_tools:
            logger.info(f"初始化工具代理，可用工具: {request.available_tools}")
            start_tool_proxy = time.time()
            # 如果request.multi_agent 是true，要确保request.available_tools没有 complete_task 这个工具
            if request.multi_agent and 'complete_task' in request.available_tools:
                request.available_tools.remove('complete_task')
            tool_proxy = ToolProxy(global_vars.get_tool_manager(), request.available_tools)
            end_tool_proxy = time.time()
            logger.info(f"初始化工具代理耗时: {end_tool_proxy - start_tool_proxy} 秒")
        else:
            tool_proxy = global_vars.get_tool_manager()

        start_stream_service = time.time()
        # 初始化新的 sage service
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
        end_stream_service = time.time()
        logger.info(f"初始化流式服务耗时: {end_stream_service - start_stream_service} 秒")
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
    # 保存conversations记录
    async def generate_stream(stream_service):
        """生成SSE流"""
        try:
            # 直接转换消息格式，不进行内容调整
            messages = []
            for msg in request.messages:
                # 保持原始消息的所有字段
                message_dict = msg.model_dump()
                # 如果有content 一定要转化成str
                if message_dict.get('content'):
                    message_dict['content'] = str(message_dict['content'])
                messages.append(message_dict)
            
            logger.info(f"开始流式处理，会话ID: {session_id}")
            
            # 打印请求体内容
            logger.info(f"请求体内容: {request}")
            
            # 添加流处理计数器和连接状态跟踪
            stream_counter = 0
            last_activity_time = time.time()
            
            # 初始化消息收集器，用于合并基于message_id的消息，保持顺序
            message_collector = {}  # {message_id: merged_message}
            message_order = []  # 保持消息的原始顺序
            
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
                force_summary=global_vars.get_server_args().force_summary
            ):
                # 更新流处理计数器和活动时间
                stream_counter += 1
                current_time = time.time()
                time_since_last = current_time - last_activity_time
                last_activity_time = current_time
                
                # 每100个结果记录一次连接状态
                if stream_counter % 100 == 0:
                    logger.info(f"📊 流处理状态 - 会话: {session_id}, 计数: {stream_counter}, 间隔: {time_since_last:.3f}s")

                # 收集消息用于后续保存到数据库
                if isinstance(result, dict) and result.get('message_id'):
                    message_id = result['message_id']
                    
                    # 如果是新消息，初始化并记录顺序
                    if message_id not in message_collector:
                        message_collector[message_id] = result
                        # 记录消息的原始顺序
                        message_order.append(message_id)
                    # 对于工具调用结果消息，完整替换而不是合并
                    if result.get('role') != 'tool':
                        # 合并content和show_content字段（追加）
                        if result.get('content'):
                            message_collector[message_id]['content'] += str(result['content'])
                        if result.get('show_content'):
                            message_collector[message_id]['show_content'] += str(result['show_content'])
                    
            
                # 处理大JSON的分块传输
                try:
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
            logger.info(f"✅ 流结束数据: {end_data}")
            yield json.dumps(end_data, ensure_ascii=False) + "\n"
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
                
        except GeneratorExit as ge:
            import sys
            disconnect_msg = f"🔌 [GENERATOR_EXIT] 客户端断开连接，生成器被关闭 - 会话ID: {session_id}, 时间: {time.time()}"
            logger.error(disconnect_msg)
            logger.error(f"🔍 [GENERATOR_EXIT] GeneratorExit详情: {type(ge).__name__} - {str(ge)}")
            logger.error(f"📋 [GENERATOR_EXIT] 堆栈跟踪: {traceback.format_exc()}")
            logger.error(f"📊 [GENERATOR_EXIT] 流处理统计: 已处理 {stream_counter if 'stream_counter' in locals() else 0} 个流结果")
            # 强制刷新日志缓冲区
            sys.stdout.flush()
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
            logger.info('server generate_stream finally save info and delete')
            # 清理会话资源
            all_active_sessions_service_map = global_vars.get_all_active_sessions_service_map()
            if session_id in all_active_sessions_service_map:
                stream_service = all_active_sessions_service_map[session_id]['stream_service']
                if stream_service:
                    if stream_service.save_session(session_id):
                        logger.info(f"会话 {session_id} 状态已保存")
                    else:
                        logger.error(f"会话 {session_id} 保存失败，已经保存")
                del all_active_sessions_service_map[session_id]
                logger.info(f"会话 {session_id} 资源已清理")
    
    return StreamingResponse(
        generate_stream(stream_service),
        media_type="text/plain"
    )