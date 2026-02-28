# ChatBotura 🤖

Multi-tenant AI Chatbot Platform Boilerplate

## Tech Stack

- **Backend:** FastAPI
- **AI Orchestration:** LangChain / LangGraph
- **LLM:** OpenAI gpt-4o (or OpenRouter)
- **Database:** SQLite (tenant config)
- **Vector Store:** ChromaDB (local RAG)
- **UI:** Streamlit
- **Observability:** OpenTelemetry + Prometheus

## Project Structure

```
chatbotura/
├── app/
│   ├── __init__.py          # Package init
│   ├── db.py                # SQLite tenant config management
│   ├── rag.py               # ChromaDB vector store & RAG
│   ├── engine.py            # AI Engine with LangChain
│   ├── observability.py     # OpenTelemetry & Prometheus metrics
│   └── logging_config.py    # Structured JSON logging
├── ui/
│   ├── __init__.py
│   └── app.py               # Streamlit UI
├── requirements.txt
├── .gitignore
└── README.md
```

## Quick Start

### 1. Clone & Setup

```bash
cd chatbotura
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file:

```bash
OPENAI_API_KEY=your-api-key-here

# Optional: OpenRouter configuration
# LLM_PROVIDER=openrouter
# OPENROUTER_API_KEY=your-openrouter-key

# Observability (optional)
# LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR
# OTEL_EXPORTER_OTLP_ENDPOINT=      # OTLP collector (e.g., http://localhost:4317)
# OTEL_SERVICE_NAME=chatbotura-api
# DEPLOYMENT_ENV=development
```

### 3. Initialize Database & RAG

```bash
python -c "from app.db import init_db; init_db()"
python -c "from app.rag import init_rag; init_rag()"
```

Or from the app directory:

```bash
cd chatbotura
python -c "
import sys
sys.path.insert(0, '.')
from app.db import init_db
from app.rag import init_rag
init_db()
init_rag()
"
```

### 4. Run the API Server

```bash
python main.py
```

The API will be available at `http://localhost:8000`

### 5. Run the UI

```bash
streamlit run ui/app.py
```

The app will open at `http://localhost:8501`

## Usage

1. Select a tenant from the sidebar (Pizza Shop or Law Firm)
2. Type your message in the chat
3. The AI will respond using:
   - Tenant-specific system prompt
   - Relevant documents from RAG
   - Conversation history

## Features

- **Multi-tenancy:** Switch between different businesses
- **RAG:** Context-aware responses using ChromaDB similarity search
- **Chat History:** Maintains conversation context
- **Tenant Config:** Each tenant has custom system prompt and tone
- **Observability:** OpenTelemetry tracing + Prometheus metrics

## Observability

### Structured Logging

All logs are in JSON format with context:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Chat request completed in 245.32ms",
  "tenant_id": "pizza_shop",
  "session_id": "abc123",
  "latency_ms": 245.32,
  "module": "main",
  "function": "chat"
}
```

**Log Levels:**
- `DEBUG`: Detailed development information
- `INFO`: Operational events (requests, responses)
- `WARNING`: Potential issues that don't stop operation
- `ERROR`: Failures that need attention

Set via `LOG_LEVEL` environment variable.

### OpenTelemetry Tracing

Traces are automatically generated for:
- HTTP requests (via middleware)
- LLM calls (with latency metrics)
- RAG searches
- Database queries

**Environment Variables:**
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP collector URL (optional)
- `OTEL_SERVICE_NAME`: Service name for traces (default: chatbotura-api)
- `DEPLOYMENT_ENV`: Environment tag (development/staging/production)

For local development, traces print to console by default.

### Prometheus Metrics

Access metrics at: `http://localhost:8000/metrics`

**Available Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `chatbotura_http_requests_total` | Counter | Total HTTP requests |
| `chatbotura_http_request_duration_seconds` | Histogram | Request latency |
| `chatbotura_llm_calls_total` | Counter | Total LLM calls |
| `chatbotura_llm_call_duration_seconds` | Histogram | LLM call latency |
| `chatbotura_rag_search_total` | Counter | Total RAG searches |
| `chatbotura_rag_search_duration_seconds` | Histogram | RAG search latency |
| `chatbotura_db_queries_total` | Counter | Total DB queries |
| `chatbotura_db_query_duration_seconds` | Histogram | DB query latency |

All metrics include `tenant_id` label for per-tenant monitoring.

### Example: Using with Grafana + Prometheus

1. Run Prometheus with config:
```yaml
scrape_configs:
  - job_name: 'chatbotura'
    static_configs:
      - targets: ['localhost:8000']
```

2. Import dashboard with queries:
```promql
# Request rate
rate(chatbotura_http_requests_total[5m])

# P95 latency
histogram_quantile(0.95, rate(chatbotura_http_request_duration_seconds_bucket[5m]))

# Error rate
rate(chatbotura_http_requests_total{status="500"}[5m])
```

## API Usage (Programmatic)

```python
from app.engine import generate_response
from app.db import init_db, get_all_tenants

# Initialize
init_db()

# Get response
response = generate_response(
    tenant_id="pizza_shop",
    user_message="What's your most popular pizza?",
    chat_history=[]
)
print(response)
```

## License

MIT