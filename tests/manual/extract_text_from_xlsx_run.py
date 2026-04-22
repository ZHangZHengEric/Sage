#!/usr/bin/env python3
"""
在 conda 环境 zz 中测试 Sage.sagents.tool.file_parser_tool.ExcelParser.extract_text_from_xlsx：
- 验证返回的 markdown 中包含“统计月份”列
- 验证元数据 headers 包含“统计月份”
- 使用 _read_excel_to_dict 进一步确认该列值非空

运行示例：
  conda run -n zz python3 /Users/zhangzheng/zavixai/Sage/tests/test_extract_text_from_xlsx.py
"""
import os
import sys
import types

EXCEL_PATH = "/Users/zhangzheng/zavixai/4G5G吞吐量数据.xlsx"


def _inject_stubs():
    """为缺失的第三方库注入轻量 stub，避免导入 file_parser_tool 时失败。"""
    # pdfplumber stub
    try:
        import pdfplumber  # noqa: F401
    except Exception:
        mod = types.ModuleType("pdfplumber")
        class _DummyPDF:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            pages = []
        def _open(*args, **kwargs):
            return _DummyPDF()
        mod.open = _open
        sys.modules["pdfplumber"] = mod

    # pypandoc stub
    try:
        import pypandoc  # noqa: F401
    except Exception:
        mod = types.ModuleType("pypandoc")
        def _convert_file(*args, **kwargs):
            return ""
        mod.convert_file = _convert_file
        sys.modules["pypandoc"] = mod

    # pptx stub: from pptx import Presentation
    try:
        import pptx  # noqa: F401
    except Exception:
        mod = types.ModuleType("pptx")
        class Presentation:  # minimal stub
            def __init__(self, *args, **kwargs):
                pass
        mod.Presentation = Presentation
        sys.modules["pptx"] = mod

    # html2text stub
    try:
        import html2text  # noqa: F401
    except Exception:
        mod = types.ModuleType("html2text")
        class HTML2Text:
            def __init__(self):
                self.ignore_links = True
                self.bodywidth = 0
            def handle(self, content: str) -> str:
                return content
        mod.HTML2Text = HTML2Text
        sys.modules["html2text"] = mod

    # sagents.utils.logger stub，避免包初始化导致的循环导入
    try:
        import sagents.utils.logger  # noqa: F401
    except Exception:
        import logging
        # 创建分层模块：sagents -> sagents.utils -> sagents.utils.logger
        sagents_mod = sys.modules.get("sagents") or types.ModuleType("sagents")
        utils_mod = getattr(sagents_mod, "utils", None) or types.ModuleType("sagents.utils")
        logger_mod = types.ModuleType("sagents.utils.logger")
        # 简单 logger
        logging.basicConfig(level=logging.INFO)
        logger_mod.logger = logging.getLogger("sagents-test")
        # 组装层级
        utils_mod.logger = logger_mod
        sagents_mod.utils = utils_mod
        sys.modules["sagents"] = sagents_mod
        sys.modules["sagents.utils"] = utils_mod
        sys.modules["sagents.utils.logger"] = logger_mod

    # sagents.context.session_context stub，提供 SessionContext
    try:
        from sagents.context.session_context import SessionContext  # noqa: F401
    except Exception:
        sagents_mod = sys.modules.get("sagents") or types.ModuleType("sagents")
        context_mod = getattr(sagents_mod, "context", None) or types.ModuleType("sagents.context")
        session_mod = types.ModuleType("sagents.context.session_context")
        class SessionContext:  # minimal stub
            def __init__(self):
                self.session_id = "test"
        session_mod.SessionContext = SessionContext
        context_mod.session_context = session_mod
        sagents_mod.context = context_mod
        sys.modules["sagents"] = sagents_mod
        sys.modules["sagents.context"] = context_mod
        sys.modules["sagents.context.session_context"] = session_mod


def main() -> bool:
    print("🧪 测试 ExcelParser.extract_text_from_xlsx 功能")
    print("=" * 60)

    if not os.path.exists(EXCEL_PATH):
        print(f"❌ 文件不存在: {EXCEL_PATH}")
        return False

    # 确保可导入 Sage 包
    repo_root = "/Users/zhangzheng/zavixai"
    pkg_root = "/Users/zhangzheng/zavixai/Sage"
    for p in (pkg_root, repo_root):
        if p not in sys.path:
            sys.path.insert(0, p)

    # 注入第三方库 stub，避免导入失败
    _inject_stubs()

    # 导入解析器
    try:
        from Sage.sagents.tool.file_parser_tool import ExcelParser
    except Exception as e:
        print(f"❌ 导入 ExcelParser 失败: {e}")
        return False

    # 先读取原始表数据，验证‘统计月份’列非空
    try:
        data = ExcelParser._read_excel_to_dict(EXCEL_PATH)
    except Exception as e:
        print(f"❌ _read_excel_to_dict 失败: {e}")
        return False

    if not data:
        print("❌ 未读取到任何工作表数据")
        return False

    # 选择包含‘统计月份’的工作表
    target_sheet = None
    for sname, sheet_data in data.items():
        if not sheet_data:
            continue
        header = sheet_data[0]
        if "统计月份" in header:
            target_sheet = (sname, sheet_data)
            break

    if not target_sheet:
        print("❌ 未在任何工作表表头中找到‘统计月份’列")
        return False

    sname, sheet_data = target_sheet
    header = sheet_data[0]
    col_idx = header.index("统计月份")
    samples = [row[col_idx] if len(row) > col_idx else "" for row in sheet_data[1:11]]
    print(f"🧾 目标工作表: {sname}, 表头: {header}")
    print(f"🧪 ‘统计月份’样本值: {samples}")
    if not any(v and str(v).strip() for v in samples):
        print("❌ 验证失败：‘统计月份’列样本均为空")
        return False

    # 调用 extract_text_from_xlsx 并验证返回数据
    try:
        md, meta = ExcelParser.extract_text_from_xlsx(EXCEL_PATH)
    except Exception as e:
        print(f"❌ extract_text_from_xlsx 调用失败: {e}")
        return False

    print("\n📄 Markdown 预览(节选):")
    print("-" * 60)
    print(md.splitlines()[0:10])

    # 元数据校验
    sheet_meta_key = f"sheet_{sname}"
    if sheet_meta_key not in meta:
        print(f"❌ 元数据缺少关键项: {sheet_meta_key}")
        return False
    headers = meta[sheet_meta_key].get("headers", [])
    if "统计月份" not in headers:
        print("❌ 元数据 headers 未包含‘统计月份’")
        return False

    # Markdown 包含列名
    if "统计月份" not in md:
        print("❌ Markdown 中未出现‘统计月份’字样")
        return False

    print("\n🎉 验证通过：extract_text_from_xlsx 正确解析‘统计月份’列")
    return True


if __name__ == "__main__":
    ok = main()
    print("\n" + ("🎊 测试完成！" if ok else "💥 测试失败！"))
    sys.exit(0 if ok else 1)