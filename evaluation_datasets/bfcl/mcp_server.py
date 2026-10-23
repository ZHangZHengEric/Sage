"""Expose only the official simulated BFCL business functions over stdio MCP."""
from evaluation_datasets import _support
from evaluation_datasets.bfcl import runtime

if __name__ == '__main__':
    runtime.activate()
    _support.serve_cli(runtime, 'BFCL')
