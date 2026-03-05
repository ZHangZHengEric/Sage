import logging
import traceback
from typing import Optional, AsyncGenerator, List, Dict, Any

from sagents.context.session_context import SessionContext, SessionStatus
from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager
from sagents.utils.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class FibreSubAgent:
    """
    Fibre Sub-Agent (The Executor)

    A lightweight executor that runs tasks based on AgentDefinition configuration.
    Does NOT manage session context - session context is managed by SubSession.
    """

    def __init__(self, agent_definition: "AgentDefinition"):
        """
        Initialize the sub-agent executor.

        Args:
            agent_definition: The agent definition (configuration)
        """
        self.agent_definition = agent_definition
        self.agent_id = agent_definition.agent_id
        self.name = agent_definition.name

        # Internal agent instance (lazy initialization)
        self._agent: Optional[SimpleAgent] = None
        self._initialized = False

    @property
    def agent_name(self) -> str:
        """Backward compatibility property."""
        return self.name

    async def _initialize_if_needed(
        self,
        model,
        model_config: Dict[str, Any]
    ):
        """
        Initialize the internal SimpleAgent if not already initialized.

        Args:
            model: The model to use
            model_config: Model configuration
        """
        if self._initialized:
            return

        logger.info(f"Initializing FibreSubAgent: {self.agent_definition.name} (id={self.agent_definition.agent_id})")

        # Create SimpleAgent using AgentDefinition
        self._agent = SimpleAgent(
            model=model,
            model_config=model_config,
            system_prefix=self.agent_definition.system_prompt
        )
        self._agent.agent_name = self.agent_definition.name

        self._initialized = True
        logger.info(f"FibreSubAgent {self.agent_definition.name} initialized")

    @property
    def agent(self) -> Optional[SimpleAgent]:
        """Get the internal SimpleAgent instance."""
        return self._agent

    async def process_message(
        self,
        content: str,
        session_context: SessionContext
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        Process a message and yield response chunks.
        
        Args:
            content: The message content/task
            session_context: The session context (managed by SubSession)
            
        Yields:
            Lists of MessageChunk objects
        """
        if not self._initialized:
            raise RuntimeError("FibreSubAgent not initialized. Call _initialize_if_needed first.")
        
        if self._agent is None:
            raise RuntimeError("Internal agent not created")
        
        # Log session context details for debugging
        logger.info(f"FibreSubAgent.process_message: session_id={session_context.session_id}")
        logger.info(f"FibreSubAgent.process_message: tool_manager={session_context.tool_manager}")
        logger.info(f"FibreSubAgent.process_message: has tool_manager attr={hasattr(session_context, 'tool_manager')}")
        
        try:
            # Add user message to session context
            from sagents.context.messages.message import MessageChunk
            user_msg = MessageChunk(
                role=MessageRole.USER.value,
                content=content,
                session_id=session_context.session_id
            )
            session_context.add_messages(user_msg)
            
            # Run the agent - tool_manager is obtained from session_context
            logger.info(f"Running agent with tool_manager={session_context.tool_manager}")
            async for chunks in self._agent.run_stream(
                session_context=session_context,
                tool_manager=session_context.tool_manager,
                session_id=session_context.session_id
            ):
                for chunk in chunks:
                    chunk.session_id = session_context.session_id
                    
                # Sync to sub-session context immediately
                session_context.add_messages(chunks)
                yield chunks
                
        except Exception as e:
            logger.error(f"Error in FibreSubAgent.process_message: {e}", exc_info=True)
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"Error executing task: {str(e)}",
                message_type="text",
                session_id=session_context.session_id
            )]
