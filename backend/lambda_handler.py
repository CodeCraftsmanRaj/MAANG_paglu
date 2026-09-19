"""AWS Lambda Handler for ContextForge using Mangum."""
from mangum import Mangum
from app.api import app

# Mangum adapter bridges API Gateway / ALB events to the FastAPI ASGI application
handler = Mangum(app, lifespan="off")
