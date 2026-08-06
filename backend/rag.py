import os
import logging
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)

CHROMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")

def query_hr_knowledge_base(query: str, k: int = 3) -> str:
    """
    Query the persistent ChromaDB for the given query and return formatted knowledge.
    """
    if not os.path.exists(CHROMA_DIR):
        logger.warning("ChromaDB directory not found. Have documents been ingested?")
        return "No HR policies or documents are currently available in the system."
        
    try:
        embeddings = OpenAIEmbeddings()
        vector_store = Chroma(
            collection_name="hr_knowledge_base",
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR
        )
        
        results = vector_store.similarity_search(query, k=k)
        
        if not results:
            return "No relevant information found in the HR policies."
            
        # Format the retrieved documents into a single text block
        formatted_results = "Here is the relevant information from company policies:\n\n"
        for i, doc in enumerate(results):
            source = doc.metadata.get("source", "Unknown Document")
            formatted_results += f"--- Excerpt {i+1} from {source} ---\n{doc.page_content}\n\n"
            
        return formatted_results.strip()
    except Exception as e:
        logger.error(f"Error querying ChromaDB: {e}")
        return "An error occurred while searching the knowledge base."
