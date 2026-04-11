#!/usr/bin/env python3
"""
File-based memory index for sandbox workspaces.

Current design:
- file content is indexed as overlapping chunks
- chunk rows are stored in a local SQLite FTS5 database
- lightweight metadata is still persisted in a pickle sidecar for incremental updates
"""
import asyncio
import os
import pickle
import sqlite3
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
    chunk_index: int = 0
    line_start: int = 1
    line_end: int = 1


@dataclass
class SearchResult:
    """Search result"""
    path: str           # File virtual path
    score: float        # BM25 score
    content: str        # Content preview
    line_number: int    # Line number (if applicable)


class MemoryIndex:
    """
    File-memory index manager for sandbox workspaces.

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
    DEFAULT_FILE_PROCESS_CONCURRENCY = 8
    INDEX_SCHEMA_VERSION = 2
    FTS_SCHEMA_VERSION = 1
    DEFAULT_CHUNK_SIZE = 1200
    DEFAULT_CHUNK_OVERLAP = 200

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
        self.fts_index_path = self.index_path.with_suffix(".sqlite3")
        logger.info(f"MemoryIndex: Index path created: {self.index_path},workspace_path: {self.workspace_path}")
        # In-memory data
        self.bm25 = None
        self.documents: Dict[int, FileDocument] = {}
        self.path_to_doc_ids: Dict[str, List[int]] = {}
        self._next_doc_id = 0

        # Directory mtime cache for incremental updates
        self._dir_mtime_cache: Dict[str, float] = {}
        self._file_process_semaphore = asyncio.Semaphore(self.DEFAULT_FILE_PROCESS_CONCURRENCY)

        # Blacklist
        self.blacklist = self.DEFAULT_BLACKLIST.copy()
        if blacklist:
            self.blacklist.update(blacklist)

        # Load existing index
        self._load_index()
        self._ensure_fts_schema()
        fts_has_documents = self._fts_has_documents()
        if bool(self.documents) != fts_has_documents:
            # Keep the sidecar metadata and the FTS store in sync. This also clears
            # stale FTS rows left behind by older layouts or interrupted rebuilds.
            self._rebuild_fts_index()

        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Initialized in {elapsed:.3f}s")

    def _load_index(self) -> bool:
        """Load saved index from single pkl file"""
        start_time = time.time()

        try:
            if self.index_path.exists():
                with open(self.index_path, 'rb') as f:
                    data = pickle.load(f)

                self.bm25 = None
                self.documents = data.get('documents', {})
                self._dir_mtime_cache = data.get('dir_mtime_cache', {})
                schema_version = data.get('schema_version', 1)
                if schema_version != self.INDEX_SCHEMA_VERSION:
                    logger.info(
                        f"MemoryIndex: Index schema {schema_version} != {self.INDEX_SCHEMA_VERSION}, clearing cached index for rebuild"
                    )
                    self.bm25 = None
                    self.documents = {}
                    self.path_to_doc_ids = {}
                    self._next_doc_id = 0
                    self._dir_mtime_cache = {}
                    return False

                self.path_to_doc_ids = data.get('path_to_doc_ids') or self._rebuild_path_to_doc_ids()

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
            self.path_to_doc_ids = {}
            self._next_doc_id = 0
            self._dir_mtime_cache = {}

        return False

    def _rebuild_path_to_doc_ids(self) -> Dict[str, List[int]]:
        path_to_doc_ids: Dict[str, List[int]] = {}
        for doc_id in sorted(self.documents.keys()):
            doc = self.documents[doc_id]
            path_to_doc_ids.setdefault(doc.path, []).append(doc_id)
        return path_to_doc_ids

    def _save_index(self) -> bool:
        """Save index to single pkl file"""
        start_time = time.time()

        try:
            data = {
                'schema_version': self.INDEX_SCHEMA_VERSION,
                'bm25': None,
                'documents': self.documents,
                'path_to_doc_ids': self.path_to_doc_ids,
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

    def _split_into_chunks(self, content: str) -> List[Dict[str, Any]]:
        if not content:
            return []

        lines = content.splitlines()
        if not lines:
            return [{
                "content": content,
                "line_start": 1,
                "line_end": 1,
            }]

        chunks: List[Dict[str, Any]] = []
        current_lines: List[str] = []
        current_line_start = 1
        current_chars = 0

        for index, line in enumerate(lines, start=1):
            line_len = len(line) + 1
            if current_lines and current_chars + line_len > self.DEFAULT_CHUNK_SIZE:
                chunks.append({
                    "content": "\n".join(current_lines),
                    "line_start": current_line_start,
                    "line_end": current_line_start + len(current_lines) - 1,
                })

                overlap_lines: List[str] = []
                overlap_chars = 0
                for existing_line in reversed(current_lines):
                    existing_len = len(existing_line) + 1
                    if overlap_lines and overlap_chars + existing_len > self.DEFAULT_CHUNK_OVERLAP:
                        break
                    overlap_lines.insert(0, existing_line)
                    overlap_chars += existing_len

                current_lines = overlap_lines[:]
                current_chars = sum(len(existing_line) + 1 for existing_line in current_lines)
                current_line_start = index - len(current_lines)

            if not current_lines:
                current_line_start = index
            current_lines.append(line)
            current_chars += line_len

        if current_lines:
            chunks.append({
                "content": "\n".join(current_lines),
                "line_start": current_line_start,
                "line_end": current_line_start + len(current_lines) - 1,
            })

        return chunks

    def _connect_fts(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.fts_index_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_fts_schema(self) -> None:
        with self._connect_fts() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM meta WHERE key = 'fts_schema_version'").fetchone()
            current_version = row["value"] if row else None
            if current_version != str(self.FTS_SCHEMA_VERSION):
                conn.execute("DROP TABLE IF EXISTS memory_fts")
                conn.execute("DELETE FROM meta")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    path UNINDEXED,
                    search_text,
                    content UNINDEXED,
                    line_start UNINDEXED,
                    line_end UNINDEXED,
                    chunk_index UNINDEXED,
                    tokenize='unicode61'
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_schema_version', ?)",
                (str(self.FTS_SCHEMA_VERSION),),
            )
            conn.commit()

    def _fts_has_documents(self) -> bool:
        if not self.fts_index_path.exists():
            return False
        try:
            with self._connect_fts() as conn:
                row = conn.execute("SELECT COUNT(*) AS count FROM memory_fts").fetchone()
                return bool(row and row["count"] > 0)
        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to inspect FTS index: {e}")
            return False

    def has_search_index(self) -> bool:
        return bool(self.documents) and self._fts_has_documents()

    def _build_search_text(self, doc: FileDocument) -> str:
        filename = os.path.basename(doc.path)
        text = f"{filename} {doc.content}"
        return " ".join(self._tokenize(text))

    def _delete_file_from_fts(self, filepath: str) -> None:
        self._ensure_fts_schema()
        with self._connect_fts() as conn:
            conn.execute("DELETE FROM memory_fts WHERE path = ?", (filepath,))
            conn.commit()

    def _sync_file_to_fts(self, filepath: str) -> None:
        self._ensure_fts_schema()
        doc_ids = self.path_to_doc_ids.get(filepath, [])
        with self._connect_fts() as conn:
            conn.execute("DELETE FROM memory_fts WHERE path = ?", (filepath,))
            rows = []
            for doc_id in doc_ids:
                doc = self.documents.get(doc_id)
                if not doc:
                    continue
                rows.append(
                    (
                        doc.path,
                        self._build_search_text(doc),
                        doc.content,
                        str(doc.line_start),
                        str(doc.line_end),
                        str(doc.chunk_index),
                    )
                )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO memory_fts(path, search_text, content, line_start, line_end, chunk_index)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()

    def _rebuild_fts_index(self) -> None:
        start_time = time.time()
        self._ensure_fts_schema()
        with self._connect_fts() as conn:
            conn.execute("DELETE FROM memory_fts")
            rows = []
            for doc_id in sorted(self.documents.keys()):
                doc = self.documents[doc_id]
                rows.append(
                    (
                        doc.path,
                        self._build_search_text(doc),
                        doc.content,
                        str(doc.line_start),
                        str(doc.line_end),
                        str(doc.chunk_index),
                    )
                )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO memory_fts(path, search_text, content, line_start, line_end, chunk_index)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()
        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Rebuilt SQLite FTS index for {len(rows)} chunks in {elapsed:.3f}s")

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
            for filepath in self.path_to_doc_ids.keys():
                if filepath.startswith(dir_path + '/') or filepath == dir_path:
                    current_files.add(filepath)
            return

        # Update cache
        self._dir_mtime_cache[dir_path] = current_mtime

        try:
            # List directory entries
            entries = await self.sandbox.list_directory(dir_path)
            
            ext_set = set(ext.lower() for ext in file_extensions)
            file_tasks = []

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
                    file_tasks.append(asyncio.create_task(self._process_file(entry, stats)))

            if file_tasks:
                await asyncio.gather(*file_tasks)

        except Exception as e:
            logger.warning(f"MemoryIndex: Error scanning directory {dir_path}: {e}", exc_info=True)

    async def _process_file(self, entry, stats: Dict[str, Any]) -> None:
        """Process a single file - add, update, or skip"""
        async with self._file_process_semaphore:
            filepath = entry.path
            mtime = entry.modified_time or 0
            size = entry.size or 0

            try:
                if filepath in self.path_to_doc_ids:
                    # File exists in index, check if modified
                    existing_doc_ids = self.path_to_doc_ids[filepath]
                    old_doc = self.documents[existing_doc_ids[0]]

                    # Quick check: compare mtime and size
                    if old_doc.mtime == mtime and old_doc.size == size:
                        stats["unchanged"] += 1
                        return

                    # mtime or size changed, treat as content changed and refresh directly.
                    content = await self._read_file_content(filepath)
                    self._replace_file_documents(filepath, content, mtime, size)
                    self._sync_file_to_fts(filepath)
                    stats["updated"] += 1
                    logger.debug(f"MemoryIndex: Updated file {filepath}")
                else:
                    # New file, add to index
                    content = await self._read_file_content(filepath)
                    self._replace_file_documents(filepath, content, mtime, size)
                    self._sync_file_to_fts(filepath)
                    stats["added"] += 1
                    logger.debug(f"MemoryIndex: Added file {filepath}")

            except Exception as e:
                logger.warning(f"MemoryIndex: Failed to process file {filepath}: {e}")
                stats["errors"] += 1

    def _replace_file_documents(self, filepath: str, content: str, mtime: float, size: int) -> None:
        existing_doc_ids = self.path_to_doc_ids.pop(filepath, [])
        for doc_id in existing_doc_ids:
            self.documents.pop(doc_id, None)

        chunks = self._split_into_chunks(content)
        if not chunks:
            chunks = [{
                "content": "",
                "line_start": 1,
                "line_end": 1,
            }]

        new_doc_ids: List[int] = []
        for chunk_index, chunk in enumerate(chunks):
            doc_id = self._next_doc_id
            self._next_doc_id += 1
            self.documents[doc_id] = FileDocument(
                path=filepath,
                content=chunk["content"],
                mtime=mtime,
                size=size,
                hash="",
                doc_id=doc_id,
                chunk_index=chunk_index,
                line_start=chunk["line_start"],
                line_end=chunk["line_end"],
            )
            new_doc_ids.append(doc_id)

        self.path_to_doc_ids[filepath] = new_doc_ids

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
        
        # logger.debug(f"MemoryIndex: Scan complete. Found {len(current_files)} current files, {len(self.path_to_doc_ids)} indexed files")

        # Check for deleted files
        indexed_paths = set(self.path_to_doc_ids.keys())
        deleted_paths = indexed_paths - current_files

        for filepath in deleted_paths:
            try:
                for doc_id in self.path_to_doc_ids.pop(filepath, []):
                    self.documents.pop(doc_id, None)
                self._delete_file_from_fts(filepath)
                stats["removed"] += 1
                logger.debug(f"MemoryIndex: Removed file {filepath}")
            except Exception as e:
                logger.warning(f"MemoryIndex: Failed to remove file {filepath}: {e}")

        stats["scan_time"] = time.time() - scan_start

        # Persist metadata if the file set changed. The FTS rows are updated inline
        # during file processing and full rebuild is only needed on force refresh.
        build_start = time.time()
        has_changes = stats["added"] > 0 or stats["updated"] > 0 or stats["removed"] > 0

        if has_changes or force:
            if force:
                self._rebuild_fts_index()
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

        if not self.documents or not self._fts_has_documents():
            logger.warning("MemoryIndex: Index is empty, please update index first")
            return []

        try:
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return []

            results = []
            match_expr = " OR ".join(f'"{token}"' for token in query_tokens)
            row_limit = max(top_k * 5, top_k)
            with self._connect_fts() as conn:
                rows = conn.execute(
                    """
                    SELECT path, content, line_start, line_end, chunk_index, bm25(memory_fts) AS raw_score
                    FROM memory_fts
                    WHERE search_text MATCH ?
                    ORDER BY raw_score
                    LIMIT ?
                    """,
                    (match_expr, row_limit),
                ).fetchall()

            seen_paths = set()
            for row in rows:
                path = row["path"]
                if path in seen_paths:
                    continue
                seen_paths.add(path)

                chunk_content = row["content"] or ""
                line_start = int(row["line_start"] or 1)
                snippets = self._extract_snippets(chunk_content, query)

                if snippets:
                    line_base = line_start - 1
                    preview = "\n\n".join([
                        f"[Line {line_base + s['line_number']}] {s['snippet']}"
                        for s in snippets
                    ])
                else:
                    preview = chunk_content[:500]
                    if len(chunk_content) > 500:
                        preview += "..."

                raw_score = float(row["raw_score"]) if row["raw_score"] is not None else 0.0
                results.append(SearchResult(
                    path=path,
                    score=-raw_score,
                    content=preview,
                    line_number=(line_start + snippets[0]["line_number"] - 1) if snippets else line_start,
                ))
                if len(results) >= top_k:
                    break

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
        self.path_to_doc_ids = {}
        self._next_doc_id = 0
        self._dir_mtime_cache = {}

        if self.index_path.exists():
            self.index_path.unlink()
        if self.fts_index_path.exists():
            self.fts_index_path.unlink()

        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Index cleared in {elapsed:.3f}s")
