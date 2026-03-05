"""
Sub Session Module

Defines the SubSession class - runtime session with agent instance and context.
SubSession is the main interface for running tasks, managing both the agent execution
and session lifecycle.
"""
import logging
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator, List
from datetime import datetime

from sagents.context.session_context import SessionContext, SessionStatus
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.agent.fibre.agent_definition import AgentDefinition

logger = logging.getLogger(__name__)


class SubSession:
    """
    Running sub-session with agent instance and context.
    
    This class is the main runtime interface for executing tasks.
    It manages:
    - Session lifecycle (status, parent-child relationships)
    - Agent execution (run, process_message)
    - State persistence
    
    The actual agent execution is delegated to an internal executor (FibreSubAgent).
    """
    
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        agent_definition: AgentDefinition,
        parent_session_id: Optional[str],
        session_context: SessionContext,
        model: Any,
        model_config: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize sub-session.

        Args:
            session_id: Unique session ID
            agent_id: Reference to AgentDefinition name/ID
            agent_definition: The agent definition (configuration)
            parent_session_id: Parent session ID (None for root sessions)
            session_context: The session context for this session
            model: The model to use for execution
            model_config: Model configuration
            metadata: Additional metadata (created_at, task_info, etc.)
        """
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_definition = agent_definition
        self.parent_session_id = parent_session_id
        self.session_context = session_context
        self.model = model
        self.model_config = model_config
        self.metadata = metadata or {}
        self.status = "idle"  # idle, running, completed, error, interrupted
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

        # Task workspace path (set by orchestrator when creating task folder)
        self.task_workspace: Optional[str] = None

        # Internal executor (lazy initialization)
        self._executor = None

        # Register in session context for lookup
        self.session_context.sub_session = self

        logger.info(f"SubSession created: {session_id} (agent: {agent_id}, parent: {parent_session_id})")
    
    async def _get_executor(self):
        """Lazy initialization of the executor (FibreSubAgent)."""
        if self._executor is None:
            from sagents.agent.fibre.sub_agent import FibreSubAgent

            # Create executor with agent definition only
            self._executor = FibreSubAgent(agent_definition=self.agent_definition)

            # Initialize the executor with model from SubSession
            await self._executor._initialize_if_needed(
                model=self.model,
                model_config=self.model_config
            )
            logger.info(f"SubSession {self.session_id}: Executor initialized")

        return self._executor
    
    async def run_stream(self, task_content: str) -> AsyncGenerator[List[MessageChunk], None]:
        """
        Run a task and yield message chunks as they are produced.
        
        This is the streaming interface for executing tasks.
        
        Args:
            task_content: The task content/instruction
            
        Yields:
            Lists of MessageChunk objects
        """
        self.update_status("running")
        
        try:
            executor = await self._get_executor()
            
            async for chunks in executor.process_message(
                content=task_content,
                session_context=self.session_context
            ):
                yield chunks

            self.update_status("completed")

        except Exception as e:
            logger.error(f"Error in stream execution for SubSession {self.session_id}: {e}", exc_info=True)
            self.update_status("error")
            raise
        finally:
            self.save_state()
    
    def update_status(self, status: str) -> None:
        """
        Update session status.
        
        Args:
            status: New status (idle, running, completed, error, interrupted)
        """
        old_status = self.status
        self.status = status
        self.updated_at = datetime.now().isoformat()
        
        # Also update session context status
        if hasattr(self.session_context, 'set_status'):
            status_map = {
                "idle": SessionStatus.IDLE,
                "running": SessionStatus.RUNNING,
                "completed": SessionStatus.COMPLETED,
                "error": SessionStatus.ERROR,
                "interrupted": SessionStatus.INTERRUPTED
            }
            if status in status_map:
                self.session_context.set_status(status_map[status], cascade=False)
        
        logger.info(f"SubSession {self.session_id} status changed: {old_status} -> {status}")
    
    def is_active(self) -> bool:
        """Check if session is currently active (running)."""
        return self.status == "running"
    
    def is_finished(self) -> bool:
        """Check if session has finished (completed, error, or interrupted)."""
        return self.status in ["completed", "error", "interrupted"]
    
    def interrupt(self) -> None:
        """Interrupt this session."""
        self.update_status("interrupted")
        logger.info(f"SubSession {self.session_id} interrupted")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "parent_session_id": self.parent_session_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }
    
    def save_state(self) -> None:
        """Save session state to persistent storage."""
        try:
            if self.session_context:
                self.session_context.save()
                logger.debug(f"SubSession {self.session_id} state saved")
        except Exception as e:
            logger.error(f"Failed to save SubSession {self.session_id} state: {e}")
    
    def __repr__(self) -> str:
        return f"SubSession(id={self.session_id}, agent={self.agent_id}, status={self.status})"


class SubSessionManager:
    """
    Manager for sub-sessions.
    
    Provides centralized management of all sub-sessions,
    including lookup, lifecycle management, and cleanup.
    """
    
    def __init__(self):
        self._sessions: Dict[str, SubSession] = {}
    
    def register(self, sub_session: SubSession) -> None:
        """Register a sub-session."""
        self._sessions[sub_session.session_id] = sub_session
        logger.info(f"SubSession registered: {sub_session.session_id}")
    
    def unregister(self, session_id: str) -> Optional[SubSession]:
        """Unregister a sub-session."""
        session = self._sessions.pop(session_id, None)
        if session:
            logger.info(f"SubSession unregistered: {session_id}")
        return session
    
    def get(self, session_id: str) -> Optional[SubSession]:
        """Get a sub-session by ID."""
        return self._sessions.get(session_id)
    
    def get_by_agent(self, agent_id: str) -> List[SubSession]:
        """Get all sub-sessions for a specific agent."""
        return [s for s in self._sessions.values() if s.agent_id == agent_id]
    
    def get_by_parent(self, parent_session_id: str) -> List[SubSession]:
        """Get all child sub-sessions for a parent session."""
        return [s for s in self._sessions.values() if s.parent_session_id == parent_session_id]
    
    def get_active(self) -> List[SubSession]:
        """Get all active (running) sub-sessions."""
        return [s for s in self._sessions.values() if s.is_active()]
    
    def get_all(self) -> Dict[str, SubSession]:
        """Get all sub-sessions."""
        return self._sessions.copy()
    
    def interrupt_session(self, session_id: str, cascade: bool = True) -> bool:
        """
        Interrupt a session and optionally cascade to children.
        
        Args:
            session_id: Session ID to interrupt
            cascade: Whether to cascade to child sessions
            
        Returns:
            True if interrupted, False if not found
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        # Update status
        session.interrupt()
        
        # Cascade to children
        if cascade:
            children = self.get_by_parent(session_id)
            for child in children:
                if not child.is_finished():
                    self.interrupt_session(child.session_id, cascade=True)
        
        return True
    
    async def run_task(self, session_id: str, task_content: str) -> str:
        """
        Run a task in a specific session.
        
        Args:
            session_id: Session ID
            task_content: Task content
            
        Returns:
            Task result
        """
        session = self._sessions.get(session_id)
        if not session:
            return f"Error: Session '{session_id}' not found"
        
        return await session.run(task_content)
    
    def cleanup_finished(self, max_age_hours: int = 24) -> int:
        """
        Clean up finished sessions older than specified hours.
        
        Args:
            max_age_hours: Maximum age in hours for finished sessions
            
        Returns:
            Number of sessions cleaned up
        """
        from datetime import datetime, timedelta
        
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        to_remove = []
        
        for session_id, session in self._sessions.items():
            if session.is_finished():
                updated = datetime.fromisoformat(session.updated_at)
                if updated < cutoff:
                    to_remove.append(session_id)
        
        for session_id in to_remove:
            self.unregister(session_id)
        
        logger.info(f"Cleaned up {len(to_remove)} finished sub-sessions")
        return len(to_remove)
