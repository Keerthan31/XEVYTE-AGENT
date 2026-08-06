import os
import io
import logging
from pypdf import PdfReader
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Setup Django/Spring DB connection (we'll reuse the backend db.py)
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db import get_connection, release_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHROMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")

def ingest_from_db():
    logger.info("Connecting to Postgres database to fetch employee handbooks...")
    conn = get_connection()
    if not conn:
        logger.error("Could not connect to DB.")
        return
    
    docs_to_index = []
    
    try:
        cur = conn.cursor()
        # Check if table exists first (to prevent errors in empty/dev DBs)
        cur.execute("SELECT to_regclass('public.employee_handbook');")
        if cur.fetchone()[0] is None:
            logger.warning("Table 'employee_handbook' does not exist yet. Exiting.")
            return

        cur.execute("SELECT id, original_file_name, category, file_data FROM employee_handbook;")
        rows = cur.fetchall()
        
        if not rows:
            logger.info("No documents found in employee_handbook table.")
            return
        
        logger.info(f"Found {len(rows)} documents. Processing...")
        
        for row in rows:
            doc_id, filename, category, file_data = row
            if not file_data:
                continue
                
            logger.info(f"Parsing PDF: {filename} (ID: {doc_id}, Category: {category})")
            
            try:
                # Read PDF directly from binary memory
                pdf_file = io.BytesIO(file_data)
                reader = PdfReader(pdf_file)
                
                text_content = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n\n"
                
                if not text_content.strip():
                    logger.warning(f"No text extracted from {filename}")
                    continue
                    
                # Create LangChain Document
                metadata = {
                    "source": filename,
                    "id": str(doc_id),
                    "category": category or "general"
                }
                docs_to_index.append(Document(page_content=text_content, metadata=metadata))
            except Exception as e:
                logger.error(f"Error parsing PDF {filename}: {e}")

        cur.close()
    finally:
        release_connection(conn)

    if not docs_to_index:
        logger.info("No valid text documents found to index.")
        return

    logger.info("Splitting text into semantic chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        length_function=len
    )
    
    chunks = text_splitter.split_documents(docs_to_index)
    logger.info(f"Created {len(chunks)} chunks.")
    
    logger.info("Initializing OpenAI Embeddings and ChromaDB...")
    embeddings = OpenAIEmbeddings()
    
    # Create or update ChromaDB vector store
    vector_store = Chroma(
        collection_name="hr_knowledge_base",
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR
    )
    
    # Add documents (Chroma automatically handles persistence)
    vector_store.add_documents(chunks)
    
    logger.info("Successfully ingested and saved vectors to ChromaDB!")

if __name__ == "__main__":
    ingest_from_db()
