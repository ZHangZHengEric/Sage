import unittest
from sagents.flow.schema import (
    AgentNode, SequenceNode, LoopNode, IfNode, SwitchNode, AgentFlow
)

class TestFlowSchema(unittest.TestCase):
    def test_agent_node(self):
        node = AgentNode(agent_key="test_agent", description="Test Agent")
        self.assertEqual(node.node_type, "agent")
        self.assertEqual(node.agent_key, "test_agent")
        self.assertEqual(node.description, "Test Agent")

    def test_sequence_node(self):
        step1 = AgentNode(agent_key="agent1")
        step2 = AgentNode(agent_key="agent2")
        node = SequenceNode(steps=[step1, step2])
        self.assertEqual(node.node_type, "sequence")
        self.assertEqual(len(node.steps), 2)
        self.assertIsInstance(node.steps[0], AgentNode)

    def test_loop_node(self):
        body = AgentNode(agent_key="worker")
        node = LoopNode(body=body, condition="is_running", max_loops=5)
        self.assertEqual(node.node_type, "loop")
        self.assertEqual(node.condition, "is_running")
        self.assertEqual(node.max_loops, 5)
        self.assertIsInstance(node.body, AgentNode)

    def test_if_node(self):
        true_branch = AgentNode(agent_key="true_agent")
        false_branch = AgentNode(agent_key="false_agent")
        node = IfNode(
            condition="check_ok",
            true_body=true_branch,
            false_body=false_branch
        )
        self.assertEqual(node.node_type, "if")
        self.assertEqual(node.condition, "check_ok")
        self.assertIsInstance(node.true_body, AgentNode)
        self.assertIsInstance(node.false_body, AgentNode)

    def test_switch_node(self):
        case1 = AgentNode(agent_key="case1")
        default = AgentNode(agent_key="default")
        node = SwitchNode(
            variable="mode",
            cases={"1": case1},
            default=default
        )
        self.assertEqual(node.node_type, "switch")
        self.assertEqual(node.variable, "mode")
        self.assertIn("1", node.cases)
        self.assertIsInstance(node.default, AgentNode)

    def test_agent_flow_serialization(self):
        # Test complex flow serialization/deserialization
        flow = AgentFlow(
            name="Test Flow",
            root=SequenceNode(steps=[
                AgentNode(agent_key="start"),
                IfNode(
                    condition="is_ok",
                    true_body=AgentNode(agent_key="success"),
                    false_body=AgentNode(agent_key="retry")
                )
            ])
        )
        
        json_data = flow.model_dump_json()
        restored_flow = AgentFlow.model_validate_json(json_data)
        
        self.assertEqual(restored_flow.name, "Test Flow")
        self.assertIsInstance(restored_flow.root, SequenceNode)
        self.assertEqual(len(restored_flow.root.steps), 2)
        self.assertIsInstance(restored_flow.root.steps[1], IfNode)

if __name__ == '__main__':
    unittest.main()
