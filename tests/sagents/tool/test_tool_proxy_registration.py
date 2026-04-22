
import unittest
import logging
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.tool.tool_base import tool

# Configure logger to print to console
logging.basicConfig(level=logging.INFO)

class MyTools:
    @tool()
    def my_tool(self, x: int):
        """My tool doc"""
        return x

class TestToolProxyRegistration(unittest.TestCase):
    def test_re_registration_updates_whitelist(self):
        # 1. Setup ToolManager and register a tool
        # Disable auto-discovery to reduce noise
        tm = ToolManager(isolated=True, is_auto_discover=False)
        
        obj1 = MyTools()
        
        # Register directly first
        tm.register_tools_from_object(obj1)
        self.assertIn("my_tool", tm.tools)
        
        # 2. Setup ToolProxy with empty whitelist
        # Pass the SAME tm
        proxy = ToolProxy(tool_managers=[tm], available_tools=[])
        
        # Verify initially empty
        visible_tools_initial = proxy.list_tools()
        self.assertEqual(len(visible_tools_initial), 0)
        
        # 3. Register the same object (or new instance of same class) via Proxy
        obj2 = MyTools()
        # This calls tm.register_tools_from_object(obj2)
        # Should return ['my_tool'] even if register_tool returns False
        proxy.register_tools_from_object(obj2)
        
        # 4. Verify behavior
        # Check if "my_tool" is now in proxy's available tools
        visible_tools = proxy.list_tools()
        visible_names = [t['name'] for t in visible_tools]
        
        self.assertIn("my_tool", visible_names, "my_tool should be visible in proxy after registration, even if it was already in manager")

if __name__ == '__main__':
    unittest.main()
