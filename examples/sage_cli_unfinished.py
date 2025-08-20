#!/usr/bin/env python3
"""
Sage Multi-Agent CLI

智能多智能体协作命令行工具
简化版本，专注于核心功能，不打印结果
"""

import os
import sys
import json
import uuid
import argparse
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional

# 项目路径配置
project_root = Path(os.path.realpath(__file__)).parent.parent
sys.path.insert(0, str(project_root))

from sagents.sagents import SAgent
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.logger import logger
from openai import OpenAI

class ComponentManager:
    """组件管理器 - 负责初始化和管理核心组件"""
    
    def __init__(self, api_key: str, model_name: str = None, base_url: str = None, 
                 tools_folders: List[str] = None, max_tokens: int = None, temperature: float = None):
        
        logger.debug(f"使用配置 - 模型: {model_name}, 温度: {temperature}")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature

        # 设置工具文件夹
        self.tools_folders = tools_folders or []
        
        # 初始化组件变量
        self._tool_manager: Optional[ToolManager] = None
        self._controller: Optional[SAgent] = None
        self._model: Optional[OpenAI] = None
        
    def initialize(self) -> tuple[ToolManager, SAgent]:
        """初始化所有组件"""
        try:
            logger.info(f"初始化组件，模型: {self.model_name}")
            
            # 初始化工具管理器
            self._tool_manager = self._init_tool_manager()
            
            # 初始化模型和控制器
            self._model = self._init_model()
            self._controller = self._init_controller()
            
            logger.info("所有组件初始化成功")
            return self._tool_manager, self._controller
            
        except Exception as e:
            logger.error(f"组件初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    
    def _init_tool_manager(self) -> ToolManager:
        """初始化工具管理器"""
        logger.debug("初始化工具管理器")
        tool_manager = ToolManager()
        
        # 注册工具目录
        for folder in self.tools_folders:
            if Path(folder).exists():
                logger.debug(f"注册工具目录: {folder}")
                tool_manager.register_tools_from_directory(folder)
            else:
                logger.warning(f"工具目录不存在: {folder}")
        
        return tool_manager
    
    def _init_model(self) -> OpenAI:
        """初始化模型"""
        logger.debug(f"初始化模型，base_url: {self.base_url}")
        try:
            return OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise
    
    def _init_controller(self) -> SAgent:
        """初始化控制器"""
        try:
            model_config = {
                "model": self.model_name,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }
            
            controller = SAgent(self._model, model_config, workspace="/Users/zhangzheng/zavixai/Sage/examples")
            return controller
            
        except Exception as e:
            logger.error(f"控制器初始化失败: {str(e)}")
            raise 


def create_user_message(content: str) -> Dict[str, Any]:
    """创建用户消息"""
    return {
        "role": "user",
        "content": content,
        "type": "normal",
        "message_id": str(uuid.uuid4())
    }


class CLIProcessor:
    """CLI处理器 - 处理命令行交互"""
    
    def __init__(self, controller: SAgent, tool_manager: ToolManager):
        self.controller = controller
        self.tool_manager = tool_manager
        self.conversation = []
    
    def process_query(self, query: str, use_deepthink: bool = True, use_multi_agent: bool = True) -> None:
        """处理查询，不打印结果"""
        logger.info(f"处理查询: {query[:50]}{'...' if len(query) > 50 else ''}")
        
        # 创建用户消息
        user_msg = create_user_message(query)
        self.conversation.append(user_msg)
        
        try:
            # 处理流式响应，但不打印
            new_messages = []
            for chunk in self.controller.run_stream(
                self.conversation,
                self.tool_manager,
                session_id=None,
                deep_thinking=use_deepthink,
                multi_agent=use_multi_agent
            ):
                pass
                # 将message chunk类型的chunks 转化成字典
                # chunk_dicts = [msg.to_dict() for msg in chunk]
                # new_messages.extend(chunk_dicts)
            
            # # 合并消息到对话历史
            # if new_messages:
            #     merged_messages = MessageManager._merge_messages(
            #         self.conversation, new_messages
            #     )
            #     self.conversation = merged_messages
                
            logger.info("查询处理完成")
                
        except Exception as e:
            logger.error(f"处理查询时出错: {str(e)}")
            logger.error(traceback.format_exc())
            
        
            error_response = {
                "role": "assistant",
                "content": f"处理查询时出错: {str(e)}",
                "message_id": str(uuid.uuid4())
            }
            self.conversation.append(error_response)


def parse_arguments() -> Dict[str, Any]:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Sage Multi-Agent CLI Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python sage_cli.py --api_key YOUR_API_KEY --query "你好"
  python sage_cli.py --api_key YOUR_API_KEY --model gpt-4 --query "帮我分析一下数据"
        """
    )
    
    parser.add_argument('--api_key', required=True, 
                       help='OpenRouter API key（必需）')
    parser.add_argument('--query', required=True,
                       help='要处理的查询内容（必需）')
    parser.add_argument('--model', 
                       default='mistralai/mistral-small-3.1-24b-instruct:free',
                       help='模型名称')
    parser.add_argument('--base_url', 
                       default='https://openrouter.ai/api/v1',
                       help='API base URL')
    parser.add_argument('--tools_folders', nargs='+', default=[],
                       help='工具目录路径（多个路径用空格分隔）')
    parser.add_argument('--max_tokens', type=int, default=4096,
                       help='最大令牌数')
    parser.add_argument('--temperature', type=float, default=0.2,
                       help='温度参数')
    parser.add_argument('--no-deepthink', action='store_true',
                       help='禁用深度思考')
    parser.add_argument('--no-multi-agent', action='store_true',
                       help='禁用多智能体推理')
    
    args = parser.parse_args()
    
    return {
        'api_key': args.api_key,
        'query': args.query,
        'model_name': args.model,
        'base_url': args.base_url,
        'tools_folders': args.tools_folders,
        'max_tokens': args.max_tokens,
        'temperature': args.temperature,
        'use_deepthink': not args.no_deepthink,
        'use_multi_agent': not args.no_multi_agent
    }


def main():
    """主函数"""
    try:
        # 解析配置
        config = parse_arguments()
        logger.info(f"启动CLI工具，模型: {config['model_name']}")
        
        # 初始化组件
        component_manager = ComponentManager(
            api_key=config['api_key'],
            model_name=config['model_name'],
            base_url=config['base_url'],
            tools_folders=config['tools_folders'],
            max_tokens=config['max_tokens'],
            temperature=config['temperature']
        )
        
        tool_manager, controller = component_manager.initialize()
        
        # 创建CLI处理器
        cli_processor = CLIProcessor(controller, tool_manager)
        
        # 处理查询
        cli_processor.process_query(
            config['query'],
            use_deepthink=config['use_deepthink'],
            use_multi_agent=config['use_multi_agent']
        )
        
        logger.info("CLI工具执行完成")
    except Exception as e:
        logger.error(f"CLI工具执行失败: {str(e)}")
        logger.error(traceback.format_exc())
    

if __name__ == "__main__":
    main()