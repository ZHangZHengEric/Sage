from sagents.agent.fibre.tools import FibreTools
from sagents.tool.impl.codebase_tool import CodebaseTool
from sagents.tool.impl.file_system_tool import FileSystemTool
from sagents.tool.impl.todo_tool import ToDoTool
from sagents.tool.tool_manager import ToolManager


def test_builtin_tool_classes_expose_display_groups():
    manager = ToolManager(isolated=True, is_auto_discover=False)
    for tools in (ToDoTool(), FileSystemTool(), CodebaseTool(), FibreTools()):
        manager.register_tools_from_object(tools)

    source_by_name = {
        value["name"]: value["source"] for value in manager.list_tools_with_type()
    }

    assert source_by_name["todo_write"] == "任务规划"
    assert source_by_name["file_read"] == "文件"
    assert source_by_name["grep"] == "代码检索"
    assert source_by_name["sys_spawn_agent"] == "多智能体"
