"""记忆管理工具

提供简化的用户记忆操作：记住、获取、忘记。
以user_id为索引，支持本地文件和MCP两种实现。

Author: Eric ZZ
Date: 2024-12-21
"""

import json
import os
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sagents.utils.logger import logger

from .tool_base import ToolBase

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    logger.warning("rank_bm25 not available, falling back to simple text matching")


# ========== 记忆数据格式规范 ==========
"""
记忆存储格式说明：

1. 文件结构：
   - 路径：{MEMORY_ROOT_PATH}/{user_id}/memories.json
   - 格式：JSON文件，UTF-8编码

2. 数据结构：
   {
     "memory_key1": {
       "content": "记忆内容（必需，字符串）",
       "tags": ["标签1", "标签2"],  // 可选，字符串数组
       "created_at": "2024-12-21T18:45:00.123456",  // 必需，ISO格式时间戳
       "updated_at": "2024-12-21T18:45:00.123456",  // 必需，ISO格式时间戳
       "metadata": {  // 可选，扩展元数据
         "importance": 0.8,  // 重要性评分 0-1
         "category": "技术",  // 分类
         "source": "用户输入"  // 来源
       }
     },
     "memory_key2": { ... }
   }

3. 字段说明：
   - memory_key: 记忆的唯一标识符，字符串类型，不能为空
   - content: 记忆内容，字符串类型，不能为空
   - tags: 标签数组，可选，每个标签为非空字符串
   - created_at: 创建时间，ISO 8601格式字符串
   - updated_at: 更新时间，ISO 8601格式字符串
   - metadata: 可选的扩展元数据，对象类型

4. 约束条件：
   - memory_key长度：1-100字符
   - content长度：1-10000字符
   - tags数量：最多20个
   - 单个tag长度：1-50字符
   - 时间格式：必须是有效的ISO 8601格式

5. 工具返回格式规范：
    {{
        "success": true/false,
        "message": "操作结果描述", 
        "memories": [...],     # 只有在recall 的时候返回memories 列表
        "error": "错误信息"   # 仅在success为false时存在
    }}
"""


