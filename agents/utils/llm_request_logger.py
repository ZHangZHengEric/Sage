"""
LLM请求日志记录器

用于记录所有OpenAI API调用的详细信息，只记录请求信息。
每个会话的请求记录都保存在对应的工作目录下。

作者: Eric ZZ
版本: 1.0
"""

import json
import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
from agents.utils.logger import logger


class LLMRequestLogger:
    """LLM请求日志记录器 - 保存所有OpenAI API请求信息到会话工作目录"""
    
    def __init__(self, session_id: str, workspace_root: str = None):
        """
        初始化LLM请求日志记录器
        
        Args:
            session_id: 会话ID
            workspace_root: 工作空间根目录，如果为None则使用默认的sage_demo_workspace
        """
        self.session_id = session_id
        
        # 使用传入的workspace_root，如果为None则使用默认路径
        if workspace_root is None:
            self.workspace_dir = os.path.join(os.getcwd(), "sage_demo_workspace", session_id)
        else:
            self.workspace_dir = workspace_root
        
        # 创建LLM请求日志目录
        self.llm_requests_dir = os.path.join(self.workspace_dir, "llm_requests")
        os.makedirs(self.llm_requests_dir, exist_ok=True)
        
        # 初始化统计信息
        self.session_stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "agents_used": set(),
            "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        self.request_counter = 0
        
        logger.info(f"LLMRequestLogger: 初始化会话 {session_id} 的日志记录器，工作目录: {self.workspace_dir}")
    
    def log_request(self, 
                   agent_name: str,
                   prompt: str, 
                   response: str,
                   model: str = "gpt-4",
                   tokens_used: int = 0,
                   cost: float = 0.0,
                   additional_info: Dict[str, Any] = None) -> str:
        """
        记录LLM请求信息
        
        Args:
            agent_name: 发起请求的智能体名称
            prompt: 发送给LLM的prompt
            response: LLM的响应
            model: 使用的模型名称
            tokens_used: 使用的token数量
            cost: 请求成本
            additional_info: 额外信息
            
        Returns:
            str: 日志文件路径
        """
        self.request_counter += 1
        timestamp = datetime.now()
        
        # 生成唯一的请求ID
        request_id = f"{self.session_id}_{self.request_counter:04d}_{int(time.time())}"
        
        # 准备日志数据
        log_data = {
            "request_id": request_id,
            "session_id": self.session_id,
            "agent_name": agent_name,
            "timestamp": timestamp.isoformat(),
            "model": model,
            "prompt": prompt,
            "response": response,
            "tokens_used": tokens_used,
            "cost": cost,
            "additional_info": additional_info or {}
        }
        
        # 保存到单独的JSON文件
        log_filename = f"request_{self.request_counter:04d}_{agent_name}_{timestamp.strftime('%H%M%S')}.json"
        log_filepath = os.path.join(self.llm_requests_dir, log_filename)
        
        with open(log_filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        
        # 更新会话统计
        self.session_stats["total_requests"] += 1
        self.session_stats["total_tokens"] += tokens_used
        self.session_stats["total_cost"] += cost
        self.session_stats["agents_used"].add(agent_name)
        
        # 保存会话统计信息
        self._save_session_stats()
        
        logger.debug(f"LLMRequestLogger: 已记录请求 {request_id} ({agent_name})")
        return log_filepath
    
    def _save_session_stats(self):
        """保存会话统计信息"""
        stats_file = os.path.join(self.workspace_dir, "llm_session_stats.json")
        
        # 转换set为list以便JSON序列化
        stats_copy = self.session_stats.copy()
        stats_copy["agents_used"] = list(stats_copy["agents_used"])
        stats_copy["last_updated"] = datetime.now().isoformat()
        
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats_copy, f, ensure_ascii=False, indent=2)
    
    def get_session_summary(self) -> Dict[str, Any]:
        """获取会话摘要信息"""
        return {
            "session_id": self.session_id,
            "workspace_dir": self.workspace_dir,
            "total_requests": self.session_stats["total_requests"],
            "total_tokens": self.session_stats["total_tokens"],
            "total_cost": self.session_stats["total_cost"],
            "agents_used": list(self.session_stats["agents_used"]),
            "start_time": self.session_stats["start_time"]
        }
    
    def get_requests_by_agent(self, agent_name: str) -> list:
        """获取特定智能体的所有请求记录"""
        requests = []
        
        for filename in os.listdir(self.llm_requests_dir):
            if filename.endswith('.json') and agent_name in filename:
                filepath = os.path.join(self.llm_requests_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    requests.append(json.load(f))
        
        return sorted(requests, key=lambda x: x['timestamp'])
    
    def export_session_report(self) -> str:
        """导出会话报告"""
        report_file = os.path.join(self.workspace_dir, "llm_session_report.md")
        
        # 获取所有请求
        all_requests = []
        for filename in os.listdir(self.llm_requests_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.llm_requests_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    all_requests.append(json.load(f))
        
        all_requests.sort(key=lambda x: x['timestamp'])
        
        # 生成报告
        report_content = f"""# LLM会话报告

## 会话信息
- 会话ID: {self.session_id}
- 开始时间: {self.session_stats['start_time']}
- 总请求数: {self.session_stats['total_requests']}
- 总Token数: {self.session_stats['total_tokens']}
- 总成本: ${self.session_stats['total_cost']:.4f}
- 使用的智能体: {', '.join(self.session_stats['agents_used'])}

## 请求详情

"""
        
        for i, request in enumerate(all_requests, 1):
            report_content += f"""### 请求 {i}: {request['agent_name']}
- 时间: {request['timestamp']}
- 模型: {request['model']}
- Token数: {request['tokens_used']}
- 成本: ${request['cost']:.4f}

**Prompt:**
```
{request['prompt'][:500]}{'...' if len(request['prompt']) > 500 else ''}
```

**Response:**
```
{request['response'][:500]}{'...' if len(request['response']) > 500 else ''}
```

---

"""
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return report_file
    
    def list_request_files(self) -> List[str]:
        """
        列出所有LLM请求日志文件
        
        Returns:
            List[str]: 日志文件路径列表
        """
        if not os.path.exists(self.llm_requests_dir):
            return []
        
        try:
            files = []
            for filename in os.listdir(self.llm_requests_dir):
                if filename.endswith('.json'):
                    file_path = os.path.join(self.llm_requests_dir, filename)
                    files.append(file_path)
            return sorted(files)
        except Exception as e:
            logger.error(f"LLMRequestLogger: 列出请求文件失败: {str(e)}")
            return []


# 全局日志记录器管理
_active_loggers: Dict[str, LLMRequestLogger] = {}

def init_llm_logger(session_id: str, workspace_root: str = None) -> LLMRequestLogger:
    """
    初始化指定会话的LLM请求日志记录器
    
    Args:
        session_id: 会话ID
        workspace_root: 工作空间根目录，如果为None则使用默认的sage_demo_workspace
        
    Returns:
        LLMRequestLogger: 日志记录器实例
    """
    _active_loggers[session_id] = LLMRequestLogger(session_id, workspace_root)
    return _active_loggers[session_id]

def get_llm_logger(session_id: str = None, workspace_root: str = None) -> Optional[LLMRequestLogger]:
    """
    获取指定会话的LLM日志记录器
    
    Args:
        session_id: 会话ID，如果为None则返回最后创建的记录器
        workspace_root: 工作空间根目录
        
    Returns:
        Optional[LLMRequestLogger]: 日志记录器实例或None
    """
    if session_id is None:
        # 返回最后创建的记录器
        if _active_loggers:
            return list(_active_loggers.values())[-1]
        return None
    
    # 如果记录器不存在，自动初始化
    if session_id not in _active_loggers:
        logger.debug(f"LLMRequestLogger: 自动初始化会话 {session_id} 的记录器")
        return init_llm_logger(session_id, workspace_root=workspace_root)
    
    return _active_loggers.get(session_id)

def log_llm_request(agent_name: str, prompt: str, response: str, session_id: str = None, **kwargs) -> Optional[str]:
    """
    便捷函数：记录LLM请求
    
    Args:
        agent_name: 智能体名称
        prompt: 请求prompt
        response: LLM响应
        session_id: 会话ID，如果为None则使用最后创建的记录器
        **kwargs: 其他参数
        
    Returns:
        Optional[str]: 日志文件路径或None
    """
    logger_instance = get_llm_logger(session_id)
    if logger_instance:
        return logger_instance.log_request(agent_name, prompt, response, **kwargs)
    return None

def cleanup_logger(session_id: str):
    """
    清理指定会话的日志记录器
    
    Args:
        session_id: 会话ID
    """
    if session_id in _active_loggers:
        logger_instance = _active_loggers[session_id]
        logger.info(f"LLMRequestLogger: 清理会话 {session_id} 的日志记录器，共记录了 {logger_instance.request_counter} 个请求")
        del _active_loggers[session_id]

def get_all_active_loggers() -> Dict[str, LLMRequestLogger]:
    """
    获取所有活跃的日志记录器
    
    Returns:
        Dict[str, LLMRequestLogger]: 会话ID到日志记录器的映射
    """
    return _active_loggers.copy() 