import pandas as pd

from sagents.utils.file_parser.parsers.excel_parser import ExcelParser


def test_parse_preserves_literal_nan_text_and_skips_blank_cells(tmp_path):
    excel_path = tmp_path / "sample.xlsx"
    pd.DataFrame(
        {
            "name": ["nan", ""],
            "value": ["", "ok"],
        }
    ).to_excel(excel_path, index=False)

    result = ExcelParser().parse(str(excel_path))

    assert result.success
    assert "第1行: nan\n" in result.text
    assert "第2行: ok\n" in result.text
    assert "第1行: nan |" not in result.text
    assert result.metadata["sheets"][0]["non_empty_cells"] == 2


def test_parse_limits_rows_with_display_counter(tmp_path):
    excel_path = tmp_path / "long.xlsx"
    pd.DataFrame({"value": range(101)}).to_excel(excel_path, index=False)

    result = ExcelParser().parse(str(excel_path))

    assert result.success
    assert "第100行: 99\n" in result.text
    assert "第101行:" not in result.text
    assert "... (还有 1 行数据)\n" in result.text
