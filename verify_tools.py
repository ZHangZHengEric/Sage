
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import ToolBase
import sagents.tool  # Trigger the __init__.py

def verify():
    print("Initializing ToolManager...")
    tm = ToolManager(is_auto_discover=True)
    
    print(f"Total tools registered: {len(tm.tools)}")
    
    memory_tools = [name for name, tool in tm.tools.items() if 'memory' in name.lower()]
    print(f"Memory tools found: {memory_tools}")
    
    # Check if MemoryTool class is in ToolBase subclasses
    subclasses = ToolBase.__subclasses__()
    memory_tool_class = next((cls for cls in subclasses if cls.__name__ == 'MemoryTool'), None)
    
    if memory_tool_class:
        print(f"MemoryTool class found in ToolBase subclasses: {memory_tool_class}")
    else:
        print("MemoryTool class NOT found in ToolBase subclasses")

    # Check if remember_user_memory is registered
    if 'remember_user_memory' in tm.tools:
        print("SUCCESS: 'remember_user_memory' tool is registered.")
    else:
        print("FAILURE: 'remember_user_memory' tool is NOT registered.")

if __name__ == "__main__":
    verify()
