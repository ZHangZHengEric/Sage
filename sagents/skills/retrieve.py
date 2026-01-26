from typing import Dict, List, Optional, Tuple, Set
from sagents.skills.schema import SkillSchema
from sagents.utils.logger import logger

class Retriever:
    """
    Skill retriever for finding the most relevant skills based on queries.
    
    Attributes:
        skills: Dictionary of loaded skills (name -> SkillSchema)
        top_k: Number of top results to return (default: 3)
    """

    def __init__(self, skills: Dict[str, SkillSchema], top_k: int = 3):
        self.skills = skills
        self.top_k = top_k

    def retrieve(
            self,
            query: str,
            method: str = 'keyword',
            top_k: Optional[int] = None
    ) -> List[Tuple[str, SkillSchema, float]]:
        """
        Retrieve the most relevant skills based on query.

        Args:
            query: Search query string
            method: Retrieval method ("keyword") - semantic not yet implemented
            top_k: Number of results to return

        Returns:
            List of tuples (skill_name, SkillSchema, score) sorted by relevance
        """
        k = top_k or self.top_k

        if method == 'keyword':
            return self._keyword_retrieve(query, k)
        else:
            logger.warning(f'Unknown or unimplemented retrieval method: {method}, using `keyword` by default.')
            return self._keyword_retrieve(query, k)

    def _keyword_retrieve(self, query: str, top_k: int) -> List[Tuple[str, SkillSchema, float]]:
        """
        Keyword-based retrieval using simple text matching.
        """
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        results = []

        for skill_name, schema in self.skills.items():
            score = 0.0
            
            # Defensive check for missing fields
            s_name = (schema.name or "").lower()
            s_desc = (schema.description or "").lower()
            
            # Search in name (weight: 3.0)
            if query_lower in s_name:
                score += 3.0
            
            # Search in description (weight: 1.0)
            if query_lower in s_desc:
                score += 1.0
                
            # Term-based matching
            # Name terms
            name_terms = set(s_name.split())
            common_name_terms = query_terms.intersection(name_terms)
            score += len(common_name_terms) * 0.5
            
            # Description terms
            desc_terms = set(s_desc.split())
            common_desc_terms = query_terms.intersection(desc_terms)
            score += len(common_desc_terms) * 0.1
            
            if score > 0:
                results.append((skill_name, schema, score))

        # Sort by score descending
        results.sort(key=lambda x: x[2], reverse=True)
        
        return results[:top_k]
