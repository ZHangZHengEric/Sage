import json
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union
import time

def recent_modified_subdirs_by_tools_usage(
    root_dir: Union[str, Path],
    days: int = 7,
    base_time_ts: Optional[int] = None,
) -> List[str]:

    if base_time_ts is None:
        base_time_ts = int(time.time())
    
    root = Path(root_dir)
    cutoff_ts = base_time_ts - int(timedelta(days=days).total_seconds())

    result: List[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        p = child / "tools_usage.json"
        try:
            if p.is_file() and int(p.stat().st_mtime) >= cutoff_ts:
                result.append(str(child))
        except (FileNotFoundError, PermissionError):
            continue
    return result

def read_tools_usage(subdir_path: Union[str, Path]) -> Dict[str, int]:
    p = Path(subdir_path) / "tools_usage.json"
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): int(v) for k, v in data.items()}

def read_tools_usage_batch(subdirs):
    result = []
    for d in subdirs:
        usage = read_tools_usage(d)
        if usage:
            result.append(usage)
    return result

def merge_usage_dicts(items):
    total = {}
    for d in items:
        for k, v in d.items():
            total[k] = total.get(k, 0) + int(v)
    return total

def analyze_tools_usage(root_dir: Union[str, Path], days: int = 7, base_time_ts: Optional[int] = None) -> List[Dict[str, int]]:
    subdirs = recent_modified_subdirs_by_tools_usage(root_dir, days, base_time_ts)
    usage_dicts = read_tools_usage_batch(subdirs)
    total_usage = merge_usage_dicts(usage_dicts)
    return total_usage