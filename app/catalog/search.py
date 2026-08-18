import logging
from typing import List, Optional
import chromadb

from app.catalog.models import CatalogEntry
from app.config import get_settings

logger = logging.getLogger("xeva.catalog.search")

class CatalogSearch:
    def __init__(self):
        self.catalog: dict[str, CatalogEntry] = {}
        self._chroma_client = None
        self._collection = None

    def initialize(self, catalog: dict[str, CatalogEntry]):
        """Initialize the search index with the loaded catalog."""
        self.catalog = catalog
        logger.info(f"Initializing basic text search for {len(catalog)} endpoints")
        self._collection = None
        # ChromaDB ONNX is hanging on this machine, falling back to basic search completely.

    def search_by_id(self, endpoint_id: str) -> Optional[CatalogEntry]:
        """Exact match lookup."""
        return self.catalog.get(endpoint_id)

    def search_by_intent(self, query: str, top_k: int = 5) -> List[CatalogEntry]:
        """Semantic search using ChromaDB."""
        if not self._collection:
            logger.warning("ChromaDB not initialized, falling back to basic text search")
            return self._basic_text_search(query, top_k)
            
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k
            )
            
            entries = []
            if results and results["ids"] and results["ids"][0]:
                for doc_id in results["ids"][0]:
                    if doc_id in self.catalog:
                        entries.append(self.catalog[doc_id])
                        
            return entries
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return self._basic_text_search(query, top_k)

    def _basic_text_search(self, query: str, top_k: int) -> List[CatalogEntry]:
        """Fallback basic text matching."""
        query = query.lower()
        scored = []
        
        for entry in self.catalog.values():
            score = 0
            if query in entry.search_text:
                score += 10
            if query in entry.endpoint_id.lower():
                score += 20
                
            if score > 0:
                scored.append((score, entry))
                
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for score, entry in scored[:top_k]]

# Global singleton
catalog_search = CatalogSearch()
