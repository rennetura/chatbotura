"""FastAPI application for ChatBotura REST API."""
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
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
from app.config import settings


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
    allow_origins=settings.api.cors_origins,
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


# Admin API Models
class TenantCreateRequest(BaseModel):
    """Request model for creating a tenant."""
    tenant_id: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-z0-9_]+$')
    business_name: str = Field(..., min_length=1, max_length=200)
    system_prompt: str = Field(..., min_length=10, max_length=5000)
    tone: str = Field(default="professional", pattern=r'^(friendly|professional|casual|formal)$')


class TenantUpdateRequest(BaseModel):
    """Request model for updating a tenant."""
    business_name: Optional[str] = Field(None, min_length=1, max_length=200)
    system_prompt: Optional[str] = Field(None, min_length=10, max_length=5000)
    tone: Optional[str] = Field(None, pattern=r'^(friendly|professional|casual|formal)$')


class TenantResponse(BaseModel):
    """Response model for tenant (without sensitive data)."""
    tenant_id: str
    business_name: str
    tone: str


class TenantCreateResponse(BaseModel):
    """Response model for tenant creation (includes API key)."""
    tenant_id: str
    business_name: str
    tone: str
    api_key: str
    message: str


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


@app.get("/healthz", tags=["Health"])
async def liveness():
    """Liveness probe - is the app alive?"""
    return {"status": "alive"}


@app.get("/ready", tags=["Health"])
async def readiness():
    """Readiness probe - is the app ready to serve traffic?"""
    import app.rag as rag_module
    import app.engine as engine_module
    
    checks = {
        "database": False,
        "rag": False,
        "llm": False
    }
    
    # Check database
    try:
        from app.db import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1")
        checks["database"] = True
    except Exception as e:
        logger.warning(f"Database readiness check failed: {e}")
    
    # Check RAG
    try:
        if hasattr(rag_module, '_rag_initialized') and rag_module._rag_initialized:
            checks["rag"] = True
        elif hasattr(rag_module, 'get_rag') and rag_module.get_rag() is not None:
            checks["rag"] = True
    except Exception as e:
        logger.warning(f"RAG readiness check failed: {e}")
    
    # Check LLM
    try:
        if engine_module.LLM_PROVIDER:
            checks["llm"] = True
    except Exception as e:
        logger.warning(f"LLM readiness check failed: {e}")
    
    all_ready = all(checks.values())
    status_code = 200 if all_ready else 503
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ready else "not_ready", "checks": checks}
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


# ============================================================================
# Admin Authentication Dependency
# ============================================================================

def verify_admin(request: Request) -> bool:
    """
    Verify the request is from an admin.
    Checks X-Admin-Key header against configured admin API key.
    Reads from environment variable for flexibility in tests.
    """
    admin_key = request.headers.get("x-admin-key")
    if not admin_key:
        raise HTTPException(
            status_code=401,
            detail="Admin API key required. Include x-admin-key header."
        )
    
    # Read from environment directly for test flexibility
    expected_key = os.environ.get("ADMIN__API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="Admin API key not configured on server"
        )
    
    if admin_key != expected_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin API key"
        )
    
    return True


# ============================================================================
# Admin API - Full Tenant CRUD
# ============================================================================

@app.post("/api/v1/admin/tenants", tags=["Admin - Tenants"])
async def create_tenant_admin(
    request: TenantCreateRequest,
    req: Request,
    _: bool = Depends(verify_admin)
):
    """Create a new tenant (admin only)."""
    from app.db import create_tenant as db_create_tenant
    
    result = db_create_tenant(
        tenant_id=request.tenant_id,
        business_name=request.business_name,
        system_prompt=request.system_prompt,
        tone=request.tone
    )
    
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Tenant '{request.tenant_id}' already exists"
        )
    
    return TenantCreateResponse(
        tenant_id=result["tenant_id"],
        business_name=result["business_name"],
        tone=result["tone"],
        api_key=result["api_key"],
        message="Tenant created successfully. Save the API key - it won't be shown again."
    )


@app.get("/api/v1/admin/tenants", tags=["Admin - Tenants"])
async def list_tenants_admin(
    req: Request,
    _: bool = Depends(verify_admin)
):
    """List all tenants (admin only)."""
    from app.db import get_all_tenants
    
    tenants = get_all_tenants()
    # Remove sensitive data
    for tenant in tenants:
        tenant.pop("api_key_hash", None)
        tenant.pop("system_prompt", None)
    
    return {"tenants": tenants}


@app.get("/api/v1/admin/tenants/{tenant_id}", tags=["Admin - Tenants"])
async def get_tenant_admin(
    tenant_id: str,
    req: Request,
    _: bool = Depends(verify_admin)
):
    """Get tenant details (admin only)."""
    from app.db import get_tenant
    
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    # Remove sensitive data except for admin
    tenant.pop("api_key_hash", None)
    return tenant


@app.put("/api/v1/admin/tenants/{tenant_id}", tags=["Admin - Tenants"])
async def update_tenant_admin(
    tenant_id: str,
    request: TenantUpdateRequest,
    req: Request,
    _: bool = Depends(verify_admin)
):
    """Update tenant configuration (admin only)."""
    from app.db import update_tenant as db_update_tenant
    
    result = db_update_tenant(
        tenant_id=tenant_id,
        business_name=request.business_name,
        system_prompt=request.system_prompt,
        tone=request.tone
    )
    
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    result.pop("api_key_hash", None)
    result.pop("system_prompt", None)
    return result


@app.delete("/api/v1/admin/tenants/{tenant_id}", tags=["Admin - Tenants"])
async def delete_tenant_admin(
    tenant_id: str,
    req: Request,
    _: bool = Depends(verify_admin)
):
    """Delete a tenant and all its data (admin only)."""
    from app.db import delete_tenant as db_delete_tenant
    
    success = db_delete_tenant(tenant_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    return {"message": f"Tenant '{tenant_id}' deleted successfully"}


@app.post("/api/v1/admin/tenants/{tenant_id}/regenerate-key", tags=["Admin - Tenants"])
async def regenerate_tenant_key(
    tenant_id: str,
    req: Request,
    _: bool = Depends(verify_admin)
):
    """Regenerate tenant API key (admin only)."""
    from app.db import regenerate_tenant_api_key
    
    new_key = regenerate_tenant_api_key(tenant_id)
    if new_key is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )
    
    return {"tenant_id": tenant_id, "api_key": new_key, "message": "API key regenerated. Save this key - it won't be shown again."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=True
    )