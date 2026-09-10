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
