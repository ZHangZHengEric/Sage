import unittest
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.tool.tool_base import tool

class TestToolIsolation(unittest.TestCase):
    def setUp(self):
        # Reset ToolManager singleton
        ToolManager._instance = None
        
    def tearDown(self):
        ToolManager._instance = None

    def test_singleton_behavior(self):
        """Test that ToolManager() returns the same instance by default"""
        tm1 = ToolManager(is_auto_discover=False)
        tm2 = ToolManager(is_auto_discover=False)
        self.assertIs(tm1, tm2)
        
    def test_isolated_behavior(self):
        """Test that isolated=True creates new instances"""
        tm1 = ToolManager(is_auto_discover=False, isolated=True)
        tm2 = ToolManager(is_auto_discover=False, isolated=True)
        global_tm = ToolManager(is_auto_discover=False)
        
        self.assertIsNot(tm1, tm2)
        self.assertIsNot(tm1, global_tm)
        self.assertIsNot(tm2, global_tm)
        
    def test_tool_proxy_priority(self):
        """Test ToolProxy priority logic (Index 0 is highest)"""
        
        # Create two managers
        tm1 = ToolManager(is_auto_discover=False, isolated=True)
        tm2 = ToolManager(is_auto_discover=False, isolated=True)
        
        # Define tools with same name but different implementation
        class Tools1:
            @tool()
            def conflict_tool(self):
                return "tm1"
                
        class Tools2:
            @tool()
            def conflict_tool(self):
                return "tm2"
                
        tm1.register_tools_from_object(Tools1())
        tm2.register_tools_from_object(Tools2())
        
        # Proxy with [tm1, tm2] -> tm1 should have priority (Index 0)
        proxy = ToolProxy([tm1, tm2])
        
        # Check simplified list
        tools = proxy.list_tools_simplified()
        # Should be only one tool with this name
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]['name'], 'conflict_tool')
        
        # Check execution (by inspecting tool spec)
        tool_spec = proxy.get_tool('conflict_tool')
        self.assertIn('Tools1', tool_spec.func.__qualname__)
        
    def test_add_tool_manager_priority(self):
        """Test adding a tool manager dynamically inserts at high priority"""
        tm1 = ToolManager(is_auto_discover=False, isolated=True)
        class Tools1:
            @tool()
            def test_tool(self): return "tm1"
        tm1.register_tools_from_object(Tools1())
        
        proxy = ToolProxy([tm1])
        tool_spec = proxy.get_tool('test_tool')
        self.assertIn('Tools1', tool_spec.func.__qualname__)

        # Add new manager with same tool
        tm2 = ToolManager(is_auto_discover=False, isolated=True)
        class Tools2:
            @tool()
            def test_tool(self): return "tm2"
        tm2.register_tools_from_object(Tools2())
        
        proxy.add_tool_manager(tm2)
        
        # Now tm2 should be priority
        tool_spec = proxy.get_tool('test_tool')
        self.assertIn('Tools2', tool_spec.func.__qualname__)

    def test_register_tools_from_object_proxy(self):
        """Test registering tools directly to proxy registers to highest priority manager"""
        tm1 = ToolManager(is_auto_discover=False, isolated=True)
        proxy = ToolProxy([tm1])
        
        class LocalTools:
            @tool()
            def local_tool(self): return "local"
            
        proxy.register_tools_from_object(LocalTools())
        
        # Check if it's in tm1
        self.assertIsNotNone(tm1.get_tool('local_tool'))
        self.assertIsNotNone(proxy.get_tool('local_tool'))
        
    def test_register_tools_no_manager(self):
        """Test registering tools to proxy with no managers handles gracefully"""
        proxy = ToolProxy([])
        class LocalTools:
            @tool()
            def local_tool(self): return "local"
            
        count = proxy.register_tools_from_object(LocalTools())
        self.assertEqual(count, 0)

if __name__ == '__main__':
    unittest.main()
