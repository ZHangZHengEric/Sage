import os
import re
from typing import List, Optional

SANDBOX_WORKSPACE_ROOT = "/sage-workspace"

class SandboxFileSystem:
    """
    Represents the file system within the sandbox environment.
    It manages the mapping between the host file system and the virtual sandbox path,
    providing a safe view of the file tree for the agent.
    """
    def __init__(self, host_path: str, virtual_path: str = SANDBOX_WORKSPACE_ROOT, enable_path_mapping: bool = True):
        self.host_path = host_path
        self.virtual_path = virtual_path
        # 如果 host_path == virtual_path，自动禁用路径映射
        if host_path == virtual_path:
            self.enable_path_mapping = False
        else:
            self.enable_path_mapping = enable_path_mapping

    def get_file_tree(self, include_hidden: bool = False, root_path: Optional[str] = None, max_depth: Optional[int] = None, max_items_per_dir: int = 5) -> str:
        """
        Returns a formatted string of the file tree relative to the virtual root.
        This safely exposes the structure of the sandbox file system to the agent.
        
        Args:
            include_hidden: Whether to include hidden files (starting with .) in the tree.
                            Note: Sensitive directories like .sandbox, .git are always excluded.
            root_path: The root path to start the traversal from. If None, uses self.host_path.
            max_depth: The maximum depth to traverse. None means no limit.
            max_items_per_dir: Maximum number of items (files + dirs) to show per directory 
                              for subdirectories. Root directory is not limited. Default is 5.
        
        Example output:
        file1.txt
        dir1/
        dir1/file2.txt
        ... (and 15 more items)
        """
        system_prefix = ""
        target_root = root_path if root_path else self.host_path
        
        if not os.path.exists(target_root):
            return system_prefix
            
        # Directories that are always hidden regardless of include_hidden
        ALWAYS_HIDDEN_DIRS = {'.sandbox', '.git', '.idea', '.vscode', '__pycache__', 'node_modules', 'venv', '.DS_Store'}

        target_root = os.path.abspath(target_root)
        base_depth = target_root.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(target_root):
            # Calculate current depth
            current_depth = root.rstrip(os.sep).count(os.sep) - base_depth
            
            # Check depth limit
            if max_depth is not None and current_depth >= max_depth:
                dirs[:] = []  # Don't recurse further
            
            # Filter directories
            dirs[:] = [d for d in dirs if d not in ALWAYS_HIDDEN_DIRS and (include_hidden or not d.startswith('.'))]
            
            # Filter files
            filtered_files = [f for f in files if f not in ALWAYS_HIDDEN_DIRS and (include_hidden or not f.startswith('.'))]
            
            # Collect all items (files and dirs) with their types
            all_items = []
            
            # Add directories
            for dir_item in dirs:
                try:
                    abs_path = os.path.join(root, dir_item)
                    rel_path = os.path.relpath(abs_path, target_root)
                    all_items.append(('dir', f"{rel_path}/"))
                except ValueError:
                    continue
            
            # Add files
            for file_item in filtered_files:
                try:
                    abs_path = os.path.join(root, file_item)
                    rel_path = os.path.relpath(abs_path, target_root)
                    all_items.append(('file', rel_path))
                except ValueError:
                    continue
            
            # Check if we need to truncate
            # Root directory (current_depth == 0) shows all items, subdirectories apply max_items_per_dir
            total_items = len(all_items)
            if current_depth > 0 and total_items > max_items_per_dir:
                # Show first max_items_per_dir items for subdirectories
                shown_items = all_items[:max_items_per_dir]
                hidden_count = total_items - max_items_per_dir
            else:
                # Show all items for root directory
                shown_items = all_items
                hidden_count = 0
            
            # Add shown items to output
            for item_type, item_path in shown_items:
                system_prefix += f"{item_path}\n"
            
            # Add ellipsis if truncated
            if hidden_count > 0:
                system_prefix += f"... (and {hidden_count} more items)\n"
            
            # Special handling for 'skills' directory to limit depth.
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

    def write_file(self, path: str, content: str, encoding: str = 'utf-8', append: bool = False) -> str:
        """
        Writes content to a file in the sandbox.
        Args:
            path: Virtual path or host path (will be resolved to host path).
            content: Content to write.
            encoding: File encoding.
            append: Whether to append to the file instead of overwriting.
        Returns:
            The absolute host path of the written file.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_file_path = path
        else:
             host_file_path = self.to_host_path(path)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(host_file_path), exist_ok=True)
        
        mode = 'a' if append else 'w'
        with open(host_file_path, mode, encoding=encoding) as f:
            f.write(content)
            
        return host_file_path

    def read_file(self, path: str, encoding: str = 'utf-8') -> str:
        """
        Reads content from a file in the sandbox.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_file_path = path
        else:
             host_file_path = self.to_host_path(path)
             
        with open(host_file_path, 'r', encoding=encoding) as f:
            return f.read()

    def ensure_directory(self, path: str) -> str:
        """
        Ensures that a directory exists in the sandbox.
        Args:
            path: Virtual path or host path.
        Returns:
            The absolute host path of the directory.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_dir_path = path
        else:
             host_dir_path = self.to_host_path(path)
        
        os.makedirs(host_dir_path, exist_ok=True)
        return host_dir_path

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
