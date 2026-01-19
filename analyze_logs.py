import re
from collections import defaultdict

log_file = "/Users/xiangtao/workspaces/Sage/server_logs.txt"

# Regex to capture timestamp, level, request_id
# Example: 2026-01-19 16:33:36,743 - INFO - [58b004c566b3] - ...
log_pattern = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - \[([a-f0-9]+)\]')

request_ids = set()
error_request_ids = set()

print(f"Reading {log_file}...")

try:
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            match = log_pattern.search(line)
            if match:
                timestamp, level, req_id = match.groups()
                
                # Check if this is a request initiation (contains "请求参数")
                if "请求参数" in line:
                    request_ids.add(req_id)
                
                # Check if this line is an ERROR
                if level == "ERROR":
                    # We track errors for ANY request ID we see, 
                    # but we'll intersect with the "请求参数" ones later 
                    # to calculate the ratio for *started* requests if needed.
                    # Or simply, if a request has an ERROR log, it's an error request.
                    error_request_ids.add(req_id)

except FileNotFoundError:
    print(f"File not found: {log_file}")
    exit(1)

# Filter error_request_ids to only include those that we saw "请求参数" for
# (Assuming we only care about requests that we saw the start of, 
# or at least the parameter logging part as per user instruction)
# User instruction: "根据...grep 请求参数 获取... 然后... grep ERROR"
# This implies the universe of requests is defined by those having "请求参数".

target_requests = request_ids
errored_target_requests = target_requests.intersection(error_request_ids)

total_requests = len(target_requests)
total_errors = len(errored_target_requests)

if total_requests == 0:
    print("No requests found with '请求参数'.")
else:
    ratio = (total_errors / total_requests) * 100
    print(f"Total Requests (with '请求参数'): {total_requests}")
    print(f"Requests with ERROR: {total_errors}")
    print(f"Error Rate: {ratio:.2f}%")
    
    if total_errors > 0:
        print("\nSample Error Request IDs:")
        for rid in list(errored_target_requests)[:5]:
            print(f"- {rid}")

