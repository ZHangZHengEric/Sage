#!/usr/bin/env python3
"""
Test iMessage permissions from Python environment.
"""

import subprocess
import sys


def test_permission():
    """Test if Python can access iMessage database."""
    print("Testing iMessage permissions from Python...")
    print(f"Python executable: {sys.executable}")
    print()
    
    # Test 1: Check if we can run osascript
    print("[Test 1] Running simple AppleScript...")
    result = subprocess.run(
        ["osascript", "-e", 'return "Hello from AppleScript"'],
        capture_output=True,
        text=True
    )
    print(f"  Return code: {result.returncode}")
    print(f"  Output: {result.stdout.strip()}")
    print(f"  Error: {result.stderr.strip()}")
    print()
    
    # Test 2: Check Messages app
    print("[Test 2] Checking Messages app...")
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Messages" to return running'],
        capture_output=True,
        text=True
    )
    print(f"  Return code: {result.returncode}")
    print(f"  Messages running: {result.stdout.strip()}")
    print(f"  Error: {result.stderr.strip()}")
    print()
    
    # Test 3: Try to access iMessage database
    print("[Test 3] Accessing iMessage database...")
    db_path = "/Users/caoqihang/Library/Messages/chat.db"
    script = f'do shell script "sqlite3 {db_path} \\"SELECT COUNT(*) FROM message;\\""'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10
    )
    print(f"  Return code: {result.returncode}")
    print(f"  Message count: {result.stdout.strip()}")
    print(f"  Error: {result.stderr.strip()}")
    print()
    
    # Test 4: Try to send a test message
    print("[Test 4] Sending test message...")
    result = subprocess.run(
        ["osascript", "-e", '''
            tell application "Messages"
                activate
                delay 2
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "+8619075790263" of targetService
                send "Permission test from Python" to targetBuddy
                return "Sent"
            end tell
        '''],
        capture_output=True,
        text=True,
        timeout=30
    )
    print(f"  Return code: {result.returncode}")
    print(f"  Output: {result.stdout.strip()}")
    print(f"  Error: {result.stderr.strip()}")


if __name__ == "__main__":
    test_permission()
