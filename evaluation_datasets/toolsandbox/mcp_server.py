"""Business tools only; scoring and scenario administration are not MCP tools."""
from evaluation_datasets import _support
from evaluation_datasets.toolsandbox import runtime

if __name__ == '__main__':
    runtime.activate()
    _support.serve_cli(runtime, 'ToolSandbox')
