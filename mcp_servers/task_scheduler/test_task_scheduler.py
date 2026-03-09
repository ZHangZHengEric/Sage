"""
Task Scheduler 完整单元测试
测试覆盖:
1. 数据库模型 (db.py)
2. 任务ID编码解码
3. MCP工具函数
4. 调度逻辑
"""

import os
import sys
import json
import pytest
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp_servers.task_scheduler.db import TaskSchedulerDB, TaskStatus, TaskType
from mcp_servers.task_scheduler.task_scheduler_server import (
    _encode_task_id,
    _decode_task_id,
    _get_session_lock,
    _check_and_spawn_recurring_tasks,
    ONCE_TASK_PREFIX,
    RECURRING_TASK_PREFIX,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_db_path():
    """创建临时数据库文件"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # 清理
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def db(temp_db_path):
    """创建数据库实例"""
    return TaskSchedulerDB(Path(temp_db_path))


@pytest.fixture
def sample_once_task():
    """单次任务样本数据"""
    return {
        'name': '测试单次任务',
        'description': '这是一个测试任务',
        'agent_id': 'agent_001',
        'session_id': 'session_001',
        'execute_at': (datetime.now() + timedelta(hours=1)).isoformat()
    }


@pytest.fixture
def sample_recurring_task():
    """循环任务样本数据"""
    return {
        'name': '测试循环任务',
        'description': '这是一个循环测试任务',
        'agent_id': 'agent_001',
        'session_id': 'session_001',
        'cron_expression': '0 9 * * *'  # 每天9点
    }


# =============================================================================
# 测试任务ID编码解码
# =============================================================================

class TestTaskIdEncoding:
    """测试任务ID编码解码功能"""
    
    def test_encode_once_task_id(self):
        """测试单次任务ID编码"""
        task_id = 123
        encoded = _encode_task_id(task_id, is_recurring=False)
        assert encoded == f"{ONCE_TASK_PREFIX}123"
        assert encoded.startswith(ONCE_TASK_PREFIX)
    
    def test_encode_recurring_task_id(self):
        """测试循环任务ID编码"""
        task_id = 456
        encoded = _encode_task_id(task_id, is_recurring=True)
        assert encoded == f"{RECURRING_TASK_PREFIX}456"
        assert encoded.startswith(RECURRING_TASK_PREFIX)
    
    def test_decode_once_task_id(self):
        """测试单次任务ID解码"""
        encoded = f"{ONCE_TASK_PREFIX}123"
        task_id, is_recurring = _decode_task_id(encoded)
        assert task_id == 123
        assert is_recurring is False
    
    def test_decode_recurring_task_id(self):
        """测试循环任务ID解码"""
        encoded = f"{RECURRING_TASK_PREFIX}456"
        task_id, is_recurring = _decode_task_id(encoded)
        assert task_id == 456
        assert is_recurring is True
    
    def test_decode_task_id_without_prefix(self):
        """测试无前缀任务ID解码（向后兼容）"""
        encoded = "789"
        task_id, is_recurring = _decode_task_id(encoded)
        assert task_id == 789
        assert is_recurring is False
    
    def test_encode_decode_roundtrip(self):
        """测试编码解码往返"""
        original_id = 999
        # 单次任务
        encoded = _encode_task_id(original_id, is_recurring=False)
        decoded_id, is_recurring = _decode_task_id(encoded)
        assert decoded_id == original_id
        assert is_recurring is False
        
        # 循环任务
        encoded = _encode_task_id(original_id, is_recurring=True)
        decoded_id, is_recurring = _decode_task_id(encoded)
        assert decoded_id == original_id
        assert is_recurring is True


# =============================================================================
# 测试数据库模型 - 单次任务
# =============================================================================

class TestOnceTaskDB:
    """测试单次任务数据库操作"""
    
    def test_add_once_task(self, db, sample_once_task):
        """测试添加单次任务"""
        task_id = db.add_task(**sample_once_task)
        assert task_id is not None
        assert isinstance(task_id, int)
        assert task_id > 0
    
    def test_get_task(self, db, sample_once_task):
        """测试获取单次任务"""
        task_id = db.add_task(**sample_once_task)
        task = db.get_task(task_id)
        
        assert task is not None
        assert task['name'] == sample_once_task['name']
        assert task['description'] == sample_once_task['description']
        assert task['agent_id'] == sample_once_task['agent_id']
        assert task['session_id'] == sample_once_task['session_id']
        assert task['status'] == 'pending'
        assert task['recurring_task_id'] is None
    
    def test_list_tasks(self, db, sample_once_task):
        """测试列出单次任务"""
        # 添加多个任务
        db.add_task(**sample_once_task)
        db.add_task(**{**sample_once_task, 'name': '第二个任务'})
        
        tasks = db.list_tasks()
        assert len(tasks) == 2
        assert tasks[0]['name'] == sample_once_task['name']
        assert tasks[1]['name'] == '第二个任务'
    
    def test_list_tasks_with_filter(self, db, sample_once_task):
        """测试带过滤条件的任务列表"""
        task_id = db.add_task(**sample_once_task)
        
        # 按 agent_id 过滤
        tasks = db.list_tasks(agent_id='agent_001')
        assert len(tasks) == 1
        
        tasks = db.list_tasks(agent_id='non_existent')
        assert len(tasks) == 0
        
        # 按 status 过滤
        tasks = db.list_tasks(status='pending')
        assert len(tasks) == 1
        
        tasks = db.list_tasks(status='completed')
        assert len(tasks) == 0
    
    def test_complete_task(self, db, sample_once_task):
        """测试完成任务"""
        task_id = db.add_task(**sample_once_task)
        
        # 完成任务
        result = db.complete_task(task_id)
        assert result is True
        
        # 验证状态
        task = db.get_task(task_id)
        assert task['status'] == 'completed'
        assert task['completed_at'] is not None
    
    def test_delete_task(self, db, sample_once_task):
        """测试删除任务"""
        task_id = db.add_task(**sample_once_task)
        
        # 删除任务
        result = db.delete_task(task_id)
        assert result is True
        
        # 验证已删除
        task = db.get_task(task_id)
        assert task is None
    
    def test_claim_task(self, db, sample_once_task):
        """测试认领任务"""
        task_id = db.add_task(**sample_once_task)
        
        # 认领任务
        result = db.claim_task(task_id)
        assert result is True
        
        # 验证状态
        task = db.get_task(task_id)
        assert task['status'] == 'processing'
        
        # 再次认领应该失败
        result = db.claim_task(task_id)
        assert result is False
    
    def test_update_task_status(self, db, sample_once_task):
        """测试更新任务状态"""
        task_id = db.add_task(**sample_once_task)
        
        # 更新状态
        db.update_task_status(task_id, 'failed', error_message='Test error')
        
        # 验证
        task = db.get_task(task_id)
        assert task['status'] == 'failed'
        assert task['retry_count'] == 1
    
    def test_get_pending_tasks(self, db, sample_once_task):
        """测试获取待处理任务"""
        # 添加一个即将执行的任务
        sample_once_task['execute_at'] = datetime.now().isoformat()
        db.add_task(**sample_once_task)
        
        # 添加一个未来的任务
        sample_once_task['execute_at'] = (datetime.now() + timedelta(days=1)).isoformat()
        sample_once_task['name'] = '未来任务'
        db.add_task(**sample_once_task)
        
        pending = db.get_pending_tasks()
        assert len(pending) == 1
        assert pending[0]['name'] == '测试单次任务'
    
    def test_get_pending_tasks_by_session(self, db, sample_once_task):
        """测试按会话获取待处理任务"""
        db.add_task(**sample_once_task)
        db.add_task(**{**sample_once_task, 'session_id': 'session_002'})
        
        pending = db.get_pending_tasks_by_session('session_001')
        assert len(pending) == 1
        assert pending[0]['session_id'] == 'session_001'
    
    def test_task_history(self, db, sample_once_task):
        """测试任务历史记录"""
        task_id = db.add_task(**sample_once_task)
        
        # 添加历史记录
        db.add_task_history(task_id, 'completed', response='Task completed successfully')
        db.add_task_history(task_id, 'completed', response='Another execution')
        
        # 获取历史
        history = db.get_task_history(task_id)
        assert len(history) == 2
        assert history[0]['status'] == 'completed'


# =============================================================================
# 测试数据库模型 - 循环任务
# =============================================================================

class TestRecurringTaskDB:
    """测试循环任务数据库操作"""
    
    def test_add_recurring_task(self, db, sample_recurring_task):
        """测试添加循环任务"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        assert task_id is not None
        assert isinstance(task_id, int)
        assert task_id > 0
    
    def test_get_recurring_task(self, db, sample_recurring_task):
        """测试获取循环任务"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        task = db.get_recurring_task(task_id)
        
        assert task is not None
        assert task['name'] == sample_recurring_task['name']
        assert task['cron_expression'] == sample_recurring_task['cron_expression']
        assert task['enabled'] == 1
    
    def test_list_recurring_tasks(self, db, sample_recurring_task):
        """测试列出循环任务"""
        db.add_recurring_task(**sample_recurring_task)
        db.add_recurring_task(**{**sample_recurring_task, 'name': '第二个循环任务'})
        
        tasks = db.list_recurring_tasks()
        assert len(tasks) == 2
    
    def test_list_recurring_tasks_enabled_only(self, db, sample_recurring_task):
        """测试只列出启用的循环任务"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        db.enable_recurring_task(task_id, enabled=False)
        
        tasks = db.list_recurring_tasks(enabled_only=True)
        assert len(tasks) == 0
        
        tasks = db.list_recurring_tasks(enabled_only=False)
        assert len(tasks) == 1
    
    def test_enable_disable_recurring_task(self, db, sample_recurring_task):
        """测试启用/禁用循环任务"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        
        # 禁用
        result = db.enable_recurring_task(task_id, enabled=False)
        assert result is True
        
        task = db.get_recurring_task(task_id)
        assert task['enabled'] == 0
        
        # 启用
        db.enable_recurring_task(task_id, enabled=True)
        task = db.get_recurring_task(task_id)
        assert task['enabled'] == 1
    
    def test_update_recurring_task_last_executed(self, db, sample_recurring_task):
        """测试更新循环任务最后执行时间"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        
        db.update_recurring_task_last_executed(task_id)
        
        task = db.get_recurring_task(task_id)
        assert task['last_executed_at'] is not None
    
    def test_delete_recurring_task(self, db, sample_recurring_task):
        """测试删除循环任务"""
        task_id = db.add_recurring_task(**sample_recurring_task)
        
        result = db.delete_recurring_task(task_id)
        assert result is True
        
        task = db.get_recurring_task(task_id)
        assert task is None
    
    def test_delete_recurring_task_clears_pending(self, db, sample_recurring_task, sample_once_task):
        """测试删除循环任务同时清除关联的待处理任务"""
        recurring_id = db.add_recurring_task(**sample_recurring_task)
        
        # 创建一个关联的待处理任务
        once_id = db.add_task(**{**sample_once_task, 'recurring_task_id': recurring_id})
        
        # 删除循环任务
        db.delete_recurring_task(recurring_id)
        
        # 验证待处理任务也被删除
        task = db.get_task(once_id)
        assert task is None


# =============================================================================
# 测试会话锁
# =============================================================================

class TestSessionLock:
    """测试会话锁功能"""
    
    def test_get_session_lock_creates_new_lock(self):
        """测试获取新会话锁"""
        lock1 = _get_session_lock('session_001')
        assert isinstance(lock1, threading.Lock)
        
        # 再次获取应该是同一个锁
        lock2 = _get_session_lock('session_001')
        assert lock1 is lock2
    
    def test_get_session_lock_different_sessions(self):
        """测试不同会话有不同的锁"""
        lock1 = _get_session_lock('session_001')
        lock2 = _get_session_lock('session_002')
        
        assert lock1 is not lock2


# =============================================================================
# 测试调度逻辑
# =============================================================================

class TestSchedulerLogic:
    """测试调度逻辑"""
    
    @patch('mcp_servers.task_scheduler.task_scheduler_server.db')
    @patch('mcp_servers.task_scheduler.task_scheduler_server.datetime')
    def test_check_and_spawn_recurring_tasks(self, mock_datetime, mock_db):
        """测试检查并生成循环任务实例"""
        from datetime import datetime as dt
        
        # 设置当前时间
        now = dt(2026, 3, 1, 9, 0, 0)
        mock_datetime.now.return_value = now
        
        # 模拟循环任务
        mock_db.list_recurring_tasks.return_value = [
            {
                'id': 1,
                'name': '每日任务',
                'description': '每天执行',
                'agent_id': 'agent_001',
                'session_id': 'session_001',
                'cron_expression': '0 9 * * *',
                'last_executed_at': None,
                'enabled': 1
            }
        ]
        
        # 模拟没有待处理任务
        mock_db.list_tasks.return_value = []
        
        # 执行检查
        _check_and_spawn_recurring_tasks()
        
        # 验证是否创建了新任务
        mock_db.add_task.assert_called_once()
        call_args = mock_db.add_task.call_args
        assert call_args.kwargs['name'] == '每日任务'
        assert call_args.kwargs['recurring_task_id'] == 1
        
        # 验证是否更新了最后执行时间
        mock_db.update_recurring_task_last_executed.assert_called_once_with(1)
    
    @patch('mcp_servers.task_scheduler.task_scheduler_server.db')
    def test_check_recurring_tasks_no_spawn_if_pending_exists(self, mock_db):
        """测试有待处理实例时不生成新任务"""
        mock_db.list_recurring_tasks.return_value = [
            {
                'id': 1,
                'name': '每日任务',
                'cron_expression': '0 9 * * *',
                'last_executed_at': None,
                'enabled': 1,
                'session_id': 'session_001'
            }
        ]
        
        # 模拟已存在待处理任务
        mock_db.list_tasks.return_value = [
            {'recurring_task_id': 1, 'status': 'pending'}
        ]
        
        _check_and_spawn_recurring_tasks()
        
        # 验证没有创建新任务
        mock_db.add_task.assert_not_called()


# =============================================================================
# 集成测试
# =============================================================================

class TestIntegration:
    """集成测试"""
    
    def test_full_workflow_once_task(self, db, sample_once_task):
        """测试单次任务完整工作流"""
        # 1. 添加任务
        task_id = db.add_task(**sample_once_task)
        assert task_id > 0
        
        # 2. 获取任务
        task = db.get_task(task_id)
        assert task['status'] == 'pending'
        
        # 3. 认领任务
        claimed = db.claim_task(task_id)
        assert claimed is True
        
        task = db.get_task(task_id)
        assert task['status'] == 'processing'
        
        # 4. 添加历史记录
        db.add_task_history(task_id, 'completed', response='Success')
        
        # 5. 完成任务
        db.complete_task(task_id)
        
        task = db.get_task(task_id)
        assert task['status'] == 'completed'
        
        # 6. 验证历史
        history = db.get_task_history(task_id)
        assert len(history) == 1
        assert history[0]['status'] == 'completed'
    
    def test_full_workflow_recurring_task(self, db, sample_recurring_task, sample_once_task):
        """测试循环任务完整工作流"""
        # 1. 添加循环任务
        recurring_id = db.add_recurring_task(**sample_recurring_task)
        assert recurring_id > 0
        
        # 2. 从循环任务生成单次任务
        once_id = db.add_task(
            **sample_once_task,
            recurring_task_id=recurring_id
        )
        
        # 3. 验证关联
        task = db.get_task(once_id)
        assert task['recurring_task_id'] == recurring_id
        
        # 4. 更新循环任务执行时间
        db.update_recurring_task_last_executed(recurring_id)
        
        recurring = db.get_recurring_task(recurring_id)
        assert recurring['last_executed_at'] is not None
        
        # 5. 禁用循环任务
        db.enable_recurring_task(recurring_id, enabled=False)
        
        recurring = db.get_recurring_task(recurring_id)
        assert recurring['enabled'] == 0
    
    def test_concurrent_session_tasks(self, db, sample_once_task):
        """测试同一会话的并发任务处理"""
        # 添加多个同一会话的任务
        task_ids = []
        for i in range(3):
            task_id = db.add_task(**{
                **sample_once_task,
                'name': f'任务{i+1}',
                'execute_at': datetime.now().isoformat()
            })
            task_ids.append(task_id)
        
        # 验证可以获取所有待处理任务
        pending = db.get_pending_tasks_by_session(sample_once_task['session_id'])
        assert len(pending) == 3
        
        # 验证任务按创建时间排序
        assert pending[0]['name'] == '任务1'
        assert pending[1]['name'] == '任务2'
        assert pending[2]['name'] == '任务3'


# =============================================================================
# 测试错误处理
# =============================================================================

class TestErrorHandling:
    """测试错误处理"""
    
    def test_get_nonexistent_task(self, db):
        """测试获取不存在的任务"""
        task = db.get_task(99999)
        assert task is None
    
    def test_delete_nonexistent_task(self, db):
        """测试删除不存在的任务"""
        result = db.delete_task(99999)
        assert result is False
    
    def test_complete_nonexistent_task(self, db):
        """测试完成不存在的任务"""
        result = db.complete_task(99999)
        assert result is False
    
    def test_claim_nonexistent_task(self, db):
        """测试认领不存在的任务"""
        result = db.claim_task(99999)
        assert result is False
    
    def test_decode_invalid_task_id(self):
        """测试解码无效的任务ID"""
        with pytest.raises(ValueError):
            _decode_task_id("invalid_id")


# =============================================================================
# 性能测试
# =============================================================================

class TestPerformance:
    """性能测试"""
    
    def test_large_number_of_tasks(self, db, sample_once_task):
        """测试大量任务"""
        # 添加100个任务
        for i in range(100):
            db.add_task(**{
                **sample_once_task,
                'name': f'批量任务{i}',
                'session_id': f'session_{i % 10}'  # 10个不同会话
            })
        
        # 验证可以快速列出
        import time
        start = time.time()
        tasks = db.list_tasks(limit=100)
        elapsed = time.time() - start
        
        assert len(tasks) == 100
        assert elapsed < 1.0  # 应该在1秒内完成
    
    def test_large_number_of_recurring_tasks(self, db, sample_recurring_task):
        """测试大量循环任务"""
        for i in range(50):
            db.add_recurring_task(**{
                **sample_recurring_task,
                'name': f'循环任务{i}'
            })
        
        tasks = db.list_recurring_tasks()
        assert len(tasks) == 50


# =============================================================================
# 主函数
# =============================================================================

if __name__ == '__main__':
    # 运行测试
    pytest.main([__file__, '-v', '--tb=short'])
