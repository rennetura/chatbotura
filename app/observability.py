"""Observability setup for ChatBotura - OpenTelemetry tracing and Prometheus metrics."""
import os
import time
from typing import Optional
from functools import wraps

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import Status, StatusCode

# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response


# ============================================================================
# OpenTelemetry Tracing Setup
# ============================================================================

def init_telemetry(service_name: str = "chatbotura") -> trace.Tracer:
    """
    Initialize OpenTelemetry tracing.
    
    Configured via environment variables:
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (optional)
    - OTEL_SERVICE_NAME: Service name for tracing
    
    Args:
        service_name: Name of the service for tracing
    
    Returns:
        Configured tracer instance
    """
    # Create resource with service name
    resource = Resource(attributes={
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", service_name),
        "service.version": os.getenv("APP_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
    })
    
    # Setup tracer provider
    provider = TracerProvider(resource=resource)
    
    # Add console exporter for development (easy to see traces)
    console_exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(console_exporter))
    
    # Try to add OTLP exporter if endpoint configured
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except ImportError:
            pass  # OTLP exporter not available
    
    trace.set_tracer_provider(provider)
    
    return trace.get_tracer(__name__)


def create_span(
    tracer: trace.Tracer,
    name: str,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    **attributes
) -> trace.Span:
    """
    Create a span with common attributes.
    
    Args:
        tracer: The tracer instance
        name: Span name
        tenant_id: Optional tenant ID for context
        session_id: Optional session ID for context
        **attributes: Additional span attributes
    
    Returns:
        Configured span
    """
    span = tracer.start_span(name)
    
    # Add common attributes
    if tenant_id:
        span.set_attribute("tenant_id", tenant_id)
    if session_id:
        span.set_attribute("session_id", session_id)
    
    for key, value in attributes.items():
        span.set_attribute(key, str(value))
    
    return span


def trace_function(tracer: trace.Tracer, span_name: str):
    """
    Decorator to trace a function.
    
    Usage:
        @trace_function(tracer, "my_function")
        def my_function():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator


# ============================================================================
# Prometheus Metrics Setup
# ============================================================================

# Request metrics
REQUEST_COUNT = Counter(
    "chatbotura_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status", "tenant_id"]
)

REQUEST_LATENCY = Histogram(
    "chatbotura_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "tenant_id"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# LLM metrics
LLM_CALL_COUNT = Counter(
    "chatbotura_llm_calls_total",
    "Total LLM calls",
    ["tenant_id", "provider", "status"]
)

LLM_CALL_LATENCY = Histogram(
    "chatbotura_llm_call_duration_seconds",
    "LLM call duration in seconds",
    ["tenant_id", "provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

# RAG metrics
RAG_SEARCH_COUNT = Counter(
    "chatbotura_rag_search_total",
    "Total RAG searches",
    ["tenant_id", "status"]
)

RAG_SEARCH_LATENCY = Histogram(
    "chatbotura_rag_search_duration_seconds",
    "RAG search duration in seconds",
    ["tenant_id"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# Database metrics
DB_QUERY_COUNT = Counter(
    "chatbotura_db_queries_total",
    "Total database queries",
    ["tenant_id", "operation", "status"]
)

DB_QUERY_LATENCY = Histogram(
    "chatbotura_db_query_duration_seconds",
    "Database query duration in seconds",
    ["tenant_id", "operation"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1]
)

# Active connections
ACTIVE_TENANTS = Gauge(
    "chatbotura_active_tenants",
    "Number of active tenants"
)


def metrics_endpoint():
    """Generate Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# ============================================================================
# Tracing Context
# ============================================================================

# Global tracer instance (initialized in main.py)
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    return _tracer


def set_tracer(tracer: trace.Tracer):
    """Set the global tracer instance."""
    global _tracer
    _tracer = tracer


def trace_llm_call(tenant_id: str, provider: str):
    """
    Context manager for tracing LLM calls with metrics.
    
    Usage:
        with trace_llm_call("pizza_shop", "openai") as span:
            response = llm.invoke(...)
    """
    class LLMCallContext:
        def __enter__(self):
            self.start_time = time.time()
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            duration = time.time() - self.start_time
            status = "success" if exc_type is None else "error"
            
            # Update metrics
            LLM_CALL_COUNT.labels(
                tenant_id=tenant_id,
                provider=provider,
                status=status
            ).inc()
            
            LLM_CALL_LATENCY.labels(
                tenant_id=tenant_id,
                provider=provider
            ).observe(duration)
    
    return LLMCallContext()


def trace_rag_search(tenant_id: str):
    """
    Context manager for tracing RAG searches with metrics.
    
    Usage:
        with trace_rag_search("pizza_shop") as span:
            results = search_similar(...)
    """
    class RAGSearchContext:
        def __enter__(self):
            self.start_time = time.time()
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            duration = time.time() - self.start_time
            status = "success" if exc_type is None else "error"
            
            # Update metrics
            RAG_SEARCH_COUNT.labels(
                tenant_id=tenant_id,
                status=status
            ).inc()
            
            RAG_SEARCH_LATENCY.labels(
                tenant_id=tenant_id
            ).observe(duration)
    
    return RAGSearchContext()


def trace_db_query(tenant_id: str, operation: str):
    """
    Context manager for tracing DB queries with metrics.
    
    Usage:
        with trace_db_query("pizza_shop", "select") as span:
            result = db.execute(...)
    """
    class DBQueryContext:
        def __enter__(self):
            self.start_time = time.time()
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            duration = time.time() - self.start_time
            status = "success" if exc_type is None else "error"
            
            # Update metrics
            DB_QUERY_COUNT.labels(
                tenant_id=tenant_id,
                operation=operation,
                status=status
            ).inc()
            
            DB_QUERY_LATENCY.labels(
                tenant_id=tenant_id,
                operation=operation
            ).observe(duration)
    
    return DBQueryContext()