import os
import logging
from pathlib import Path
import chromadb
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings

logger = logging.getLogger("xeva.rag.indexer")

class PolicyIndexer:
    def __init__(self):
        settings = get_settings()
        self.persist_dir = settings.CHROMA_PERSIST_DIR
        self.policies_dir = settings.RAG_POLICIES_DIR
        
        try:
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            self.collection = self.client.get_or_create_collection(name="hr_policies")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB for RAG: {e}")
            self.collection = None

    def index_all_documents(self):
        """Index all PDF and TXT files in the policies directory."""
        if not self.collection:
            logger.warning("Cannot index documents, ChromaDB not initialized")
            return
            
        policies_path = Path(self.policies_dir)
        if not policies_path.exists():
            policies_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created policies directory at {policies_path}")
            return
            
        documents = []
        metadatas = []
        ids = []
        
        # We will use simple text splitters for now
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
        for file_path in policies_path.glob("**/*"):
            if file_path.is_file():
                try:
                    if file_path.suffix.lower() == ".pdf":
                        loader = PyPDFLoader(str(file_path))
                        pages = loader.load_and_split(text_splitter)
                    elif file_path.suffix.lower() in [".txt", ".md"]:
                        loader = TextLoader(str(file_path))
                        pages = loader.load_and_split(text_splitter)
                    else:
                        continue
                        
                    for i, page in enumerate(pages):
                        # Use file name and chunk index as ID
                        chunk_id = f"{file_path.name}_chunk_{i}"
                        ids.append(chunk_id)
                        documents.append(page.page_content)
                        metadatas.append({
                            "source": file_path.name,
                            "page": page.metadata.get("page", 0)
                        })
                        
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    
        if ids:
            # We clear the collection first for simplicity in this implementation
            # In a production system, you'd want incremental updates
            try:
                # Upsert all documents
                self.collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
                logger.info(f"Successfully indexed {len(ids)} document chunks from {policies_path}")
            except Exception as e:
                logger.error(f"Failed to upsert documents to ChromaDB: {e}")
        else:
            logger.info(f"No documents found to index in {policies_path}")

indexer = PolicyIndexer()
