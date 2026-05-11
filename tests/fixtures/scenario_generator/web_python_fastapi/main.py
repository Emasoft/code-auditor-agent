"""Tiny FastAPI fixture for the web_python_fastapi discoverer."""

from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.get("/users")
async def list_users():
    """List all users in the system."""
    return []


@app.post("/orders")
def create_order(payload: dict):
    """Create a new order and return its id."""
    return {"id": 1}


@app.delete("/orders/{id}")
def delete_order(id: int):
    """Delete the order with the given id."""
    return None


@router.get("/internal/health")
def health_check():
    """Return service health status."""
    return {"status": "ok"}


app.include_router(router)
