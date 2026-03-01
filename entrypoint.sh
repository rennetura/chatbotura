#!/bin/bash
set -e

# Initialize database and RAG if not already done
echo "Initializing ChatBotura..."
python -c "from app.db import init_db; init_db()"
python -c "from app.rag import init_rag; init_rag()"
echo "Initialization complete."

# Execute the command (default to running FastAPI)
exec "$@"
