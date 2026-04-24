"""SessionContext per-request tokens 统计测试。

只验证 start_request / add_llm_request / end_request 三件套的核心流转，
不依赖沙箱与异步初始化。
"""
import json
import os

from sagents.context.session_context import SessionContext


def _make_session(tmp_path):
    ctx = SessionContext(
        session_id="sess_test",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.session_workspace = os.path.join(str(tmp_path), "sess_test")
    os.makedirs(ctx.session_workspace, exist_ok=True)
    return ctx


def _fake_request(step="exec", model="m1", prompt=10, completion=5, cached=0):
    return {
        "step_name": step,
        "model_config": {"model": model},
        "started_at": 1.0,
        "first_token_time": 1.1,
        "ttfb_sec": 0.1,
        "duration_sec": 0.5,
    }, {
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        }
    }


async def test_single_request_writes_file_with_total(tmp_path):
    ctx = _make_session(tmp_path)
    rid = ctx.start_request({"agent_mode": "simple", "model": "m1"})
    assert rid.startswith("req_")

    for _ in range(3):
        req, resp = _fake_request(prompt=10, completion=5, cached=2)
        ctx.add_llm_request(req, resp)

    file_path = ctx.end_request("completed")
    assert file_path and os.path.exists(file_path)

    data = json.loads(open(file_path, "r", encoding="utf-8").read())
    assert data["request_id"] == rid
    assert data["status"] == "completed"
    assert len(data["per_call"]) == 3
    assert data["total_usage"]["prompt_tokens"] == 30
    assert data["total_usage"]["completion_tokens"] == 15
    assert data["total_usage"]["total_tokens"] == 45
    assert data["total_usage"]["cached_tokens"] == 6


async def test_multiple_serial_requests_each_have_own_file(tmp_path):
    ctx = _make_session(tmp_path)
    files = []
    for i in range(2):
        ctx.start_request({"agent_mode": "simple"})
        req, resp = _fake_request(prompt=i + 1, completion=1)
        ctx.add_llm_request(req, resp)
        files.append(ctx.end_request("completed"))

    assert len(files) == 2 and files[0] != files[1]
    for f in files:
        assert os.path.exists(f)


async def test_nested_start_finalizes_previous_as_interrupted(tmp_path):
    ctx = _make_session(tmp_path)
    rid1 = ctx.start_request({})
    req, resp = _fake_request()
    ctx.add_llm_request(req, resp)
    rid2 = ctx.start_request({})
    assert rid1 != rid2

    prev_file = os.path.join(ctx.session_workspace, "tokens_usage", f"{rid1}.json")
    assert os.path.exists(prev_file)
    prev = json.loads(open(prev_file, "r", encoding="utf-8").read())
    assert prev["status"] == "interrupted"

    ctx.end_request("completed")


async def test_end_without_start_returns_none(tmp_path):
    ctx = _make_session(tmp_path)
    assert ctx.end_request("completed") is None
