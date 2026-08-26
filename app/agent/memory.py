import uuid
from typing import List, Sequence
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ChatMessage

class AsyncPostgresChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str, db_session: AsyncSession = None, async_session: AsyncSession = None):
        self.session_id = session_id
        # Support both kwargs used in chat.py
        self.db = db_session or async_session
        
    @property
    def messages(self) -> List[BaseMessage]:
        # We only support async retrieval for this custom history class
        return []

    def add_message(self, message: BaseMessage) -> None:
        raise NotImplementedError("Use async methods (aadd_messages) instead")
        
    def clear(self) -> None:
        pass
        
    async def aget_messages(self) -> List[BaseMessage]:
        stmt = select(ChatMessage).where(ChatMessage.session_id == self.session_id).order_by(ChatMessage.created_at)
        result = await self.db.execute(stmt)
        db_messages = result.scalars().all()
        
        messages = []
        for msg in db_messages:
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                messages.append(AIMessage(content=msg.content))
            elif msg.role == "system":
                messages.append(SystemMessage(content=msg.content))
        return messages

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            elif isinstance(msg, SystemMessage):
                role = "system"
            else:
                role = "user"
                
            db_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=self.session_id,
                role=role,
                content=msg.content
            )
            self.db.add(db_msg)
        await self.db.commit()
