import io
import logging
from typing import Dict, Any, List, Optional, Tuple
import httpx
import pypdf

try:
    import docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

from app.config import get_settings

logger = logging.getLogger("xeva.rag.doc_streamer")

async def stream_document_from_java(
    url_or_path: str,
    token: Optional[str] = None
) -> Tuple[bytes, str, str]:
    """
    Streams a document directly from Java HRMS into memory (RAM).
    Zero bytes are written to disk.
    Returns: (raw_bytes, content_type, filename)
    """
    settings = get_settings()
    target_url = url_or_path
    if url_or_path.startswith("/"):
        target_url = f"{settings.HRMS_API_BASE_URL}{url_or_path}"
    elif not url_or_path.startswith("http"):
        target_url = f"{settings.HRMS_API_BASE_URL}/{url_or_path.lstrip('/')}"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") else token

    logger.info(f"🌊 In-Memory streaming document from: {target_url}")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(target_url, headers=headers)
        if not resp.is_success:
            raise ValueError(f"Failed to stream document from Java backend (HTTP {resp.status_code}): {resp.text[:200]}")

        content_type = resp.headers.get("content-type", "").lower()
        content_disp = resp.headers.get("content-disposition", "")
        filename = "document"
        if "filename=" in content_disp:
            filename = content_disp.split("filename=")[-1].strip('"\'; ')

        raw_bytes = resp.content
        logger.info(f"✅ Successfully streamed {len(raw_bytes)} bytes into memory (Type: {content_type})")
        return raw_bytes, content_type, filename

def parse_bytes_in_memory(
    data: bytes,
    content_type: str = "",
    filename: str = ""
) -> Dict[str, Any]:
    """
    Extracts text, pages, and structured tables entirely in memory.
    Supports PDF, DOCX, XLSX, CSV, and plain text.
    """
    if not data:
        return {"type": "empty", "pages": [], "full_text": "", "metadata": {}}

    fn_lower = filename.lower()
    ct_lower = content_type.lower()

    # 1. PDF Parser
    if "pdf" in ct_lower or fn_lower.endswith(".pdf") or data.startswith(b"%PDF"):
        return _parse_pdf_in_memory(data)

    # 2. DOCX Parser
    if "wordprocessingml" in ct_lower or "docx" in ct_lower or fn_lower.endswith(".docx"):
        return _parse_docx_in_memory(data)

    # 3. Excel Parser (.xlsx / .xls)
    if "spreadsheetml" in ct_lower or "excel" in ct_lower or fn_lower.endswith(".xlsx"):
        return _parse_xlsx_in_memory(data)

    # 4. CSV / Text Parser
    if "csv" in ct_lower or "text" in ct_lower or fn_lower.endswith(".csv") or fn_lower.endswith(".txt"):
        return _parse_text_in_memory(data, is_csv=fn_lower.endswith(".csv") or "csv" in ct_lower)

    # Default fallback: try PDF then UTF-8 text
    try:
        if data.startswith(b"%PDF"):
            return _parse_pdf_in_memory(data)
        text = data.decode("utf-8", errors="ignore")
        if text.strip():
            return {"type": "text", "pages": [{"page": 1, "text": text}], "full_text": text, "metadata": {}}
    except Exception:
        pass

    return {
        "type": "unknown",
        "pages": [{"page": 1, "text": "[Binary document content could not be parsed as text]"}],
        "full_text": "[Binary document content could not be parsed as text]",
        "metadata": {"sizeBytes": len(data)}
    }

def _parse_pdf_in_memory(data: bytes) -> Dict[str, Any]:
    try:
        stream = io.BytesIO(data)
        reader = pypdf.PdfReader(stream)
        pages = []
        full_text_parts = []

        total_pages = len(reader.pages)
        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            page_text = page.extract_text() or ""
            cleaned_text = "\n".join([line.strip() for line in page_text.splitlines() if line.strip()])
            pages.append({
                "page": page_num,
                "text": cleaned_text
            })
            if cleaned_text:
                full_text_parts.append(f"--- Page {page_num} ---\n{cleaned_text}")

        full_text = "\n\n".join(full_text_parts)
        meta = {}
        if reader.metadata:
            meta = {k.strip("/"): str(v) for k, v in reader.metadata.items() if v}

        return {
            "type": "pdf",
            "totalPages": total_pages,
            "pages": pages,
            "full_text": full_text,
            "metadata": meta
        }
    except Exception as e:
        logger.warning(f"Failed to parse PDF bytes: {e}")
        # Fallback to UTF-8 / latin-1 text extraction
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = str(data)
        return {
            "type": "pdf",
            "totalPages": 1,
            "pages": [{"page": 1, "text": text}],
            "full_text": text,
            "metadata": {"parseError": str(e)}
        }

def _parse_docx_in_memory(data: bytes) -> Dict[str, Any]:
    if docx is None:
        return {"type": "docx", "totalPages": 1, "pages": [{"page": 1, "text": "[python-docx library not installed]"}], "full_text": "[python-docx library not installed]", "metadata": {}}
    stream = io.BytesIO(data)
    doc = docx.Document(stream)
    paragraphs = []

    for p in doc.paragraphs:
        if p.text.strip():
            paragraphs.append(p.text.strip())

    for t in doc.tables:
        for row in t.rows:
            row_text = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
            if row_text:
                paragraphs.append(row_text)

    full_text = "\n\n".join(paragraphs)
    return {
        "type": "docx",
        "totalPages": 1,
        "pages": [{"page": 1, "text": full_text}],
        "full_text": full_text,
        "metadata": {}
    }

def _parse_xlsx_in_memory(data: bytes) -> Dict[str, Any]:
    if openpyxl is None:
        return {"type": "xlsx", "totalPages": 1, "pages": [{"page": 1, "text": "[openpyxl library not installed]"}], "full_text": "[openpyxl library not installed]", "metadata": {}}
    stream = io.BytesIO(data)
    wb = openpyxl.load_workbook(stream, data_only=True)
    sheets_text = []

    for sheetname in wb.sheetnames:
        sheet = wb[sheetname]
        rows_text = [f"### Sheet: {sheetname}"]
        for row in sheet.iter_rows(values_only=True):
            non_empty = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            if non_empty:
                rows_text.append(" | ".join(non_empty))
        sheets_text.append("\n".join(rows_text))

    full_text = "\n\n".join(sheets_text)
    return {
        "type": "xlsx",
        "totalPages": len(wb.sheetnames),
        "pages": [{"page": i + 1, "text": t} for i, t in enumerate(sheets_text)],
        "full_text": full_text,
        "metadata": {"sheets": wb.sheetnames}
    }

def _parse_text_in_memory(data: bytes, is_csv: bool = False) -> Dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="ignore")

    return {
        "type": "csv" if is_csv else "text",
        "totalPages": 1,
        "pages": [{"page": 1, "text": text}],
        "full_text": text,
        "metadata": {}
    }
