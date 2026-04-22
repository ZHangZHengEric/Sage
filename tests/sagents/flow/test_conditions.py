import unittest
from unittest.mock import MagicMock
from sagents.flow.conditions import ConditionRegistry

class TestConditionRegistry(unittest.TestCase):
    def setUp(self):
        ConditionRegistry._registry.clear()

    def test_registration_and_check(self):
        @ConditionRegistry.register("is_testing")
        def mock_check(ctx, session=None):
            return ctx.get("test_flag", False)

        ctx_true = {"test_flag": True}
        ctx_false = {"test_flag": False}
        
        self.assertTrue(ConditionRegistry.check("is_testing", ctx_true))
        self.assertFalse(ConditionRegistry.check("is_testing", ctx_false))

    def test_unregistered_condition(self):
        self.assertFalse(ConditionRegistry.check("non_existent", {}))

    def test_exception_handling(self):
        @ConditionRegistry.register("faulty_condition")
        def faulty_check(ctx, session=None):
            raise ValueError("Something went wrong")

        # Should log error and return False
        self.assertFalse(ConditionRegistry.check("faulty_condition", {}))

    def test_preset_conditions_structure(self):
        # Since we clear registry in setUp, we need to manually trigger registration 
        # or reload the module to test presets. 
        # However, reloading modules in tests can be tricky.
        # Instead, let's just verify the functions exist in the module
        import sagents.flow.conditions as conditions_module
        
        # Manually register for this test
        ConditionRegistry.register("is_deep_thinking")(conditions_module.check_deep_thinking)
        ConditionRegistry.register("enable_more_suggest")(conditions_module.check_more_suggest)
        
        self.assertIn("is_deep_thinking", ConditionRegistry.list_conditions())
        self.assertIn("enable_more_suggest", ConditionRegistry.list_conditions())

    def test_need_summary_condition(self):
        import sagents.flow.conditions as conditions_module
        from sagents.context.messages.message import MessageChunk, MessageRole
        
        # Manually register
        ConditionRegistry.register("need_summary")(conditions_module.check_need_summary)
        
        # Mock session context
        mock_ctx = MagicMock()
        mock_msg = MagicMock(spec=MessageChunk)
        mock_msg.role = MessageRole.TOOL.value
        mock_ctx.message_manager.messages = [mock_msg]
        mock_ctx.audit_status = {"force_summary": False}
        
        # Test tool role triggers summary
        self.assertTrue(ConditionRegistry.check("need_summary", mock_ctx))
        
        # Test force_summary flag triggers summary
        mock_msg.role = MessageRole.USER.value
        mock_ctx.audit_status = {"force_summary": True}
        self.assertTrue(ConditionRegistry.check("need_summary", mock_ctx))
        
        # Test no summary needed
        mock_ctx.audit_status = {"force_summary": False}
        self.assertFalse(ConditionRegistry.check("need_summary", mock_ctx))

if __name__ == '__main__':
    unittest.main()
