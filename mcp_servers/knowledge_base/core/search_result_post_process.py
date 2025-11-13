"""
Search Result Post-Process Tool for MCP Server

A tool for post-processing search results including RRF fusion and overlap merging.
Based on SearchResultPostProcess from the provided search_result_postprocess.py.
"""

from typing import List, Dict, Any
import logging

import traceback
logger = logging.getLogger(__name__)


class SearchResultPostProcessTool:
    """搜索结果后处理工具"""
    
    def __init__(self):
        """初始化搜索结果后处理工具"""
        pass
    
    def rrf_fusion_for_search_chunks(self, search_results: List[Dict[str, Any]], rrf_k: int = 1) -> List[Dict[str, Any]]:
        """
        使用RRF（Reciprocal Rank Fusion）融合搜索结果
        
        Args:
            search_results: 搜索结果列表
            rrf_k: RRF参数k值
            
        Returns:
            融合后的搜索结果
        """
        if not search_results:
            return []
            
        # 获取所有搜索源
        search_source = set([item['source'] for item in search_results])
        search_results_by_source = {item: [] for item in search_source}
        document_nums_by_source = {item: {} for item in search_source}
        
        # 按搜索源分组
        for result in search_results:
            search_results_by_source[result['source']].append(result)
            if result['doc_id'] not in document_nums_by_source[result['source']]:
                document_nums_by_source[result['source']][result['doc_id']] = 0
            document_nums_by_source[result['source']][result['doc_id']] += 1
        
        # 对每个搜索源的结果进行排序和归一化
        search_results_new = []
        for source_item in search_results_by_source.keys():
            search_results_by_source[source_item] = sorted(
                search_results_by_source[source_item], 
                key=lambda x: x['score'], 
                reverse=True
            )
            
            max_score = max(item['score'] for item in search_results_by_source[source_item])
            min_score = min(item['score'] for item in search_results_by_source[source_item])
            
            for index in range(len(search_results_by_source[source_item])):
                search_results_by_source[source_item][index]['ranking'] = index + 1
                if max_score - min_score > 0:
                    search_results_by_source[source_item][index]['normal_score'] = (
                        search_results_by_source[source_item][index]["score"] - min_score
                    ) / (max_score - min_score)
                else:
                    search_results_by_source[source_item][index]['normal_score'] = 1
                    
            search_results_new.extend(search_results_by_source[source_item])
        
        search_results = search_results_new
        
        # 合并相同内容的结果
        merged_results = {}
        for result in search_results:
            chunk = result["doc_content"]
            if chunk not in merged_results:
                merged_results[chunk] = {
                    "scores": {},
                    "normal_scores": {},
                    "doc_id": result['doc_id'],
                    "rankings": {},
                    "doc_content": chunk,
                    "sources": [],
                    "doc_segment_id": result['doc_segment_id'],
                    "start": result['start'],
                    "end": result['end']
                }
            merged_results[chunk]['sources'].append(result['source'])
            merged_results[chunk]['scores'][result['source']] = result['score']
            merged_results[chunk]['normal_scores'][result['source']] = result['normal_score']
            merged_results[chunk]['rankings'][result['source']] = result['ranking']
        
        # 计算RRF分数
        for chunk in merged_results.keys():
            rrf_score = 0
            for search_source_item in search_source:
                rank = merged_results[chunk]["rankings"].get(
                    search_source_item, 
                    len(search_results_by_source[search_source_item]) + 1
                )
                score = merged_results[chunk]['normal_scores'].get(search_source_item, 0)
                document_frequency_in_source = document_nums_by_source[search_source_item].get(
                    merged_results[chunk]['doc_id'], 0
                )
                document_frequency = len(merged_results[chunk]["rankings"].keys()) / len(search_source)
                adjusted_score = score * (1 + 0.05 * document_frequency_in_source)
                rrf_score += document_frequency * (adjusted_score / (rrf_k + rank))
            merged_results[chunk]["score"] = rrf_score
        
        # 按分数排序
        sorted_merged_results = dict(sorted(
            merged_results.items(), 
            key=lambda x: x[1]["score"], 
            reverse=True
        ))
        
        return list(sorted_merged_results.values())
    
    def merge_overlap_chunk(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并重叠的文本块
        
        Args:
            search_results: 搜索结果列表
            
        Returns:
            合并后的搜索结果
        """
        if not search_results:
            return []
            
        new_search_result = []
        doc_dict = {}
        
        # 按文档ID分组
        for result in search_results:
            doc_name = result["doc_id"]
            if doc_name not in doc_dict:
                doc_dict[doc_name] = []
            doc_dict[doc_name].append(result)
        
        # 对每个文档的块按开始位置排序
        for chunks in doc_dict.values():
            chunks.sort(key=lambda x: x["start"])
        
        # 合并重叠的块
        for doc_id, doc_chunks in doc_dict.items():
            i = 0
            while i < len(doc_chunks):
                current_chunk = doc_chunks[i]
                merged_chunk = current_chunk.copy()
                merged_chunk['doc_segment_ids'] = str(merged_chunk['doc_segment_id'])
                
                j = i + 1
                while j < len(doc_chunks):
                    next_chunk = doc_chunks[j]
                    if next_chunk["start"] <= merged_chunk["end"]:
                        # 存在重叠，更新合并chunk的结束索引和分数（取最大分数）
                        merged_chunk["score"] = max(merged_chunk["score"], next_chunk["score"])
                        
                        if merged_chunk["end"] - next_chunk["start"] >= 0:
                            merged_chunk['doc_content'] += next_chunk["doc_content"][
                                merged_chunk["end"] - next_chunk["start"]:
                            ]
                        merged_chunk["end"] = max(merged_chunk["end"], next_chunk["end"])
                        merged_chunk['doc_segment_ids'] += '+' + str(next_chunk['doc_segment_id'])
                        j += 1
                    else:
                        break
                        
                new_search_result.append(merged_chunk)
                i = j
                
        return new_search_result
    
    def remove_redundant(
        self,
        result_list: List[Dict[str, Any]],
        merge_length: int = 5120,
        merge_times: int = 10,
        group_key: str = "doc_id",
        merge_key: str = "passage_content",
        sorted_key: str = "passage_bm25_score"
    ) -> List[Dict[str, Any]]:
        """
        去除冗余内容
        
        Args:
            result_list: 结果列表
            merge_length: 合并长度限制
            merge_times: 合并次数限制
            group_key: 分组键
            merge_key: 合并键
            sorted_key: 排序键
            
        Returns:
            去重后的结果列表
        """
        if not result_list:
            return []
            
        stop_merge = {'merge_length': merge_length, 'merge_times': merge_times}
        
        # 先按照doc_name分组
        group_by_doc_name = {}
        for item in result_list:
            if item[group_key] not in group_by_doc_name.keys():
                group_by_doc_name[item[group_key]] = []
            group_by_doc_name[item[group_key]].append(item)
        
        # 对小组成员按照start升序
        result_list = []
        for key, group in group_by_doc_name.items():
            group_list = sorted(group, key=lambda x: x['start'])
            result_list.extend(group_list)
        
        # 检查必需的键
        if result_list:
            key_check = result_list[0]
            if "start" not in key_check.keys() and "end" not in key_check.keys():
                raise ValueError("key start 或者 key end 不在元素中")
        
        new_result_list = []
        for i, result in enumerate(result_list):
            if (i == 0 or
                result[group_key] != new_result_list[-1][group_key] or
                result['start'] > new_result_list[-1]['end'] or
                new_result_list[-1]['text_length'] >= stop_merge['merge_length'] or
                new_result_list[-1]['merge_times'] >= stop_merge['merge_times']):
                
                result['merge_times'] = 0
                result['text_length'] = result['end'] - result['start'] + 1
                new_result_list.append(result)
            else:
                if result['end'] > new_result_list[-1]['end']:
                    new_result_list[-1][merge_key] += result[merge_key][
                        -(result["end"] - new_result_list[-1]["end"]):
                    ]
                    new_result_list[-1]['end'] = result['end']
                    new_result_list[-1]['text_length'] = (
                        new_result_list[-1]['end'] - new_result_list[-1]['start'] + 1
                    )
                    new_result_list[-1]["merge_times"] += 1
                    new_result_list[-1][sorted_key] = max(
                        new_result_list[-1][sorted_key], result[sorted_key]
                    )
                else:
                    new_result_list[-1][sorted_key] = max(
                        new_result_list[-1][sorted_key], result[sorted_key]
                    )
                    new_result_list[-1]['merge_times'] += 1  # 完全cover情况
        
        # 去除重复文字
        merge_results = []
        unique_list = []
        for item in new_result_list:
            if item[merge_key] not in unique_list:
                unique_list.append(item[merge_key])
                merge_results.append(item)
                
        merge_results = sorted(merge_results, key=lambda x: x[sorted_key], reverse=True)
        return merge_results
    
    def process_search_results(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理搜索结果的主要方法
        
        Args:
            search_results: 原始搜索结果
            
        Returns:
            处理后的搜索结果
        """
        search_results = self.rrf_fusion_for_search_chunks(search_results=search_results)
        search_results = self.merge_overlap_chunk(search_results)
        return search_results
    
    async def post_process_search_results(
        self,
        search_results: List[Dict[str, Any]],
        rrf_k: int = 1,
        enable_rrf_fusion: bool = True,
        enable_overlap_merge: bool = True,
        enable_redundant_removal: bool = True,
        merge_length: int = 5120,
        merge_times: int = 10,
        group_key: str = "doc_id",
        merge_key: str = "doc_content",
        sorted_key: str = "score"
    ) -> Dict[str, Any]:
        """
        搜索结果后处理的异步接口（包含RRF融合、重叠合并和去重）
        
        Args:
            search_results: 搜索结果列表
            rrf_k: RRF参数k值
            enable_rrf_fusion: 是否启用RRF融合
            enable_overlap_merge: 是否启用重叠合并
            enable_redundant_removal: 是否启用去重处理
            merge_length: 合并长度限制（用于去重）
            merge_times: 合并次数限制（用于去重）
            group_key: 分组键（用于去重）
            merge_key: 合并键（用于去重）
            sorted_key: 排序键（用于去重）
            
        Returns:
            处理结果
        """
        try:
            if not search_results:
                return {
                    "success": True,
                    "search_results": [],
                    "total_results": 0,
                    "message": "空搜索结果"
                }
            
            processed_results = search_results.copy()
            original_count = len(search_results)
            processing_steps = []
            
            # 步骤1: RRF融合
            if enable_rrf_fusion:
                processed_results = self.rrf_fusion_for_search_chunks(
                    processed_results, rrf_k=rrf_k
                )
                processing_steps.append(f"RRF融合: {len(processed_results)} 个结果")
            
            # 步骤2: 重叠合并
            if enable_overlap_merge:
                processed_results = self.merge_overlap_chunk(processed_results)
                processing_steps.append(f"重叠合并: {len(processed_results)} 个结果")
            
            # 步骤3: 去重处理
            if enable_redundant_removal:
                # 需要为去重功能适配数据格式
                adapted_results = []
                for result in processed_results:
                    adapted_result = result.copy()
                    # 确保包含去重所需的字段
                    if merge_key not in adapted_result and "doc_content" in adapted_result:
                        adapted_result[merge_key] = adapted_result["doc_content"]
                    if sorted_key not in adapted_result and "score" in adapted_result:
                        adapted_result[sorted_key] = adapted_result["score"]
                    if "start" not in adapted_result:
                        adapted_result["start"] = 0
                    if "end" not in adapted_result:
                        adapted_result["end"] = len(adapted_result.get(merge_key, ""))
                    adapted_results.append(adapted_result)
                
                processed_results = self.remove_redundant(
                    result_list=adapted_results,
                    merge_length=merge_length,
                    merge_times=merge_times,
                    group_key=group_key,
                    merge_key=merge_key,
                    sorted_key=sorted_key
                )
                processing_steps.append(f"去重处理: {len(processed_results)} 个结果")
            
            return {
                "success": True,
                "search_results": processed_results,
                "total_results": len(processed_results),
                "original_count": original_count,
                "processing_steps": processing_steps,
                "settings": {
                    "rrf_k": rrf_k,
                    "rrf_fusion_enabled": enable_rrf_fusion,
                    "overlap_merge_enabled": enable_overlap_merge,
                    "redundant_removal_enabled": enable_redundant_removal,
                    "merge_length": merge_length,
                    "merge_times": merge_times
                }
            }
            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"搜索结果后处理失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "search_results": search_results,
                "total_results": len(search_results) if search_results else 0
            }
    
    async def remove_redundant_results(
        self,
        result_list: List[Dict[str, Any]],
        merge_length: int = 5120,
        merge_times: int = 10,
        group_key: str = "doc_id",
        merge_key: str = "passage_content",
        sorted_key: str = "passage_bm25_score"
    ) -> Dict[str, Any]:
        """
        去除冗余结果的异步接口
        
        Args:
            result_list: 结果列表
            merge_length: 合并长度限制
            merge_times: 合并次数限制
            group_key: 分组键
            merge_key: 合并键
            sorted_key: 排序键
            
        Returns:
            去重结果
        """
        try:
            if not result_list:
                return {
                    "success": True,
                    "results": [],
                    "total_results": 0,
                    "message": "空结果列表"
                }
            
            deduplicated_results = self.remove_redundant(
                result_list=result_list,
                merge_length=merge_length,
                merge_times=merge_times,
                group_key=group_key,
                merge_key=merge_key,
                sorted_key=sorted_key
            )
            
            return {
                "success": True,
                "results": deduplicated_results,
                "total_results": len(deduplicated_results),
                "original_count": len(result_list),
                "merge_length": merge_length,
                "merge_times": merge_times
            }
            
        except Exception as e:
            logger.error(f"去除冗余结果失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "results": result_list,
                "total_results": len(result_list) if result_list else 0
            } 