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
from contextlib import contextmanager
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
    FTS_SCHEMA_VERSION = 3
    DEFAULT_CHUNK_SIZE = 1200
    DEFAULT_CHUNK_OVERLAP = 200
    DEFAULT_FILE_SEARCH_LIMIT_MULTIPLIER = 4
    DEFAULT_RERANK_LIMIT_MULTIPLIER = 3
    DEFAULT_CHUNK_ROW_LIMIT_MULTIPLIER = 4

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
        """通过沙箱接口拿目录 mtime。

        统一走 ``sandbox.get_mtime``：
        - 本地/直通沙箱内部用 ``os.path.getmtime``，恒定开销；
        - 远端/容器沙箱用各自 provider 的实现（默认通过 ``list_directory(parent)``
          找到该条目，避免每次启 ``stat`` 子进程）。

        历史实现是 ``execute_command("stat ...")``，在 macOS Seatbelt 下每次
        都要拉起 ``sandbox-exec + python launcher`` 子进程，单次 0.3~1s，
        递归扫几十个子目录就把 ``search_memory`` 拖成"看起来卡死"。
        """
        try:
            return float(await self.sandbox.get_mtime(dir_path))
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
        Character-based tokenization with identifier-aware expansion.
        - English/code identifiers: keep the original token and expand snake_case / camelCase parts
        - Chinese: split by characters
        - Numbers: consecutive digits as one token
        """
        import re

        raw_tokens = re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]', text)
        tokens: List[str] = []
        seen: Set[str] = set()

        def add_token(token: str) -> None:
            normalized = token.lower()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            tokens.append(normalized)

        def split_identifier_parts(identifier: str) -> List[str]:
            parts: List[str] = []
            underscore_parts = [part for part in identifier.split("_") if part]
            camel_pattern = re.compile(r'[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+')
            for part in underscore_parts or [identifier]:
                matches = camel_pattern.findall(part)
                if matches:
                    parts.extend(matches)
                elif part:
                    parts.append(part)
            return parts

        for token in raw_tokens:
            add_token(token)
            if re.fullmatch(r'[A-Za-z0-9_]+', token):
                for part in split_identifier_parts(token):
                    add_token(part)

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

    @contextmanager
    def _fts_connection(self):
        conn = self._connect_fts()
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_fts_schema(self) -> None:
        with self._fts_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM meta WHERE key = 'fts_schema_version'").fetchone()
            current_version = row["value"] if row else None
            if current_version != str(self.FTS_SCHEMA_VERSION):
                conn.execute("DROP TABLE IF EXISTS memory_fts")
                conn.execute("DROP TABLE IF EXISTS memory_file_fts")
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
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_file_fts
                USING fts5(
                    path UNINDEXED,
                    search_text,
                    content UNINDEXED,
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
            with self._fts_connection() as conn:
                chunk_row = conn.execute("SELECT COUNT(*) AS count FROM memory_fts").fetchone()
                file_row = conn.execute("SELECT COUNT(*) AS count FROM memory_file_fts").fetchone()
                return bool(
                    chunk_row
                    and file_row
                    and chunk_row["count"] > 0
                    and file_row["count"] > 0
                )
        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to inspect FTS index: {e}")
            return False

    def has_search_index(self) -> bool:
        return bool(self.documents) and self._fts_has_documents()

    def _build_chunk_search_text(self, doc: FileDocument) -> str:
        filename = os.path.basename(doc.path)
        text = f"{doc.path} {filename} {doc.content}"
        return " ".join(self._tokenize(text))

    def _build_file_search_text(self, path: str, content: str) -> str:
        filename = os.path.basename(path)
        text = f"{path} {filename} {content}"
        return " ".join(self._tokenize(text))

    def _delete_file_from_fts(self, filepath: str) -> None:
        self._ensure_fts_schema()
        with self._fts_connection() as conn:
            conn.execute("DELETE FROM memory_fts WHERE path = ?", (filepath,))
            conn.execute("DELETE FROM memory_file_fts WHERE path = ?", (filepath,))
            conn.commit()

    def _sync_file_to_fts(self, filepath: str) -> None:
        self._ensure_fts_schema()
        doc_ids = self.path_to_doc_ids.get(filepath, [])
        with self._fts_connection() as conn:
            conn.execute("DELETE FROM memory_fts WHERE path = ?", (filepath,))
            conn.execute("DELETE FROM memory_file_fts WHERE path = ?", (filepath,))
            rows = []
            file_content_parts: List[str] = []
            for doc_id in doc_ids:
                doc = self.documents.get(doc_id)
                if not doc:
                    continue
                file_content_parts.append(doc.content)
                rows.append(
                    (
                        doc.path,
                        self._build_chunk_search_text(doc),
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
            if file_content_parts:
                full_content = "\n".join(file_content_parts)
                conn.execute(
                    """
                    INSERT INTO memory_file_fts(path, search_text, content)
                    VALUES (?, ?, ?)
                    """,
                    (
                        filepath,
                        self._build_file_search_text(filepath, full_content),
                        full_content,
                    ),
                )
            conn.commit()

    def _rebuild_fts_index(self) -> None:
        start_time = time.time()
        self._ensure_fts_schema()
        with self._fts_connection() as conn:
            conn.execute("DELETE FROM memory_fts")
            conn.execute("DELETE FROM memory_file_fts")
            rows = []
            file_rows = []
            for filepath in sorted(self.path_to_doc_ids.keys()):
                doc_ids = self.path_to_doc_ids[filepath]
                docs = [self.documents[doc_id] for doc_id in doc_ids if doc_id in self.documents]
                if not docs:
                    continue
                full_content = "\n".join(doc.content for doc in docs)
                file_rows.append(
                    (
                        filepath,
                        self._build_file_search_text(filepath, full_content),
                        full_content,
                    )
                )
            for doc_id in sorted(self.documents.keys()):
                doc = self.documents[doc_id]
                rows.append(
                    (
                        doc.path,
                        self._build_chunk_search_text(doc),
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
            if file_rows:
                conn.executemany(
                    """
                    INSERT INTO memory_file_fts(path, search_text, content)
                    VALUES (?, ?, ?)
                    """,
                    file_rows,
                )
            conn.commit()
        elapsed = time.time() - start_time
        logger.info(
            f"MemoryIndex: Rebuilt SQLite FTS index for {len(file_rows)} files and {len(rows)} chunks in {elapsed:.3f}s"
        )

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

    def _row_token_set(self, row: Any) -> Set[str]:
        """Tokenize both row content and row path for row-level reranking."""
        try:
            row_path = row["path"] or ""
        except (KeyError, TypeError):
            row_path = ""
        try:
            row_content = row["content"] or ""
        except (KeyError, TypeError):
            row_content = ""
        return set(self._tokenize(f"{row_path} {row_content}"))

    def _build_result_preview(self, chunk_content: str, query: str, line_start: int) -> tuple[str, int]:
        """Build a preview and line number from the strongest chunk hit."""
        snippets = self._extract_snippets(chunk_content, query)
        if snippets:
            line_base = line_start - 1
            preview = "\n\n".join([
                f"[Line {line_base + s['line_number']}] {s['snippet']}"
                for s in snippets
            ])
            return preview, line_start + snippets[0]["line_number"] - 1

        preview = chunk_content[:500]
        if len(chunk_content) > 500:
            preview += "..."
        return preview, line_start

    def _select_preview_rows(self, rows: List[Any], query_tokens: List[str], max_rows: int = 3) -> List[Any]:
        """Greedily select preview rows that maximize query-term coverage."""
        if not rows:
            return []

        significant_tokens = self._significant_query_tokens(query_tokens)
        if not significant_tokens:
            ranked_rows = sorted(
                rows,
                key=lambda row: (
                    -float(row["raw_score"]) if row["raw_score"] is not None else 0.0,
                    -float(row["line_start"] or 1),
                ),
                reverse=True,
            )
            return ranked_rows[:max_rows]

        remaining_tokens = set(significant_tokens)
        selected: List[Any] = []
        remaining_rows = list(rows)

        while remaining_rows and len(selected) < max_rows:
            best_row = None
            best_key = None
            for row in remaining_rows:
                row_tokens = self._row_token_set(row)
                matched_terms = {token for token in significant_tokens if token in row_tokens}
                new_terms = matched_terms & remaining_tokens
                if self._is_redundant_preview_row(row, selected, new_terms):
                    continue
                raw_score = -float(row["raw_score"]) if row["raw_score"] is not None else 0.0
                candidate_key = (
                    len(new_terms),
                    len(matched_terms),
                    raw_score,
                    -float(row["line_start"] or 1),
                )
                if best_key is None or candidate_key > best_key:
                    best_key = candidate_key
                    best_row = row

            if best_row is None:
                break

            selected.append(best_row)
            row_tokens = self._row_token_set(best_row)
            remaining_tokens -= {token for token in significant_tokens if token in row_tokens}
            remaining_rows = [row for row in remaining_rows if row is not best_row]
            if not remaining_tokens and len(selected) >= 2:
                break

        selected.sort(key=lambda row: float(row["line_start"] or 1))
        return selected

    def _row_overlap_ratio(self, left: Any, right: Any) -> float:
        """Return line-range overlap ratio relative to the shorter row span."""
        left_start = int(left["line_start"] or 1)
        left_end = int(left["line_end"] or left_start)
        right_start = int(right["line_start"] or 1)
        right_end = int(right["line_end"] or right_start)

        overlap_start = max(left_start, right_start)
        overlap_end = min(left_end, right_end)
        if overlap_end < overlap_start:
            return 0.0

        overlap_span = overlap_end - overlap_start + 1
        left_span = max(left_end - left_start + 1, 1)
        right_span = max(right_end - right_start + 1, 1)
        return overlap_span / min(left_span, right_span)

    def _is_redundant_preview_row(self, candidate: Any, selected: List[Any], matched_terms: Set[str]) -> bool:
        """Skip strongly overlapping preview rows unless they add new query coverage."""
        if not selected:
            return False

        for row in selected:
            overlap_ratio = self._row_overlap_ratio(candidate, row)
            if overlap_ratio < 0.6:
                continue

            if not matched_terms:
                return True

        return False

    def _build_multi_chunk_preview(
        self,
        rows: List[Any],
        query: str,
        query_tokens: List[str],
    ) -> tuple[str, int]:
        preview_rows = self._select_preview_rows(rows, query_tokens)
        if not preview_rows:
            return "", 1

        preview_parts: List[str] = []
        first_line_number: Optional[int] = None

        for row in preview_rows:
            chunk_content = row["content"] or ""
            line_start = int(row["line_start"] or 1)
            preview, resolved_line_number = self._build_result_preview(chunk_content, query, line_start)
            if preview:
                preview_parts.append(preview)
                if first_line_number is None or resolved_line_number < first_line_number:
                    first_line_number = resolved_line_number

        if not preview_parts:
            return "", int(preview_rows[0]["line_start"] or 1)

        return "\n\n".join(preview_parts), first_line_number or int(preview_rows[0]["line_start"] or 1)

    def _filename_match_bonus(self, path: str, query_tokens: List[str]) -> float:
        """Add a small bonus when the file path itself matches the query."""
        normalized_path = path.lower()
        basename = os.path.basename(normalized_path)
        stem, _ = os.path.splitext(basename)
        directory_part = os.path.dirname(normalized_path)

        significant_tokens = self._significant_query_tokens(query_tokens)
        if not significant_tokens:
            return 0.0

        basename_token_set = set(self._tokenize(basename))
        stem_token_set = set(self._tokenize(stem))
        directory_token_set = set(self._tokenize(directory_part))
        path_token_set = set(self._tokenize(normalized_path))

        basename_matches = sum(1 for token in significant_tokens if token in basename_token_set)
        stem_matches = sum(1 for token in significant_tokens if token in stem_token_set)
        directory_matches = sum(1 for token in significant_tokens if token in directory_token_set)
        path_matches = sum(1 for token in significant_tokens if token in path_token_set)

        coverage = basename_matches / len(significant_tokens)
        stem_coverage = stem_matches / len(significant_tokens)
        directory_coverage = directory_matches / len(significant_tokens)
        path_coverage = path_matches / len(significant_tokens)
        return min(0.5, coverage * 0.18 + stem_coverage * 0.16 + directory_coverage * 0.08 + path_coverage * 0.08)

    def _significant_query_tokens(self, query_tokens: List[str]) -> List[str]:
        significant_tokens = [token.lower() for token in query_tokens if len(token) > 1]
        if not significant_tokens:
            significant_tokens = [token.lower() for token in query_tokens if token]
        return significant_tokens

    def _extract_row_token_stats(self, rows: List[Any], query_tokens: List[str]) -> tuple[Set[str], Dict[int, Set[str]]]:
        significant_tokens = self._significant_query_tokens(query_tokens)
        if not significant_tokens:
            return set(), {}

        matched_terms: Set[str] = set()
        chunk_matches: Dict[int, Set[str]] = {}
        for row in rows:
            row_tokens = self._row_token_set(row)
            row_matches = {token for token in significant_tokens if token in row_tokens}
            if not row_matches:
                continue
            matched_terms.update(row_matches)
            chunk_index = int(row["chunk_index"] or 0)
            chunk_matches.setdefault(chunk_index, set()).update(row_matches)
        return matched_terms, chunk_matches

    def _select_best_chunk_row(self, rows: List[Any], query_tokens: List[str]) -> Optional[Any]:
        if not rows:
            return None

        significant_tokens = self._significant_query_tokens(query_tokens)

        def row_rank_key(row: Any) -> tuple[float, float, float]:
            row_tokens = self._row_token_set(row)
            matched_count = sum(1 for token in significant_tokens if token in row_tokens)
            raw_score = -float(row["raw_score"]) if row["raw_score"] is not None else 0.0
            return (
                matched_count,
                raw_score,
                -float(row["line_start"] or 1),
            )

        return max(rows, key=row_rank_key)

    def _chunk_cohesion_bonus(
        self,
        chunk_matches: Dict[int, Set[str]],
        significant_tokens: List[str],
    ) -> float:
        """Reward files whose query terms appear in the same or nearby chunks."""
        if not chunk_matches or not significant_tokens:
            return 0.0

        token_count = len(significant_tokens)
        best_single_chunk = max(len(terms) for terms in chunk_matches.values())
        single_chunk_bonus = (best_single_chunk / token_count) * 0.12

        sorted_indexes = sorted(chunk_matches)
        best_window_coverage = 0
        for start_pos, start_idx in enumerate(sorted_indexes):
            covered_terms: Set[str] = set()
            for idx in sorted_indexes[start_pos:]:
                if idx - start_idx > 1:
                    break
                covered_terms.update(chunk_matches[idx])
            best_window_coverage = max(best_window_coverage, len(covered_terms))

        adjacent_window_bonus = (best_window_coverage / token_count) * 0.1
        if best_window_coverage == token_count and token_count > 1:
            adjacent_window_bonus += 0.04

        return single_chunk_bonus + adjacent_window_bonus

    def _chunk_span_bonus(
        self,
        chunk_matches: Dict[int, Set[str]],
        significant_tokens: List[str],
    ) -> float:
        """Reward files that cover the query within a tighter chunk span."""
        if not chunk_matches or not significant_tokens:
            return 0.0

        target_terms = set(significant_tokens)
        if not target_terms:
            return 0.0

        ordered_chunks = sorted((idx, terms & target_terms) for idx, terms in chunk_matches.items() if terms & target_terms)
        if not ordered_chunks:
            return 0.0

        best_bonus = 0.0
        for start_pos, (start_idx, start_terms) in enumerate(ordered_chunks):
            covered_terms = set(start_terms)
            if covered_terms == target_terms:
                return 0.16

            for end_idx, end_terms in ordered_chunks[start_pos + 1:]:
                covered_terms.update(end_terms)
                if covered_terms != target_terms:
                    continue

                span = max(end_idx - start_idx, 0)
                span_bonus = 0.16 / (span + 1)
                if span_bonus > best_bonus:
                    best_bonus = span_bonus
                break

        return best_bonus

    def _score_chunk_hits(self, rows: List[Any], query_tokens: List[str]) -> tuple[float, Optional[Any]]:
        """Return a rerank boost plus the best preview chunk row."""
        if not rows:
            return 0.0, None

        ranked_rows = sorted(
            rows,
            key=lambda row: -float(row["raw_score"]) if row["raw_score"] is not None else 0.0,
            reverse=True,
        )
        chunk_scores = [
            -float(row["raw_score"]) if row["raw_score"] is not None else 0.0
            for row in ranked_rows[:3]
        ]
        best_score = chunk_scores[0]
        second_score = chunk_scores[1] if len(chunk_scores) > 1 else 0.0
        third_score = chunk_scores[2] if len(chunk_scores) > 2 else 0.0
        hit_count_bonus = min(max(len(ranked_rows) - 1, 0), 4) * 0.03
        matched_terms, chunk_matches = self._extract_row_token_stats(ranked_rows, query_tokens)
        significant_tokens = self._significant_query_tokens(query_tokens)
        coverage_bonus = 0.0
        if significant_tokens:
            coverage_ratio = len(matched_terms) / len(significant_tokens)
            coverage_bonus += coverage_ratio * 0.45
            if coverage_ratio >= 1.0 and len(significant_tokens) > 1:
                coverage_bonus += 0.08

        distinct_matching_chunks = sum(1 for terms in chunk_matches.values() if terms)
        chunk_diversity_bonus = min(max(distinct_matching_chunks - 1, 0), 3) * 0.03
        cohesion_bonus = self._chunk_cohesion_bonus(chunk_matches, significant_tokens)
        span_bonus = self._chunk_span_bonus(chunk_matches, significant_tokens)

        return (
            best_score * 0.2
            + second_score * 0.08
            + third_score * 0.04
            + hit_count_bonus
            + coverage_bonus
            + chunk_diversity_bonus
            + cohesion_bonus
            + span_bonus,
            self._select_best_chunk_row(ranked_rows, query_tokens),
        )

    def _build_aggregated_search_result(
        self,
        path: str,
        file_score: float,
        query: str,
        query_tokens: List[str],
        best_chunk_row: Optional[Any],
        preview_rows: Optional[List[Any]] = None,
    ) -> SearchResult:
        """Build the final result preview after ranking has already completed."""
        preview = ""
        line_number = 1

        if preview_rows:
            preview, line_number = self._build_multi_chunk_preview(preview_rows, query, query_tokens)
        elif best_chunk_row is not None:
            chunk_content = best_chunk_row["content"] or ""
            line_start = int(best_chunk_row["line_start"] or 1)
            preview, line_number = self._build_result_preview(chunk_content, query, line_start)
        else:
            doc_ids = self.path_to_doc_ids.get(path, [])
            if doc_ids:
                first_doc = self.documents.get(doc_ids[0])
                if first_doc:
                    preview, line_number = self._build_result_preview(first_doc.content or "", query, first_doc.line_start)

        return SearchResult(
            path=path,
            score=file_score,
            content=preview,
            line_number=line_number,
        )

    def _score_file_candidate(
        self,
        path: str,
        file_score: float,
        rows: List[Any],
        query: str,
        query_tokens: List[str],
    ) -> tuple[float, Optional[Any], List[Any]]:
        """Score a file candidate without eagerly building preview text."""
        file_score_weight = 0.65 if len(query_tokens) > 1 else 1.0
        aggregate_score = file_score * file_score_weight + self._filename_match_bonus(path, query_tokens)
        chunk_boost, best_chunk_row = self._score_chunk_hits(rows, query_tokens)
        aggregate_score += chunk_boost
        preview_rows = self._select_preview_rows(rows, query_tokens)
        return aggregate_score, best_chunk_row, preview_rows

    def _fetch_chunk_rows(
        self,
        conn: sqlite3.Connection,
        match_expr: str,
        paths: List[str],
        chunk_limit: int,
    ) -> List[Any]:
        """Fetch chunk hits for a bounded set of candidate files."""
        if not paths:
            return []

        placeholders = ",".join("?" for _ in paths)
        if not placeholders:
            return []

        return conn.execute(
            f"""
            SELECT path, content, line_start, line_end, chunk_index, bm25(memory_fts) AS raw_score
            FROM memory_fts
            WHERE search_text MATCH ?
              AND path IN ({placeholders})
            ORDER BY raw_score
            LIMIT ?
            """,
            (match_expr, *paths, chunk_limit),
        ).fetchall()

    def _build_match_expr(self, query_tokens: List[str], operator: str = "OR") -> str:
        """Build a safe FTS match expression from query tokens."""
        filtered_tokens = [token for token in query_tokens if token]
        if not filtered_tokens:
            return ""
        joiner = f" {operator} "
        return joiner.join(f'"{token}"' for token in filtered_tokens)

    def _fetch_file_rows(
        self,
        conn: sqlite3.Connection,
        match_expr: str,
        file_limit: int,
        exclude_paths: Optional[Set[str]] = None,
    ) -> List[Any]:
        """Fetch file-level FTS candidates, optionally excluding already-selected paths."""
        if not match_expr or file_limit <= 0:
            return []

        exclude_paths = exclude_paths or set()
        params: List[Any] = [match_expr]
        query = [
            """
            SELECT path, bm25(memory_file_fts) AS raw_file_score
            FROM memory_file_fts
            WHERE search_text MATCH ?
            """
        ]

        if exclude_paths:
            placeholders = ",".join("?" for _ in exclude_paths)
            query.append(f"AND path NOT IN ({placeholders})")
            params.extend(sorted(exclude_paths))

        query.append("ORDER BY raw_file_score")
        query.append("LIMIT ?")
        params.append(file_limit)

        return conn.execute("\n".join(query), params).fetchall()

    def _fetch_candidate_file_rows(
        self,
        conn: sqlite3.Connection,
        query_tokens: List[str],
        file_limit: int,
    ) -> List[Any]:
        """Prefer full multi-term matches, then backfill with partial matches."""
        or_match_expr = self._build_match_expr(query_tokens, operator="OR")
        if not or_match_expr:
            return []

        if len(query_tokens) <= 1:
            return self._fetch_file_rows(conn, or_match_expr, file_limit)

        and_match_expr = self._build_match_expr(query_tokens, operator="AND")
        primary_rows = self._fetch_file_rows(conn, and_match_expr, file_limit)
        if len(primary_rows) >= file_limit:
            return primary_rows

        selected_paths = {row["path"] for row in primary_rows}
        fallback_rows = self._fetch_file_rows(
            conn,
            or_match_expr,
            file_limit - len(primary_rows),
            exclude_paths=selected_paths,
        )
        return primary_rows + fallback_rows

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

            match_expr = self._build_match_expr(query_tokens, operator="OR")
            file_limit = max(top_k * self.DEFAULT_FILE_SEARCH_LIMIT_MULTIPLIER, 20)
            with self._fts_connection() as conn:
                file_rows = self._fetch_candidate_file_rows(conn, query_tokens, file_limit)

                if not file_rows:
                    elapsed = time.time() - start_time
                    logger.info(f"MemoryIndex: Search '{query}' completed, found 0 results in {elapsed:.3f}s")
                    return []

                candidate_paths = [row["path"] for row in file_rows]
                multi_term_query = len(query_tokens) > 1

                if multi_term_query:
                    rerank_limit = min(len(candidate_paths), max(top_k * self.DEFAULT_RERANK_LIMIT_MULTIPLIER, 12))
                    rerank_paths = candidate_paths[:rerank_limit]
                    chunk_limit = max(rerank_limit * self.DEFAULT_CHUNK_ROW_LIMIT_MULTIPLIER, top_k * 6, 20)
                    chunk_rows = self._fetch_chunk_rows(conn, match_expr, rerank_paths, chunk_limit)

                    file_hits: Dict[str, List[Any]] = {}
                    for row in chunk_rows:
                        path = row["path"]
                        file_hits.setdefault(path, []).append(row)

                    scored_candidates = []
                    for file_row in file_rows:
                        path = file_row["path"]
                        file_score = -float(file_row["raw_file_score"]) if file_row["raw_file_score"] is not None else 0.0
                        aggregate_score, best_chunk_row, preview_rows = self._score_file_candidate(
                            path=path,
                            file_score=file_score,
                            rows=file_hits.get(path, []),
                            query=query,
                            query_tokens=query_tokens,
                        )
                        scored_candidates.append((aggregate_score, path, best_chunk_row, preview_rows))

                    scored_candidates.sort(key=lambda item: item[0], reverse=True)
                    top_candidates = scored_candidates[:top_k]
                else:
                    preview_rerank_limit = min(len(candidate_paths), max(top_k * 2, 8))
                    preview_rerank_paths = candidate_paths[:preview_rerank_limit]
                    preview_chunk_limit = max(len(preview_rerank_paths) * 2, top_k * 2, 8)
                    preview_rows = self._fetch_chunk_rows(conn, match_expr, preview_rerank_paths, preview_chunk_limit)
                    preview_hits: Dict[str, List[Any]] = {}
                    for row in preview_rows:
                        preview_hits.setdefault(row["path"], []).append(row)

                    scored_candidates = []
                    for file_row in file_rows:
                        path = file_row["path"]
                        file_score = -float(file_row["raw_file_score"]) if file_row["raw_file_score"] is not None else 0.0
                        rows = preview_hits.get(path, [])
                        if rows:
                            aggregate_score, best_chunk_row, preview_rows = self._score_file_candidate(
                                path=path,
                                file_score=file_score,
                                rows=rows,
                                query=query,
                                query_tokens=query_tokens,
                            )
                        else:
                            aggregate_score = file_score + self._filename_match_bonus(path, query_tokens)
                            best_chunk_row = None
                            preview_rows = []
                        scored_candidates.append((aggregate_score, path, best_chunk_row, preview_rows))

                    scored_candidates.sort(key=lambda item: item[0], reverse=True)
                    top_candidates = scored_candidates[:top_k]

            results = [
                self._build_aggregated_search_result(
                    path=path,
                    file_score=score,
                    query=query,
                    query_tokens=query_tokens,
                    best_chunk_row=best_chunk_row,
                    preview_rows=preview_rows,
                )
                for score, path, best_chunk_row, preview_rows in top_candidates
            ]

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
