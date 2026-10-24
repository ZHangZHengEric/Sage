from evaluation_datasets import _support
from evaluation_datasets.scienceworld import runtime

if __name__ == '__main__':
    runtime.activate()
    _support.serve_cli(runtime, 'ScienceWorld')
