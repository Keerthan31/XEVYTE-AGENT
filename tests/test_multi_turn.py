"""
Category 8: Multi-Turn Testing
Tests multi-turn context retention, conversational history construction,
clarification flows, and follow-up command sequencing.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.agent.engine import run_agent


@pytest.mark.asyncio
async def test_multi_turn_history_passed_to_agent(employee_context):
    """
    Verify that conversation history is properly passed to the agent
    and preserved across dialogue turns.
    """
    history = [
        {"role": "user", "content": "What is my current leave balance?"},
        {"role": "assistant", "content": "You have 12 days of Casual Leave and 8 days of Sick Leave remaining."}
    ]
    user_follow_up = "Okay, please apply for 2 days of Casual Leave starting tomorrow."
    
    with patch("langchain_openai.ChatOpenAI.ainvoke", new_callable=AsyncMock) as mock_model:
        # Mock model response
        mock_response = AIMessage(content="I have prepared your leave request for 2 days of Casual Leave.")
        mock_model.return_value = mock_response

        res = await run_agent(
            user_message=user_follow_up,
            history=history,
            user_context=employee_context,
            token="test_token"
        )
        
        assert "content" in res
        assert "prepared your leave request" in res["content"]
        
        # Verify call included the conversation history messages
        called_messages = mock_model.call_args[0][0]
        # At least SystemMessage, UserContext, Turn 1 User, Turn 1 AI, Turn 2 User
        contents = [getattr(m, "content", "") for m in called_messages]
        assert any("What is my current leave balance?" in str(c) for c in contents)
        assert any("You have 12 days of Casual Leave" in str(c) for c in contents)


@pytest.mark.asyncio
async def test_multi_turn_clarification_flow(employee_context):
    """
    Simulate a multi-turn clarification sequence where the user provides missing details.
    """
    history = [
        {"role": "user", "content": "I want to raise a ticket."},
        {"role": "assistant", "content": "Sure, what is the issue category and description?"}
    ]
    user_follow_up = "It is an IT hardware issue with my monitor flickering."
    
    with patch("langchain_openai.ChatOpenAI.ainvoke", new_callable=AsyncMock) as mock_model:
        mock_model.return_value = AIMessage(content="Ticket submitted for IT hardware issue.")

        res = await run_agent(
            user_message=user_follow_up,
            history=history,
            user_context=employee_context,
            token="test_token"
        )
        
        assert "content" in res
        assert "Ticket submitted" in res["content"]
