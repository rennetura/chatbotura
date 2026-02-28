"""AI Engine for ChatBotura - LangChain + OpenAI integration."""
import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, AIMessage
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from app.db import get_tenant
from app.rag import search_similar

# Initialize LLM (uses OPENAI_API_KEY from environment)
_llm = None


def get_llm():
    """Get or create OpenAI LLM instance."""
    global _llm
    if _llm is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.7,
            api_key=api_key
        )
    return _llm


class ChatMessage(BaseModel):
    """Chat message model."""
    role: str
    content: str


def format_chat_history(chat_history: list[dict]) -> list:
    """Convert chat history dicts to LangChain message objects."""
    messages = []
    for msg in chat_history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    return messages


def generate_response(
    tenant_id: str,
    user_message: str,
    chat_history: Optional[list[dict]] = None
) -> str:
    """
    Generate a response using tenant config, RAG context, and chat history.

    Args:
        tenant_id: The tenant identifier
        user_message: The user's input message
        chat_history: List of previous messages [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        Generated response string
    """
    if chat_history is None:
        chat_history = []

    # 1. Fetch tenant config
    tenant = get_tenant(tenant_id)
    if not tenant:
        return f"Error: Tenant '{tenant_id}' not found."

    system_prompt = tenant["system_prompt"]
    tone = tenant["tone"]
    business_name = tenant["business_name"]

    # 2. Perform RAG similarity search
    relevant_docs = search_similar(tenant_id, user_message, n_results=3)
    context = "\n\n".join(relevant_docs) if relevant_docs else "No relevant context found."

    # 3. Build prompt with persona, context, and history
    context_block = f"""You are representing: {business_name}
Tone: {tone}

Relevant Information:
{context}

Previous Conversation:
"""

    # Add chat history to context
    for msg in chat_history[-5:]:  # Last 5 messages for context
        role_label = "Customer" if msg["role"] == "user" else "You"
        context_block += f"{role_label}: {msg['content']}\n"

    context_block += f"\nCustomer: {user_message}\n\nYou:"

    # 4. Call LLM
    try:
        llm = get_llm()
        response = llm.invoke([
            HumanMessage(content=f"{system_prompt}\n\n{context_block}")
        ])
        return response.content
    except Exception as e:
        return f"Error generating response: {str(e)}"


def init_engine() -> None:
    """Initialize the AI engine."""
    # Validate API key on init
    try:
        llm = get_llm()
        print("✓ AI Engine initialized")
    except ValueError as e:
        print(f"⚠ Warning: {e}")


if __name__ == "__main__":
    init_engine()
    # Test basic response generation
    if os.getenv("OPENAI_API_KEY"):
        response = generate_response(
            "pizza_shop",
            "What pizzas do you have?"
        )
        print(f"Test response: {response[:200]}...")
    else:
        print("OPENAI_API_KEY not set, skipping test")
