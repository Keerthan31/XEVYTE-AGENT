from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import get_chat_model


async def summarize_history(messages: list[dict], existing_summary: str | None = None) -> str:
    """
    Summarize the given conversation history.
    If an existing_summary is provided, it incorporates that summary with the new messages.
    """
    if not messages:
        return existing_summary or ""

    model = get_chat_model(temperature=0.0)

    # Format the new messages for the prompt
    messages_text = ""
    for m in messages:
        role = "User" if m["role"] == "user" else "Assistant"
        messages_text += f"{role}: {m['content']}\n"

    if existing_summary:
        prompt = (
            "You are a helpful AI assistant. Your task is to update an existing summary of a conversation "
            "with new messages that occurred.\n\n"
            f"Existing Summary:\n{existing_summary}\n\n"
            f"New Messages to incorporate:\n{messages_text}\n\n"
            "Return ONLY the new updated summary. Keep it concise, but ensure all important context, "
            "facts, and user intents are retained."
        )
    else:
        prompt = (
            "You are a helpful AI assistant. Your task is to summarize the following conversation history.\n\n"
            f"Conversation History:\n{messages_text}\n\n"
            "Return ONLY the summary. Keep it concise, but ensure all important context, "
            "facts, and user intents are retained."
        )

    response = await model.ainvoke([HumanMessage(content=prompt)])
    return response.content
