"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(
    title="Operations Strategy Agent",
    version="0.1.0",
    description="Evidence-based operations strategy decision support.",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a lightweight liveness response."""
    return {"status": "ok"}
