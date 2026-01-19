import re
from collections import defaultdict

log_file = "/Users/xiangtao/workspaces/Sage/server_logs.txt"

# Regex to capture timestamp, level, request_id, and the rest of the message
# Example: 2026-01-19 16:33:36,743 - INFO - [58b004c566b3] - ...
# We want to capture the content after the metadata.
# Adjusting regex to capture the message.
# Assuming standard format: DATE TIME - LEVEL - [REQ_ID] - [SESSION?] - [FILE:LINE] - MESSAGE
# But sometimes parts might be missing or different.
# Let's just find the line with ERROR and the REQ_ID, then take everything after the 3rd or 4th hyphen?
# Or simpler: split by " - " and take the last part?

# Let's stick to the structure we saw earlier:
# 2026-01-19 16:11:27,746 - ERROR - [ac30a7f41c28] - [NO_SESSION] - [exceptions.py:32] - 未处理异常: ...

log_pattern = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - \[([a-f0-9]+)\]')

request_ids = set()
error_reasons = defaultdict(int)
error_samples = defaultdict(list)

print(f"Reading {log_file}...")

try:
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            match = log_pattern.search(line)
            if match:
                timestamp, level, req_id = match.groups()
                
                if "请求参数" in line:
                    request_ids.add(req_id)
                
                if level == "ERROR":
                    # Extract the error message
                    # Split by " - " and take from the 5th element onwards if possible, or just the last part?
                    # The format seems to be: Time - Level - [ReqID] - [Session] - [File] - Message
                    parts = line.split(" - ")
                    if len(parts) >= 6:
                        msg = " - ".join(parts[5:]).strip()
                    else:
                        # Fallback if format is different
                        msg = line.strip()
                    
                    # Clean up the message to group similar errors
                    # e.g., remove specific memory addresses or variable parts if needed
                    # For now, let's keep it raw but maybe truncate if too long
                    
                    # Common pattern: "未处理异常: (pymysql.err.InterfaceError) ..."
                    # We can try to extract the exception type.
                    if "未处理异常" in msg:
                        # Try to get the exception class
                        # e.g. "未处理异常: (pymysql.err.InterfaceError) Cancelled during execution ..."
                        # We want "(pymysql.err.InterfaceError) Cancelled during execution"
                        # It might span multiple lines in the file, but here we process line by line.
                        # The log file might have the traceback on subsequent lines, but the first line usually has the summary.
                        pass

                    # Simplify message for grouping
                    # If it contains "Cancelled during execution", group as such
                    if "Cancelled during execution" in msg:
                        simple_reason = "InterfaceError: Cancelled during execution"
                    elif "Connection refused" in msg:
                         simple_reason = "Connection refused"
                    elif "timeout" in msg.lower():
                        simple_reason = "Timeout Error"
                    else:
                        # Use the first 100 chars of the message as the key
                        simple_reason = msg[:150]
                    
                    error_reasons[simple_reason] += 1
                    if len(error_samples[simple_reason]) < 3:
                        error_samples[simple_reason].append(req_id)

except FileNotFoundError:
    print(f"File not found: {log_file}")
    exit(1)

print("\nError Reason Summary:")
sorted_reasons = sorted(error_reasons.items(), key=lambda x: x[1], reverse=True)

for reason, count in sorted_reasons:
    print(f"\nReason: {reason}")
    print(f"Count: {count}")
    print(f"Sample Request IDs: {', '.join(error_samples[reason])}")
