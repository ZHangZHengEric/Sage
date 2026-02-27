from typing import List, Dict, Any, Optional, Union
from .tool_manager import ToolManager
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext

class ToolProxy:
    """
    工具代理类
    
    作为 ToolManager 的代理，支持管理多个 ToolManager 实例并进行工具筛选。
    兼容 ToolManager 的所有工具相关接口。
    """
    
    def __init__(self, tool_managers: Union[ToolManager, List[ToolManager]], available_tools: Optional[List[str]] = None):
        """
        初始化工具代理
        
        Args:
            tool_managers: 工具管理器实例或实例列表（优先级按列表顺序递减）
            available_tools: 可用工具名称列表（白名单）。如果不传或为None，则所有工具可用。
        """
        if isinstance(tool_managers, list):
            self.tool_managers = tool_managers
        else:
            self.tool_managers = [tool_managers]
            
        self.tool_manager = self.tool_managers[0] if self.tool_managers else None # Backward compatibility attribute
        self._available_tools = set(available_tools) if available_tools is not None else None
        
        # 验证工具是否存在（仅当设置了 available_tools 时）
        if self._available_tools is not None:
            all_tools_names = set()
            for tm in self.tool_managers:
                all_tools_names.update(tm.list_all_tools_name())
            
            invalid_tools = self._available_tools - all_tools_names
            if invalid_tools:
                logger.warning(f"ToolProxy: 以下工具不存在: {invalid_tools}")
                self._available_tools -= invalid_tools
    
    def _check_tool_available(self, tool_name: str) -> None:
        """
        检查工具是否可用
        """
        if self._available_tools is None:
            return
            
        if tool_name not in self._available_tools:
            raise ValueError(f"工具 '{tool_name}' 不在可用工具列表中")
    
    # ToolManager 兼容接口
    
    def get_openai_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取 OpenAI 格式的工具规范（仅限可用工具），支持语言筛选
        """
        all_tools_map = {}
        # Iterate in reverse order so higher priority managers overwrite lower ones
        for tm in reversed(self.tool_managers):
            tools = tm.get_openai_tools(lang=lang, fallback_chain=fallback_chain)
            for tool in tools:
                name = tool['function']['name']
                if self._available_tools is None or name in self._available_tools:
                    all_tools_map[name] = tool
                    
        return list(all_tools_map.values())
    
    def list_tools_simplified(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取简化的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools_map = {}
        for tm in reversed(self.tool_managers):
            tools = tm.list_tools_simplified(lang=lang, fallback_chain=fallback_chain)
            for tool in tools:
                if self._available_tools is None or tool['name'] in self._available_tools:
                    all_tools_map[tool['name']] = tool
        
        return list(all_tools_map.values())
    
    def list_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取详细的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools_map = {}
        for tm in reversed(self.tool_managers):
            tools = tm.list_tools(lang=lang, fallback_chain=fallback_chain)
            for tool in tools:
                if self._available_tools is None or tool['name'] in self._available_tools:
                    all_tools_map[tool['name']] = tool
                    
        return list(all_tools_map.values())
    
    def list_all_tools_name(self, lang: Optional[str] = None) -> List[str]:
        """
        获取所有工具名称（包括不可用工具），接受语言参数以保持接口一致性
        """
        all_names = set()
        for tm in self.tool_managers:
            names = tm.list_all_tools_name(lang=lang)
            if self._available_tools is None:
                all_names.update(names)
            else:
                all_names.update([n for n in names if n in self._available_tools])
        return list(all_names)
    
    def list_tools_with_type(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        获取带类型的工具列表（仅限可用工具），支持语言筛选
        """
        all_tools_map = {}
        for tm in reversed(self.tool_managers):
            tools = tm.list_tools_with_type(lang=lang, fallback_chain=fallback_chain)
            for tool in tools:
                if self._available_tools is None or tool['name'] in self._available_tools:
                    all_tools_map[tool['name']] = tool
                    
        return list(all_tools_map.values())
    
    def get_tool(self, name: str) -> Optional[Any]:
        """
        根据名称获取工具（仅限可用工具）
        """
        try:
            self._check_tool_available(name)
            # Search in managers by priority
            for tm in self.tool_managers:
                tool = tm.get_tool(name)
                if tool:
                    return tool
            return None
        except ValueError:
            return None
    
    async def run_tool_async(self, tool_name: str, session_context: SessionContext, **kwargs) -> Any:
        """
        异步执行工具（仅限可用工具）
        """
        self._check_tool_available(tool_name)
        
        for tm in self.tool_managers:
            if tm.get_tool(tool_name):
                return await tm.run_tool_async(tool_name, session_context, **kwargs)
                
        raise ValueError(f"Tool {tool_name} not found")

    async def register_mcp_server(self, server_name: str, config: dict) -> Any:
        """
        注册 MCP Server 到优先级最高的 ToolManager
        
        Args:
            server_name: MCP server 名称
            config: MCP server 配置
            
        Returns:
            注册结果
        """
        if not self.tool_managers:
            logger.warning("ToolProxy: No tool managers available to register MCP server")
            return False
        
        # 注册到优先级最高的 manager (index 0)
        target_tm = self.tool_managers[0]
        logger.info(f"ToolProxy: Registering MCP server '{server_name}' to highest priority manager")
        return await target_tm.register_mcp_server(server_name, config)

    def add_tool_manager(self, tool_manager: ToolManager) -> None:
        """
        Add a tool manager to the proxy with highest priority.
        
        Args:
            tool_manager: The tool manager to add.
        """
        self.tool_managers.insert(0, tool_manager)
        
        # If available_tools is set, we need to ensure the new manager's tools are allowed if they were not implicitly.
        # However, available_tools acts as a whitelist filter. 
        # If the user adds a manager dynamically, they likely want its tools to be available.
        # But if available_tools was restricted, we should probably update it or assume the new manager's tools are allowed?
        # The current implementation of methods filters by self._available_tools.
        # If self._available_tools is not None, new tools won't be visible unless added to the set.
        
        if self._available_tools is not None:
             new_tools = tool_manager.list_all_tools_name()
             self._available_tools.update(new_tools)
             logger.info(f"ToolProxy: Added tools from new manager to whitelist: {new_tools}")

    def register_tools_from_object(self, obj: Any) -> int:
        """
        Register tools from an object instance or class into the highest priority ToolManager.
        
        Args:
            obj: An object instance or class to scan for tools.
            
        Returns:
            int: Number of tools successfully registered.
        """
        if not self.tool_managers:
            logger.warning("ToolProxy: No tool managers available to register tools")
            return 0

        # Register to the highest priority manager (index 0)
        target_tm = self.tool_managers[0]
        # ToolManager.register_tools_from_object now returns List[str] (names of registered tools)
        registered_tool_names = target_tm.register_tools_from_object(obj)
        count = len(registered_tool_names)
        
        if count > 0:
            # Update whitelist only with the newly registered tools
            if self._available_tools is not None:
                try:
                    self._available_tools.update(registered_tool_names)
                    logger.info(f"ToolProxy: Added {count} newly registered tools to whitelist: {registered_tool_names}")
                except Exception as e:
                    logger.warning(f"ToolProxy: Failed to update available_tools after registration: {e}")

            logger.info(f"ToolProxy: Registered {count} tools from {obj} into highest priority manager")
            
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
            'execute_python_code', 'complete_task',
            'todo_write', 'todo_read'
        ],
        'sales_assistant': [
            'calculate', 'file_read', 'file_write', 'web_search', 
            'send_email', 'complete_task',
            'todo_write', 'todo_read'
        ],
        'batch_operation': [
            'file_read', 'file_write', 'execute_python_code', 
            'batch_process', 'complete_task',
            'todo_write', 'todo_read'
        ],
        'basic': [
            'calculate', 'factorial', 'complete_task',
            'todo_write', 'todo_read'
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
