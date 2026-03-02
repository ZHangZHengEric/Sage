#!/usr/bin/env python3
"""Test script to send iMessage via IM Server."""

import asyncio
import sys
import subprocess
sys.path.insert(0, '/Users/zhangzheng/zavixai/Sage')


async def test_send_imessage():
    """Test sending iMessage to 18910982928."""
    print("=" * 60)
    print("iMessage Send Test")
    print("=" * 60)
    
    phone_number = "18910982928"
    message = "Hello! This is a test message from Sage IM Server."
    
    print(f"Sending message to {phone_number}...")
    print(f"Message: {message}")
    print("-" * 60)
    
    # Escape quotes in content
    escaped_message = message.replace('"', '\\"').replace("'", "\\'")
    
    # AppleScript to send iMessage
    script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{phone_number}" of targetService
            send "{escaped_message}" to targetBuddy
        end tell
    '''
    
    print(f"AppleScript:\n{script}")
    print("-" * 60)
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        
        if result.returncode == 0:
            print("\n✓ Message sent successfully!")
        else:
            print(f"\n✗ Failed to send: {result.stderr}")
            print("\n可能的原因：")
            print("1. 需要在 系统设置 → 隐私与安全性 → 自动化 中允许 Terminal 控制 Messages")
            print("2. Messages 应用需要登录 iMessage 账号")
            print("3. 接收方手机号需要已经存在于通讯录中")
            
    except Exception as e:
        print(f"\n✗ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_send_imessage())
