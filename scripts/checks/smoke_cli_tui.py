"""Execute CLI and PTY terminal tasks against a local deterministic model.

Run with the project's Python environment after building sage-terminal.
By default no external model credentials or network requests are used.
Use --app-model to test both default v2 clients against the APP's real default model.
"""
from __future__ import annotations

import fcntl
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
MARKER = "SAGE_SMOKE_TASK_COMPLETED"
TASK = "Return the completion marker."


class ModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/responses"):
            self.server.requests += 1
            events = [
                {"type": "response.output_text.delta", "delta": MARKER[:8], "output_index": 0, "content_index": 0},
                {"type": "response.output_text.delta", "delta": MARKER[8:], "output_index": 0, "content_index": 0},
                {"type": "response.completed", "response": {"id": "smoke-response", "status": "completed",
                 "output": [], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
            ]
            body = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                           for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        self.server.requests += 1
        if request.get("stream"):
            chunks = [
                {"index": 0, "delta": {"role": "assistant", "content": MARKER[:8]}, "finish_reason": None},
                {"index": 0, "delta": {"content": MARKER[8:]}, "finish_reason": None},
                {"index": 0, "delta": {}, "finish_reason": "stop"},
            ]
            payload = "".join("data: " + json.dumps({
                "id": "smoke-response", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": "smoke-model", "choices": [choice],
            }) + "\n\n" for choice in chunks) + "data: [DONE]\n\n"
            content_type = "text/event-stream"
        else:
            payload = json.dumps({
                "id": "smoke-response", "object": "chat.completion", "created": int(time.time()),
                "model": "smoke-model", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": MARKER}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
            content_type = "application/json"
        body = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_env(workspace: Path, endpoint: str) -> dict[str, str]:
    # Each case owns its configuration and storage; repository .env is not loaded.
    env = {k: v for k, v in os.environ.items() if not k.startswith("SAGE_")}
    launcher = workspace / "sage-smoke"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import os\nfrom pathlib import Path\n"
        "os.chdir(Path(__file__).resolve().parent)\n"
        "from app.clients.cli.main import main\nraise SystemExit(main())\n"
    )
    launcher.chmod(0o755)
    env.update({
        "PYTHONPATH": str(ROOT), "SAGE_PYTHON": sys.executable,
        "SAGE_TERMINAL_RUNTIME_ROOT": str(ROOT),
        "SAGE_TERMINAL_CLI": str(launcher),
        "SAGE_TERMINAL_STATE_ROOT": str(workspace / "terminal-state"),
        "SAGE_LOCAL_DATA_ROOT": str(workspace / "data"),
        "SAGE_DB_TYPE": "file", "SAGE_DB_FILE": str(workspace / "terminal-state/sage.db"),
        "SAGE_DEFAULT_LLM_API_KEY": "local-smoke-key",
        "SAGE_DEFAULT_LLM_API_BASE_URL": endpoint,
        "SAGE_DEFAULT_LLM_MODEL_NAME": "smoke-model",
        "SAGE_CLI_USER_ID": "smoke-user", "TERM": "xterm-256color",
    })
    return env


def configure_v1_provider(workspace: Path, env: dict[str, str]):
    result = subprocess.run(
        [sys.executable, "-m", "app.clients.cli.main", "v1", "provider", "create", "--set-default", "--json"],
        cwd=workspace, env=env, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def cli_case(workspace: Path, env: dict[str, str], version: str):
    args = [sys.executable, "-m", "app.clients.cli.main"]
    if version == "v1":
        args += ["v1"]
    args += ["run", TASK, "--json", "--workspace", str(workspace)]
    if version == "v1":
        args += ["--agent-mode", "simple", "--sandbox-type", "local"]
    else:
        args += ["--session-root", str(workspace / "runtime")]
    result = subprocess.run(args, cwd=workspace, env=env, input="", capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    if version == "v2":
        assert any(row.get("type") == "cli_v2_result" and row.get("state") == "completed"
                   and MARKER in row.get("final_text", "") for row in rows), result.stdout + result.stderr
    else:
        replies: dict[str, str] = {}
        for row in rows:
            if row.get("role") == "assistant" and row.get("type") == "do_subtask_result":
                message_id = row.get("message_id", "")
                replies[message_id] = replies.get(message_id, "") + (row.get("content") or "")
        assert any(MARKER in reply for reply in replies.values()), result.stdout + result.stderr
    print(f"CLI {version}: task completed", flush=True)


def tui_case(workspace: Path, env: dict[str, str], version: str):
    args = [sys.executable, "-m", "app.clients.cli.main", "tui",
            "--workspace", str(workspace)]
    if version == "v1":
        args += ["--runtime", "v1", "--agent-mode", "simple", "--sandbox-type", "local"]
    args += ["run", TASK]
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
    process = subprocess.Popen(args, cwd=workspace, env=env, stdin=slave, stdout=slave, stderr=slave,
                               start_new_session=True)
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 45
    completed = False
    try:
        while time.monotonic() < deadline and process.poll() is None:
            if not select.select([master], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            output.extend(chunk)
            if b"\x1b[6n" in chunk:
                os.write(master, b"\x1b[1;1R")
            rendered = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output.decode(errors="replace"))
            # Require the completed transcript summary; session metadata can arrive
            # before the assistant stream and does not prove Finished was handled.
            marker_at = rendered.rfind(MARKER)
            if marker_at >= 0 and "completed •" in rendered[marker_at:] and "ready" in rendered[marker_at:]:
                completed = True
                break
        assert completed, output.decode(errors="replace")[-12000:]
        os.write(master, b"\x03")
        # Keep draining the PTY while the terminal redraws/restores on exit.
        # Waiting without reading can block a writer on the PTY's small buffer.
        exit_deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < exit_deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        process.wait(timeout=1)
        assert process.returncode == 0, process.returncode
        print(f"TUI {version}: task completed and terminal exited cleanly", flush=True)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        os.close(master)


def app_model_env(workspace: Path) -> dict[str, str]:
    env = test_env(workspace, "unused")
    for key in ("SAGE_DEFAULT_LLM_API_KEY", "SAGE_DEFAULT_LLM_API_BASE_URL", "SAGE_DEFAULT_LLM_MODEL_NAME"):
        env.pop(key, None)
    env["SAGE_CLI_USER_ID"] = os.environ.get("SAGE_CLI_USER_ID") or os.environ.get("SAGE_DESKTOP_USER_ID") or "default_user"
    if os.environ.get("SAGE_DESKTOP_DATA_ROOT"):
        env["SAGE_DESKTOP_DATA_ROOT"] = os.environ["SAGE_DESKTOP_DATA_ROOT"]
    return env


def live_app_main():
    global MARKER, TASK
    MARKER = "SAGE_LIVE_437"
    TASK = "Calculate 19 times 23, then return SAGE_LIVE_ followed by the answer. No explanation or tools."
    with tempfile.TemporaryDirectory(prefix="sage-app-model-smoke-") as folder:
        for kind, case in (("cli", cli_case), ("tui", tui_case)):
            workspace = Path(folder) / kind
            workspace.mkdir()
            case(workspace, app_model_env(workspace), "v2")
    print("Both default v2 clients passed with the APP default model.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-model", action="store_true", help="Use the APP's configured real default model")
    if parser.parse_args().app_model:
        live_app_main()
        return
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    server.requests = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="sage-cli-tui-smoke-") as folder:
            for kind, case in (("cli", cli_case), ("tui", tui_case)):
                for version in ("v1", "v2"):
                    workspace = Path(folder) / f"{kind}-{version}"
                    workspace.mkdir()
                    env = test_env(workspace, f"http://127.0.0.1:{server.server_port}/v1")
                    if version == "v1":
                        configure_v1_provider(workspace, env)
                    case(workspace, env, version)
            # Test catalog discovery through both public v2 entry points as well.
            for protocol, kind, case in (
                (protocol, kind, case)
                for protocol in ("openai-chat-completions", "openai-responses")
                for kind, case in (("cli", cli_case), ("tui", tui_case))
            ):
                workspace = Path(folder) / f"app-{protocol}-{kind}"
                workspace.mkdir()
                env = app_model_env(workspace)
                app_root = workspace / "app-data"
                (app_root / "runtime").mkdir(parents=True)
                (app_root / "runtime" / "desktop-catalog.json").write_text(json.dumps({
                    "format_version": "sage.desktop-catalog/v2",
                    "model_providers": [{"user_id": env["SAGE_CLI_USER_ID"], "is_default": True,
                                         "protocol": protocol, "model": "smoke-model",
                                         "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                                         "api_key": "catalog-smoke-key"}],
                }))
                env["SAGE_DESKTOP_DATA_ROOT"] = str(app_root)
                case(workspace, env, "v2")
        assert server.requests >= 8, server.requests
        print("All four runtime paths and four APP catalog/protocol task paths passed.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
