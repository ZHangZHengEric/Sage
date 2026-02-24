"""
单元测试 for Task Scheduler MCP Server
"""
import os
import sys
import time
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import TaskSchedulerDB, TaskStatus, TaskType


class TestTaskSchedulerDB:
    """Test TaskSchedulerDB class"""

    def setup_method(self):
        """Setup test database before each test"""
        self.test_dir = Path("./test_data/task_scheduler")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.test_dir / "test_tasks.db"
        self.db = TaskSchedulerDB(self.db_path)

    def teardown_method(self):
        """Cleanup after each test"""
        # Close any open connections
        import gc
        gc.collect()
        # Remove test directory
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir.parent)

    def test_add_task(self):
        """Test adding a task"""
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_id = self.db.add_task(
            name="Test Task",
            description="This is a test task",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=execute_at,
            task_type="once"
        )

        assert task_id > 0, "Task ID should be positive integer"

        # Verify task was added
        task = self.db.get_task(task_id)
        assert task is not None, "Task should exist"
        assert task['name'] == "Test Task", "Task name should match"
        assert task['agent_id'] == "test_agent", "Agent ID should match"
        assert task['status'] == TaskStatus.PENDING, "Status should be pending"

    def test_list_tasks(self):
        """Test listing tasks"""
        # Add multiple tasks
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_ids = []
        for i in range(3):
            task_id = self.db.add_task(
                name=f"Test Task {i}",
                description=f"Description {i}",
                agent_id="test_agent",
                session_id="test_session",
                execute_at=execute_at,
                task_type="once"
            )
            task_ids.append(task_id)

        # List all tasks
        tasks = self.db.list_tasks()
        assert len(tasks) == 3, "Should return 3 tasks"

        # List tasks by agent_id
        tasks = self.db.list_tasks(agent_id="test_agent")
        assert len(tasks) == 3, "Should return 3 tasks for test_agent"

        # List tasks by non-existent agent
        tasks = self.db.list_tasks(agent_id="non_existent")
        assert len(tasks) == 0, "Should return 0 tasks for non-existent agent"

    def test_complete_task(self):
        """Test completing a task"""
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_id = self.db.add_task(
            name="Test Task",
            description="This is a test task",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=execute_at,
            task_type="once"
        )

        # Complete the task
        result = self.db.complete_task(task_id)
        assert result is True, "Complete task should return True"

        # Verify task status
        task = self.db.get_task(task_id)
        assert task['status'] == TaskStatus.COMPLETED, "Status should be completed"
        assert task['completed_at'] is not None, "Completed at should be set"

    def test_delete_task(self):
        """Test deleting a task"""
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_id = self.db.add_task(
            name="Test Task",
            description="This is a test task",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=execute_at,
            task_type="once"
        )

        # Delete the task
        result = self.db.delete_task(task_id)
        assert result is True, "Delete task should return True"

        # Verify task is deleted
        task = self.db.get_task(task_id)
        assert task is None, "Task should not exist after deletion"

    def test_claim_task(self):
        """Test claiming a task"""
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_id = self.db.add_task(
            name="Test Task",
            description="This is a test task",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=execute_at,
            task_type="once"
        )

        # Claim the task
        result = self.db.claim_task(task_id)
        assert result is True, "Claim task should return True"

        # Verify task status
        task = self.db.get_task(task_id)
        assert task['status'] == TaskStatus.PROCESSING, "Status should be processing"

        # Try to claim again (should fail)
        result = self.db.claim_task(task_id)
        assert result is False, "Claiming already processing task should return False"

    def test_get_pending_tasks(self):
        """Test getting pending tasks"""
        now = datetime.now()

        # Add a pending task (execute_at in the past)
        task_id_1 = self.db.add_task(
            name="Pending Task 1",
            description="Should be pending",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=(now - timedelta(hours=1)).isoformat(),
            task_type="once"
        )

        # Add a future task (should not be pending)
        self.db.add_task(
            name="Future Task",
            description="Should not be pending yet",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=(now + timedelta(hours=1)).isoformat(),
            task_type="once"
        )

        # Get pending tasks
        pending = self.db.get_pending_tasks()
        assert len(pending) == 1, "Should return 1 pending task"
        assert pending[0]['id'] == task_id_1, "Should be the past task"

    def test_reschedule_recurring_task(self):
        """Test rescheduling recurring tasks"""
        now = datetime.now()

        # Add a daily task
        task_id = self.db.add_task(
            name="Daily Task",
            description="Recurring daily",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=now.isoformat(),
            task_type="daily"
        )

        # Complete and reschedule
        result = self.db.reschedule_recurring_task(task_id, TaskType.DAILY)
        assert result is True, "Reschedule should return True"

        # Verify task was rescheduled
        task = self.db.get_task(task_id)
        new_execute_at = datetime.fromisoformat(task['execute_at'])
        assert new_execute_at > now, "New execute_at should be in the future"
        assert task['status'] == TaskStatus.PENDING, "Status should be reset to pending"

    def test_task_history(self):
        """Test task history tracking"""
        execute_at = (datetime.now() + timedelta(hours=1)).isoformat()
        task_id = self.db.add_task(
            name="Test Task",
            description="This is a test task",
            agent_id="test_agent",
            session_id="test_session",
            execute_at=execute_at,
            task_type="once"
        )

        # Add history entries
        self.db.add_task_history(task_id, 'started')
        time.sleep(0.1)  # Small delay to ensure different timestamps
        self.db.add_task_history(task_id, 'completed', response='Task completed successfully')

        # Verify history
        with self.db._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_history WHERE task_id = ? ORDER BY executed_at DESC, id DESC",
                (task_id,)
            )
            history = [dict(row) for row in cursor.fetchall()]

        assert len(history) == 2, "Should have 2 history entries"
        assert history[0]['status'] == 'completed', "Latest status should be completed"
        assert history[0]['response'] == 'Task completed successfully', "Response should match"


