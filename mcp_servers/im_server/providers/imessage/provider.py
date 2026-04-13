"""iMessage IM provider for macOS.

This provider uses AppleScript to interact with iMessage on macOS.
Note: iMessage doesn't support webhooks for incoming messages, so this is send-only.
"""

import subprocess
import platform
import logging
import asyncio
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

    async def _run_applescript(self, script: str) -> tuple[bool, str]:
        """Run AppleScript and return (success, output_or_error)."""
        try:
            # Log the script for debugging (truncated if too long)
            script_preview = script[:200] + "..." if len(script) > 200 else script
            logger.debug(f"[iMessage] Executing AppleScript: {script_preview}")

            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            result_stdout = stdout.decode().strip() if stdout else ""
            result_stderr = stderr.decode().strip() if stderr else ""

            logger.debug(f"[iMessage] AppleScript returncode: {proc.returncode}")
            logger.debug(f"[iMessage] AppleScript stdout: {result_stdout}")
            logger.debug(f"[iMessage] AppleScript stderr: {result_stderr}")
            
            if proc.returncode == 0:
                return True, result_stdout
            else:
                error_msg = result_stderr
                if not error_msg and result_stdout:
                    error_msg = result_stdout
                return False, error_msg
        except asyncio.TimeoutError:
            logger.error("[iMessage] AppleScript execution timed out")
            return False, "AppleScript execution timed out"
        except Exception as e:
            logger.error(f"[iMessage] AppleScript execution error: {e}")
            return False, str(e)

    def _normalize_phone_for_send(self, user_id: str) -> str:
        """
        Normalize phone number for iMessage sending.
        
        iMessage requires phone numbers to be in international format (+86xxxxxxxxxxx)
        for reliable delivery. This method adds +86 prefix for Chinese phone numbers.
        
        Args:
            user_id: Phone number or email address
            
        Returns:
            Normalized phone number or original email
        """
        # If it's an email, return as-is
        if '@' in user_id:
            return user_id
        
        # Remove all non-digit characters
        digits = ''.join(c for c in user_id if c.isdigit())
        
        # If already has country code (+86), return as +86...
        if digits.startswith('86') and len(digits) == 13:
            return f"+{digits}"
        
        # If it's a Chinese mobile number (11 digits, starts with 1), add +86
        if len(digits) == 11 and digits.startswith('1'):
            return f"+86{digits}"
        
        # Otherwise return original (might be landline or other format)
        return user_id

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

        # Normalize phone number for sending (add +86 for Chinese numbers)
        normalized_user_id = self._normalize_phone_for_send(user_id)
        if normalized_user_id != user_id:
            logger.info(f"[iMessage] Normalized recipient from '{user_id}' to '{normalized_user_id}'")

        # Escape quotes and special characters to prevent AppleScript injection
        escaped_content = content.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        # Remove control characters that might break AppleScript
        escaped_content = ''.join(char for char in escaped_content if ord(char) >= 32 or char in '\n\r\t')
        
        logger.info(f"[iMessage] Sending message to {normalized_user_id}, content length: {len(escaped_content)}")
        
        # Ensure Messages app is running and activated
        logger.info("[iMessage] Ensuring Messages app is running...")
        
        # Step 1: Launch Messages if not running
        launch_script = '''
            tell application "Messages"
                if not running then
                    launch
                    delay 3
                end if
            end tell
        '''
        await self._run_applescript(launch_script)
        
        # Step 2: Activate Messages and wait
        activate_script = '''
            tell application "Messages"
                activate
                delay 3
            end tell
        '''
        activate_success, activate_output = await self._run_applescript(activate_script)
        if not activate_success:
            logger.warning(f"[iMessage] Failed to activate Messages app: {activate_output}")
        
        # AppleScript to send iMessage with better error handling
        # Note: delay after sending is important for message delivery status
        script = f'''
            tell application "Messages"
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "{normalized_user_id}" of targetService
                send "{escaped_content}" to targetBuddy
                delay 5
                return "Message sent successfully"
            end tell
        '''

        logger.info(f"[iMessage] AppleScript:\n{script}")
        success, output = await self._run_applescript(script)
        logger.info(f"[iMessage] AppleScript result: success={success}, output={output}")
        
        if success:
            logger.info(f"[iMessage] Message sent successfully to {normalized_user_id}")
            return {"success": True, "message_id": output}
        else:
            logger.error(f"[iMessage] Failed to send message to {normalized_user_id}: {output}")
            
            # Try alternative format if first attempt failed
            if normalized_user_id != user_id and normalized_user_id.startswith('+86'):
                logger.info(f"[iMessage] Retrying with original format: {user_id}")
                script = f'''
                    tell application "Messages"
                        set targetService to 1st service whose service type = iMessage
                        set targetBuddy to buddy "{user_id}" of targetService
                        send "{escaped_content}" to targetBuddy
                        delay 5
                        return "Message sent successfully (original format)"
                    end tell
                '''
                logger.info(f"[iMessage] Retry AppleScript:\n{script}")
                success, output = await self._run_applescript(script)
                logger.info(f"[iMessage] Retry result: success={success}, output={output}")
                if success:
                    logger.info(f"[iMessage] Message sent successfully with original format")
                    return {"success": True, "message_id": output}
            
            return {"success": False, "error": output}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """iMessage doesn't support webhooks, so this always returns False."""
        return False

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """iMessage doesn't support incoming webhooks, so this returns None."""
        return None

    async def get_chat_history(
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
        
        success, output = await self._run_applescript(script)
        
        if success:
            # Parse the AppleScript list output
            messages = [msg.strip() for msg in output.split(",") if msg.strip()]
            return {"success": True, "messages": messages}
        else:
            return {"success": False, "error": output}

    async def _check_availability_async(self) -> Dict[str, Any]:
        """Check if iMessage is available and configured.
        
        Returns:
            Dict with availability status and details
        """
        script = '''
            tell application "Messages"
                return enabled of 1st service whose service type = iMessage
            end tell
        '''
        
        success, output = await self._run_applescript(script)
        
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

    async def check_availability(self) -> Dict[str, Any]:
        """Synchronous wrapper for startup checks."""
        return await self._check_availability_async()
