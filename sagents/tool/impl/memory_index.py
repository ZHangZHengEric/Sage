#!/usr/bin/env python3
"""
File-based memory index using BM25 algorithm - Sandbox version
Supports incremental updates and fast search through sandbox interface
"""
import os
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass

from sagents.utils.logger import logger


@dataclass
class FileDocument:
    """File document"""
    path: str           # Virtual file path (in sandbox)
    content: str        # File content (text for BM25)
    mtime: float        # Modification time
    size: int           # File size
    hash: str           # Content hash
    doc_id: int         # Document ID (index in BM25)


@dataclass
class SearchResult:
    """Search result"""
    path: str           # File virtual path
    score: float        # BM25 score
    content: str        # Content preview
    line_number: int    # Line number (if applicable)


class MemoryIndex:
    """
    BM25-based memory index manager - Sandbox version

    Features:
    1. Incremental updates - only process changed files
    2. Fast folder mtime check - skip scanning if no changes
    3. Smart tokenization - supports Chinese and English
    4. Blacklist filtering - skip unwanted directories
    5. Sandbox integration - all file operations through sandbox
    """

    # Default blacklist directories
    DEFAULT_BLACKLIST: Set[str] = {
        '.git', '.svn', '.hg',
        'node_modules', 'vendor',
        '__pycache__', '.pytest_cache', '.mypy_cache',
        'venv', '.venv', 'env', '.env', 'virtualenv',
        'dist', 'build', 'target', 'out',
        '.idea', '.vscode', '.vs',
        'coverage', '.coverage', 'htmlcov',
        '.tox', '.eggs', '*.egg-info',
        'migrations', 'alembic',
        'logs', 'log', 'tmp', 'temp',
        '.cache',
    }

    # Default file extension whitelist
    DEFAULT_EXTENSIONS: List[str] = [
        '.py', '.js', '.ts', '.jsx', '.tsx',
        '.md', '.txt', '.rst',
        '.json', '.yaml', '.yml', '.toml',
        '.html', '.css', '.scss', '.less',
        '.vue', '.svelte',
        '.sql', '.sh', '.bash', '.zsh',
        '.java', '.kt', '.scala',
        '.go', '.rs', '.swift',
        '.c', '.cpp', '.h', '.hpp',
        '.rb', '.php', '.pl',
    ]

    def __init__(self, sandbox, workspace_path: str, index_path: str, blacklist: Optional[Set[str]] = None):
        """
        Initialize memory index

        Args:
            sandbox: Sandbox instance for file operations
            workspace_path: Workspace virtual path to index (folder)
            index_path: Index file save path (.pkl file) on host
            blacklist: Additional blacklist directory set
        """
        start_time = time.time()

        self.sandbox = sandbox
        self.workspace_path = workspace_path.rstrip('/')
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"MemoryIndex: Index path created: {self.index_path},workspace_path: {self.workspace_path}")
        # In-memory data
        self.bm25 = None
        self.documents: Dict[int, FileDocument] = {}
        self.path_to_id: Dict[str, int] = {}
        self._next_doc_id = 0

        # Directory mtime cache for incremental updates
        self._dir_mtime_cache: Dict[str, float] = {}

        # Blacklist
        self.blacklist = self.DEFAULT_BLACKLIST.copy()
        if blacklist:
            self.blacklist.update(blacklist)

        # Load existing index
        self._load_index()

        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Initialized in {elapsed:.3f}s")

    def _load_index(self) -> bool:
        """Load saved index from single pkl file"""
        start_time = time.time()

        try:
            if self.index_path.exists():
                with open(self.index_path, 'rb') as f:
                    data = pickle.load(f)

                self.bm25 = data.get('bm25')
                self.documents = data.get('documents', {})
                self._dir_mtime_cache = data.get('dir_mtime_cache', {})

                # Rebuild path -> id mapping
                self.path_to_id = {doc.path: doc.doc_id for doc in self.documents.values()}

                # Calculate next doc_id
                if self.documents:
                    self._next_doc_id = max(self.documents.keys()) + 1

                elapsed = time.time() - start_time
                logger.info(f"MemoryIndex: Loaded {len(self.documents)} documents from {self.index_path} in {elapsed:.3f}s")
                
                # If documents is empty but mtime cache exists, clear mtime cache to force rescan
                if not self.documents and self._dir_mtime_cache:
                    logger.info("MemoryIndex: Documents empty but mtime cache exists, clearing mtime cache to force rescan")
                    self._dir_mtime_cache = {}
                
                return True
        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to load index: {e}")
            self.bm25 = None
            self.documents = {}
            self.path_to_id = {}
            self._next_doc_id = 0
            self._dir_mtime_cache = {}

        return False

    def _save_index(self) -> bool:
        """Save index to single pkl file"""
        start_time = time.time()

        try:
            data = {
                'bm25': self.bm25,
                'documents': self.documents,
                'dir_mtime_cache': self._dir_mtime_cache,
                'document_count': len(self.documents)
            }

            with open(self.index_path, 'wb') as f:
                pickle.dump(data, f)

            elapsed = time.time() - start_time
            logger.info(f"MemoryIndex: Index saved to {self.index_path} in {elapsed:.3f}s")
            return True
        except Exception as e:
            logger.error(f"MemoryIndex: Failed to save index: {e}")
            return False

    async def _get_dir_mtime(self, dir_path: str) -> float:
        """Get directory modification time through sandbox"""
        try:
            # 在沙箱内执行命令，使用虚拟路径
            # logger.debug(f"MemoryIndex: Executing stat command for: {dir_path}")
            result = await self.sandbox.execute_command(
                command=f"stat -c %Y {dir_path} 2>/dev/null || stat -f %m {dir_path}",
                timeout=5
            )
            # logger.debug(f"MemoryIndex: Stat result for {dir_path}: success={result.success}")
            if result.success:
                return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"MemoryIndex: Error getting mtime for {dir_path}: {e}")
        return 0

    async def _compute_file_hash(self, filepath: str) -> str:
        """Compute file content hash through sandbox using md5sum command"""
        try:
            result = await self.sandbox.execute_command(
                command=f"md5sum {filepath}",
                timeout=10
            )
            if result.success:
                # md5sum output format: "hash  filename"
                hash_value = result.stdout.strip().split()[0]
                return hash_value
            return ""
        except Exception:
            return ""

    async def _read_file_content(self, filepath: str, max_size: int = 10 * 1024 * 1024) -> str:
        """Read file content with size limit through sandbox"""
        try:
            # Get file info
            entries = await self.sandbox.list_directory(os.path.dirname(filepath))
            file_info = None
            for entry in entries:
                if entry.path == filepath or entry.path.endswith(os.path.basename(filepath)):
                    file_info = entry
                    break

            if not file_info:
                return ""

            if file_info.size > max_size:
                # For large files, read first max_size bytes
                # Use head command through sandbox
                result = await self.sandbox.execute_command(
                    command=f"head -c {max_size} {filepath}",
                    timeout=10
                )
                if result.success:
                    return result.stdout + "\n[File too large, truncated]"
                return ""
            else:
                content = await self.sandbox.read_file(filepath)
                if isinstance(content, bytes):
                    return content.decode('utf-8', errors='ignore')
                return content
        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to read file {filepath}: {e}")
            return ""

    def _tokenize(self, text: str) -> List[str]:
        """
        Character-based tokenization
        - English: split by words (consecutive alphanumeric)
        - Chinese: split by characters
        - Numbers: consecutive digits as one token
        """
        import re
        text = text.lower()
        tokens = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', text)
        return tokens

    def _build_bm25(self) -> None:
        """Build BM25 index"""
        start_time = time.time()

        try:
            from rank_bm25 import BM25Okapi

            if not self.documents:
                self.bm25 = None
                return

            # Prepare corpus
            corpus = []
            for doc_id in sorted(self.documents.keys()):
                doc = self.documents[doc_id]
                filename = os.path.basename(doc.path)
                text = f"{filename} {doc.content}"
                tokens = self._tokenize(text)
                corpus.append(tokens)

            # Build BM25
            self.bm25 = BM25Okapi(corpus)

            elapsed = time.time() - start_time
            logger.info(f"MemoryIndex: Built BM25 index for {len(corpus)} documents in {elapsed:.3f}s")

        except ImportError:
            logger.error("MemoryIndex: Please install rank-bm25: pip install rank-bm25")
            raise
        except Exception as e:
            logger.error(f"MemoryIndex: Failed to build BM25: {e}")
            raise

    def _is_path_blacklisted(self, path: str) -> bool:
        """Check if path is in blacklist"""
        # Remove workspace prefix to get relative path
        if path.startswith(self.workspace_path):
            rel_path = path[len(self.workspace_path):].lstrip('/')
        else:
            rel_path = path

        parts = rel_path.split('/')
        for part in parts:
            if part in self.blacklist:
                return True
            for pattern in self.blacklist:
                if '*' in pattern:
                    import fnmatch
                    if fnmatch.fnmatch(part, pattern):
                        return True
        return False

    async def _scan_directory_recursive(
        self,
        dir_path: str,
        file_extensions: List[str],
        stats: Dict[str, Any],
        current_files: Set[str]
    ) -> None:
        """
        Recursively scan directory, skipping unchanged subdirectories

        Args:
            dir_path: Current directory path to scan
            file_extensions: Allowed file extensions
            stats: Statistics dictionary to update
            current_files: Set to collect current file paths
        """
        # Check if directory is blacklisted
        if self._is_path_blacklisted(dir_path):
            return

        # Get current directory mtime
        # logger.debug(f"MemoryIndex: Checking mtime for dir: {dir_path}")
        current_mtime = await self._get_dir_mtime(dir_path)
        # logger.debug(f"MemoryIndex: Dir {dir_path} mtime: {current_mtime}")

        # Check if directory has changed
        last_mtime = self._dir_mtime_cache.get(dir_path, 0)
        # logger.debug(f"MemoryIndex: Dir {dir_path} last_mtime: {last_mtime}, current_mtime: {current_mtime}")
        if current_mtime <= last_mtime:
            # Directory unchanged, skip scanning
            # But we still need to collect files from this directory from existing index
            # logger.debug(f"MemoryIndex: Skipping unchanged directory: {dir_path}")
            # Collect files from existing index that belong to this directory
            for filepath in self.path_to_id.keys():
                if filepath.startswith(dir_path + '/') or filepath == dir_path:
                    current_files.add(filepath)
            return

        # Update cache
        self._dir_mtime_cache[dir_path] = current_mtime

        try:
            # List directory entries
            entries = await self.sandbox.list_directory(dir_path)
            
            ext_set = set(ext.lower() for ext in file_extensions)

            for entry in entries:
                if entry.is_dir:
                    # Recursively scan subdirectory
                    await self._scan_directory_recursive(
                        entry.path, file_extensions, stats, current_files
                    )
                elif entry.is_file:
                    # Check extension
                    ext = os.path.splitext(entry.path)[1].lower()
                    if ext not in ext_set:
                        continue

                    # Check blacklist
                    if self._is_path_blacklisted(entry.path):
                        continue

                    current_files.add(entry.path)

                    # Process file
                    await self._process_file(entry, stats)

        except Exception as e:
            logger.warning(f"MemoryIndex: Error scanning directory {dir_path}: {e}", exc_info=True)

    async def _process_file(self, entry, stats: Dict[str, Any]) -> None:
        """Process a single file - add, update, or skip"""
        filepath = entry.path
        mtime = entry.modified_time or 0
        size = entry.size or 0

        try:
            if filepath in self.path_to_id:
                # File exists in index, check if modified
                doc_id = self.path_to_id[filepath]
                old_doc = self.documents[doc_id]

                # Quick check: compare mtime and size
                if old_doc.mtime == mtime and old_doc.size == size:
                    stats["unchanged"] += 1
                    return

                # mtime or size changed, verify with hash
                file_hash = await self._compute_file_hash(filepath)

                if old_doc.hash != file_hash:
                    # File content changed, update
                    content = await self._read_file_content(filepath)
                    self.documents[doc_id] = FileDocument(
                        path=filepath,
                        content=content,
                        mtime=mtime,
                        size=size,
                        hash=file_hash,
                        doc_id=doc_id
                    )
                    stats["updated"] += 1
                    logger.debug(f"MemoryIndex: Updated file {filepath}")
                else:
                    # Only mtime changed, update mtime only
                    old_doc.mtime = mtime
                    stats["unchanged"] += 1
            else:
                # New file, add to index
                file_hash = await self._compute_file_hash(filepath)
                content = await self._read_file_content(filepath)
                doc_id = self._next_doc_id
                self._next_doc_id += 1

                self.documents[doc_id] = FileDocument(
                    path=filepath,
                    content=content,
                    mtime=mtime,
                    size=size,
                    hash=file_hash,
                    doc_id=doc_id
                )
                self.path_to_id[filepath] = doc_id
                stats["added"] += 1
                logger.debug(f"MemoryIndex: Added file {filepath}")

        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to process file {filepath}: {e}")
            stats["errors"] += 1

    async def update_index(self, file_extensions: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
        """
        Update index (auto incremental with directory-level change detection)

        Args:
            file_extensions: File extension whitelist, None for default
            force: Force full scan even if folder mtime hasn't changed

        Returns:
            Update statistics with timing info
        """
        total_start_time = time.time()

        if file_extensions is None:
            file_extensions = self.DEFAULT_EXTENSIONS

        stats = {
            "added": 0,
            "updated": 0,
            "removed": 0,
            "unchanged": 0,
            "errors": 0,
            "scan_time": 0.0,
            "build_time": 0.0,
            "save_time": 0.0,
            "total_time": 0.0,
            "skipped": False
        }

        scan_start = time.time()

        # Collect current files by recursively scanning directories
        current_files: Set[str] = set()

        if force:
            # Force full scan: clear mtime cache
            self._dir_mtime_cache = {}

        # Start recursive scan from workspace root
        logger.info(f"MemoryIndex: Starting scan from workspace: {self.workspace_path}")
        await self._scan_directory_recursive(
            self.workspace_path,
            file_extensions,
            stats,
            current_files
        )
        
        # logger.debug(f"MemoryIndex: Scan complete. Found {len(current_files)} current files, {len(self.path_to_id)} indexed files")

        # Check for deleted files
        indexed_paths = set(self.path_to_id.keys())
        deleted_paths = indexed_paths - current_files

        for filepath in deleted_paths:
            try:
                doc_id = self.path_to_id[filepath]
                del self.documents[doc_id]
                del self.path_to_id[filepath]
                stats["removed"] += 1
                logger.debug(f"MemoryIndex: Removed file {filepath}")
            except Exception as e:
                logger.warning(f"MemoryIndex: Failed to remove file {filepath}: {e}")

        stats["scan_time"] = time.time() - scan_start

        # Rebuild BM25 index if needed
        build_start = time.time()
        has_changes = stats["added"] > 0 or stats["updated"] > 0 or stats["removed"] > 0

        if has_changes or force:
            self._build_bm25()
            stats["build_time"] = time.time() - build_start

            save_start = time.time()
            self._save_index()
            stats["save_time"] = time.time() - save_start

            stats["total_time"] = time.time() - total_start_time
            logger.info(f"MemoryIndex: Index updated - added:{stats['added']}, updated:{stats['updated']}, removed:{stats['removed']}, unchanged:{stats['unchanged']}, scan:{stats['scan_time']:.3f}s, build:{stats['build_time']:.3f}s, save:{stats['save_time']:.3f}s, total:{stats['total_time']:.3f}s")
        else:
            stats["total_time"] = time.time() - total_start_time
            logger.info(f"MemoryIndex: No file changes, unchanged:{stats['unchanged']}, scan:{stats['scan_time']:.3f}s, total:{stats['total_time']:.3f}s")

        return stats

    def _extract_snippets(self, content: str, query: str, snippet_size: int = 100) -> List[Dict[str, Any]]:
        """
        Extract snippets containing query terms from content

        Args:
            content: File content
            query: Search query
            snippet_size: Size of each snippet in characters (default 100)

        Returns:
            List of snippets with line numbers (max 1 per file)
        """
        import re

        # Tokenize query to get search terms
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Build regex pattern for all query tokens
        patterns = [re.escape(token) for token in query_tokens if len(token) > 1]
        if not patterns:
            patterns = [re.escape(token) for token in query_tokens]

        combined_pattern = '|'.join(patterns)

        content_lower = content.lower()

        # Find first match only (max 1 snippet per file)
        match = re.search(combined_pattern, content_lower, re.IGNORECASE)
        if not match:
            return []

        start_pos = max(0, match.start() - snippet_size // 2)
        end_pos = min(len(content), match.end() + snippet_size // 2)

        # Find line number
        line_num = content_lower[:match.start()].count('\n') + 1

        # Extract snippet
        snippet = content[start_pos:end_pos]

        # Add ellipsis if truncated
        if start_pos > 0:
            snippet = "..." + snippet
        if end_pos < len(content):
            snippet = snippet + "..."

        return [{
            "line_number": line_num,
            "snippet": snippet.strip(),
            "matched_term": match.group()
        }]

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """
        Search memory

        Args:
            query: Search query
            top_k: Return top K results

        Returns:
            List of search results with snippets
        """
        start_time = time.time()

        if not self.bm25 or not self.documents:
            logger.warning("MemoryIndex: Index is empty, please update index first")
            return []

        try:
            query_tokens = self._tokenize(query)

            if not query_tokens:
                return []

            # Get scores for all documents
            scores = self.bm25.get_scores(query_tokens)

            # Get top_k results
            top_indices = scores.argsort()[-top_k:][::-1]

            results = []
            for idx in top_indices:
                score = scores[idx]
                if score <= 0:
                    continue

                doc_id = list(sorted(self.documents.keys()))[idx]
                doc = self.documents[doc_id]

                # Extract relevant snippets
                snippets = self._extract_snippets(doc.content, query)

                # Build preview from snippets or fallback to first 500 chars
                if snippets:
                    preview = "\n\n".join([
                        f"[Line {s['line_number']}] {s['snippet']}"
                        for s in snippets
                    ])
                else:
                    preview = doc.content[:500]
                    if len(doc.content) > 500:
                        preview += "..."

                results.append(SearchResult(
                    path=doc.path,
                    score=float(score),
                    content=preview,
                    line_number=snippets[0]["line_number"] if snippets else 0
                ))

            elapsed = time.time() - start_time
            logger.info(f"MemoryIndex: Search '{query}' completed, found {len(results)} results in {elapsed:.3f}s")
            return results

        except Exception as e:
            logger.error(f"MemoryIndex: Search failed: {e}")
            return []

    def get_document_count(self) -> int:
        """Get document count"""
        return len(self.documents)

    def clear_index(self) -> None:
        """Clear index"""
        start_time = time.time()

        self.bm25 = None
        self.documents = {}
        self.path_to_id = {}
        self._next_doc_id = 0
        self._dir_mtime_cache = {}

        if self.index_path.exists():
            self.index_path.unlink()

        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Index cleared in {elapsed:.3f}s")
