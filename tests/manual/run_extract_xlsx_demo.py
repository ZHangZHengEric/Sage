import os
import sys
import json
import types

# 保证可以导入 sagents 包（本文件在 tests/manual/ 下，需两级回到仓库根）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from sagents.tool.file_parser_tool import FileParserTool


def main():
    input_path = "/Users/zhangzheng/zavixai/4G5G吞吐量数据.xlsx"
    print(f"开始提取Excel: {input_path}")
    try:
        result = FileParserTool().extract_text_from_non_text_file(input_path)
        print(result)

        
    except Exception as e:
        import traceback
        print("提取失败:", str(e))
        print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()