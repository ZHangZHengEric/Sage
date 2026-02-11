import os
import re
import time
from typing import Optional
from sagents.utils.logger import logger
from sagents.context.session_context import get_session_context

def save_agent_response_content(content: str, session_id: str):
    """
    Parses agent response content, extracts markdown code blocks,
    and saves them to the session's agent workspace.
    
    Args:
        content: The full content text returned by the agent.
        session_id: The session ID to locate the workspace.
    """
    if not content or not session_id:
        return

    try:
        # Avoid circular import by importing inside function if needed, 
        # but get_session_context is already imported.
        session_context = get_session_context(session_id)
        if not session_context or not hasattr(session_context, 'agent_workspace'):
            # This is expected if session is not found or mock environment
            return
            
        host_path = getattr(session_context.agent_workspace, 'host_path', None)
        if not host_path:
            return

        # Define artifacts directory name
        ARTIFACTS_DIR = "artifacts"
        artifacts_path = os.path.join(host_path, ARTIFACTS_DIR)
        
        # Create artifacts directory if it doesn't exist
        if not os.path.exists(artifacts_path):
            try:
                os.makedirs(artifacts_path, exist_ok=True)
            except Exception as e:
                logger.error(f"SaveContent: Failed to create artifacts directory {artifacts_path}: {e}")
                return

        # Regex to match code blocks: ```language\ncode\n```
        # We capture language (optional) and code
        # Use DOTALL to match across lines
        code_block_pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
        
        matches = list(code_block_pattern.finditer(content))
        if not matches:
            return

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        
        for idx, match in enumerate(matches):
            lang = match.group(1) or ""
            code = match.group(2)
            lang = lang.lower().strip()
            
            # Determine extension and filename
            filename = ""
            ext = "txt"
            
            # Handle Markdown blocks specifically
            if lang in ['markdown', 'md']:
                ext = "md"
                # Try to get filename from first line of code
                lines = code.strip().split('\n')
                if lines:
                    first_line = lines[0].strip()
                    # Remove markdown headers if present
                    clean_line = re.sub(r'^#+\s*', '', first_line)
                    # Sanitize filename: remove invalid chars
                    clean_line = re.sub(r'[\\/*?:"<>|]', '', clean_line)
                    clean_line = clean_line.strip()
                    if clean_line:
                        # Limit length
                        clean_line = clean_line[:50]
                        filename = f"{clean_line}.md"
            
            # Handle other code blocks or if markdown filename generation failed
            if not filename:
                # Map common languages to extensions
                lang_map = {
                    'python': 'py', 'py': 'py',
                    'javascript': 'js', 'js': 'js',
                    'typescript': 'ts', 'ts': 'ts',
                    'html': 'html',
                    'css': 'css',
                    'json': 'json',
                    'bash': 'sh', 'sh': 'sh',
                    'shell': 'sh',
                    'sql': 'sql',
                    'java': 'java',
                    'cpp': 'cpp', 'c++': 'cpp',
                    'c': 'c',
                    'go': 'go',
                    'rust': 'rs',
                    'ruby': 'rb',
                    'php': 'php',
                    'swift': 'swift',
                    'kotlin': 'kt',
                    'xml': 'xml',
                    'yaml': 'yaml', 'yml': 'yaml',
                    'dockerfile': 'dockerfile',
                    'docker': 'dockerfile'
                }
                ext = lang_map.get(lang, 'txt')
                # If extension is dockerfile, filename shouldn't have .dockerfile suffix usually, but for safety use .dockerfile or just Dockerfile if singular
                if ext == 'dockerfile':
                    filename = f"Dockerfile_{timestamp_str}_{idx}"
                else:
                    # Use language name as prefix (consistent with file format)
                    prefix = lang if lang else "snippet"
                    # Sanitize prefix: c++ -> cpp, c# -> csharp
                    prefix = prefix.replace('+', 'p').replace('#', 'sharp')
                    prefix = re.sub(r'[^a-zA-Z0-9]', '', prefix)
                    if not prefix:
                        prefix = "snippet"
                    filename = f"{prefix}_{timestamp_str}_{idx}.{ext}"
            
            # Save file
            try:
                file_path = os.path.join(artifacts_path, filename)
                
                # If file exists, append suffix
                counter = 1
                while os.path.exists(file_path):
                    name_part, ext_part = os.path.splitext(filename)
                    # Handle case where filename starts with . (e.g. .gitignore) or no extension
                    if not name_part and ext_part:
                        name_part = ext_part
                        ext_part = ""
                    
                    file_path = os.path.join(artifacts_path, f"{name_part}_{counter}{ext_part}")
                    counter += 1
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(code)
                    
                logger.info(f"SaveContent: Saved extracted content to {file_path}")
            except Exception as e:
                logger.error(f"SaveContent: Failed to save file {filename}: {e}")

    except Exception as e:
        logger.error(f"SaveContent: Unexpected error: {e}")
