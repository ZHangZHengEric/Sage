from __future__ import annotations

from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SearchResultPostProcessTool:
    def rrf_fusion_for_search_chunks(self, search_results: List[Dict[str, Any]], rrf_k: int = 1) -> List[Dict[str, Any]]:
        if not search_results:
            return []
        search_source = set([item['source'] for item in search_results])
        search_results_by_source = {item: [] for item in search_source}
        document_nums_by_source = {item: {} for item in search_source}
        for result in search_results:
            search_results_by_source[result['source']].append(result)
            if result['doc_id'] not in document_nums_by_source[result['source']]:
                document_nums_by_source[result['source']][result['doc_id']] = 0
            document_nums_by_source[result['source']][result['doc_id']] += 1
        search_results_new = []
        for source_item in search_results_by_source.keys():
            search_results_by_source[source_item] = sorted(search_results_by_source[source_item], key=lambda x: x['score'], reverse=True)
            max_score = max(item['score'] for item in search_results_by_source[source_item])
            min_score = min(item['score'] for item in search_results_by_source[source_item])
            for index in range(len(search_results_by_source[source_item])):
                search_results_by_source[source_item][index]['ranking'] = index + 1
                if max_score - min_score > 0:
                    search_results_by_source[source_item][index]['normal_score'] = (search_results_by_source[source_item][index]["score"] - min_score) / (max_score - min_score)
                else:
                    search_results_by_source[source_item][index]['normal_score'] = 1
            search_results_new.extend(search_results_by_source[source_item])
        search_results = search_results_new
        merged_results: Dict[str, Dict[str, Any]] = {}
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
        for chunk in merged_results.keys():
            rrf_score = 0
            for search_source_item in search_source:
                rank = merged_results[chunk]["rankings"].get(search_source_item, len(search_results_by_source[search_source_item]) + 1)
                score = merged_results[chunk]['normal_scores'].get(search_source_item, 0)
                document_frequency_in_source = document_nums_by_source[search_source_item].get(merged_results[chunk]['doc_id'], 0)
                document_frequency = len(merged_results[chunk]["rankings"].keys()) / len(search_source)
                adjusted_score = score * (1 + 0.05 * document_frequency_in_source)
                rrf_score += document_frequency * (adjusted_score / (rrf_k + rank))
            merged_results[chunk]["score"] = rrf_score
        sorted_merged_results = dict(sorted(merged_results.items(), key=lambda x: x[1]["score"], reverse=True))
        return list(sorted_merged_results.values())

    def merge_overlap_chunk(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not search_results:
            return []
        new_search_result = []
        doc_dict: Dict[str, List[Dict[str, Any]]] = {}
        for result in search_results:
            doc_name = result["doc_id"]
            if doc_name not in doc_dict:
                doc_dict[doc_name] = []
            doc_dict[doc_name].append(result)
        for chunks in doc_dict.values():
            chunks.sort(key=lambda x: x["start"])
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
                        merged_chunk["score"] = max(merged_chunk["score"], next_chunk["score"])
                        if merged_chunk["end"] - next_chunk["start"] >= 0:
                            merged_chunk['doc_content'] += next_chunk["doc_content"][merged_chunk["end"] - next_chunk["start"]:]
                        merged_chunk["end"] = max(merged_chunk["end"], next_chunk["end"])
                        merged_chunk['doc_segment_ids'] += '+' + str(next_chunk['doc_segment_id'])
                        j += 1
                    else:
                        break
                new_search_result.append(merged_chunk)
                i = j
        return new_search_result

    def process_search_results(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = self.rrf_fusion_for_search_chunks(search_results=search_results)
        results = self.merge_overlap_chunk(results)
        return results