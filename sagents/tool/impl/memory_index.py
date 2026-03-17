#!/usr/bin/env python3
"""
File-based memory index using BM25 algorithm
Supports incremental updates and fast search
"""
import os
import pickle
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime

from sagents.utils.logger import logger


@dataclass
class FileDocument:
    """File document"""
    path: str           # Absolute file path
    content: str        # File content (text for BM25)
    mtime: float        # Modification time
    size: int           # File size
    hash: str           # Content hash
    doc_id: int         # Document ID (index in BM25)


@dataclass
class SearchResult:
    """Search result"""
    path: str           # File path
    score: float        # BM25 score
    content: str        # Content preview
    line_number: int    # Line number (if applicable)


class MemoryIndex:
    """
    BM25-based memory index manager

    Features:
    1. Incremental updates - only process changed files
    2. Fast folder mtime check - skip scanning if no changes
    3. Smart tokenization - supports Chinese and English
    4. Blacklist filtering - skip unwanted directories
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

    def __init__(self, workspace_path: str, index_path: str, blacklist: Optional[Set[str]] = None):
        """
        Initialize memory index

        Args:
            workspace_path: Workspace path to index (folder)
            index_path: Index file save path (.pkl file)
            blacklist: Additional blacklist directory set
        """
        start_time = time.time()
        
        self.workspace_path = Path(workspace_path)
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory data
        self.bm25 = None
        self.documents: Dict[int, FileDocument] = {}
        self.path_to_id: Dict[str, int] = {}
        self._next_doc_id = 0
        self._last_folder_mtime: float = 0  # Last known folder mtime
        self._last_file_count: int = 0  # Last known file count

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
                self._last_folder_mtime = data.get('last_folder_mtime', 0)
                self._last_file_count = data.get('last_file_count', 0)

                # Rebuild path -> id mapping
                self.path_to_id = {doc.path: doc.doc_id for doc in self.documents.values()}

                # Calculate next doc_id
                if self.documents:
                    self._next_doc_id = max(self.documents.keys()) + 1

                elapsed = time.time() - start_time
                logger.info(f"MemoryIndex: Loaded {len(self.documents)} documents from {self.index_path} in {elapsed:.3f}s")
                return True
        except Exception as e:
            logger.warning(f"MemoryIndex: Failed to load index: {e}")
            self.bm25 = None
            self.documents = {}
            self.path_to_id = {}
            self._next_doc_id = 0
            self._last_folder_mtime = 0
            self._last_file_count = 0

        return False

    def _save_index(self) -> bool:
        """Save index to single pkl file"""
        start_time = time.time()
        
        try:
            data = {
                'bm25': self.bm25,
                'documents': self.documents,
                'last_folder_mtime': self._last_folder_mtime,
                'last_file_count': self._last_file_count,
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

    def _compute_file_hash(self, filepath: str) -> str:
        """Compute file content hash"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""

    def _read_file_content(self, filepath: str, max_size: int = 100 * 1024) -> str:
        """Read file content with size limit"""
        try:
            size = os.path.getsize(filepath)
            if size > max_size:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read(max_size) + "\n[File too large, truncated]"
            else:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
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

    def _is_path_blacklisted(self, path: Path) -> bool:
        """Check if path is in blacklist"""
        try:
            rel_path = path.relative_to(self.workspace_path)
        except ValueError:
            rel_path = path

        for part in rel_path.parts:
            if part in self.blacklist:
                return True
            for pattern in self.blacklist:
                if '*' in pattern:
                    import fnmatch
                    if fnmatch.fnmatch(part, pattern):
                        return True
        return False

    def _get_folder_state(self, file_extensions: List[str]) -> tuple[float, int]:
        """
        Get folder state for change detection
        Returns: (latest_mtime, file_count)
        """
        latest_mtime = 0
        file_count = 0
        ext_set = set(ext.lower() for ext in file_extensions)
        
        try:
            for root, dirs, files in os.walk(self.workspace_path):
                # Filter out blacklisted directories
                dirs[:] = [d for d in dirs if d not in self.blacklist]
                
                for file in files:
                    # Quick extension check
                    if Path(file).suffix.lower() not in ext_set:
                        continue
                    
                    filepath = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(filepath)
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                        file_count += 1
                    except OSError:
                        continue
        except Exception as e:
            logger.warning(f"MemoryIndex: Error getting folder state: {e}")
        
        return latest_mtime, file_count

    def _collect_files(self, file_extensions: List[str]) -> Set[str]:
        """Collect all files matching extensions in workspace"""
        current_files: Set[str] = set()
        ext_set = set(ext.lower() for ext in file_extensions)
        
        for root, dirs, files in os.walk(self.workspace_path):
            # Filter out blacklisted directories
            dirs[:] = [d for d in dirs if d not in self.blacklist]
            
            for file in files:
                # Quick extension check
                if Path(file).suffix.lower() not in ext_set:
                    continue
                
                filepath = os.path.join(root, file)
                current_files.add(str(Path(filepath).resolve()))
        
        return current_files

    def update_index(self, file_extensions: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
        """
        Update index (auto incremental)

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

        if not self.workspace_path.exists():
            logger.warning(f"MemoryIndex: Workspace does not exist: {self.workspace_path}")
            return stats

        # Fast check: compare folder state (mtime + file count)
        if not force and self.documents:
            folder_mtime, file_count = self._get_folder_state(file_extensions)
            # Check if mtime changed OR file count changed (handles deletions)
            if folder_mtime <= self._last_folder_mtime and file_count == self._last_file_count:
                stats["skipped"] = True
                stats["total_time"] = time.time() - total_start_time
                logger.info(f"MemoryIndex: No changes detected, skipping scan. Total time: {stats['total_time']:.3f}s")
                return stats
            self._last_folder_mtime = folder_mtime
            self._last_file_count = file_count

        scan_start = time.time()
        
        # Collect current files
        current_files = self._collect_files(file_extensions)
        
        # Check added and modified files
        files_to_check = list(current_files)
        for filepath in files_to_check:
            try:
                stat = os.stat(filepath)
                mtime = stat.st_mtime
                size = stat.st_size

                if filepath in self.path_to_id:
                    # File exists, check if modified
                    doc_id = self.path_to_id[filepath]
                    old_doc = self.documents[doc_id]

                    # Optimization: compare mtime and size first
                    if old_doc.mtime == mtime and old_doc.size == size:
                        stats["unchanged"] += 1
                        continue

                    # mtime or size changed, need hash to confirm
                    file_hash = self._compute_file_hash(filepath)
                    
                    if old_doc.hash != file_hash:
                        # File modified, update
                        content = self._read_file_content(filepath)
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
                        # Hash same, only mtime changed
                        old_doc.mtime = mtime
                        stats["unchanged"] += 1
                else:
                    # New file, add
                    file_hash = self._compute_file_hash(filepath)
                    content = self._read_file_content(filepath)
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

        # Check deleted files
        indexed_paths = set(self.path_to_id.keys())
        deleted_paths = indexed_paths - current_files

        for filepath in deleted_paths:
            doc_id = self.path_to_id[filepath]
            del self.documents[doc_id]
            del self.path_to_id[filepath]
            stats["removed"] += 1
            logger.debug(f"MemoryIndex: Removed file {filepath}")

        stats["scan_time"] = time.time() - scan_start

        # Rebuild BM25 index
        build_start = time.time()
        has_changes = stats["added"] > 0 or stats["updated"] > 0 or stats["removed"] > 0
        
        if has_changes:
            self._build_bm25()
            stats["build_time"] = time.time() - build_start
            
            save_start = time.time()
            self._save_index()
            stats["save_time"] = time.time() - save_start
            
            stats["total_time"] = time.time() - total_start_time
            logger.info(f"MemoryIndex: Index updated - added:{stats['added']}, updated:{stats['updated']}, removed:{stats['removed']}, unchanged:{stats['unchanged']}, scan:{stats['scan_time']:.3f}s, build:{stats['build_time']:.3f}s, save:{stats['save_time']:.3f}s, total:{stats['total_time']:.3f}s")
        else:
            # Update folder state even if no file changes
            self._last_folder_mtime, self._last_file_count = self._get_folder_state(file_extensions)
            self._save_index()
            
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
        self._last_folder_mtime = 0
        self._last_file_count = 0

        if self.index_path.exists():
            self.index_path.unlink()

        elapsed = time.time() - start_time
        logger.info(f"MemoryIndex: Index cleared in {elapsed:.3f}s")
