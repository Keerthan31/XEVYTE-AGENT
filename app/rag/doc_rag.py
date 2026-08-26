import logging
from typing import Dict, Any, List, Optional
import math

from app.config import get_settings
from app.rag.doc_streamer import parse_bytes_in_memory, stream_document_from_java

logger = logging.getLogger("xeva.rag.doc_rag")

def _chunk_pages(pages: List[Dict[str, Any]], max_chunk_chars: int = 1500) -> List[Dict[str, Any]]:
    """Splits pages into manageable semantic chunks while preserving exact page numbers."""
    chunks = []
    for p in pages:
        page_num = p["page"]
        text = p["text"]
        if len(text) <= max_chunk_chars:
            if text.strip():
                chunks.append({"page": page_num, "text": text})
        else:
            paragraphs = text.split("\n\n")
            current_chunk = []
            current_len = 0
            for para in paragraphs:
                if current_len + len(para) > max_chunk_chars and current_chunk:
                    chunks.append({"page": page_num, "text": "\n\n".join(current_chunk)})
                    current_chunk = [para]
                    current_len = len(para)
                else:
                    current_chunk.append(para)
                    current_len += len(para)
            if current_chunk:
                chunks.append({"page": page_num, "text": "\n\n".join(current_chunk)})
    return chunks

def _rank_chunks_for_query(chunks: List[Dict[str, Any]], query: str, top_k: int = 6) -> List[Dict[str, Any]]:
    """Simple BM25/term frequency ranking across in-memory chunks."""
    terms = set([t.lower() for t in query.split() if len(t) > 2])
    scored = []
    for c in chunks:
        text_lower = c["text"].lower()
        score = sum(text_lower.count(t) for t in terms)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [c for score, c in scored[:top_k] if score > 0]
    if not selected:
        selected = chunks[:top_k]
    return selected

async def answer_question_from_document_stream(
    url_or_path: str,
    question: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Streams a document from Java HRMS in RAM, extracts content, and answers
    the user's question with exact page citations and zero disk footprint.
    """
    settings = get_settings()
    raw_bytes, content_type, filename = await stream_document_from_java(url_or_path, token)
    parsed = parse_bytes_in_memory(raw_bytes, content_type, filename)

    if not parsed.get("full_text") or parsed.get("type") == "unknown":
        return {
            "answer": "Unable to extract readable text from this document.",
            "citations": [],
            "document": filename,
            "totalPages": parsed.get("totalPages", 0)
        }

    pages = parsed.get("pages", [])
    total_pages = parsed.get("totalPages", len(pages))
    
    # If small document (< 10 pages), use all text with page markers
    if total_pages <= 8 or len(parsed.get("full_text", "")) < 12000:
        context_text = parsed.get("full_text", "")
    else:
        # Long document: retrieve relevant page chunks
        chunks = _chunk_pages(pages)
        relevant_chunks = _rank_chunks_for_query(chunks, question, top_k=6)
        context_text = "\n\n".join([f"[Page {c['page']}]\n{c['text']}" for c in relevant_chunks])

    # Query LLM with strict grounding
    prompt = (
        f"You are analyzing a business document from Xevyte HRMS ({filename}).\n"
        f"Answer the user's question accurately based ONLY on the provided document text below.\n"
        f"Always mention specific figures, dates, employee names, or clause numbers if present.\n"
        f"Cite the page number(s) where each piece of information is found.\n\n"
        f"Document Content:\n{context_text}\n\n"
        f"User Question: {question}\n\n"
        f"Provide a structured, direct answer:"
    )

    try:
        from openai import AsyncOpenAI
        client_kwargs = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            client_kwargs["base_url"] = settings.OPENAI_BASE_URL

        client = AsyncOpenAI(**client_kwargs)
        response = await client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise HRMS document analyst. Answer based strictly on the provided document context."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error invoking LLM for document RAG: {e}")
        answer = f"Extracted document text (Summary):\n\n{parsed.get('full_text', '')[:1000]}..."

    return {
        "answer": answer,
        "filename": filename,
        "docType": parsed.get("type"),
        "totalPages": total_pages,
        "metadata": parsed.get("metadata", {})
    }

async def summarize_document_from_stream(
    url_or_path: str,
    focus_area: Optional[str] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Streams a document and produces an executive summary with key metadata, numbers, and action items.
    """
    question = f"Provide a complete executive summary of this document. Focus especially on: {focus_area}" if focus_area else (
        "Provide a comprehensive executive summary of this document, including key headings, major terms, financial amounts, important dates, and action items."
    )
    return await answer_question_from_document_stream(url_or_path, question, token)