def _get_api_base_url() -> str:
    """Copy of the function from task_scheduler_server for testing"""
    port = os.getenv("SAGE_PORT", "8001")
    return f"http://localhost:{port}"


class TestTaskSchedulerServer:
    """Test Task Scheduler Server functionality"""

    def setup_method(self):
        """Setup test environment"""
        self.test_dir = Path("./test_data/task_scheduler")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        """Cleanup after each test"""
        import gc
        gc.collect()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir.parent)

    def test_api_base_url(self):
        """Test API base URL generation"""
        # Test with default port
        os.environ.pop('SAGE_PORT', None)  # Remove if exists
        url = _get_api_base_url()
        assert url == "http://localhost:8001", f"Expected http://localhost:8001, got {url}"

        # Test with custom port
        os.environ['SAGE_PORT'] = '9000'
        url = _get_api_base_url()
        assert url == "http://localhost:9000", f"Expected http://localhost:9000, got {url}"

        # Cleanup
        os.environ.pop('SAGE_PORT', None)


def run_tests():
    """Run all tests"""
    import traceback

    test_classes = [
        TestTaskSchedulerDB,
        TestTaskSchedulerServer
    ]

    total_tests = 0
    passed_tests = 0
    failed_tests = []

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Running {test_class.__name__}")
        print('='*60)

        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith('test_')]

        for method_name in methods:
            total_tests += 1
            print(f"\n  Running {method_name}...", end=' ')

            try:
                instance.setup_method()
                method = getattr(instance, method_name)
                method()
                instance.teardown_method()
                print("✓ PASSED")
                passed_tests += 1
            except Exception as e:
                print("✗ FAILED")
                print(f"    Error: {str(e)}")
                print("    Traceback:")
                for line in traceback.format_exc().split('\n')[-6:-1]:
                    print(f"      {line}")
                failed_tests.append((test_class.__name__, method_name, str(e)))
                try:
                    instance.teardown_method()
                except Exception:
                    pass

    print(f"\n{'='*60}")
    print(f"Test Results: {passed_tests}/{total_tests} passed")
    print('='*60)

    if failed_tests:
        print("\nFailed Tests:")
        for class_name, method_name, error in failed_tests:
            print(f"  - {class_name}.{method_name}: {error}")
        return False
    else:
        print("\nAll tests passed! ✓")
        return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
