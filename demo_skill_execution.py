import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to sys.path
sys.path.append(os.getcwd())

from sagents.llm.chat import OpenAIChat
from sagents.sagents import SAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.skills.skill_manager import SkillManager
from sagents.tool.tool_manager import ToolManager

async def run_demo():
    print("=== Starting PPTX Skill Execution Demo ===")

    # 1. Initialize Components
    model_config = {
        "model": os.getenv("SAGE_DEFAULT_LLM_MODEL_NAME", "gpt-4o"),
        "api_key": os.getenv("SAGE_DEFAULT_LLM_API_KEY"),
        "base_url": os.getenv("SAGE_DEFAULT_LLM_API_BASE_URL"),
        "temperature": 0.2
    }

    print(f"Initializing LLM with model: {model_config['model']}")
    chat_client = OpenAIChat(
        api_key=model_config['api_key'],
        base_url=model_config['base_url'],
        model_name=model_config['model']
    )
    llm = chat_client.raw_client

    # Initialize SkillManager (it will automatically scan skill_workspace)
    skill_manager = SkillManager()
    skills = skill_manager.list_skills()
    print(f"Loaded skills count: {len(skills)}")
    print(f"Loaded skills: {skills}")
    if len(skills) == 0:
        print("WARNING: No skills loaded! SkillExecutorAgent will be skipped.")
        # Try to force load or check path
        print(f"Skill workspace path: {skill_manager.skill_workspace}")

    # DEBUG: Check PromptManager
    from sagents.utils.prompt_manager import PromptManager
    pm = PromptManager()
    print("\n[DEBUG] PromptManager State:")
    print(f"Agent Prompts Keys (ZH): {list(pm.agent_prompts_zh.keys())}")
    if "SkillExecutorAgent" in pm.agent_prompts_zh:
        print(f"SkillExecutorAgent Prompts (ZH): {list(pm.agent_prompts_zh['SkillExecutorAgent'].keys())}")
    else:
        print("SkillExecutorAgent NOT FOUND in agent_prompts_zh")
    print("\n")

    # Initialize ToolManager (empty for now, skill executor adds tools dynamically)
    tool_manager = ToolManager(is_auto_discover=False)

    # Initialize SAgent
    agent = SAgent(
        model=llm,
        model_config=model_config,
        system_prefix="You are a helpful assistant.",
        enable_obs=False # Disable observability for simple demo
    )

    # 2. Define User Query
    user_query = "请使用PPTX工具创建一个包含3个幻灯片的演示文稿。"
    print(f"\nUser Query: {user_query}\n")

    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content=user_query,
            message_type=MessageType.NORMAL.value
        )
    ]

    # 3. Run Agent Stream
    import uuid
    session_id = f"demo_session_{uuid.uuid4().hex[:8]}"
    print(f"Using Session ID: {session_id}")
    print("=== Agent Execution Log ===")
    async for chunks in agent.run_stream(
        input_messages=messages,
        tool_manager=tool_manager,
        skill_manager=skill_manager,
        session_id=session_id,
        deep_thinking=False, # Disable deep thinking to go straight to execution
        multi_agent=False    # Use simplified workflow
    ):
        for chunk in chunks:
            # Print relevant output
            if chunk.role == MessageRole.ASSISTANT.value:
                if chunk.show_content:
                    print(f"[Assistant]: {chunk.show_content}")
                elif chunk.tool_calls:
                    print(f"[Tool Call]: {chunk.tool_calls}")
                elif chunk.content:
                    # Filter out some noise if needed
                    pass
            elif chunk.role == MessageRole.TOOL.value:
                print(f"[Tool Output]: {chunk.content[:200]}..." if len(chunk.content) > 200 else f"[Tool Output]: {chunk.content}")

    print("\n=== Demo Completed ===")

if __name__ == "__main__":
    asyncio.run(run_demo())
