import json

from common.services.chat_processor import ContentProcessor


def test_clean_content_keeps_tool_content_as_json_string():
    original = {
        "role": "tool",
        "content": json.dumps(
            {
                "content": json.dumps(
                    {"status": "success", "query": "kitten", "results": []},
                    ensure_ascii=False,
                )
            },
            ensure_ascii=False,
        ),
        "tool_call_id": "call_1",
        "session_id": "parent_sub_0",
    }
    source = dict(original)

    cleaned = ContentProcessor.clean_content(source)

    assert source == original
    assert isinstance(cleaned["content"], str)
    assert json.loads(cleaned["content"]) == {
        "status": "success",
        "query": "kitten",
        "results": [],
    }


def test_clean_content_stringifies_already_dict_tool_content():
    cleaned = ContentProcessor.clean_content(
        {
            "role": "tool",
            "content": {"status": "success", "summary": "ok"},
            "tool_call_id": "call_2",
        }
    )

    assert isinstance(cleaned["content"], str)
    assert json.loads(cleaned["content"]) == {"status": "success", "summary": "ok"}
