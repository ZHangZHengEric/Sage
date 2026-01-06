from abc import ABC, abstractmethod
from typing import List, Dict, Any
from sagents.rag.text_splitter import ChineseRecursiveTextSplitter
from sagents.rag.interface.splitter import BaseSplitter

class DefaultSplitter(BaseSplitter):
    """
    Default implementation using ChineseRecursiveTextSplitter from sagents.rag.text_splitter.
    """
    
    def __init__(self):
        self._splitter = ChineseRecursiveTextSplitter()
        
    async def split_text(self, text: str, **kwargs) -> List[Dict[str, Any]]:
        # Extract parameters or use defaults matching ChineseRecursiveTextSplitter's expectations
        fix_length_list = kwargs.get("fix_length_list", [128, 256, 512])
        
        result = await self._splitter.split_text_by_punctuation(
            text, 
            fix_length_list=fix_length_list
        )
        
        if not result.get("success", False):
            # In case of failure, we might return empty list or raise error.
            # Logging is already handled in ChineseRecursiveTextSplitter
            return []
            
        return result.get("sentences_list", [])
