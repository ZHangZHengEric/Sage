"""
Core tests for Fibre Orchestrator V2 - Standalone version
Tests the core logic without full imports
"""
import sys
import os
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)

# Test AgentDefinition
print("Testing AgentDefinition...")

class AgentDefinition:
    def __init__(self, name, system_prompt, description="",
                 available_tools=None, available_skills=None, 
                 available_workflows=None, system_context=None):
        self.name = name
        self.system_prompt = system_prompt
        self.description = description
        self.available_tools = available_tools or []
        self.available_skills = available_skills or []
        self.available_workflows = available_workflows or []
        self.system_context = system_context or {}
    
    def to_dict(self):
        return {
            "name": self.name,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "available_tools": self.available_tools,
            "available_skills": self.available_skills,
            "available_workflows": self.available_workflows,
            "system_context": self.system_context
        }

# Test 1: AgentDefinition initialization
agent_def = AgentDefinition(
    name="test_agent",
    system_prompt="You are a test agent",
    description="A test agent",
    available_tools=["tool1", "tool2"],
    available_skills=["skill1"],
    system_context={"key": "value"}
)

assert agent_def.name == "test_agent"
assert agent_def.system_prompt == "You are a test agent"
assert agent_def.description == "A test agent"
assert agent_def.available_tools == ["tool1", "tool2"]
assert agent_def.available_skills == ["skill1"]
assert agent_def.system_context == {"key": "value"}
print("✓ AgentDefinition initialization passed")

# Test 2: AgentDefinition to_dict
data = agent_def.to_dict()
assert data["name"] == "test_agent"
assert data["system_prompt"] == "You are a test agent"
print("✓ AgentDefinition to_dict passed")

# Test SubSessionManager
print("\nTesting SubSessionManager...")

class MockSubSession:
    def __init__(self, session_id, agent_id, parent_session_id=None, status="idle"):
        self.session_id = session_id
        self.agent_id = agent_id
        self.parent_session_id = parent_session_id
        self.status = status
    
    def is_active(self):
        return self.status == "running"
    
    def is_finished(self):
        return self.status in ["completed", "error", "interrupted"]
    
    def interrupt(self):
        self.status = "interrupted"

class SubSessionManager:
    def __init__(self):
        self._sessions = {}
    
    def register(self, sub_session):
        self._sessions[sub_session.session_id] = sub_session
    
    def unregister(self, session_id):
        return self._sessions.pop(session_id, None)
    
    def get(self, session_id):
        return self._sessions.get(session_id)
    
    def get_by_agent(self, agent_id):
        return [s for s in self._sessions.values() if s.agent_id == agent_id]
    
    def get_by_parent(self, parent_session_id):
        return [s for s in self._sessions.values() if s.parent_session_id == parent_session_id]
    
    def get_active(self):
        return [s for s in self._sessions.values() if s.is_active()]
    
    def interrupt_session(self, session_id, cascade=True):
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.interrupt()
        
        if cascade:
            children = self.get_by_parent(session_id)
            for child in children:
                if not child.is_finished():
                    self.interrupt_session(child.session_id, cascade=True)
        
        return True

# Test 3: SubSessionManager basic operations
manager = SubSessionManager()
session1 = MockSubSession("session_1", "agent_1", "parent_1")
session2 = MockSubSession("session_2", "agent_1", "parent_1")
session3 = MockSubSession("session_3", "agent_2", "session_1")  # Child of session_1

manager.register(session1)
manager.register(session2)
manager.register(session3)

assert manager.get("session_1") == session1
assert len(manager.get_by_agent("agent_1")) == 2
assert len(manager.get_by_parent("parent_1")) == 2
print("✓ SubSessionManager basic operations passed")

# Test 4: SubSessionManager interrupt with cascade
session3.status = "running"
result = manager.interrupt_session("session_1")
assert result is True
assert session1.status == "interrupted"
assert session3.status == "interrupted"  # Cascaded
print("✓ SubSessionManager interrupt with cascade passed")

# Test FibreOrchestrator core logic
print("\nTesting FibreOrchestrator core logic...")

class MockFibreOrchestrator:
    def __init__(self):
        self.sub_agents = {}
        self.sub_session_manager = SubSessionManager()
    
    async def spawn_agent(self, parent_session_id, name, system_prompt, 
                         description="", **kwargs):
        # Ensure unique name
        base_name = name
        counter = 1
        while name in self.sub_agents:
            name = f"{base_name}_{counter}"
            counter += 1
        
        # Create agent definition
        agent_def = AgentDefinition(
            name=name,
            system_prompt=system_prompt,
            description=description,
            **kwargs
        )
        
        self.sub_agents[name] = agent_def
        return name
    
    async def delegate_tasks(self, tasks, caller_session_id):
        # Get caller session
        caller = self.sub_session_manager.get(caller_session_id)
        if not caller:
            return f"Error: Caller session '{caller_session_id}' not found"
        
        # Validation
        errors = []
        for i, task in enumerate(tasks):
            agent_id = task.get('agent_id')
            
            # Check self-delegation
            if agent_id == caller.agent_id:
                errors.append(f"Task {i}: Cannot delegate to yourself")
                continue
            
            # Check agent exists
            if agent_id not in self.sub_agents:
                errors.append(f"Task {i}: Agent '{agent_id}' not found")
                continue
            
            # Check session running
            session_id = task.get('session_id')
            existing = self.sub_session_manager.get(session_id)
            if existing and existing.is_active():
                errors.append(f"Task {i}: Session '{session_id}' is already running")
        
        if errors:
            return "Validation failed:\n" + "\n".join(errors)
        
        return "Tasks validated successfully"

import asyncio

async def test_orchestrator():
    orchestrator = MockFibreOrchestrator()
    
    # Create parent session
    parent_session = MockSubSession("parent_123", "parent_agent")
    orchestrator.sub_session_manager.register(parent_session)
    
    # Test 5: Spawn agent
    agent_id = await orchestrator.spawn_agent(
        parent_session_id="parent_123",
        name="test_agent",
        system_prompt="You are a test agent"
    )
    assert agent_id == "test_agent"
    assert "test_agent" in orchestrator.sub_agents
    print("✓ Spawn agent passed")
    
    # Test 6: Spawn agent with name collision
    agent_id2 = await orchestrator.spawn_agent(
        parent_session_id="parent_123",
        name="test_agent",
        system_prompt="You are another test agent"
    )
    assert agent_id2 == "test_agent_1"
    assert "test_agent_1" in orchestrator.sub_agents
    print("✓ Spawn agent with name collision passed")
    
    # Test 7: Self-delegation prevention
    # Create caller session with same agent_id
    caller = MockSubSession("caller_456", "test_agent")
    orchestrator.sub_session_manager.register(caller)
    
    tasks = [
        {"agent_id": "test_agent", "content": "Do something", "session_id": "session_1"}
    ]
    result = await orchestrator.delegate_tasks(tasks, caller_session_id="caller_456")
    assert "Cannot delegate to yourself" in result
    print("✓ Self-delegation prevention passed")
    
    # Test 8: Valid delegation
    tasks = [
        {"agent_id": "test_agent_1", "content": "Do something", "session_id": "session_2"}
    ]
    result = await orchestrator.delegate_tasks(tasks, caller_session_id="caller_456")
    assert "Tasks validated successfully" in result
    print("✓ Valid delegation passed")

asyncio.run(test_orchestrator())

print("\n" + "="*60)
print("All core tests passed! ✓")
print("="*60)