class MemoryTool(ToolBase):
    """记忆管理工具 - 简化的记忆操作接口（以user_id为索引）"""

    def __init__(self):
        """
        初始化记忆工具

        不在初始化时获取环境变量，而是在使用时动态获取
        """
        super().__init__()
        logger.info("MemoryTool initialized, will get memory_root dynamically from environment")

    def _validate_memory_data(self, memory_key: str = None, content: str = None,
                              tags: List[str] = None, memories: Dict[str, Any] = None) -> tuple[bool, str]:
        """统一的记忆数据校验函数

        Args:
            memory_key: 记忆键（可选）
            content: 记忆内容（可选）
            tags: 标签列表（可选）
            memories: 完整记忆数据（可选）

        Returns:
            (是否有效, 错误信息)
        """
        try:
            # 校验记忆键
            if memory_key is not None:
                if not memory_key or not isinstance(memory_key, str):
                    return False, "记忆键不能为空且必须是字符串"
                if len(memory_key) < 1 or len(memory_key) > 100:
                    return False, "记忆键长度必须在1-100字符之间"
                if any(char in memory_key for char in ['/', '\\', '..', '\0']):
                    return False, "记忆键不能包含路径分隔符"

            # 校验内容
            if content is not None:
                if not content or not isinstance(content, str):
                    return False, "记忆内容不能为空且必须是字符串"
                if len(content.strip()) < 1 or len(content) > 10000:
                    return False, "记忆内容长度必须在1-10000字符之间"

            # 校验标签
            if tags is not None:
                if not isinstance(tags, list):
                    return False, "标签必须是列表类型"
                if len(tags) > 20:
                    return False, "标签数量不能超过20个"
                for tag in tags:
                    if not isinstance(tag, str) or len(tag.strip()) < 1 or len(tag) > 50:
                        return False, "每个标签必须是1-50字符的非空字符串"

            # 校验完整记忆数据
            if memories is not None:
                if not isinstance(memories, dict):
                    return False, "记忆数据必须是字典类型"

                for key, entry in memories.items():
                    # 递归校验每个条目
                    is_valid, error_msg = self._validate_memory_data(memory_key=key)
                    if not is_valid:
                        return False, f"记忆键 '{key}' 无效: {error_msg}"

                    if not isinstance(entry, dict):
                        return False, f"记忆条目 '{key}' 必须是字典类型"

                    # 检查必需字段
                    if 'content' not in entry:
                        return False, f"记忆条目 '{key}' 缺少content字段"

                    is_valid, error_msg = self._validate_memory_data(content=entry['content'])
                    if not is_valid:
                        return False, f"记忆条目 '{key}' 内容无效: {error_msg}"

                    # 校验可选字段
                    if 'tags' in entry:
                        is_valid, error_msg = self._validate_memory_data(tags=entry['tags'])
                        if not is_valid:
                            return False, f"记忆条目 '{key}' 标签无效: {error_msg}"

            return True, ""

        except Exception as e:
            return False, f"校验过程中发生错误: {str(e)}"

    def _format_response(self, success: bool, message: str, memories: List[Dict] = None, error: str = None) -> str:
        """格式化标准返回结果

        Args:
            success: 操作是否成功
            message: 操作结果描述
            memories: 记忆列表（仅在recall时使用）
            error: 错误信息（仅在success为false时使用）

        Returns:
            JSON格式的标准返回字符串
        """
        import json

        response = {
            "success": success,
            "message": message
        }

        if memories is not None:
            response["memories"] = memories

        if not success and error:
            response["error"] = error

        return json.dumps(response, ensure_ascii=False)

    def _repair_memories_data(self, memories: Dict[str, Any]) -> Dict[str, Any]:
        """尝试修复损坏的记忆数据

        Args:
            memories: 原始记忆数据

        Returns:
            修复后的记忆数据
        """
        repaired_memories = {}
        current_time = datetime.now().isoformat()

        if not isinstance(memories, dict):
            logger.warning("记忆数据不是字典类型，返回空数据")
            return {}

        for memory_key, memory_entry in memories.items():
            try:
                # 校验记忆键
                is_valid, _ = self._validate_memory_data(memory_key=memory_key)
                if not is_valid:
                    logger.warning(f"跳过无效的记忆键: {memory_key}")
                    continue

                # 修复记忆条目
                if not isinstance(memory_entry, dict):
                    logger.warning(f"跳过无效的记忆条目: {memory_key}")
                    continue

                repaired_entry = {}

                # 修复内容字段
                content = memory_entry.get('content', '')
                is_valid, _ = self._validate_memory_data(content=content)
                if not is_valid:
                    if isinstance(content, str) and len(content.strip()) > 0:
                        # 截断过长的内容
                        content = content[:10000]
                        is_valid, _ = self._validate_memory_data(content=content)
                        if not is_valid:
                            logger.warning(f"跳过内容无效的记忆: {memory_key}")
                            continue
                    else:
                        logger.warning(f"跳过内容无效的记忆: {memory_key}")
                        continue
                repaired_entry['content'] = content

                # 修复标签字段
                tags = memory_entry.get('tags', [])
                if not isinstance(tags, list):
                    tags = []
                else:
                    # 过滤无效标签
                    valid_tags = []
                    for tag in tags[:20]:  # 最多保留20个标签
                        if isinstance(tag, str) and 1 <= len(tag.strip()) <= 50:
                            valid_tags.append(tag.strip())
                    tags = valid_tags

                # 校验修复后的标签
                is_valid, _ = self._validate_memory_data(tags=tags)
                if is_valid:
                    repaired_entry['tags'] = tags
                else:
                    repaired_entry['tags'] = []

                # 修复时间戳字段
                created_at = memory_entry.get('created_at', current_time)
                if not self._validate_timestamp(created_at):
                    created_at = current_time
                repaired_entry['created_at'] = created_at

                updated_at = memory_entry.get('updated_at', current_time)
                if not self._validate_timestamp(updated_at):
                    updated_at = current_time
                repaired_entry['updated_at'] = updated_at

                # 保留有效的元数据
                if 'metadata' in memory_entry and isinstance(memory_entry['metadata'], dict):
                    repaired_entry['metadata'] = memory_entry['metadata']

                repaired_memories[memory_key] = repaired_entry

            except Exception as e:
                logger.warning(f"修复记忆条目失败 {memory_key}: {e}")
                continue

        logger.info(f"数据修复完成，保留 {len(repaired_memories)} 条有效记忆")
        return repaired_memories

    def _get_user_memory_path(self, user_id: str) -> Path:
        """获取用户记忆文件路径

        Args:
            user_id: 用户ID

        Returns:
            用户记忆文件路径
        """
        memory_root = os.getenv('MEMORY_ROOT_PATH')
        logger.debug(f"获取用户记忆文件路径，用户ID: {user_id}")
        logger.debug(f"获取用户记忆文件路径，记忆根路径: {memory_root}")

        if not memory_root:
            raise RuntimeError("本地记忆功能不可用：未设置MEMORY_ROOT_PATH环境变量")

        user_dir = Path(memory_root) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "memories.json"

    def _load_user_memories(self, user_id: str) -> Dict[str, Any]:
        """加载用户记忆（带数据校验）

        Args:
            user_id: 用户ID

        Returns:
            用户记忆字典
        """
        try:
            memory_file = self._get_user_memory_path(user_id)
            if memory_file.exists():
                with open(memory_file, 'r', encoding='utf-8') as f:
                    memories = json.load(f)

                # 数据校验
                is_valid, error_msg = self._validate_memory_data(memories=memories)
                if not is_valid:
                    logger.warning(f"用户记忆数据格式无效 {user_id}: {error_msg}，尝试修复")
                    # 尝试修复数据
                    memories = self._repair_memories_data(memories)
                    # 保存修复后的数据
                    self._save_user_memories(user_id, memories)

                return memories
            return {}
        except Exception as e:
            logger.error(f"加载用户记忆失败 {user_id}: {e}")
            return {}

    def _save_user_memories(self, user_id: str, memories: Dict[str, Any]):
        """保存用户记忆（带数据校验）

        Args:
            user_id: 用户ID
            memories: 记忆字典

        Raises:
            ValueError: 数据格式无效
            IOError: 文件保存失败
        """
        try:
            # 保存前进行数据校验
            is_valid, error_msg = self._validate_memory_data(memories=memories)
            if not is_valid:
                raise ValueError(f"记忆数据格式无效: {error_msg}")

            memory_file = self._get_user_memory_path(user_id)

            # 创建备份（如果原文件存在）
            if memory_file.exists():
                backup_file = memory_file.with_suffix('.json.backup')
                memory_file.rename(backup_file)
                logger.debug(f"创建备份文件: {backup_file}")

            # 保存新数据
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(memories, f, ensure_ascii=False, indent=2)

            logger.debug(f"成功保存用户记忆 {user_id}: {len(memories)} 条记忆")

        except Exception as e:
            logger.error(f"保存用户记忆失败 {user_id}: {e}")
            # 如果保存失败且存在备份，尝试恢复
            backup_file = self._get_user_memory_path(user_id).with_suffix('.json.backup')
            if backup_file.exists():
                try:
                    backup_file.rename(self._get_user_memory_path(user_id))
                    logger.info(f"已恢复备份文件 {user_id}")
                except Exception as restore_error:
                    logger.error(f"恢复备份失败 {user_id}: {restore_error}")
            raise

    def _tokenize_text(self, text: str) -> List[str]:
        """文本分词

        Args:
            text: 输入文本

        Returns:
            分词结果列表
        """
        if not text or not text.strip():
            return []

        # 简单的中英文分词
        # 移除标点符号，转换为小写
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text.lower())

        tokens = []
        # 按空格分割
        words = text.split()

        for word in words:
            if not word.strip():
                continue

            # 检查是否包含中文
            if re.search(r'[\u4e00-\u9fff]', word):
                # 包含中文，提取中文字符和英文单词
                chinese_chars = re.findall(r'[\u4e00-\u9fff]', word)
                english_parts = re.findall(r'[a-zA-Z]+', word)
                tokens.extend(chinese_chars)
                tokens.extend(english_parts)
            else:
                # 纯英文单词
                if len(word) > 1:  # 过滤单字符
                    tokens.append(word)

        return [token for token in tokens if token.strip() and len(token) > 0]

    def _bm25_search(self, query: str, documents: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        """使用BM25算法进行相似度搜索

        Args:
            query: 查询字符串
            documents: 文档列表，每个文档包含key, content, tags等字段
            limit: 返回结果数量限制

        Returns:
            按相似度排序的文档列表
        """
        if not BM25_AVAILABLE or not documents:
            return []

        try:
            # 构建文档语料库（key + content的拼接）
            corpus = []
            for doc in documents:
                key = doc.get('key', '')
                content = doc.get('content', '')
                # 拼接key和content
                combined_text = f"{key} {content}"
                # 分词
                tokens = self._tokenize_text(combined_text)
                corpus.append(tokens)

            if not corpus:
                return []

            # 创建BM25模型
            bm25 = BM25Okapi(corpus)

            # 查询分词
            query_tokens = self._tokenize_text(query)

            # 计算相似度分数
            scores = bm25.get_scores(query_tokens)

            # 将分数与文档配对并排序
            scored_docs = list(zip(documents, scores))
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            # 调试信息
            logger.debug(f"BM25搜索结果: {[(doc['key'], score) for doc, score in scored_docs[:5]]}")

            # 降低阈值，只要分数大于0.1就认为相关
            filtered_docs = [(doc, score) for doc, score in scored_docs if score > 0.1][:limit]

            # 如果没有找到相关结果，返回分数最高的几个
            if not filtered_docs and scored_docs:
                filtered_docs = scored_docs[:limit]

            return [doc for doc, score in filtered_docs]

        except Exception as e:
            logger.error(f"BM25搜索失败: {e}")
            return []

    def _simple_search(self, query: str, documents: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        """简单文本匹配搜索（BM25不可用时的回退方案）

        Args:
            query: 查询字符串
            documents: 文档列表
            limit: 返回结果数量限制

        Returns:
            匹配的文档列表
        """
        matches = []
        query_lower = query.lower()

        for doc in documents:
            key = doc.get('key', '')
            content = doc.get('content', '')
            tags = doc.get('tags', [])

            # 在key、content和标签中搜索
            if (query_lower in content.lower() or
                query_lower in key.lower() or
                    any(query_lower in tag.lower() for tag in tags)):
                matches.append(doc)

        # 按创建时间排序
        matches.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return matches[:limit]

    @ToolBase.tool()
    def remember_user_memory(self, user_id: str, memory_key: str, content: str, memory_type: str = "experience", tags: str = "") -> str:
        """记录用户的记忆，包括不限于用户偏好、个人信息、特殊要求、重要上下文等，memory_key和content 均使用用户的语言种类，便于后续检索。
        memory_key 和 content 中的描述尽可能使用绝对值，例如时间"明天"，要转换成绝对日期。

        Args:
            user_id: 用户ID
            memory_key: 记忆键（唯一标识）
            content: 记忆内容
            memory_type: 记忆类型（preference/requirement/persona/constraint/context/project/workflow/experience/learning/skill/note/bookmark/pattern）
            tags: 标签（逗号分隔或列表）

        Returns:
            JSON格式的标准返回字符串

        Example:
            remember('user123', 'coding_style', '用户偏好函数式编程', 'preference', 'coding')
        """
        # 检查环境变量是否设置
        if not os.getenv('MEMORY_ROOT_PATH'):
            return self._format_response(False, "本地记忆功能不可用：未设置MEMORY_ROOT_PATH环境变量")

        try:
            logger.debug(f"记录记忆 {user_id}: {memory_key}, 类型: {memory_type}")

            # 输入参数校验
            is_valid, error_msg = self._validate_memory_data(memory_key=memory_key)
            if not is_valid:
                return self._format_response(False, "记忆键格式无效", error=error_msg)

            is_valid, error_msg = self._validate_memory_data(content=content)
            if not is_valid:
                return self._format_response(False, "记忆内容格式无效", error=error_msg)

            # 验证记忆类型
            valid_types = ["preference", "requirement", "persona", "constraint", "context",
                           "project", "workflow", "experience", "learning", "skill",
                           "note", "bookmark", "pattern"]
            if memory_type not in valid_types:
                return self._format_response(False, f"无效的记忆类型: {memory_type}，支持的类型: {', '.join(valid_types)}")

            # 处理标签
            if isinstance(tags, list):
                tag_list = tags
            else:
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
            is_valid, error_msg = self._validate_memory_data(tags=tag_list)
            if not is_valid:
                return self._format_response(False, "标签格式无效", error=error_msg)

            memories = self._load_user_memories(user_id)

            # 创建记忆条目
            current_time = datetime.now().isoformat()
            memory_entry = {
                "content": content.strip(),
                "memory_type": memory_type,
                "tags": tag_list,
                "created_at": current_time,
                "updated_at": current_time
            }

            # 如果记忆已存在，更新时间戳
            is_update = memory_key in memories
            if is_update:
                memory_entry["created_at"] = memories[memory_key].get("created_at", current_time)
                logger.debug(f"更新已存在的记忆: {memory_key}")

            memories[memory_key] = memory_entry
            self._save_user_memories(user_id, memories)

            action = "更新" if is_update else "记住"
            return self._format_response(True, f"已{action}记忆：{memory_key} (类型: {memory_type})")

        except ValueError as e:
            logger.error(traceback.format_exc())
            logger.error(f"记录记忆数据校验失败 {user_id}: {e}")
            return self._format_response(False, "记录记忆失败", error=str(e))
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"记录记忆失败 {user_id}: {e}")
            return self._format_response(False, "记录记忆失败", error=str(e))

    @ToolBase.tool()
    def recall_user_memory_by_type(self, user_id: str, memory_type: str, query: str = "", limit: int = 5) -> str:
        """按记忆类型检索用户的记忆

        Args:
            user_id: 用户ID
            memory_type: 记忆类型（preference/requirement/persona/constraint/context/project/workflow/experience/learning/skill/note/bookmark/pattern）
            query: 查询内容（可选，为空时返回该类型的所有记忆）
            limit: 返回结果数量限制（1-50）

        Returns:
            按相似度排序的匹配记忆列表

        Example:
            recall_by_type('user123', 'preference', 'coding', 3)
        """
        # 检查环境变量是否设置
        if not os.getenv('MEMORY_ROOT_PATH'):
            return self._format_response(False, "本地记忆功能不可用：未设置MEMORY_ROOT_PATH环境变量")

        try:
            # 验证记忆类型
            valid_types = ["preference", "requirement", "persona", "constraint", "context",
                           "project", "workflow", "experience", "learning", "skill",
                           "note", "bookmark", "pattern"]
            if memory_type not in valid_types:
                return self._format_response(False, f"无效的记忆类型: {memory_type}，支持的类型: {', '.join(valid_types)}")

            logger.debug(f"按类型搜索记忆 {user_id}: 类型={memory_type}, 查询={query}")

            memories = self._load_user_memories(user_id)

            if not memories:
                return "未找到任何记忆"

            # 按类型过滤记忆
            type_filtered_docs = []
            for key, memory in memories.items():
                if memory.get('memory_type') == memory_type:
                    content = memory.get('content', '')
                    if content and content.strip():
                        type_filtered_docs.append({
                            'key': key,
                            'content': content,
                            'memory_type': memory.get('memory_type', ''),
                            'tags': memory.get('tags', []),
                            'created_at': memory.get('created_at', '')
                        })

            if not type_filtered_docs:
                return self._format_response(True, f"未找到类型为 '{memory_type}' 的记忆", memories=[])

            # 如果有查询条件，进行搜索；否则返回所有该类型的记忆
            if query and query.strip():
                if BM25_AVAILABLE:
                    matches = self._bm25_search(query, type_filtered_docs, limit)
                    search_method = "BM25"
                else:
                    matches = self._simple_search(query, type_filtered_docs, limit)
                    search_method = "简单匹配"

                if matches:
                    formatted_memories = []
                    for match in matches:
                        formatted_memories.append({
                            "key": match['key'],
                            "content": match['content'],
                            "memory_type": match['memory_type'],
                            "tags": match['tags'],
                            "created_at": match.get('created_at', '')
                        })

                    message = f"找到 {len(matches)} 条类型为 '{memory_type}' 的相关记忆（{search_method}）"
                    return self._format_response(True, message, memories=formatted_memories)
                else:
                    return self._format_response(True, f"未找到类型为 '{memory_type}' 且与 '{query}' 相关的记忆", memories=[])
            else:
                # 无查询条件，返回所有该类型的记忆
                # 按创建时间排序
                type_filtered_docs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                limited_docs = type_filtered_docs[:limit]

                formatted_memories = []
                for doc in limited_docs:
                    formatted_memories.append({
                        "key": doc['key'],
                        "content": doc['content'],
                        "memory_type": doc['memory_type'],
                        "tags": doc['tags'],
                        "created_at": doc.get('created_at', '')
                    })

                message = f"找到 {len(formatted_memories)} 条类型为 '{memory_type}' 的记忆"
                return self._format_response(True, message, memories=formatted_memories)

        except Exception as e:
            logger.error(f"按类型搜索记忆失败 {user_id}: {e}")
            return self._format_response(False, "搜索记忆失败", error=str(e))

    @ToolBase.tool()
    def recall_user_memory(self, user_id: str, query: str, limit: int = 5) -> str:
        """根据查询内容检索用户的记忆，返回与查询内容相关的记忆列表

        Args:
            user_id: 用户ID
            query: 查询内容（关键词）
            limit: 返回结果数量限制（1-50）

        Returns:
            按相似度排序的匹配记忆列表

        Example:
            recall('user123', 'coding', 3)
        """
        # 检查环境变量是否设置
        if not os.getenv('MEMORY_ROOT_PATH'):
            return self._format_response(False, "本地记忆功能不可用：未设置MEMORY_ROOT_PATH环境变量")

        try:
            logger.debug(f"使用BM25搜索记忆 {user_id}: {query}")

            memories = self._load_user_memories(user_id)

            if not memories:
                return "未找到任何记忆"

            # 将记忆转换为文档格式，过滤掉空内容
            documents = []
            for key, memory in memories.items():
                content = memory.get('content', '')
                # 过滤掉空内容的记忆
                if content and content.strip():
                    documents.append({
                        'key': key,
                        'content': content,
                        'tags': memory.get('tags', []),
                        'created_at': memory.get('created_at', '')
                    })

            if not documents:
                return "未找到任何有效记忆"

            # 使用BM25搜索或简单搜索
            if BM25_AVAILABLE:
                matches = self._bm25_search(query, documents, limit)
                search_method = "BM25"
            else:
                matches = self._simple_search(query, documents, limit)
                search_method = "简单匹配"

            if matches:
                # 格式化记忆列表
                formatted_memories = []
                for match in matches:
                    formatted_memories.append({
                        "key": match['key'],
                        "content": match['content'],
                        "tags": match['tags'],
                        "created_at": match.get('created_at', '')
                    })

                message = f"找到 {len(matches)} 条相关记忆（{search_method}）"
                return self._format_response(True, message, memories=formatted_memories)
            else:
                return self._format_response(True, f"未找到与 '{query}' 相关的记忆", memories=[])

        except Exception as e:
            logger.error(f"搜索记忆失败 {user_id}: {e}")
            return self._format_response(False, "搜索记忆失败", error=str(e))

    @ToolBase.tool()
    def forget_user_memory(self, user_id: str, memory_key: str) -> str:
        """删除用户的指定的记忆

        Args:
            user_id: 用户ID
            memory_key: 要删除的记忆键

        Returns:
            JSON格式的标准返回字符串

        Example:
            forget('user123', 'old_preference')
        """
        # 检查环境变量是否设置
        if not os.getenv('MEMORY_ROOT_PATH'):
            return self._format_response(False, "本地记忆功能不可用：未设置MEMORY_ROOT_PATH环境变量")

        try:
            logger.debug(f"删除记忆 {user_id}: {memory_key}")

            memories = self._load_user_memories(user_id)

            if memory_key in memories:
                del memories[memory_key]
                self._save_user_memories(user_id, memories)
                return self._format_response(True, f"已忘记：{memory_key}")
            else:
                return self._format_response(False, f"记忆不存在：{memory_key}")

        except Exception as e:
            logger.error(f"删除记忆失败 {user_id}: {e}")
            return self._format_response(False, "删除记忆失败", error=str(e))

    def _validate_timestamp(self, timestamp: str) -> bool:
        """验证时间戳格式是否正确

        Args:
            timestamp: 时间戳字符串

        Returns:
            是否为正确的时间戳格式
        """
        try:
            datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            return True
        except ValueError:
            return False


# 工具实例（单例模式）
_memory_tool_instance = None


def get_memory_tool() -> MemoryTool:
    """获取记忆工具实例

    Returns:
        记忆工具实例
    """
    global _memory_tool_instance

    if _memory_tool_instance is None:
        _memory_tool_instance = MemoryTool()

    return _memory_tool_instance
