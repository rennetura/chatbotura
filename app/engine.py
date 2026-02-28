"""AI Engine for ChatBotura - Configurable LLM Provider (OpenAI or OpenRouter)."""
import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from app.db import get_tenant
from app.rag import search_similar

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Model configurations
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")

# Initialize LLM (lazy loaded)
_llm = None


def get_llm():
    """Get or create LLM instance based on configured provider."""
    global _llm
    if _llm is None:
        if LLM_PROVIDER == "openrouter":
            if not OPENROUTER_API_KEY:
                raise ValueError("OPENROUTER_API_KEY environment variable not set")
            _llm = ChatOpenAI(
                model=OPENROUTER_MODEL,
                temperature=0.7,
                api_key=OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                extra_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://chatbotura.local"),
                    "X-Title": os.getenv("OPENROUTER_TITLE", "ChatBotura"),
                }
            )
            print(f"✓ Using OpenRouter with model: {OPENROUTER_MODEL}")
        else:
            # Default to OpenAI
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            _llm = ChatOpenAI(
                model=OPENAI_MODEL,
                temperature=0.7,
                api_key=OPENAI_API_KEY
            )
            print(f"✓ Using OpenAI with model: {OPENAI_MODEL}")
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
    chat_history: Optional[list[dict]] = None,
    session_id: Optional[str] = None
) -> str:
    """
    Generate a response using tenant config, RAG context, and chat history.

    Args:
        tenant_id: The tenant identifier
        user_message: The user's input message
        chat_history: List of previous messages [{"role": "user"|"assistant", "content": "..."}]
        session_id: Optional session ID for persistent conversation storage

    Returns:
        Generated response string
    """
    from app.db import get_or_create_conversation, add_message, get_conversation_history
    
    if chat_history is None:
        chat_history = []

    # 0. Load history from DB if session_id provided
    if session_id:
        try:
            db_history = get_conversation_history(tenant_id, session_id)
            if db_history:
                chat_history = db_history
        except Exception as e:
            print(f"Warning: Failed to load conversation history: {e}")

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
        response_text = response.content
        
        # Save messages to DB if session_id provided
        if session_id:
            try:
                conversation_id = get_or_create_conversation(tenant_id, session_id)
                add_message(conversation_id, "user", user_message)
                add_message(conversation_id, "assistant", response_text)
            except Exception as e:
                print(f"Warning: Failed to save message to history: {e}")
        
        return response_text
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
