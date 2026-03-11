#!/usr/bin/env python3
"""
Task Scheduler 独立测试

Mock 后端接口和数据库，只测试调度循环逻辑
"""

import os
import sys
import time
import json
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, MagicMock, patch

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TestScheduler")


# Mock 数据库
class MockDB:
    """Mock 数据库"""
    
    def __init__(self):
        self.tasks = []
        self.recurring_tasks = []
        self.task_history = []
        self.task_counter = 0
        self.recurring_counter = 0
        logger.info("[MOCK DB] 数据库初始化完成")
    
    def add_task(self, name: str, description: str, agent_id: str, execute_at: str, recurring_task_id: Optional[int] = None) -> int:
        """添加一次性任务"""
        self.task_counter += 1
        task = {
            'id': self.task_counter,
            'name': name,
            'description': description,
            'agent_id': agent_id,
            'execute_at': execute_at,
            'status': 'pending',
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'recurring_task_id': recurring_task_id,
            'retry_count': 0,
            'max_retries': 3
        }
        self.tasks.append(task)
        logger.info(f"[MOCK DB] 添加任务: {name} (ID: {self.task_counter})")
        return self.task_counter
    
    def add_recurring_task(self, name: str, description: str, agent_id: str, cron_expression: str) -> int:
        """添加循环任务"""
        self.recurring_counter += 1
        task = {
            'id': self.recurring_counter,
            'name': name,
            'description': description,
            'agent_id': agent_id,
            'cron_expression': cron_expression,
            'enabled': 1,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_executed_at': None
        }
        self.recurring_tasks.append(task)
        logger.info(f"[MOCK DB] 添加循环任务: {name} (ID: {self.recurring_counter}, Cron: {cron_expression})")
        return self.recurring_counter
    
    def list_recurring_tasks(self, enabled_only: bool = True) -> List[Dict]:
        """获取循环任务列表"""
        if enabled_only:
            return [t for t in self.recurring_tasks if t['enabled']]
        return self.recurring_tasks
    
    def list_tasks(self, agent_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """获取任务列表"""
        result = self.tasks
        if agent_id:
            result = [t for t in result if t['agent_id'] == agent_id]
        if status:
            result = [t for t in result if t['status'] == status]
        return result[:limit]
    
    def get_pending_tasks(self) -> List[Dict]:
        """获取待处理任务"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pending = [t for t in self.tasks 
                   if t['status'] == 'pending' and t['execute_at'] <= now]
        logger.debug(f"[MOCK DB] 获取待处理任务: {len(pending)} 个")
        return pending
    
    def claim_task(self, task_id: int) -> bool:
        """认领任务"""
        for task in self.tasks:
            if task['id'] == task_id and task['status'] == 'pending':
                task['status'] = 'processing'
                logger.info(f"[MOCK DB] 任务 {task_id} 已被认领")
                return True
        return False
    
    def complete_task(self, task_id: int):
        """完成任务"""
        for task in self.tasks:
            if task['id'] == task_id:
                task['status'] = 'completed'
                logger.info(f"[MOCK DB] 任务 {task_id} 已完成")
                break
    
    def update_task_status(self, task_id: int, status: str, error_message: Optional[str] = None):
        """更新任务状态"""
        for task in self.tasks:
            if task['id'] == task_id:
                task['status'] = status
                if error_message:
                    task['error_message'] = error_message
                logger.info(f"[MOCK DB] 任务 {task_id} 状态更新为: {status}")
                break
    
    def update_recurring_task_last_executed(self, task_id: int, executed_at: str):
        """更新循环任务最后执行时间"""
        for task in self.recurring_tasks:
            if task['id'] == task_id:
                task['last_executed_at'] = executed_at
                logger.debug(f"[MOCK DB] 循环任务 {task_id} 最后执行时间更新为: {executed_at}")
                break
    
    def add_task_history(self, task_id: int, status: str, response: Optional[str] = None, error_message: Optional[str] = None):
        """添加任务历史"""
        self.task_history.append({
            'task_id': task_id,
            'status': status,
            'response': response,
            'error_message': error_message,
            'executed_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })


# Mock HTTP 响应
class MockResponse:
    """Mock HTTP 响应"""
    def __init__(self):
        self.status_code = 200
        self._lines = [
            b'data: {"role": "assistant", "content": "Task executed successfully"}'
        ]
    
    def iter_lines(self):
        return iter(self._lines)
    
    def raise_for_status(self):
        pass


class MockHTTPClient:
    """Mock HTTP 客户端"""
    
    def __init__(self, *args, **kwargs):
        self.request_count = 0
        logger.info("[MOCK HTTP] HTTP 客户端初始化完成")
    
    def stream(self, method: str, url: str, **kwargs):
        """Mock stream 请求"""
        self.request_count += 1
        logger.info(f"[MOCK HTTP] {method} {url}")
        logger.debug(f"[MOCK HTTP] 请求参数: {kwargs}")
        
        mock_response = MockResponse()
        
        class ContextManager:
            def __enter__(inner_self):
                return mock_response
            def __exit__(inner_self, *args):
                pass
        
        return ContextManager()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass


def test_scheduler():
    """测试调度循环"""
    print("\n" + "=" * 60)
    print("Task Scheduler 独立测试")
    print("=" * 60)
    
    # 使用 patch 来 mock httpx
    with patch('mcp_servers.task_scheduler.task_scheduler_server.httpx') as mock_httpx:
        mock_httpx.Client = MockHTTPClient
        
        # 现在导入 task_scheduler_server 的函数
        from mcp_servers.task_scheduler.task_scheduler_server import (
            _check_and_spawn_recurring_tasks,
            _execute_task,
            _execute_task_sync,
        )
        import mcp_servers.task_scheduler.task_scheduler_server as server_module
        
        # 创建 mock 数据库
        mock_db = MockDB()
        server_module.db = mock_db
        
        print("\n[TEST] 步骤 1: 创建循环任务")
        # 创建一个每分钟执行的循环任务
        recurring_id = mock_db.add_recurring_task(
            name="每分钟测试任务",
            description="这是一个测试循环任务",
            agent_id="test_agent",
            cron_expression="* * * * *"  # 每分钟
        )
        
        # 设置 last_executed_at 为很久以前（确保会触发）
        past_time = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        mock_db.update_recurring_task_last_executed(recurring_id, past_time)
        
        print(f"[TEST] 循环任务创建完成，ID: {recurring_id}")
        print(f"[TEST] 设置最后执行时间为: {past_time}")
        
        print("\n[TEST] 步骤 2: 手动触发循环任务检查")
        # 手动调用一次检查函数
        _check_and_spawn_recurring_tasks()
        
        # 检查是否生成了新的任务
        tasks = mock_db.list_tasks()
        print(f"[TEST] 当前任务数量: {len(tasks)}")
        for task in tasks:
            print(f"  - {task['name']} (ID: {task['id']}, Status: {task['status']})")
        
        print("\n[TEST] 步骤 3: 检查待处理任务")
        pending = mock_db.get_pending_tasks()
        print(f"[TEST] 待处理任务数量: {len(pending)}")
        
        if pending:
            print("\n[TEST] 步骤 4: 执行任务")
            for task in pending:
                print(f"\n[TEST] 执行任务: {task['name']} (ID: {task['id']})")
                _execute_task(task)
                time.sleep(1)  # 等待任务执行
        
        print("\n[TEST] 步骤 5: 检查结果")
        all_tasks = mock_db.list_tasks()
        print(f"[TEST] 所有任务状态:")
        for task in all_tasks:
            print(f"  - {task['name']}: {task['status']}")
        
        print(f"\n[TEST] HTTP 请求次数: {mock_httpx.Client().request_count}")
        
        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)
        
        return True


def test_scheduler_loop():
    """测试调度循环（运行几个周期）"""
    print("\n" + "=" * 60)
    print("Task Scheduler 循环测试（运行 3 个周期）")
    print("=" * 60)
    
    # 使用 patch 来 mock httpx
    with patch('mcp_servers.task_scheduler.task_scheduler_server.httpx') as mock_httpx:
        mock_httpx.Client = MockHTTPClient
        
        # 现在导入 task_scheduler_server 的函数
        from mcp_servers.task_scheduler.task_scheduler_server import (
            _check_and_spawn_recurring_tasks,
            _execute_task,
        )
        import mcp_servers.task_scheduler.task_scheduler_server as server_module
        
        # 创建 mock 数据库
        mock_db = MockDB()
        server_module.db = mock_db
        
        # 创建一个每分钟执行的循环任务
        recurring_id = mock_db.add_recurring_task(
            name="循环测试任务",
            description="测试调度循环",
            agent_id="loop_test_agent",
            cron_expression="* * * * *"
        )
        mock_db.update_recurring_task_last_executed(
            recurring_id, 
            (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        )
        
        print(f"[LOOP TEST] 创建循环任务: {recurring_id}")
        
        # 手动运行几个调度周期
        for i in range(3):
            print(f"\n[LOOP TEST] ===== 周期 {i + 1} =====")
            
            # 检查循环任务
            _check_and_spawn_recurring_tasks()
            
            # 获取待处理任务
            pending = mock_db.get_pending_tasks()
            print(f"[LOOP TEST] 待处理任务: {len(pending)}")
            
            # 执行任务
            for task in pending:
                print(f"[LOOP TEST] 执行任务: {task['name']}")
                _execute_task(task)
            
            # 等待一下
            if i < 2:
                print("[LOOP TEST] 等待 2 秒...")
                time.sleep(2)
        
        print("\n[LOOP TEST] 最终状态:")
        all_tasks = mock_db.list_tasks()
        print(f"  总任务数: {len(all_tasks)}")
        for task in all_tasks:
            print(f"  - {task['name']}: {task['status']}")
        
        print(f"\n[LOOP TEST] HTTP 请求次数: {mock_httpx.Client().request_count}")
        
        print("\n" + "=" * 60)
        print("循环测试完成！")
        print("=" * 60)
        
        return True


if __name__ == "__main__":
    # 运行单次测试
    test_scheduler()
    
    # 运行循环测试
    test_scheduler_loop()
    
    print("\n✓ 所有测试完成！")
