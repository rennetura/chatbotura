"""AI Engine for ChatBotura - Configurable LLM Provider (OpenAI or OpenRouter)."""
import os
import time
import uuid
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from app.db import get_tenant, get_or_create_conversation, add_message
from app.rag import search_similar
from app.observability import get_tracer, trace_llm_call, trace_rag_search, trace_db_query
from app.graph import build_graph

# Global graph instance
_graph = None

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
    Generate a response using LangGraph state machine.

    Args:
        tenant_id: The tenant identifier
        user_message: The user's input message
        chat_history: List of previous messages [{"role": "user"|"assistant", "content": "..."}]
        session_id: Optional session ID for persistent conversation storage

    Returns:
        Generated response string
    """
    from app.logging_config import get_logger
    
    logger = get_logger(__name__)
    tracer = get_tracer()
    
    if chat_history is None:
        chat_history = []

    # Create span for this generation request
    with tracer.start_as_current_span("generate_response") as span:
        span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("message_length", len(user_message))
        if session_id:
            span.set_attribute("session_id", session_id)

        # Build message list: chat_history + new user message
        messages = chat_history + [{"role": "user", "content": user_message}]

        # Prepare initial state for graph
        state = {
            "tenant_id": tenant_id,
            "messages": messages,
            "context": [],
            "response": ""
        }

        # Use session_id as thread_id for checkpointing, or generate a unique one
        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        try:
            # Invoke the graph
            result = _graph.invoke(state, config=config)
            response_text = result["response"]
            span.set_attribute("success", True)
        except Exception as e:
            span.record_exception(e)
            span.set_attribute("error", str(e))
            logger.error(f"Graph invocation failed: {e}")
            return f"Error generating response: {str(e)}"

        # Save messages to DB if session_id provided
        if session_id:
            try:
                # Save both user and assistant messages
                conversation_id = get_or_create_conversation(tenant_id, session_id)
                # Only add if not already present? For simplicity, we add.
                # To avoid duplicates, we could check, but it's fine.
                add_message(conversation_id, "user", user_message)
                add_message(conversation_id, "assistant", response_text)
            except Exception as e:
                logger.warning(f"Failed to save message to history: {e}")

        return response_text


def init_engine() -> None:
    """Initialize the AI engine."""
    # Validate API key and initialize LLM
    try:
        llm = get_llm()
    except ValueError as e:
        print(f"⚠ Warning: {e}")

    # Build LangGraph conversation graph
    global _graph
    try:
        _graph = build_graph()
        print("✓ AI Engine with LangGraph initialized")
    except Exception as e:
        print(f"⚠ Failed to initialize LangGraph: {e}")


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