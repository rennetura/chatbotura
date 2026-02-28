"""FastAPI application for ChatBotura REST API."""
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, get_tenant, get_or_create_conversation, add_message, get_conversation_history
from app.rag import init_rag
from app.engine import init_engine, generate_response, LLM_PROVIDER


# Application settings
APP_NAME = "ChatBotura"
APP_VERSION = "1.0.0"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    print("Initializing ChatBotura services...")
    init_db()
    init_rag()
    init_engine()
    yield
    print("Shutting down ChatBotura...")


# Create FastAPI app
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Multi-tenant AI Chatbot Platform REST API",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    """Chat request model."""
    tenant_id: str
    message: str
    session_id: Optional[str] = None
    chat_history: Optional[list[dict]] = None


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str
    tenant_id: str
    llm_provider: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    llm_provider: str
    database: str


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to ChatBotura API",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        llm_provider=LLM_PROVIDER,
        database="sqlite"
    )


@app.post("/api/v1/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(
    request: ChatRequest,
    x_api_key: Optional[str] = Header(None)
):
    """
    Generate a chat response.

    Args:
        request: Chat request with tenant_id, message, optional session_id, and optional chat_history
        x_api_key: Optional API key for authentication

    Returns:
        ChatResponse with the generated response
    """
    # Validate tenant exists
    tenant = get_tenant(request.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{request.tenant_id}' not found"
        )

    # Get conversation history from DB if session_id provided
    chat_history = request.chat_history or []
    if request.session_id:
        # Try to load from DB
        try:
            db_history = get_conversation_history(request.tenant_id, request.session_id)
            if db_history:
                chat_history = db_history
        except Exception:
            pass  # Fall back to provided chat_history

    # Generate response
    try:
        response = generate_response(
            tenant_id=request.tenant_id,
            user_message=request.message,
            chat_history=chat_history
        )
        
        # Save messages to DB if session_id provided
        if request.session_id:
            try:
                conversation_id = get_or_create_conversation(request.tenant_id, request.session_id)
                add_message(conversation_id, "user", request.message)
                add_message(conversation_id, "assistant", response)
            except Exception as e:
                print(f"Warning: Failed to save message to DB: {e}")
        
        return ChatResponse(
            response=response,
            tenant_id=request.tenant_id,
            llm_provider=LLM_PROVIDER
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )


@app.get("/api/v1/conversations/{tenant_id}/{session_id}/history", tags=["Conversations"])
async def get_history(tenant_id: str, session_id: str):
    """Get conversation history for a tenant/session.
    
    Args:
        tenant_id: The tenant identifier
        session_id: The session identifier
    
    Returns:
        List of messages
    """
    # Validate tenant exists
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    try:
        history = get_conversation_history(tenant_id, session_id)
        return {"session_id": session_id, "tenant_id": tenant_id, "messages": history}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting history: {str(e)}"
        )


@app.delete("/api/v1/conversations/{tenant_id}/{session_id}", tags=["Conversations"])
async def delete_conversation_endpoint(tenant_id: str, session_id: str):
    """Delete a conversation.
    
    Args:
        tenant_id: The tenant identifier
        session_id: The session identifier
    
    Returns:
        Success message
    """
    from app.db import get_or_create_conversation, delete_conversation
    
    # Validate tenant exists
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    try:
        conversation_id = get_or_create_conversation(tenant_id, session_id)
        delete_conversation(conversation_id)
        return {"message": "Conversation deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting conversation: {str(e)}"
        )


@app.get("/api/v1/tenants", tags=["Tenants"])
async def list_tenants():
    """List all available tenants."""
    from app.db import get_all_tenants
    tenants = get_all_tenants()
    # Remove sensitive info
    for tenant in tenants:
        tenant.pop("system_prompt", None)
    return {"tenants": tenants}


@app.get("/api/v1/tenants/{tenant_id}", tags=["Tenants"])
async def get_tenant_info(tenant_id: str):
    """Get tenant information."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    # Remove sensitive system prompt
    tenant.pop("system_prompt", None)
    return tenant


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )