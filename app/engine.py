"""AI Engine for ChatBotura - Configurable LLM Provider (OpenAI or OpenRouter)."""
import os
import time
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from app.db import get_tenant
from app.rag import search_similar
from app.observability import get_tracer, trace_llm_call, trace_rag_search, trace_db_query

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

        # 0. Load history from DB if session_id provided
        if session_id:
            try:
                with trace_db_query(tenant_id, "select"):
                    db_history = get_conversation_history(tenant_id, session_id)
                    if db_history:
                        chat_history = db_history
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")

        # 1. Fetch tenant config
        with tracer.start_as_current_span("fetch_tenant_config") as fetch_span:
            tenant = get_tenant(tenant_id)
            fetch_span.set_attribute("tenant_id", tenant_id)
            if not tenant:
                return f"Error: Tenant '{tenant_id}' not found."

            system_prompt = tenant["system_prompt"]
            tone = tenant["tone"]
            business_name = tenant["business_name"]

        # 2. Perform RAG similarity search with tracing
        with tracer.start_as_current_span("rag_search") as rag_span:
            rag_span.set_attribute("tenant_id", tenant_id)
            rag_span.set_attribute("n_results", 3)
            
            with trace_rag_search(tenant_id):
                relevant_docs = search_similar(tenant_id, user_message, n_results=3)
            
            context = "\n\n".join(relevant_docs) if relevant_docs else "No relevant context found."
            rag_span.set_attribute("docs_found", len(relevant_docs))

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

        # 4. Call LLM with tracing
        with tracer.start_as_current_span("llm_invoke") as llm_span:
            llm_span.set_attribute("tenant_id", tenant_id)
            llm_span.set_attribute("provider", LLM_PROVIDER)
            
            try:
                llm = get_llm()
                
                with trace_llm_call(tenant_id, LLM_PROVIDER):
                    response = llm.invoke([
                        HumanMessage(content=f"{system_prompt}\n\n{context_block}")
                    ])
                
                response_text = response.content
                llm_span.set_attribute("response_length", len(response_text))
                
                # Save messages to DB if session_id provided
                if session_id:
                    try:
                        with trace_db_query(tenant_id, "insert"):
                            conversation_id = get_or_create_conversation(tenant_id, session_id)
                            add_message(conversation_id, "user", user_message)
                            add_message(conversation_id, "assistant", response_text)
                    except Exception as e:
                        logger.warning(f"Failed to save message to history: {e}")
                
                span.set_attribute("success", True)
                return response_text
                
            except Exception as e:
                llm_span.record_exception(e)
                span.set_attribute("error", str(e))
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