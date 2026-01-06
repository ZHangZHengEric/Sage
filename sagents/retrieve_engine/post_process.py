from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from sagents.retrieve_engine.schema import SearchResult, Chunk

logger = logging.getLogger(__name__)


class SearchResultPostProcessTool:
    def rrf_fusion_for_search_chunks(self, search_results: List[SearchResult], rrf_k: int = 1) -> List[SearchResult]:
        if not search_results:
            return []
            
        # 1. Group by source
        results_by_source: Dict[str, List[SearchResult]] = {}
        for res in search_results:
            if res.source not in results_by_source:
                results_by_source[res.source] = []
            results_by_source[res.source].append(res)
            
        search_sources = list(results_by_source.keys())
        
        # 2. Calculate Rankings and Normalized Scores within each source
        for source, items in results_by_source.items():
            # Sort by score desc
            items.sort(key=lambda x: x.score, reverse=True)
            
            if not items:
                continue
                
            max_score = items[0].score
            min_score = items[-1].score
            score_range = max_score - min_score
            
            for i, item in enumerate(items):
                item.ranking = i + 1
                if score_range > 0:
                    item.normalized_score = (item.score - min_score) / score_range
                else:
                    item.normalized_score = 1.0

        # 3. Merge and Calculate RRF Score
        # We use (document_id, chunk_id) as the unique key for a chunk
        merged_map: Dict[str, Dict[str, Any]] = {}
        
        for source, items in results_by_source.items():
            for item in items:
                # Assuming chunk.id is unique within a document. 
                # If chunk.id is globally unique, we can just use item.chunk.id
                key = f"{item.chunk.document_id}_{item.chunk.id}"
                
                if key not in merged_map:
                    merged_map[key] = {
                        "result": item, # Store one instance as base
                        "rankings": {},
                        "normalized_scores": {},
                        "sources": set()
                    }
                
                merged_map[key]["sources"].add(source)
                merged_map[key]["rankings"][source] = item.ranking
                merged_map[key]["normalized_scores"][source] = item.normalized_score

        final_results: List[SearchResult] = []
        
        for key, data in merged_map.items():
            rrf_score = 0.0
            base_result = data["result"]
            
            # Re-implementing logic similar to original:
            # Weighted by how many sources found this chunk
            doc_frequency = len(data["sources"]) / len(search_sources)
            
            for source in search_sources:
                # If not found in this source, rank is essentially infinite (or very low)
                # Original logic: len(items) + 1
                rank = data["rankings"].get(source, len(results_by_source[source]) + 1)
                norm_score = data["normalized_scores"].get(source, 0.0)
                
                # Original logic included "document_frequency_in_source" which was doc freq of doc_id in that source.
                # Here we simplify to use the chunk's score directly.
                # Standard RRF is 1/(k+rank). 
                # We will use a hybrid approach to respect the original logic's intent of using scores.
                
                # Adjusted score based on original idea: score * (1 + 0.05 * frequency)
                # Since we don't calculate doc_freq per source easily without extra pass, we skip that micro-optimization
                # and focus on the main RRF formula + score contribution.
                
                # Let's use a weighted RRF:
                # rrf += (norm_score) / (k + rank)
                
                # To be safe and closer to standard RRF which is robust:
                rrf_score += 1.0 / (rrf_k + rank)
                
            # Create a new SearchResult with the fused score
            # We perform a deep copy of the chunk to avoid side effects if we modify it later
            new_chunk = base_result.chunk.model_copy()
            new_result = SearchResult(
                chunk=new_chunk,
                source="rrf_fusion",
                score=rrf_score,
                ranking=0, # Will be re-ranked
                normalized_score=0.0
            )
            final_results.append(new_result)
            
        final_results.sort(key=lambda x: x.score, reverse=True)
        return final_results

    def merge_overlap_chunk(self, search_results: List[SearchResult]) -> List[SearchResult]:
        if not search_results:
            return []
            
        # Group by Document ID
        doc_groups: Dict[str, List[SearchResult]] = {}
        for res in search_results:
            doc_id = res.chunk.document_id
            if doc_id not in doc_groups:
                doc_groups[doc_id] = []
            doc_groups[doc_id].append(res)
            
        merged_results = []
        
        for doc_id, items in doc_groups.items():
            # Sort by start position
            # We assume 'start' is in metadata
            items.sort(key=lambda x: x.chunk.metadata.get("start", 0))
            
            i = 0
            while i < len(items):
                current_res = items[i]
                current_chunk = current_res.chunk.model_copy()
                
                # Create a merged result starting with current
                merged_res = SearchResult(
                    chunk=current_chunk,
                    source=current_res.source,
                    score=current_res.score
                )
                
                current_start = current_chunk.metadata.get("start", 0)
                current_end = current_chunk.metadata.get("end", 0)
                
                j = i + 1
                while j < len(items):
                    next_res = items[j]
                    next_chunk = next_res.chunk
                    next_start = next_chunk.metadata.get("start", 0)
                    next_end = next_chunk.metadata.get("end", 0)
                    
                    # Check if next chunk starts before (or at) current ends
                    if next_start <= current_end:
                        # Overlap or Adjacent found
                        
                        # 1. Update Score (Max)
                        merged_res.score = max(merged_res.score, next_res.score)
                        
                        # 2. Merge Content
                        # Calculate non-overlapping part
                        overlap_len = current_end - next_start
                        if overlap_len >= 0:
                            # Append only the new part
                            remaining_content = next_chunk.content[overlap_len:]
                            current_chunk.content += remaining_content
                        
                        # 3. Update End position
                        current_end = max(current_end, next_end)
                        current_chunk.metadata["end"] = current_end
                        
                        # 4. Merge other metadata if needed (e.g., chunk ids)
                        # current_chunk.id += "+" + next_chunk.id 
                        
                        j += 1
                    else:
                        # Gap found, stop merging for this sequence
                        break
                
                merged_results.append(merged_res)
                i = j # Move to the next unmerged item
                
        # Sort final results by score again as merging might have changed order
        merged_results.sort(key=lambda x: x.score, reverse=True)
        return merged_results

    def process_search_results(self, search_results: List[SearchResult]) -> List[SearchResult]:
        results = self.rrf_fusion_for_search_chunks(search_results=search_results)
        results = self.merge_overlap_chunk(results)
        return results
