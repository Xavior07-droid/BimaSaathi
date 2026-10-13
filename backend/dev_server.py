
"""Local-only development server for BimaSaathi.
M's real app/main.py replaces this later. Do not deploy this file.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import ingest, policy


# Create FastAPI application
app = FastAPI(
    title="BimaSaathi (A dev server)",
    version="0.1.0",
)


# Configure CORS
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.allowed_origins.split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register routers
app.include_router(ingest.router)
app.include_router(policy.router)


# Homepage
@app.get("/")
def home():
    return {
        "message": "BimaSaathi backend is running!",
        "docs": "/docs",
        "health": "/health",
    }


# Health check
@app.get("/health")
def health():
    return {"status": "ok"}
