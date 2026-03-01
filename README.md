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

### 2. Configuration

ChatBotura uses **Pydantic Settings** to manage configuration from environment variables and optional YAML templates.

#### Option A: Use `.env` file (recommended for development)

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and fill in the required values, especially `OPENAI_API_KEY` or `OPENROUTER_API_KEY`.

#### Option B: Use `config.yaml`

You can also provide a `config.yaml` file with the same settings in a hierarchical format. The application expects environment variables, so if you use YAML, you must either export them or use a tool to convert. For simplicity, use `.env`.

See the **Configuration** section below for a complete list of available settings.

#### Environment Variables (Nested Delimiter)

The settings are structured into nested sections. Environment variables use double underscores (`__`) to denote nesting.

Examples:
- `DATABASE__PATH=chatbotura.db`
- `API__PORT=8000`
- `API__CORS_ORIGINS=["*"]`
- `LLM__PROVIDER=openai`

### 3. Environment Variables (Common)

At minimum, set:

```bash
OPENAI_API_KEY=your-api-key-here
```

Optional (with defaults):

- `LLM_PROVIDER=openai` (or `openrouter`)
- `LOG_LEVEL=INFO`
- `API__PORT=8000`
- `RATE_LIMIT__REQUESTS=100`
- `RATE_LIMIT__WINDOW=60`

Refer to `.env.example` for the full list.

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

## Configuration

ChatBotura's behavior is controlled by a central settings object. You can configure it via environment variables (or a `.env` file) using **Pydantic Settings**.

### Settings Structure

| Section | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| **database** | `path` | string | `chatbotura.db` | SQLite database file path |
| **chroma** | `path` | string | `chroma_data` | ChromaDB persistent storage directory |
| **api** | `host` | string | `0.0.0.0` | API server host |
| | `port` | integer | `8000` | API server port |
| | `cors_origins` | list of strings | `["*"]` | Allowed CORS origins |
| **llm** | `provider` | string | `openai` | LLM provider: `openai` or `openrouter` |
| | `openai_api_key` | string (optional) | `None` | OpenAI API key |
| | `openrouter_api_key` | string (optional) | `None` | OpenRouter API key |
| | `openai_model` | string | `gpt-4o` | OpenAI model name |
| | `openrouter_model` | string | `openai/gpt-4o` | OpenRouter model name |
| | `openrouter_referer` | string | `https://chatbotura.local` | OpenRouter referer header |
| | `openrouter_title` | string | `ChatBotura` | OpenRouter site title |
| **rate_limit** | `requests` | integer | `100` | Max requests per minute per tenant |
| | `window` | integer | `60` | Rate limit window in seconds |
| **logging** | `level` | string | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Using Environment Variables

Prefix section keys in uppercase and separate nested fields with double underscores:

```bash
export DATABASE__PATH=mydb.db
export API__PORT=8080
export LLM__PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-...
```

For list values like `API__CORS_ORIGINS`, use a JSON array string:

```bash
export API__CORS_ORIGINS='["http://localhost:3000","https://myapp.com"]'
```

### Configuration Files

- **`.env`**: Place environment variable definitions here (automatically loaded).
- **`.env.example`**: Template file with all available options.
- **`config.yaml`**: YAML template showing hierarchical structure (for reference).

> **Note:** The application primary reads from environment variables. The `config.yaml` is provided as a human‑readable reference; it is not automatically loaded. To use it, convert its values into environment variables or a `.env` file.

## Docker Deployment

For quick setup using Docker and Docker Compose:

```bash
# Build and run all services
docker-compose up --build

# Access
# - API: http://localhost:8000
# - UI:  http://localhost:8501
```

A `docker-compose.yml` defines two services:

- `api`: FastAPI server on port 8000
- `ui`: Streamlit interface on port 8501

Both share a persistent volume `data` to store the SQLite database and ChromaDB files. Environment variables (like `OPENAI_API_KEY`) are injected from your shell or a `.env` file.

> **Note:** The entrypoint automatically initializes the database and RAG on first start.

### Customizing via Docker

You can override settings using environment variables:

```bash
export OPENAI_API_KEY=your-key
export LLM_PROVIDER=openai
docker-compose up
```

Or define them in a `.env` file in the same directory as `docker-compose.yml`.

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

## API Reference

### Health Endpoints

| Endpoint | Description | Auth Required |
|----------|-------------|---------------|
| `GET /` | Root info | No |
| `GET /health` | Health check | No |
| `GET /healthz` | Liveness probe | No |
| `GET /ready` | Readiness probe (DB + RAG) | No |
| `GET /metrics` | Prometheus metrics | No |

### Chat API

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/api/v1/chat` | POST | Generate chat response | Yes (X-API-Key) |
| `/api/v1/conversations/{tenant_id}/{session_id}/history` | GET | Get conversation history | Yes |
| `/api/v1/conversations/{tenant_id}/{session_id}` | DELETE | Delete conversation | Yes |

### Tenant API (Tenant-scoped)

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/api/v1/tenants` | GET | Get authenticated tenant info | Yes |
| `/api/v1/tenants/{tenant_id}` | GET | Get specific tenant info | Yes |

### Admin API (Full tenant management)

All admin endpoints require `X-Admin-Key` header with the configured admin API key.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/admin/tenants` | POST | Create new tenant |
| `/api/v1/admin/tenants` | GET | List all tenants |
| `/api/v1/admin/tenants/{tenant_id}` | GET | Get tenant details |
| `/api/v1/admin/tenants/{tenant_id}` | PUT | Update tenant config |
| `/api/v1/admin/tenants/{tenant_id}` | DELETE | Delete tenant |
| `/api/v1/admin/tenants/{tenant_id}/regenerate-key` | POST | Regenerate API key |

#### Create Tenant Request

```json
{
  "tenant_id": "my_business",
  "business_name": "My Business Name",
  "system_prompt": "You are a helpful assistant for My Business...",
  "tone": "professional"
}
```

Valid `tone` values: `friendly`, `professional`, `casual`, `formal`

### Docker Deployment

```bash
# Build and run
docker-compose up --build

# Access
# - API: http://localhost:8000
# - UI: http://localhost:8501
# - Docs: http://localhost:8000/docs
```

Set admin API key via environment:
```bash
export ADMIN_API_KEY=your-secure-admin-key
docker-compose up
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run integration tests
make test-integration
```

## License

MIT