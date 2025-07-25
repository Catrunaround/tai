import logging

# Import model pipeline initializer
from app.dependencies.model import initialize_model_engine

initialize_model_engine()
print("✅ Model pipeline initialization completed successfully!")

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from app.admin import setup_admin
from app.api.router import api_router
from app.config import settings  # Import the configuration
from app.core.dbs.course_db import Base, engine

# Import the new database initializer
from app.core.dbs.db_initializer import initialize_database_on_startup

# Import to ensure table creation

# from app.core.actions.model_selector import get_model


logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] {%(filename)s:%(funcName)s:%(lineno)d} %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs.log"), logging.StreamHandler()],
)

# Initialize database with automatic file import and migration
print("🚀 Initializing database and importing existing files...")

if not initialize_database_on_startup():
    print("❌ Database initialization failed! Server may not work correctly.")
    print("💡 Check the logs above for details, or run database scripts manually.")
else:
    print("✅ Database initialization completed successfully!")

# Fallback table creation (in case the initializer doesn't work)
Base.metadata.create_all(bind=engine)

# Initialize model pipeline once at startup
print("\n🤖 Initializing AI model pipeline...")
# try:
#     initialize_model_engine()
#     print("✅ Model pipeline initialization completed successfully!")
# except Exception as e:
#     print(f"❌ Model pipeline initialization failed: {e}")
#     print("💡 The server will start but model-dependent endpoints may not work.")

# File categories are now simplified and handled automatically

app = FastAPI(
    title="Course AI Assistant API",
    description="API for interacting with the course AI assistant and file management",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add CORS middleware to allow the frontend to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with your frontend origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Setup the admin interface
setup_admin(app)

# Include consolidated API router
app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/home")


@app.get("/home", response_class=HTMLResponse)
async def home():
    return """
    <html>
        <head>
            <title>Course AI Assistant API</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
                h1 { color: #333; }
                h2 { color: #666; margin-top: 30px; }
                .links { margin-top: 20px; }
                .links a { display: block; margin-bottom: 10px; color: #0066cc; text-decoration: none; }
                .links a:hover { text-decoration: underline; }
                .auth-section { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <h1>Course AI Assistant API</h1>
            <p>Welcome to the Course AI Assistant API. Use the links below to explore the API.</p>

            <h2>API Documentation</h2>
            <div class="links">
                <a href="/docs">API Documentation (Swagger UI)</a>
                <a href="/redoc">API Documentation (ReDoc)</a>
            </div>

            <h2>Testing Tools</h2>
            <div class="links">
                <a href="/course-config">Course Configuration</a>
                <a href="/database-status">Database Status</a>
                <a href="/health">Health Check</a>
            </div>
        </body>
    </html>
    """
  
@app.get("/course-config", response_class=HTMLResponse)
async def course_config():
    """
    Admin interface for course configuration and management
    """
    return RedirectResponse(url="admin/course-model/list")


@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "ok", "version": app.version}


@app.get("/database-status")
async def database_status():
    """
    Database status endpoint - shows database initialization status
    """
    from app.core.dbs.db_initializer import get_initializer

    try:
        initializer = get_initializer()
        status = initializer.get_database_status()

        return {
            "status": "ok",
            "database": status,
            "message": "Database status retrieved successfully",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to get database status",
        }


if __name__ == "__main__":
    # Use settings from .env file configuration
    print("🚀 Starting server...")
    print(f"📍 Environment: {settings.environment}")
    print(
        f"🔄 Auto-reload: {'disabled' if settings.is_production or not settings.RELOAD else 'enabled'}"
    )
    print(f"🌐 Host: {settings.HOST}:{settings.PORT}")
    print(f"🤖 LLM Mode: {settings.effective_llm_mode}")
    print(f"📁 Data Directory: {settings.DATA_DIR}")

    # Determine reload setting: disabled in production or based on RELOAD setting
    reload_enabled = not settings.is_production and settings.RELOAD

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload_enabled,
        reload_excludes=["*.log", "*.log.*", "*.log.*.*", "*.log.*.*.*"],
    )
