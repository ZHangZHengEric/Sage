
import sys
import os
import shutil
import json
import logging
import asyncio
from datetime import timezone
from unittest.mock import MagicMock

# --- MOCKING DEPENDENCIES START ---
# We mock these BEFORE importing any project modules

# Mock pydantic
class MockBaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
    
    def dict(self):
        return self.__dict__
    
    def model_dump(self):
        return self.__dict__

    @classmethod
    def parse_obj(cls, obj):
        return cls(**obj)

mock_pydantic = MagicMock()
mock_pydantic.BaseModel = MockBaseModel
mock_pydantic.Field = MagicMock(return_value=None)
sys.modules["pydantic"] = mock_pydantic

# Mock other missing libs
sys.modules["rank_bm25"] = MagicMock()
sys.modules["docstring_parser"] = MagicMock()
sys.modules["numpy"] = MagicMock()

# Mock pytz
mock_pytz = MagicMock()
mock_pytz.utc = timezone.utc
mock_pytz.timezone = MagicMock(return_value=timezone.utc) # Return valid tzinfo
sys.modules["pytz"] = mock_pytz

# Mock litellm if needed
sys.modules["litellm"] = MagicMock()
sys.modules["tiktoken"] = MagicMock()

# Mock internal modules that SessionContext imports in __init__
sys.modules["sagents.context.workflows"] = MagicMock()
sys.modules["sagents.context.session_memory.session_memory_manager"] = MagicMock()

# Mock TaskManager
class MockTaskManager:
    def __init__(self, **kwargs):
        self.tasks = []
    
    def to_dict(self):
        return [t for t in self.tasks]

mock_task_manager_mod = MagicMock()
mock_task_manager_mod.TaskManager = MockTaskManager
sys.modules["sagents.context.tasks.task_manager"] = mock_task_manager_mod

# Mock MessageManager since it might have heavy imports
# We need to make sure message_manager.messages is a list
class MockMessageManager:
    def __init__(self, **kwargs):
        self.messages = []
        self.context_budget_manager = MagicMock()
        # Mock budget attributes to avoid attribute errors during copy
        self.context_budget_manager.max_model_len = 1000
        self.context_budget_manager.history_ratio = 0.5
        self.context_budget_manager.active_ratio = 0.2
        self.context_budget_manager.max_new_message_ratio = 0.3
        self.context_budget_manager.recent_turns = 10

mock_msg_manager_mod = MagicMock()
mock_msg_manager_mod.MessageManager = MockMessageManager
sys.modules["sagents.context.messages.message_manager"] = mock_msg_manager_mod

# Mock schema if needed
mock_schema = MagicMock()
mock_schema.Document = MagicMock
mock_schema.Chunk = MagicMock
# sys.modules["sagents.retrieve_engine.schema"] = mock_schema 

# --- MOCKING DEPENDENCIES END ---

# Ensure project root is in path
sys.path.append("/Users/zhangzheng/zavixai/Sage")

from sagents.context.session_context import SessionContext, get_session_context

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("verify_sub_session")

async def test_sub_session_logging():
    print("--- Starting Sub-Session Logging Test ---")
    
    # 1. Setup paths
    base_dir = "/Users/zhangzheng/zavixai/Sage/app/agent_workspace"
    test_session_id = "test_parent_session_123"
    test_sub_session_id = f"{test_session_id}_1_sub_agent"
    
    # Clean up previous test
    parent_dir = os.path.join(base_dir, test_session_id)
    if os.path.exists(parent_dir):
        shutil.rmtree(parent_dir)
        
    print(f"Created parent session dir: {parent_dir}")
    
    # 2. Create Parent SessionContext
    parent_ctx = SessionContext(
        session_id=test_session_id,
        workspace_root=base_dir
    )
    # Initialize workspace (SessionContext init does this but good to double check)
    if not os.path.exists(parent_ctx.session_workspace):
        os.makedirs(parent_ctx.session_workspace)
        
    print(f"Parent Session Workspace: {parent_ctx.session_workspace}")
    
    # 3. Create Sub-Session Context
    # Simulate what FibreSubAgent does:
    # self.sub_session_context = SessionContext(
    #     session_id=self.sub_session_id,
    #     workspace_root=self.parent_context.session_workspace
    # )
    
    # Note: FibreSubAgent passes parent's session_workspace as workspace_root.
    # So sub-session workspace will be parent_workspace/sub_session_id.
    
    sub_ctx = SessionContext(
        session_id=test_sub_session_id,
        workspace_root=parent_ctx.session_workspace 
    )
    
    print(f"Sub Session Workspace: {sub_ctx.session_workspace}")
    
    # 4. Simulate adding LLM request logs
    llm_request = {
        "messages": [{"role": "user", "content": "hello"}],
        "model": "gpt-4",
        "step_name": "test_step"
    }
    llm_response = {
        "choices": [{"message": {"content": "world"}}]
    }
    
    sub_ctx.add_llm_request(llm_request, llm_response)
    print(f"Added LLM request. Log count: {len(sub_ctx.llm_requests_logs)}")

    # 5. Simulate adding Messages (which simple_agent needs to sync)
    # We add a dummy message to sub_ctx.message_manager.messages
    # This simulates what I added in simple_agent.py finally block
    sub_ctx.message_manager.messages.append({
        "role": "user",
        "content": "This is a test message synced from simple_agent"
    })
    
    # 6. Save Sub-Session
    print("Saving sub-session...")
    sub_ctx.save()
    
    # 7. Verify LLM Request File Existence
    llm_req_dir = os.path.join(sub_ctx.session_workspace, "llm_request")
    print(f"Checking directory: {llm_req_dir}")
    
    if os.path.exists(llm_req_dir):
        files = os.listdir(llm_req_dir)
        print(f"Files in llm_request: {files}")
        if len(files) > 0:
            print("SUCCESS: LLM Log file created.")
        else:
            print("FAILURE: LLM Log Directory exists but is empty.")
    else:
        print("FAILURE: llm_request directory does not exist.")

    # 8. Verify Messages File Existence
    messages_path = os.path.join(sub_ctx.session_workspace, "messages.json")
    if os.path.exists(messages_path):
        print("SUCCESS: messages.json created.")
        with open(messages_path, 'r') as f:
            msgs = json.load(f)
            print(f"Messages content: {msgs}")
    else:
        print("FAILURE: messages.json does not exist.")


if __name__ == "__main__":
    asyncio.run(test_sub_session_logging())
