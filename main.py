"""FastAPI application for ChatBotura REST API."""
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Observability imports
from app.observability import (
    init_telemetry, set_tracer, get_tracer, metrics_endpoint,
    REQUEST_COUNT, REQUEST_LATENCY
)
from app.logging_config import setup_logging, get_logger, LogContext, log_error

from app.db import init_db, get_tenant, get_or_create_conversation, add_message, get_conversation_history
from app.rag import init_rag
from app.engine import init_engine, generate_response, LLM_PROVIDER
from app.auth import AuthMiddleware, RateLimiterMiddleware, verify_tenant_access


# Application settings
APP_NAME = "ChatBotura"
APP_VERSION = "1.0.0"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Setup logging
logger = setup_logging("chatbotura")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    logger.info("Initializing ChatBotura services...")
    
    # Initialize telemetry
    tracer = init_telemetry("chatbotura-api")
    set_tracer(tracer)
    logger.info("OpenTelemetry tracing initialized")
    
    # Initialize services
    init_db()
    init_rag()
    init_engine()
    
    logger.info("ChatBotura services initialized successfully")
    yield
    logger.info("Shutting down ChatBotura...")


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

# Add rate limiting middleware (will run after auth due to LIFO order)
app.add_middleware(RateLimiterMiddleware)

# Add authentication middleware (must run before rate limiter to set tenant)
app.add_middleware(AuthMiddleware)


# Request/Response models
class ChatRequest(BaseModel):
    """Chat request model."""
    tenant_id: str
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    chat_history: Optional[list[dict]] = None

    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Validate and sanitize user message."""
        # Check for suspicious patterns (basic XSS/SQL injection prevention)
        suspicious_patterns = [
            r'<script[^>]*>.*?</script>',  # Script tags
            r'javascript:',
            r'on\w+\s*=',  # Event handlers like onclick=
            r'<iframe[^>]*>',  # iframes
            r'SELECT.*FROM|INSERT.*INTO|UPDATE.*SET|DELETE.*FROM',  # Basic SQL patterns
            r'DROP\s+TABLE',
            r'--|/\*|\*/',  # SQL comments
            r'EXEC(\s+|\(|xpodb_)',
        ]
        for pattern in suspicious_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError(f"Message contains prohibited content")
        return v


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


# Middleware for metrics and logging
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Middleware for request tracing and metrics."""
    start_time = time.time()
    
    # Extract tenant_id from path or query if available
    tenant_id = request.path_params.get("tenant_id")
    if not tenant_id and request.query_params.get("tenant_id"):
        tenant_id = request.query_params.get("tenant_id")
    
    # Get tracer
    tracer = get_tracer()
    
    with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        span.set_attribute("http.target", request.url.path)
        if tenant_id:
            span.set_attribute("tenant_id", tenant_id)
        
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception as e:
            status = "500"
            raise
        finally:
            duration = time.time() - start_time
            
            # Update Prometheus metrics
            endpoint = request.url.path
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=status,
                tenant_id=tenant_id or "unknown"
            ).inc()
            
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=endpoint,
                tenant_id=tenant_id or "unknown"
            ).observe(duration)
            
            # Set span attributes
            span.set_attribute("http.status_code", int(status))
            span.set_attribute("latency_ms", duration * 1000)
    
    return response


# Metrics endpoint
@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Prometheus metrics endpoint."""
    return metrics_endpoint()


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
    req: Request
):
    """
    Generate a chat response.

    Requires X-API-Key header for authentication.

    Args:
        request: Chat request with tenant_id, message, optional session_id, and optional chat_history
        req: FastAPI Request object

    Returns:
        ChatResponse with the generated response
    """
    start_time = time.time()
    tracer = get_tracer()

    with tracer.start_as_current_span("chat_request") as span:
        span.set_attribute("tenant_id", request.tenant_id)
        if request.session_id:
            span.set_attribute("session_id", request.session_id)
        span.set_attribute("message_length", len(request.message))

        # Verify tenant access (ensures the authenticated tenant matches the requested tenant_id)
        # This will raise HTTPException if not authorized
        verify_tenant_access(request.tenant_id, req)

        # Validate tenant exists (additional check)
        tenant = get_tenant(request.tenant_id)
        if not tenant:
            span.set_attribute("error", "tenant_not_found")
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
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")

        # Generate response
        try:
            response = generate_response(
                tenant_id=request.tenant_id,
                user_message=request.message,
                chat_history=chat_history,
                session_id=request.session_id
            )
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            span.set_attribute("latency_ms", latency_ms)
            span.set_attribute("response_length", len(response))
            
            # Structured logging
            with LogContext(
                tenant_id=request.tenant_id,
                session_id=request.session_id,
                latency_ms=round(latency_ms, 2)
            ):
                logger.info(f"Chat request completed in {latency_ms:.2f}ms")
            
            return ChatResponse(
                response=response,
                tenant_id=request.tenant_id,
                llm_provider=LLM_PROVIDER
            )
        except Exception as e:
            span.set_attribute("error", str(e))
            span.record_exception(e)
            log_error(logger, e, tenant_id=request.tenant_id, session_id=request.session_id)
            raise HTTPException(
                status_code=500,
                detail=f"Error generating response: {str(e)}"
            )


@app.get("/api/v1/conversations/{tenant_id}/{session_id}/history", tags=["Conversations"])
async def get_history(tenant_id: str, session_id: str, req: Request):
    """Get conversation history for a tenant/session.

    Args:
        tenant_id: The tenant identifier
        session_id: The session identifier
        req: FastAPI Request object

    Returns:
        List of messages
    """
    # Verify tenant access
    verify_tenant_access(tenant_id, req)

    try:
        history = get_conversation_history(tenant_id, session_id)
        return {"session_id": session_id, "tenant_id": tenant_id, "messages": history}
    except Exception as e:
        log_error(logger, e, tenant_id=tenant_id, session_id=session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting history: {str(e)}"
        )


@app.delete("/api/v1/conversations/{tenant_id}/{session_id}", tags=["Conversations"])
async def delete_conversation_endpoint(tenant_id: str, session_id: str, req: Request):
    """Delete a conversation.

    Args:
        tenant_id: The tenant identifier
        session_id: The session identifier
        req: FastAPI Request object

    Returns:
        Success message
    """
    from app.db import get_or_create_conversation, delete_conversation

    # Verify tenant access
    verify_tenant_access(tenant_id, req)

    try:
        conversation_id = get_or_create_conversation(tenant_id, session_id)
        delete_conversation(conversation_id)
        return {"message": "Conversation deleted"}
    except Exception as e:
        log_error(logger, e, tenant_id=tenant_id, session_id=session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting conversation: {str(e)}"
        )


@app.get("/api/v1/tenants", tags=["Tenants"])
async def list_tenants(req: Request):
    """List the authenticated tenant's information."""
    from app.db import get_all_tenants
    tenant = getattr(req.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Return only the authenticated tenant's info (tenant isolation)
    # Remove sensitive info
    tenant_info = tenant.copy()
    tenant_info.pop("api_key_hash", None)
    tenant_info.pop("system_prompt", None)
    return {"tenants": [tenant_info]}


@app.get("/api/v1/tenants/{tenant_id}", tags=["Tenants"])
async def get_tenant_info(tenant_id: str, req: Request):
    """Get tenant information."""
    # Verify the authenticated tenant has access to the requested tenant_id
    verify_tenant_access(tenant_id, req)

    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    # Remove sensitive system prompt
    tenant.pop("system_prompt", None)
    tenant.pop("api_key_hash", None)
    return tenant


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )