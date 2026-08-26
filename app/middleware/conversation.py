import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger("xeva.middleware.conversation")

class ConversationLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            logger.info(f"[{request.method}] {request.url.path} completed in {process_time:.4f}s - Status: {response.status_code}")
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"[{request.method}] {request.url.path} failed in {process_time:.4f}s with error: {str(e)}")
            raise
