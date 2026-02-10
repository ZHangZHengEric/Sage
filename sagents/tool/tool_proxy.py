from typing import List, Dict, Any, Optional
from .tool_manager import ToolManager
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext

class ToolProxy:
    """
    工具代理类
    
    作为 ToolManager 的代理，只暴露指定的工具子集。
    兼容 ToolManager 的所有工具相关接口。
    """
    
    def __init__(self, tool_manager: ToolManager, available_tools: List[str]):
        """
        初始化工具代理
        
        Args:
            tool_manager: 全局工具管理器实例
            available_tools: 可用工具名称列表
        """
        self.tool_manager = tool_manager
        self._available_tools = set(available_tools)
        
        # 验证工具是否存在
        all_tools = {tool['name'] for tool in self.tool_manager.list_tools_simplified()}
        invalid_tools = self._available_tools - all_tools
        if invalid_tools:
            logger.warning(f"ToolProxy: 以下工具不存在: {invalid_tools}")
            self._available_tools -= invalid_tools
    
    def _check_tool_available(self, tool_name: str) -> None:
        """
        检查工具是否可用
        
        Args:
            tool_name: 工具名称
            
        Raises:
            ValueError: 工具不可用时抛出异常
        """
        if tool_name not in self._available_tools:
            raise ValueError(f"工具 '{tool_name}' 不在可用工具列表中")
    
    # ToolManager 兼容接口
    
    def get_openai_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取 OpenAI 格式的工具规范（仅限可用工具），支持语言筛选
        """
        all_tools = self.tool_manager.get_openai_tools(lang=lang, fallback_chain=fallback_chain)
        return [tool for tool in all_tools if tool['function']['name'] in self._available_tools]
    
    def list_tools_simplified(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取简化的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools = self.tool_manager.list_tools_simplified(lang=lang, fallback_chain=fallback_chain)
        return [tool for tool in all_tools if tool['name'] in self._available_tools]
    
    def list_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取详细的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools = self.tool_manager.list_tools(lang=lang, fallback_chain=fallback_chain)
        return [tool for tool in all_tools if tool['name'] in self._available_tools]
    
    def list_all_tools_name(self, lang: Optional[str] = None) -> List[str]:
        """
        获取所有工具名称（包括不可用工具），接受语言参数以保持接口一致性
        """
        all_tools_name =  self.tool_manager.list_all_tools_name(lang=lang)
        return [tool_name for tool_name in all_tools_name if tool_name in self._available_tools]
    
    def list_tools_with_type(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取带类型的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools = self.tool_manager.list_tools_with_type(lang=lang, fallback_chain=fallback_chain)
        return [tool for tool in all_tools if tool['name'] in self._available_tools]
    
    def get_tool(self, name: str) -> Optional[Any]:
        """
        根据名称获取工具（仅限可用工具）
        """
        self._check_tool_available(name)
        return self.tool_manager.get_tool(name)
    
    async def run_tool_async(self, tool_name: str, session_context: SessionContext, **kwargs) -> Any:
        """
        异步执行工具（仅限可用工具）
        """
        self._check_tool_available(tool_name)
        return await self.tool_manager.run_tool_async(tool_name, session_context, **kwargs)

    def register_tools_from_object(self, obj: Any) -> int:
        """
        Register tools from an object instance or class.
        Delegates to ToolManager and updates available tools list.
        """
        # Delegate to base manager
        count = self.tool_manager.register_tools_from_object(obj)
        
        if count > 0:
            # If successful, we need to add the registered tools to available_tools
            # We scan the object to find tool names
            import inspect
            
            for name, member in inspect.getmembers(obj):
                # Check if member has _tool_spec (added by @tool decorator)
                tool_spec = getattr(member, "_tool_spec", None)
                
                # If not found directly, check underlying function for bound methods
                if not tool_spec and hasattr(member, "__func__"):
                    tool_spec = getattr(member.__func__, "_tool_spec", None)
                    
                if tool_spec:
                    tool_name = tool_spec.name
                    if tool_name not in self._available_tools:
                        self._available_tools.add(tool_name)
                        logger.info(f"ToolProxy: Added newly registered tool '{tool_name}' to available tools")
                        
        return count

class ToolProxyFactory:
    """
    工具代理工厂类
    
    用于创建和管理预定义的工具组合。
    """
    
    # 预定义的工具组合
    PREDEFINED_TOOL_SETS = {
        'im_invitation': [
            'calculate', 'factorial', 'file_read', 'file_write', 
            'execute_python_code', 'complete_task'
        ],
        'sales_assistant': [
            'calculate', 'file_read', 'file_write', 'web_search', 
            'send_email', 'complete_task'
        ],
        'batch_operation': [
            'file_read', 'file_write', 'execute_python_code', 
            'batch_process', 'complete_task'
        ],
        'basic': [
            'calculate', 'factorial', 'complete_task'
        ]
    }
    
    def __init__(self, tool_manager: ToolManager):
        """
        初始化工具代理工厂
        
        Args:
            tool_manager: 全局工具管理器实例
        """
        self.tool_manager = tool_manager
        logger.info("ToolProxyFactory: 工具代理工厂初始化完成")
    
    def get_available_tool_sets(self) -> List[str]:
        """
        获取可用的工具集名称
        
        Returns:
            工具集名称列表
        """
        return list(self.PREDEFINED_TOOL_SETS.keys())
    
    def create_proxy(self, tool_set_name: str) -> ToolProxy:
        """
        创建预定义工具集的代理
        
        Args:
            tool_set_name: 工具集名称
            
        Returns:
            工具代理实例
            
        Raises:
            ValueError: 工具集不存在时抛出异常
        """
        if tool_set_name not in self.PREDEFINED_TOOL_SETS:
            raise ValueError(f"工具集 '{tool_set_name}' 不存在。可用工具集: {list(self.PREDEFINED_TOOL_SETS.keys())}")
        
        tools = self.PREDEFINED_TOOL_SETS[tool_set_name]
        logger.info(f"ToolProxyFactory: 创建 '{tool_set_name}' 工具集代理")
        return ToolProxy(self.tool_manager, tools)
    
    def create_custom_proxy(self, tools: List[str]) -> ToolProxy:
        """
        创建自定义工具集的代理
        
        Args:
            tools: 工具名称列表
            
        Returns:
            工具代理实例
        """
        logger.info(f"ToolProxyFactory: 创建自定义工具集代理: {tools}")
        return ToolProxy(self.tool_manager, tools)
