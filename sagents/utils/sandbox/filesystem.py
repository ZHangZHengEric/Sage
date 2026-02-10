import os
import re
from typing import List, Optional

class SandboxFileSystem:
    """
    Represents the file system within the sandbox environment.
    It manages the mapping between the host file system and the virtual sandbox path,
    providing a safe view of the file tree for the agent.
    """
    def __init__(self, host_path: str, virtual_path: str = "/workspace", enable_path_mapping: bool = True):
        self.host_path = host_path
        self.virtual_path = virtual_path
        self.enable_path_mapping = enable_path_mapping

    def get_file_tree(self, include_hidden: bool = False) -> str:
        """
        Returns a formatted string of the file tree relative to the virtual root.
        This safely exposes the structure of the sandbox file system to the agent.
        
        Args:
            include_hidden: Whether to include hidden files (starting with .) in the tree.
                            Note: Sensitive directories like .sandbox, .git are always excluded.
        
        Example output:
        file1.txt
        dir1/
        dir1/file2.txt
        """
        system_prefix = ""
        if not os.path.exists(self.host_path):
            return system_prefix
            
        # Directories that are always hidden regardless of include_hidden
        ALWAYS_HIDDEN_DIRS = {'.sandbox', '.git', '.idea', '.vscode', '__pycache__', 'node_modules', 'venv', '.DS_Store'}

        for root, dirs, files in os.walk(self.host_path):
            # Filter directories
            # 1. Always exclude ALWAYS_HIDDEN_DIRS
            # 2. If include_hidden is False, also exclude directories starting with .
            dirs[:] = [d for d in dirs if d not in ALWAYS_HIDDEN_DIRS and (include_hidden or not d.startswith('.'))]
            
            # Files
            for file_item in files:
                if file_item in ALWAYS_HIDDEN_DIRS:
                    continue
                if not include_hidden and file_item.startswith('.'):
                    continue
                try:
                    abs_path = os.path.join(root, file_item)
                    rel_path = os.path.relpath(abs_path, self.host_path)
                    system_prefix += f"{rel_path}\n"
                except ValueError:
                    continue

            # Directories
            for dir_item in dirs:
                try:
                    abs_path = os.path.join(root, dir_item)
                    rel_path = os.path.relpath(abs_path, self.host_path)
                    system_prefix += f"{rel_path}/\n"
                except ValueError:
                    continue
            
            # Special handling for 'skills' directory to limit depth.
            # We want to list 'skills/' and its immediate children (e.g. 'skills/weather/'),
            # but we do NOT want to recurse deeper into those children.
            # So if we are currently visiting the 'skills' directory, we clear 'dirs'
            # to prevent os.walk from descending into the subdirectories we just listed.
            rel_root = os.path.relpath(root, self.host_path)
            if rel_root == 'skills':
                dirs[:] = []
        
        return system_prefix

    def to_host_path(self, virtual_path: str) -> str:
        """
        Converts a virtual path to a host path.
        Handles both exact matches and subpaths.
        """
        if virtual_path == self.virtual_path:
            return self.host_path
        
        if virtual_path.startswith(self.virtual_path + os.sep) or virtual_path.startswith(self.virtual_path + "/"):
            rel_path = virtual_path[len(self.virtual_path):].lstrip(os.sep).lstrip("/")
            return os.path.join(self.host_path, rel_path)
        
        # If it's already a host path or doesn't match virtual path, return as is (or handle error)
        # For robustness, we assume if it's not virtual, it might be a relative path or something else.
        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """
        Converts a host path to a virtual path.
        """
        if host_path == self.host_path:
            return self.virtual_path
        
        if host_path.startswith(self.host_path + os.sep) or host_path.startswith(self.host_path + "/"):
            rel_path = host_path[len(self.host_path):].lstrip(os.sep).lstrip("/")
            return os.path.join(self.virtual_path, rel_path)
            
        return host_path

    def map_text_to_host(self, text: str) -> str:
        """
        Replaces all occurrences of virtual path with host path in a text string.
        Useful for processing commands or scripts containing virtual paths.
        Uses regex to ensure we only replace full path segments, avoiding partial matches.
        If enable_path_mapping is False, returns text as-is.
        """
        if not self.enable_path_mapping:
            return text

        if not text:
            return text
            
        # Escape the virtual path for regex
        escaped_path = re.escape(self.virtual_path)
        
        # Regex explanation:
        # (?<![a-zA-Z0-9_\.\-/]) : Lookbehind to ensure the preceding character is NOT a path character
        # escaped_path           : The virtual path we want to replace
        # (?=$|/|[^a-zA-Z0-9_\.\-]) : Lookahead to ensure the following character is either end of string, 
        #                             a path separator, or a non-path character.
        pattern = r'(?<![a-zA-Z0-9_\.\-/])' + escaped_path + r'(?=$|/|[^a-zA-Z0-9_\.\-])'
        
        return re.sub(pattern, lambda m: self.host_path, text)

    def map_text_to_virtual(self, text: str) -> str:
        """
        Replaces all occurrences of host path with virtual path in a text string.
        """
        if not text:
            return text
            
        escaped_path = re.escape(self.host_path)
        pattern = r'(?<![a-zA-Z0-9_\.\-/])' + escaped_path + r'(?=$|/|[^a-zA-Z0-9_\.\-])'
        
        return re.sub(pattern, lambda m: self.virtual_path, text)

    @property
    def root(self) -> str:
        """Alias for host_path"""
        return self.host_path

    def __str__(self) -> str:
        """Return the virtual path representation."""
        return self.virtual_path
