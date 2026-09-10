import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from sagents.v2.tool.official.filesystem import (
    FileSystemTools,
    _update_operations_are_applied,
)
from sagents.v2.tool.official.filesystem import _apply_update_operations


def test_line_range_uses_1based_inclusive_bounds():
    content, summaries, count = _apply_update_operations(
        "line1\nline2\nline3\n",
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "middle",
            }
        ],
    )

    assert content == "line1\nmiddle\nline3\n"
    assert count == 1
    assert summaries[0]["replacements"] == 1


def test_line_range_replaces_first_line_as_1():
    content, _, _ = _apply_update_operations(
        "line1\nline2\nline3\n",
        [
            {
                "update_mode": "line_range",
                "start_line": 1,
                "end_line": 1,
                "replacement": "head",
            }
        ],
    )

    assert content == "head\nline2\nline3\n"


def test_line_range_rejects_zero_based_input():
    try:
        _apply_update_operations(
            "line1\nline2\n",
            [
                {
                    "update_mode": "line_range",
                    "start_line": 0,
                    "end_line": 0,
                    "replacement": "x",
                }
            ],
        )
    except ValueError as exc:
        assert "1-based" in str(exc)
        return
    raise AssertionError("expected ValueError for 0-based line_range")


def test_multiple_line_ranges_use_original_file_numbers_bottom_up():
    content, summaries, _ = _apply_update_operations(
        "a\nb\nc\nd\ne\n",
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 3,
                "replacement": "X",
            },
            {
                "update_mode": "line_range",
                "start_line": 5,
                "end_line": 5,
                "replacement": "E",
            },
        ],
    )

    assert content == "a\nX\nd\nE\n"
    assert [item["index"] for item in summaries] == [0, 1]


def test_line_ranges_run_before_search_replace():
    content, _, _ = _apply_update_operations(
        "foo\nbar\nfoo\n",
        [
            {
                "update_mode": "search_replace",
                "search_pattern": "foo",
                "replacement": "qux",
            },
            {
                "update_mode": "line_range",
                "start_line": 3,
                "end_line": 3,
                "replacement": "baz",
            },
        ],
    )

    assert content == "qux\nbar\nbaz\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("trailing", [False, True])
def test_line_updates_preserve_existing_terminators(newline, trailing):
    original = "a" + newline + "b" + (newline if trailing else "")
    replacement = "b" + (newline if trailing else "")
    updated, _, count = _apply_update_operations(
        original,
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": replacement,
            }
        ],
    )
    assert updated == original
    assert count == 0


def test_literal_replace_all_updates_every_match():
    updated, _, count = _apply_update_operations(
        "foo foo",
        [
            {
                "update_mode": "search_replace",
                "search_pattern": "foo",
                "replacement": "bar",
                "replace_all": True,
            }
        ],
    )
    assert updated == "bar bar"
    assert count == 2


def test_overlapping_original_line_ranges_are_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        _apply_update_operations(
            "a\nb\nc\nd\n",
            [
                {
                    "update_mode": "line_range",
                    "start_line": 2,
                    "end_line": 3,
                    "replacement": "B",
                },
                {
                    "update_mode": "line_range",
                    "start_line": 3,
                    "end_line": 4,
                    "replacement": "C",
                },
            ],
        )


@pytest.mark.asyncio
async def test_unchanged_update_does_not_write():
    runtime = SimpleNamespace(
        read_text=AsyncMock(return_value="a\nb\n"), write_text=AsyncMock()
    )
    result = await FileSystemTools(runtime).file_update(
        "notes.txt",
        None,
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "b\n",
            }
        ],
    )
    assert result["replacements"] == 0
    runtime.write_text.assert_not_awaited()


def test_mixed_updates_do_not_claim_unverifiable_line_evidence():
    assert not _update_operations_are_applied(
        "a\nB\n",
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "B",
            },
            {
                "update_mode": "search_replace",
                "search_pattern": "b",
                "replacement": "B",
            },
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["overwrite", "append"])
async def test_yaml_write_reports_duplicate_keys_after_successful_write(mode):
    runtime = SimpleNamespace(
        read_text=AsyncMock(return_value="a: 1\na: 2\n"), write_text=AsyncMock()
    )
    result = await FileSystemTools(runtime).file_write(
        "compose.yaml", "a: 1\na: 2\n", None, mode=mode
    )
    assert result["status"] == "success"
    assert result["validation"]["passed"] is False
    assert "duplicate key" in result["validation"]["message"]
    runtime.write_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_yaml_append_validates_whole_file_not_just_fragment():
    runtime = SimpleNamespace(
        read_text=AsyncMock(return_value="base: &base {x: 1}\ncopy: {<<: *base}\n"),
        write_text=AsyncMock(),
    )
    result = await FileSystemTools(runtime).file_write(
        "compose.yaml", "copy: {<<: *base}\n", None, mode="append"
    )
    assert result["validation"]["passed"] is True


@pytest.mark.asyncio
async def test_post_write_read_failure_does_not_report_failed_append():
    runtime = SimpleNamespace(
        read_text=AsyncMock(side_effect=PermissionError("read denied")),
        write_text=AsyncMock(),
    )
    result = await FileSystemTools(runtime).file_write(
        "compose.yaml", "a: 1\n", None, mode="append"
    )
    assert result["status"] == "success"
    assert result["validation"]["status"] == "error"
    runtime.write_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_yaml_update_reports_validation_without_hiding_success():
    runtime = SimpleNamespace(
        read_text=AsyncMock(return_value="a: 1\nb: 2\n"), write_text=AsyncMock()
    )
    result = await FileSystemTools(runtime).file_update(
        "compose.yml",
        None,
        [
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "a: 2",
            }
        ],
    )
    assert result["status"] == "success"
    assert result["validation"]["passed"] is False
    runtime.write_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_read_and_update_share_one_based_inclusive_ranges():
    runtime = SimpleNamespace(read_text=AsyncMock(return_value="a\nb\nc\n"))
    tools = FileSystemTools(runtime)
    result = await tools.file_read("notes.txt", None, start_line=2, end_line=3)
    assert result["content"].splitlines() == ["     2\tb", "     3\tc"]
    assert (result["start_line"], result["end_line"]) == (2, 3)
    with pytest.raises(ValueError, match="1-based"):
        await tools.file_read("notes.txt", None, start_line=0)
