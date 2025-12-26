
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.middleware.error_handler import AppError

client = TestClient(app, raise_server_exceptions=False)

def test_health_check_resilience():
    """Test standard health check works with middleware."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_404_handling():
    """Test 404 handling."""
    response = client.get("/api/non-existent-route")
    assert response.status_code == 404
    # Starlette default 404 might not go through our global exception handler for Exception/AppError 
    # unless we override 404 specifically, but let's check what we get.
    # Actually, default 404 is handled by FastAPI default exception handlers if not overridden.
    # Our global handler handles Exception, AppError, StarletteHTTPException.
    # 404 is a StarletteHTTPException.
    assert response.json()["error"] is True
    assert response.json()["message"] == "Not Found"


from fastapi import APIRouter, Depends
from slowapi import Limiter
from slowapi.util import get_remote_address

def test_exception_handling_flow():
    """Test that exceptions are caught and formatted correctly."""
    # Create a router that raises errors
    router = APIRouter()
    
    @router.get("/test/error")
    def raise_error():
        raise AppError("Custom Error", status_code=400, details={"foo": "bar"})

    @router.get("/test/value_error")
    def raise_value_error():
        raise ValueError("Unexpected value error")
        
    app.include_router(router)
    
    # Test AppError
    response = client.get("/test/error")
    assert response.status_code == 400
    data = response.json()
    assert data["error"] is True
    assert data["message"] == "Custom Error"
    assert data["details"] == {"foo": "bar"}

    # Test Unexpected Error
    response = client.get("/test/value_error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] is True
    assert data["message"] == "Internal Server Error"

def test_rate_limiting_flow():
    """Test rate limiting works."""
    # Access the limiter from app state
    limiter = app.state.limiter
    
    router = APIRouter()
    
    @router.get("/test/limited")
    @limiter.limit("5/minute")
    def limited_route(request: Request):
        return {"status": "ok"}
        
    app.include_router(router)
    
    # First 5 requests should succeed
    for _ in range(5):
        response = client.get("/test/limited")
        assert response.status_code == 200
        
    # 6th request should fail
    response = client.get("/test/limited")
    assert response.status_code == 429
    data = response.json()
    assert "error" in data # Starlette default 429 handler might differ, let's check our override 
    # Wait, we registered rate_limit_exceeded_handler which returns _rate_limit_exceeded_handler
    # The default _rate_limit_exceeded_handler returns PlainTextResponse/JSONResponse keys 'error'
    # Actually slowapi default handler returns JSON with "error" key.
    
from starlette.requests import Request

