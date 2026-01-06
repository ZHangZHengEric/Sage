from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseSplitter(ABC):
    """
    Abstract base class for document splitters.
    """
    
    @abstractmethod
    async def split_text(self, text: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Split text into chunks.
        Returns a list of dicts, where each dict typically contains:
        - passage_id: str
        - passage_content: str
        - start: int
        - end: int
        """
        pass
