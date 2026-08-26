import io
import logging

try:
    import pypdf
except ImportError:
    pypdf = None

logger = logging.getLogger("xeva.agent.file_parser")

def parse_file_for_agent(filename: str, content: bytes, content_type: str) -> dict:
    """
    Parse uploaded files into text context for the agent.
    Returns a dict with 'type' ('document' or 'image'), 'filename', and 'data'.
    """
    logger.info(f"Parsing file: {filename} of type {content_type}")
    
    file_text = ""
    
    try:
        if content_type.startswith("image/"):
            import base64
            base64_data = base64.b64encode(content).decode("utf-8")
            return {
                "type": "image",
                "filename": filename,
                "data": f"data:{content_type};base64,{base64_data}"
            }
            
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            if pypdf:
                pdf_file = io.BytesIO(content)
                reader = pypdf.PdfReader(pdf_file)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        file_text += text + "\n"
            else:
                file_text = "[PDF parsing not supported: pypdf not installed]"
                
        elif content_type.startswith("text/") or filename.lower().endswith((".txt", ".md", ".csv", ".json", ".log")):
            file_text = content.decode("utf-8", errors="replace")
            
        else:
            file_text = f"[Uploaded file {filename} of type {content_type}. Content cannot be directly parsed into text.]"
            
    except Exception as e:
        logger.error(f"Failed to parse file {filename}: {e}")
        file_text = f"[Error reading file {filename}]"
        
    return {
        "type": "document",
        "filename": filename,
        "data": file_text
    }
