"""iMessage IM provider for macOS.

This provider uses AppleScript to interact with iMessage on macOS.
Note: iMessage doesn't support webhooks for incoming messages, so this is send-only.
"""

import subprocess
import platform
import logging
from typing import Optional, Dict, Any

from ..base import IMProviderBase

logger = logging.getLogger("iMessageProvider")


class iMessageProvider(IMProviderBase):
    """iMessage provider for macOS using AppleScript."""

    PROVIDER_NAME = "imessage"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Check if running on macOS
        if platform.system() != "Darwin":
            raise RuntimeError("iMessage provider is only available on macOS")
        
        # Whitelist of allowed phone numbers/emails
        # If empty, all incoming messages are accepted
        self.allowed_senders = config.get("allowed_senders", [])
        
    def is_sender_allowed(self, sender: str) -> bool:
        """
        Check if sender is in whitelist.
        
        Args:
            sender: Phone number or email address
            
        Returns:
            True if allowed, False otherwise
        """
        logger.info(f"[iMessage] Checking if sender '{sender}' is allowed. Whitelist: {self.allowed_senders}")
        
        # If no whitelist configured, allow all
        if not self.allowed_senders:
            logger.info("[iMessage] No whitelist configured, allowing all senders")
            return True
        
        # Normalize sender: remove all non-digit characters for phone numbers
        # Keep email as-is (case-insensitive)
        def normalize(value: str) -> str:
            value = value.strip().lower()
            # If it's an email, return as-is
            if '@' in value:
                return value
            # For phone numbers: remove all non-digit characters
            digits = ''.join(c for c in value if c.isdigit())
            # Remove leading country code (86, +86, etc.) for comparison
            if digits.startswith('86') and len(digits) > 10:
                digits = digits[2:]
            return digits
        
        normalized_sender = normalize(sender)
        logger.info(f"[iMessage] Normalized sender '{sender}' -> '{normalized_sender}'")
        
        for allowed in self.allowed_senders:
            normalized_allowed = normalize(allowed)
            logger.debug(f"[iMessage] Comparing '{normalized_sender}' with '{normalized_allowed}'")
            
            # Exact match
            if normalized_sender == normalized_allowed:
                logger.info(f"[iMessage] Sender '{sender}' is in whitelist (exact match)")
                return True
            
            # For phone numbers: also check if one contains the other
            # This handles cases like: 13800138000 vs 8613800138000
            if '@' not in normalized_sender and '@' not in normalized_allowed:
                if normalized_sender in normalized_allowed or normalized_allowed in normalized_sender:
                    logger.info(f"[iMessage] Sender '{sender}' is in whitelist (partial match)")
                    return True
                
        logger.info(f"[iMessage] Sender '{sender}' is NOT in whitelist, ignoring message")
        return False

    def _run_applescript(self, script: str) -> tuple[bool, str]:
        """Run AppleScript and return (success, output_or_error)."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "AppleScript execution timed out"
        except Exception as e:
            return False, str(e)

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via iMessage.
        
        Args:
            content: Message content
            chat_id: Not used for iMessage (use user_id instead)
            user_id: Phone number or email address of the recipient
            msg_type: Only "text" is supported
            
        Returns:
            Dict with success status and error message if failed
        """
        if not user_id:
            return {"success": False, "error": "user_id (phone/email) is required"}

        # Escape quotes in content to prevent AppleScript injection
        escaped_content = content.replace('"', '\\"').replace("'", "\\'")
        
        # AppleScript to send iMessage
        script = f'''
            tell application "Messages"
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "{user_id}" of targetService
                send "{escaped_content}" to targetBuddy
            end tell
        '''

        success, output = self._run_applescript(script)
        
        if success:
            return {"success": True, "message_id": output}
        else:
            return {"success": False, "error": output}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """iMessage doesn't support webhooks, so this always returns False."""
        return False

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """iMessage doesn't support incoming webhooks, so this returns None."""
        return None

    def get_chat_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get chat history with a specific contact.
        
        Note: This requires Full Disk Access permission for the Terminal/app.
        
        Args:
            user_id: Phone number or email address
            limit: Maximum number of messages to retrieve
            
        Returns:
            Dict with success status and list of messages
        """
        script = f'''
            tell application "Messages"
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "{user_id}" of targetService
                set messageList to {{}}
                repeat with msg in (get texts of targetBuddy)
                    set end of messageList to (text of msg as string)
                    if length of messageList >= {limit} then exit repeat
                end repeat
                return messageList
            end tell
        '''
        
        success, output = self._run_applescript(script)
        
        if success:
            # Parse the AppleScript list output
            messages = [msg.strip() for msg in output.split(",") if msg.strip()]
            return {"success": True, "messages": messages}
        else:
            return {"success": False, "error": output}

    def check_availability(self) -> Dict[str, Any]:
        """Check if iMessage is available and configured.
        
        Returns:
            Dict with availability status and details
        """
        script = '''
            tell application "Messages"
                return enabled of 1st service whose service type = iMessage
            end tell
        '''
        
        success, output = self._run_applescript(script)
        
        if success and output == "true":
            return {
                "success": True,
                "available": True,
                "message": "iMessage is available and enabled"
            }
        else:
            return {
                "success": False,
                "available": False,
                "error": "iMessage is not available or not enabled"
            }
