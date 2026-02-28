# ChatBotura 🤖

Multi-tenant AI Chatbot Platform Boilerplate

## Tech Stack

- **Backend:** FastAPI
- **AI Orchestration:** LangChain / LangGraph
- **LLM:** OpenAI gpt-4o
- **Database:** SQLite (tenant config)
- **Vector Store:** ChromaDB (local RAG)
- **UI:** Streamlit

## Project Structure

```
chatbotura/
├── app/
│   ├── __init__.py      # Package init
│   ├── db.py            # SQLite tenant config management
│   ├── rag.py           # ChromaDB vector store & RAG
│   └── engine.py        # AI Engine with LangChain
├── ui/
│   ├── __init__.py
│   └── app.py           # Streamlit UI
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
```

Get your API key from: https://platform.openai.com/api-keys

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

### 4. Run the UI

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
