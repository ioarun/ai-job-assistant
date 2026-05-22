from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.logger import logger
from app.db.init_db import init_db
from app.models.schemas import HealthCheck
import os

# Initialize settings
settings = get_settings()

# Initialize database
init_db()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI-powered job application assistant",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create data directories
os.makedirs("./data/vector_store", exist_ok=True)
os.makedirs("./logs", exist_ok=True)
os.makedirs("./data/uploads", exist_ok=True)


# Health check endpoint
@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    logger.info("Health check called")
    return HealthCheck(status="ok")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "AI Job Application Assistant API",
        "version": "0.1.0",
        "docs": "/docs"
    }


# Import and include API routes
@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.app_name}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database URL: {settings.database_url}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"Shutting down {settings.app_name}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
