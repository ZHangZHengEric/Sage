"""iMessage notification listener for macOS.

This module listens to macOS notifications to receive incoming iMessage messages.
Requires macOS 10.14+ and notification access permission.
"""

import asyncio
import subprocess
import re
import time
import threading
from datetime import datetime
from typing import Callable, Optional, Dict, Any
from pathlib import Path


class iMessageNotificationListener:
    """Listen to iMessage notifications on macOS."""
    
    def __init__(self, message_handler: Callable[[Dict[str, Any]], None]):
        """
        Initialize the listener.
        
        Args:
            message_handler: Callback function when new message is received
                            Receives dict with: sender, content, timestamp
        """
        self.message_handler = message_handler
        self.running = False
        self.listener_thread: Optional[threading.Thread] = None
        self._last_messages: Dict[str, str] = {}  # Deduplication cache
        
    def start(self):
        """Start listening to notifications."""
        if self.running:
            return
            
        self.running = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        
    def stop(self):
        """Stop listening."""
        self.running = False
        
    def _listen_loop(self):
        """Main listening loop using AppleScript to poll notifications."""
        while self.running:
            try:
                # Use AppleScript to check recent notifications
                # This requires notification access permission
                script = '''
                    tell application "System Events"
                        tell process "NotificationCenter"
                            try
                                set notifGroups to groups of UI element 1 of scroll area 1 of window "Notification Center"
                                set results to {}
                                repeat with notifGroup in notifGroups
                                    try
                                        set notifTitle to value of static text 1 of notifGroup
                                        set notifBody to value of static text 2 of notifGroup
                                        if notifTitle contains "消息" or notifTitle contains "iMessage" or notifTitle contains "Messages" then
                                            set end of results to {title:notifTitle, body:notifBody}
                                        end if
                                    end try
                                end repeat
                                return results
                            on error
                                return {}
                            end try
                        end tell
                    end tell
                '''
                
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    self._parse_notifications(result.stdout)
                    
            except Exception:
                # Silent fail - notifications might not be accessible
                pass
                
            time.sleep(2)  # Poll every 2 seconds
            
    def _parse_notifications(self, output: str):
        """Parse notification output and extract messages."""
        # Parse AppleScript record format
        # Example: {title:"John", body:"Hello"}
        pattern = r'\{title:"([^"]+)",\s*body:"([^"]*)"\}'
        matches = re.findall(pattern, output)
        
        for sender, content in matches:
            # Deduplication check
            msg_key = f"{sender}:{content}"
            if msg_key in self._last_messages:
                continue
            self._last_messages[msg_key] = datetime.now().isoformat()
            
            # Clean old cache (keep last 100)
            if len(self._last_messages) > 100:
                oldest = sorted(self._last_messages.items(), key=lambda x: x[1])[:50]
                for key, _ in oldest:
                    del self._last_messages[key]
            
            # Call handler
            self.message_handler({
                "sender": sender,
                "content": content,
                "timestamp": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": "imessage"
            })


