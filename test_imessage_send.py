#!/usr/bin/env python3
"""
Test script for iMessage sending.
This script tests sending iMessage directly without going through the full Sage system.

Usage:
    python test_imessage_send.py "+8619075790263" "测试消息"
"""

import subprocess
import sys


def run_applescript(script: str, timeout: int = 60) -> tuple[bool, str]:
    """Run AppleScript and return (success, output_or_error)."""
    try:
        print(f"[DEBUG] Executing AppleScript:\n{script}\n")
        
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        print(f"[DEBUG] Return code: {result.returncode}")
        print(f"[DEBUG] stdout: {result.stdout.strip()}")
        print(f"[DEBUG] stderr: {result.stderr.strip()}")
        
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, error_msg
    except subprocess.TimeoutExpired:
        return False, "AppleScript execution timed out"
    except Exception as e:
        return False, str(e)


def send_imessage(phone: str, message: str) -> bool:
    """Send iMessage to the given phone number."""
    
    # Escape quotes in message
    escaped_message = message.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    
    print(f"[INFO] Sending iMessage to: {phone}")
    print(f"[INFO] Message: {message}")
    print(f"[INFO] Escaped message: {escaped_message}")
    
    # Step 1: Launch Messages if not running
    print("\n[STEP 1] Launching Messages app...")
    launch_script = '''
        tell application "Messages"
            if not running then
                launch
                delay 3
            end if
        end tell
    '''
    success, output = run_applescript(launch_script)
    print(f"[STEP 1] Result: success={success}, output={output}")
    
    # Step 2: Activate Messages
    print("\n[STEP 2] Activating Messages app...")
    activate_script = '''
        tell application "Messages"
            activate
            delay 3
        end tell
    '''
    success, output = run_applescript(activate_script)
    print(f"[STEP 2] Result: success={success}, output={output}")
    
    # Step 3: Send message
    print("\n[STEP 3] Sending message...")
    send_script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{phone}" of targetService
            send "{escaped_message}" to targetBuddy
            delay 5
            return "Message sent successfully"
        end tell
    '''
    success, output = run_applescript(send_script, timeout=60)
    print(f"[STEP 3] Result: success={success}, output={output}")
    
    return success


def main():
    if len(sys.argv) < 3:
        print("Usage: python test_imessage_send.py <phone_number> <message>")
        print("Example: python test_imessage_send.py \"+8619075790263\" \"Hello\"")
        sys.exit(1)
    
    phone = sys.argv[1]
    message = sys.argv[2]
    
    print("=" * 60)
    print("iMessage Send Test")
    print("=" * 60)
    
    success = send_imessage(phone, message)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Message sent successfully!")
    else:
        print("❌ Failed to send message")
    print("=" * 60)


if __name__ == "__main__":
    main()
