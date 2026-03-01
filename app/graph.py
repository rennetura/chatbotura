"""LangGraph state machine for ChatBotura conversation flow."""
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.db import get_tenant
from app.rag import search_similar
from app.logging_config import get_logger
from app.observability import get_tracer, trace_rag_search, trace_llm_call

logger = get_logger(__name__)


class GraphState(TypedDict):
    """State for the conversation graph."""
    tenant_id: str
    messages: List[dict]     # Conversation history including latest user message
    context: List[str]       # RAG retrieved documents
    prompt: str              # Constructed prompt for LLM
    response: str            # Generated response (final)


def retrieve_context(state: GraphState):
    """Node: Perform RAG search to get relevant context."""
    tenant_id = state["tenant_id"]
    user_message = state["messages"][-1]["content"]
    tracer = get_tracer()

    with tracer.start_as_current_span("rag_search") as rag_span:
        rag_span.set_attribute("tenant_id", tenant_id)
        with trace_rag_search(tenant_id):
            docs = search_similar(tenant_id, user_message, n_results=3)

    rag_span.set_attribute("docs_found", len(docs))
    logger.debug(f"RAG retrieved {len(docs)} documents for tenant {tenant_id}")
    return {"context": docs}


def build_prompt(state: GraphState):
    """Node: Build the prompt for the LLM using tenant config, context, and conversation history."""
    tenant_id = state["tenant_id"]
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise ValueError(f"Tenant {tenant_id} not found")

    system_prompt = tenant["system_prompt"]
    tone = tenant["tone"]
    business_name = tenant["business_name"]
    context = "\n\n".join(state["context"]) if state["context"] else "No relevant context found."

    # Use last 5 messages for context
    history = state["messages"][-5:]
    conversation = ""
    for msg in history:
        role_label = "Customer" if msg["role"] == "user" else "You"
        conversation += f"{role_label}: {msg['content']}\n"

    full_prompt = f"""{system_prompt}

You are representing: {business_name}
Tone: {tone}

Relevant Information:
{context}

Previous Conversation:
{conversation}
"""
    return {"prompt": full_prompt}


def generate_response(state: GraphState):
    """Node: Call LLM to generate a response using the constructed prompt."""
    prompt = state["prompt"]
    # Import here to avoid circular imports
    from app.engine import get_llm, LLM_PROVIDER

    tracer = get_tracer()
    with tracer.start_as_current_span("llm_invoke") as llm_span:
        llm_span.set_attribute("tenant_id", state["tenant_id"])
        llm_span.set_attribute("provider", LLM_PROVIDER)
        try:
            llm = get_llm()
            from langchain_core.messages import HumanMessage
            with trace_llm_call(state["tenant_id"], LLM_PROVIDER):
                response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content
        except Exception as e:
            llm_span.record_exception(e)
            logger.error(f"LLM invocation failed: {e}")
            response_text = f"Error generating response: {str(e)}"

    return {"response": response_text}


def maybe_human_feedback(state: GraphState):
    """Node: Possibly replace the LLM response with a clarification request if needed.
    This node is reached only when the router determines low confidence.
    """
    # In a real implementation, we could examine state["response"] for signs of low confidence.
    # For this task, we provide a generic clarification message.
    clarification = "I'm not confident I understand fully. Could you please provide more details or rephrase your question?"
    return {"response": clarification}


def should_ask_clarification(state: GraphState) -> str:
    """Conditional router: decide if we need to ask for clarification."""
    response = state.get("response", "")
    # Simple heuristic: if response contains "error" or is very short (<30 chars), ask clarification
    if "error" in response.lower() or len(response.strip()) < 30:
        return "maybe_human_feedback"
    return "end"


def build_graph():
    """Build and compile the LangGraph state machine."""
    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("build_prompt", build_prompt)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("maybe_human_feedback", maybe_human_feedback)

    # Set entry point
    workflow.set_entry_point("retrieve_context")

    # Define edges
    workflow.add_edge("retrieve_context", "build_prompt")
    workflow.add_edge("build_prompt", "generate_response")
    workflow.add_conditional_edges(
        "generate_response",
        should_ask_clarification,
        {
            "maybe_human_feedback": "maybe_human_feedback",
            "end": END
        }
    )
    workflow.add_edge("maybe_human_feedback", END)

    # Use memory checkpointer
    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)
    logger.info("LangGraph conversation graph compiled")
    return graph
