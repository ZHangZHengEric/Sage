"""
LLM日志记录集成示例
演示如何在Sage框架中集成LLM请求日志记录功能
"""

import os
import sys
import uuid
from pathlib import Path

# 添加Sage路径
sys.path.append(str(Path(__file__).parent.parent.parent))

from sagents.utils.llm_request_logger import init_llm_logger, log_llm_request
from sagents.agent.planning_agent.planning_agent import PlanningAgent
from sagents.agent.observation_agent.observation_agent import ObservationAgent

class LLMLoggingDemo:
    """LLM日志记录演示类"""
    
    def __init__(self):
        # 生成会话ID
        self.session_id = str(uuid.uuid4())
        print(f"会话ID: {self.session_id}")
        
        # 初始化LLM日志记录器
        self.logger = init_llm_logger(self.session_id)
        print(f"LLM日志记录器已初始化，工作目录: {self.logger.workspace_dir}")
    
    def demo_manual_logging(self):
        """演示手动记录LLM请求"""
        print("\n=== 手动LLM日志记录演示 ===")
        
        # 模拟LLM请求
        agent_name = "PlanningAgent"
        prompt = "请帮我制定一个学习Python的计划"
        response = "我建议您按以下步骤学习Python:\n1. 学习基础语法\n2. 练习数据结构\n3. 学习面向对象编程\n4. 实践项目开发"
        
        # 记录请求
        log_file = self.logger.log_request(
            agent_name=agent_name,
            prompt=prompt,
            response=response,
            model="gpt-4",
            tokens_used=150,
            cost=0.003,
            additional_info={"demo": True, "manual": True}
        )
        
        print(f"已记录LLM请求到: {log_file}")
        
        # 再记录一个请求
        log_file2 = self.logger.log_request(
            agent_name="ObservationAgent",
            prompt="分析当前任务执行状态",
            response="当前任务进度良好，已完成3个子任务，剩余2个待处理",
            model="gpt-4",
            tokens_used=80,
            cost=0.0016
        )
        
        print(f"已记录第二个LLM请求到: {log_file2}")
    
    def demo_session_summary(self):
        """演示会话摘要功能"""
        print("\n=== 会话摘要演示 ===")
        
        summary = self.logger.get_session_summary()
        print("会话摘要:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
    
    def demo_agent_requests(self):
        """演示按智能体查询请求"""
        print("\n=== 按智能体查询请求演示 ===")
        
        planning_requests = self.logger.get_requests_by_agent("PlanningAgent")
        print(f"PlanningAgent的请求数量: {len(planning_requests)}")
        
        if planning_requests:
            print("第一个请求的详情:")
            first_request = planning_requests[0]
            print(f"  时间: {first_request['timestamp']}")
            print(f"  模型: {first_request['model']}")
            print(f"  Token数: {first_request['tokens_used']}")
            print(f"  Prompt前100字符: {first_request['prompt'][:100]}...")
    
    def demo_export_report(self):
        """演示导出会话报告"""
        print("\n=== 导出会话报告演示 ===")
        
        report_file = self.logger.export_session_report()
        print(f"会话报告已导出到: {report_file}")
        
        # 读取并显示报告的前几行
        with open(report_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print("\n报告前10行预览:")
            for i, line in enumerate(lines[:10], 1):
                print(f"{i:2d}: {line.rstrip()}")
    
    def demo_directory_structure(self):
        """演示生成的目录结构"""
        print("\n=== 目录结构演示 ===")
        
        workspace_dir = Path(self.logger.workspace_dir)
        print(f"工作目录: {workspace_dir}")
        
        if workspace_dir.exists():
            print("目录结构:")
            for root, dirs, files in os.walk(workspace_dir):
                level = root.replace(str(workspace_dir), '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    print(f"{subindent}{file}")

def main():
    """主函数"""
    print("LLM日志记录集成演示")
    print("=" * 50)
    
    # 创建演示实例
    demo = LLMLoggingDemo()
    
    # 运行各种演示
    demo.demo_manual_logging()
    demo.demo_session_summary()
    demo.demo_agent_requests()
    demo.demo_export_report()
    demo.demo_directory_structure()
    
    print("\n演示完成！")
    print(f"所有日志文件保存在: {demo.logger.workspace_dir}")

if __name__ == "__main__":
    main() 