class iMessageDatabasePoller:
    """Poll iMessage database for new messages (alternative method)."""

    def __init__(
        self,
        message_handler: Callable[[Dict[str, Any]], None],
        allowed_senders: Optional[list] = None
    ):
        self.message_handler = message_handler
        self.allowed_senders = allowed_senders or []
        self.running = False
        self.poller_thread: Optional[threading.Thread] = None
        # 初始化为当前最大 ROWID，避免获取历史消息
        self._last_row_id = self._get_current_max_row_id()

    def _get_current_max_row_id(self) -> int:
        """获取当前数据库中的最大 ROWID，用于避免获取历史消息"""
        try:
            db_path = Path.home() / "Library" / "Messages" / "chat.db"
            if not db_path.exists():
                return 0

            script = f'''
                do shell script "sqlite3 {db_path} \\"
                    SELECT MAX(ROWID) FROM message;\\""
            '''

            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip():
                max_row_id = int(result.stdout.strip())
                import logging
                logger = logging.getLogger("iMessagePoller")
                logger.info(f"[iMessage] Initialized with max ROWID: {max_row_id}")
                return max_row_id
        except Exception as e:
            import logging
            logger = logging.getLogger("iMessagePoller")
            logger.warning(f"[iMessage] Failed to get max ROWID: {e}")

        return 0

    def _is_sender_allowed(self, sender: str) -> bool:
        """Check if sender is in allowed list."""
        if not self.allowed_senders:
            return True

        def normalize(value: str) -> str:
            value = value.strip().lower()
            if '@' in value:
                return value
            # For phone numbers: remove all non-digit characters
            digits = ''.join(c for c in value if c.isdigit())
            # Remove leading country code
            if digits.startswith('86') and len(digits) > 10:
                digits = digits[2:]
            return digits

        normalized_sender = normalize(sender)

        for allowed in self.allowed_senders:
            normalized_allowed = normalize(allowed)
            if normalized_sender == normalized_allowed:
                return True
            # For phone numbers: also check partial match
            if '@' not in normalized_sender and '@' not in normalized_allowed:
                if normalized_sender in normalized_allowed or normalized_allowed in normalized_sender:
                    return True

        return False
        
    def start(self):
        """Start polling database."""
        if self.running:
            return
            
        self.running = True
        self.poller_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poller_thread.start()
        
    def stop(self):
        """Stop polling."""
        self.running = False
        
    def _poll_loop(self):
        """Poll chat.db for new messages."""
        import logging
        logger = logging.getLogger("iMessagePoller")
        
        db_path = Path.home() / "Library" / "Messages" / "chat.db"
        
        logger.info(f"[iMessage] Starting database poller, checking path: {db_path}")
        logger.info(f"[iMessage] Allowed senders: {self.allowed_senders}")
        logger.info(f"[iMessage] Last row ID: {self._last_row_id}")
        
        if not db_path.exists():
            logger.error(f"[iMessage] Database not found at {db_path}")
            return
        
        # Check if we can read the database (Full Disk Access permission)
        try:
            test_script = f'do shell script "ls -la {db_path}"'
            result = subprocess.run(
                ["osascript", "-e", test_script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                logger.error("[iMessage] Cannot access database. Please grant Full Disk Access permission in System Settings > Privacy & Security > Full Disk Access.")
                logger.error(f"[iMessage] Error: {result.stderr}")
                return
            else:
                logger.info("[iMessage] Database access OK")
        except Exception as e:
            logger.error(f"[iMessage] Error checking database access: {e}")
            return
        
        logger.info("[iMessage] Database found and accessible, starting poll loop")
            
        while self.running:
            try:
                # Query for new messages
                # This requires Full Disk Access permission
                script = f'''
                    do shell script "sqlite3 {db_path} \\"
                        SELECT m.ROWID, h.id, m.text, m.date 
                        FROM message m 
                        JOIN handle h ON m.handle_id = h.ROWID 
                        WHERE m.ROWID > {self._last_row_id} 
                        AND m.is_from_me = 0 
                        ORDER BY m.ROWID DESC 
                        LIMIT 10;\\""
                '''
                
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    if result.stdout.strip():
                        lines = result.stdout.strip().split("\n")
                        logger.info(f"[iMessage] Found {len(lines)} new messages")
                        for line in lines:
                            parts = line.split("|")
                            if len(parts) >= 3:
                                row_id = int(parts[0])
                                sender_id = parts[1]  # Phone number or email
                                content = parts[2]
                                
                                if row_id > self._last_row_id:
                                    self._last_row_id = row_id
                                
                                # Check if sender is allowed
                                if self.allowed_senders and not self._is_sender_allowed(sender_id):
                                    logger.info(f"[iMessage] Ignoring message from non-allowed sender: {sender_id}")
                                    continue
                                
                                # Note: iMessage database only stores phone/email, not contact names
                                # Contact names are stored in macOS Contacts app, which requires separate access
                                logger.info(f"[iMessage] New message from {sender_id}: {content[:50]}...")
                                msg_data = {
                                    "sender": sender_id,  # Phone number or email
                                    "sender_name": None,  # Not available in iMessage database
                                    "content": content,
                                    "timestamp": datetime.now().astimezone().isoformat(),
                                    "provider": "imessage",
                                    "row_id": row_id
                                }
                                # Handle async message handler
                                try:
                                    result = self.message_handler(msg_data)
                                    if asyncio.iscoroutine(result):
                                        # Create event loop if needed
                                        try:
                                            loop = asyncio.get_event_loop()
                                            if loop.is_running():
                                                loop.create_task(result)
                                            else:
                                                loop.run_until_complete(result)
                                        except RuntimeError:
                                            loop = asyncio.new_event_loop()
                                            asyncio.set_event_loop(loop)
                                            loop.run_until_complete(result)
                                            loop.close()
                                except Exception as e:
                                    logger.error(f"[iMessage] Error in message_handler: {e}", exc_info=True)
                else:
                    if "authorization" in result.stderr.lower() or "permission" in result.stderr.lower():
                        logger.error(f"[iMessage] Permission denied accessing {db_path}. Please grant Full Disk Access to your Terminal/IDE in System Settings > Privacy & Security > Full Disk Access.")
                        # Stop the loop to avoid flooding logs and CPU
                        logger.info("[iMessage] Stopping poller due to permission denied. Please restart the application after granting permission.")
                        self.running = False
                        break
                    else:
                        logger.debug(f"[iMessage] Query returned no results or error: {result.stderr}")
                            
            except Exception as e:
                logger.error(f"[iMessage] Error polling database: {e}")
                
            time.sleep(3)  # Poll every 3 seconds
