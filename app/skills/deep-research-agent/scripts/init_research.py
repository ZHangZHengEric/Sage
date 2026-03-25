#!/usr/bin/env python3
"""
Initialize Research Workspace
创建研究项目目录结构
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


def resolve_template_path(template_path: str) -> Path:
    """解析模板文件绝对路径"""
    path = Path(template_path).expanduser()
    if not path.is_absolute():
        print(f"Error: Template path must be absolute: {template_path}")
        sys.exit(1)
    path = path.resolve()
    if not path.exists():
        print(f"Error: Template not found: {path}")
        sys.exit(1)
    return path


def get_topic_from_path(project_path: str) -> str:
    """从路径中提取主题名称"""
    # 使用路径的最后一部分作为主题
    return Path(project_path).name


def init_research_workspace(template_path: str, project_path: str) -> str:
    """
    初始化研究工作区
    
    Args:
        template_path: 模板文件绝对路径
        project_path: 项目文件夹绝对路径
    
    Returns:
        创建的项目路径
    """
    # 获取模板路径
    template_path = resolve_template_path(template_path)
    
    # 创建项目目录
    project_dir = Path(project_path)
    
    if project_dir.exists():
        if not project_dir.is_dir():
            print(f"Error: Path exists and is not a directory: {project_dir}")
            sys.exit(1)
        if any(project_dir.iterdir()):
            print(f"Error: Directory already exists: {project_dir}")
            print("Please choose a different path or remove the existing directory.")
            sys.exit(1)
    
    # 创建目录结构
    materials_dir = project_dir / "materials"
    materials_dir.mkdir(parents=True)
    
    # 创建子目录
    (materials_dir / "raw").mkdir()
    (materials_dir / "notes").mkdir()
    
    # 读取模板并替换占位符
    template_content = template_path.read_text(encoding="utf-8")
    topic = get_topic_from_path(project_path)
    today = datetime.now().strftime("%Y-%m-%d")
    
    report_content = template_content.replace("{topic}", topic).replace("{date}", today)
    
    # 写入报告文件
    report_path = project_dir / "report.md"
    report_path.write_text(report_content, encoding="utf-8")
    
    return str(project_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Initialize a research workspace with template",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 使用行业研究模板
  python init_research.py /app/agent_workspace/session_1770980272542/agent_workspace/skills/deep-research-agent/templates/02-industry.md /app/agent_workspace/session_1770980272542/agent_workspace/research/新能源汽车市场
  
  # 使用通用模板（默认）
  python init_research.py /app/agent_workspace/session_1770980272542/agent_workspace/skills/deep-research-agent/templates/01-general.md /app/agent_workspace/session_1770980272542/agent_workspace/research/AI技术调研
  
  # 使用竞品分析模板
  python init_research.py /app/agent_workspace/session_1770980272542/agent_workspace/skills/deep-research-agent/templates/03-competitive.md /app/agent_workspace/session_1770980272542/agent_workspace/research/竞品分析报告
        """
    )
    
    parser.add_argument("template", help="Absolute template path to use")
    
    parser.add_argument(
        "project_path",
        help="Absolute path for the research project directory (will be created)"
    )
    
    args = parser.parse_args()
    
    # 确保路径是绝对路径
    project_path = os.path.abspath(args.project_path)
    
    # 创建工作区
    created_path = init_research_workspace(args.template, project_path)
    
    print(f"✓ Research workspace created: {created_path}")
    print(f"  - Report: {created_path}/report.md")
    print(f"  - Materials: {created_path}/materials/")
    print()
    print("Next steps:")
    print("  1. Review the outline in report.md")
    print("  2. Start collecting info by chapter")
    print("  3. Save valuable findings to materials/")
    print("  4. Update report.md as content gets ready")


if __name__ == "__main__":
    main()
