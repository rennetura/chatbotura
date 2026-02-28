"""ChatBotura - Streamlit UI for Multi-tenant AI Chatbot."""
import streamlit as st
import os
import sys
import uuid

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, get_all_tenants, get_conversation_history, delete_conversation, get_or_create_conversation
from app.rag import init_rag
from app.engine import generate_response, init_engine

# Page config
st.set_page_config(
    page_title="ChatBotura",
    page_icon="🤖",
    layout="centered"
)

# Session state initialization
if "messages" not in st.session_state:
    st.session_state.messages = []

if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None

if "session_id" not in st.session_state:
    # Generate a new session ID for persistent conversations
    st.session_state.session_id = str(uuid.uuid4())


def init_services():
    """Initialize all services."""
    init_db()
    init_rag()
    init_engine()


def get_tenant_display_name(tenant: dict) -> str:
    """Get display name for tenant dropdown."""
    return f"{tenant['business_name']} ({tenant['tenant_id']})"


def main():
    """Main Streamlit app."""
    st.title("🤖 ChatBotura")
    st.caption("Multi-tenant AI Chatbot Platform")

    # Initialize services
    init_services()

    # Get available tenants
    tenants = get_all_tenants()

    if not tenants:
        st.error("No tenants found. Please run the database initialization.")
        return

    # Tenant selector in sidebar
    st.sidebar.header("Configuration")

    tenant_options = {get_tenant_display_name(t): t["tenant_id"] for t in tenants}

    selected_tenant_name = st.sidebar.selectbox(
        "Select Tenant",
        options=list(tenant_options.keys()),
        index=0
    )

    current_tenant_id = tenant_options[selected_tenant_name]

    # Reset chat when tenant changes
    if current_tenant_id != st.session_state.tenant_id:
        st.session_state.tenant_id = current_tenant_id
        # Generate new session ID for new tenant
        st.session_state.session_id = str(uuid.uuid4())
        # Load history from DB for this tenant/session
        try:
            st.session_state.messages = get_conversation_history(current_tenant_id, st.session_state.session_id)
        except Exception:
            st.session_state.messages = []
        st.rerun()

    # Show tenant info
    tenant = next(t for t in tenants if t["tenant_id"] == current_tenant_id)
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Tone:** {tenant['tone']}")
    st.sidebar.markdown(f"**Session:** {st.session_state.session_id[:8]}...")

    # Clear chat button (clears both UI and DB)
    if st.sidebar.button("Clear Chat"):
        try:
            conversation_id = get_or_create_conversation(current_tenant_id, st.session_state.session_id)
            delete_conversation(conversation_id)
        except Exception:
            pass
        st.session_state.messages = []
        st.rerun()

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Type your message..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Use session_id for persistent conversation history
                    # The engine will load history from DB and save new messages
                    response = generate_response(
                        tenant_id=current_tenant_id,
                        user_message=prompt,
                        chat_history=[],  # Engine loads from DB via session_id
                        session_id=st.session_state.session_id
                    )
                    st.markdown(response)

                    # Add to UI history for display
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response
                    })
                except Exception as e:
                    st.error(f"Error: {str(e)}")


if __name__ == "__main__":
    main()
