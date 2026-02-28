"""RAG layer for ChatBotura - ChromaDB vector store for document retrieval."""
import os
import chromadb
from chromadb.config import Settings
from typing import Optional

# Persistent storage for ChromaDB
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "chroma_data")

# In-memory client for simplicity (use PersistentClient for production)
_client = None


def get_client() -> chromadb.Client:
    """Get or create ChromaDB client."""
    global _client
    if _client is None:
        os.makedirs(CHROMA_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def get_collection(tenant_id: str):
    """Get or create a collection for a specific tenant."""
    client = get_client()
    return client.get_or_create_collection(
        name=f"tenant_{tenant_id}",
        metadata={"tenant_id": tenant_id}
    )


def insert_fake_docs(tenant_id: str) -> None:
    """Insert fake documents into ChromaDB for a tenant."""
    collection = get_collection(tenant_id)

    if tenant_id == "pizza_shop":
        docs = [
            "Our pizza sizes are: Small (10\"), Medium (12\"), Large (14\"), and Family (18\"). Prices range from $12.99 to $29.99.",
            "Toppings available: Pepperoni, Mushrooms, Olives, Bell Peppers, Onions, Sausage, Bacon, Extra Cheese. Each additional topping costs $1.50.",
            "We offer specialty pizzas: Margherita ($15.99), BBQ Chicken ($17.99), Meat Lovers ($18.99), and Veggie Delight ($16.99).",
            "Our crust options are: Classic Hand-Tossed, Thin Crust, Stuffed Crust, and Gluten-Free. Gluten-Free costs $2.00 extra.",
            "Operating hours: Monday-Thursday 11AM-10PM, Friday-Saturday 11AM-11PM, Sunday 12PM-9PM. Free delivery on orders over $25.",
            "We also offer salads, garlic bread, wings, and desserts. Try our Tiramisu ($6.99) or Chocolate Lava Cake ($7.99).",
            "Order online at www.mariospizza.com or call (555) 123-4567. Follow us on social media for daily specials!"
        ]
        ids = [f"pizza_doc_{i}" for i in range(len(docs))]

    elif tenant_id == "law_firm":
        docs = [
            "Pearson & Associates provides legal services in: Family Law, Criminal Defense, Corporate Law, Real Estate, and Personal Injury.",
            "Our attorneys have an average of 15+ years of experience. Initial consultations are $150 for 30 minutes.",
            "Office hours: Monday-Friday 9AM-6PM. We offer evening and weekend appointments upon request.",
            "Our fee structure: Hourly rates ($250-$500/hour), Flat fees for certain services, and Contingency for personal injury cases.",
            "Location: 123 Legal Plaza, Suite 500, Downtown. Free parking available for clients. Accessible by public transit.",
            "Contact us at (555) 987-6543 or info@pearsonlaw.com. Emergency line available 24/7 for existing clients.",
            "We are committed to client communication. Expect response within 24 hours. Case updates provided every 2 weeks."
        ]
        ids = [f"law_doc_{i}" for i in range(len(docs))]

    else:
        raise ValueError(f"Unknown tenant: {tenant_id}")

    # Check if docs already exist
    existing = collection.get()
    if len(existing["ids"]) > 0:
        print(f"  Documents already exist for {tenant_id}, skipping insert")
        return

    collection.add(documents=docs, ids=ids)
    print(f"✓ Inserted {len(docs)} documents for tenant: {tenant_id}")


def search_similar(tenant_id: str, query: str, n_results: int = 3) -> list[str]:
    """Search for similar documents in the tenant's collection."""
    try:
        collection = get_collection(tenant_id)
        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )
        if results and results["documents"] and results["documents"][0]:
            return results["documents"][0]
    except Exception as e:
        print(f"Warning: Search error for tenant {tenant_id}: {e}")
    return []


def init_rag() -> None:
    """Initialize RAG with mock documents for all tenants."""
    print("Initializing RAG...")
    insert_fake_docs("pizza_shop")
    insert_fake_docs("law_firm")
    print("✓ RAG initialized")


if __name__ == "__main__":
    init_rag()
    print(f"\nChromaDB data at: {os.path.abspath(CHROMA_PATH)}")
