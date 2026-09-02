"""Tests for FastAPI endpoints and health checks."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    """Verify backend health endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "CITYSHIELD GIS" in data["app"]


def test_optimization_status_endpoint():
    """Verify T-014 optimization status endpoint."""
    response = client.get("/api/v1/optimization/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert data["algorithm_implemented"] is True
    assert "T-014" in data["module"]
    assert len(data["supported_objectives"]) > 0


def test_optimization_sample_payload():
    """Verify demo sample payload conforms to request schema."""
    response = client.get("/api/v1/optimization/sample-payload")
    assert response.status_code == 200
    data = response.json()
    assert "incident_id" in data
    assert "available_resources" in data
    assert "zones" in data
    assert len(data["zones"]) >= 1


def test_optimization_allocate_endpoint():
    """Verify allocation endpoint validates and executes properly."""
    sample_response = client.get("/api/v1/optimization/sample-payload")
    payload = sample_response.json()

    response = client.post("/api/v1/optimization/allocate", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] in ("OPTIMAL", "FEASIBLE_SHORTAGE")
    assert result["is_demo_data"] is True
    assert len(result["allocations"]) == len(payload["zones"])
    assert result["total_allocated"]["ambulances"] > 0
