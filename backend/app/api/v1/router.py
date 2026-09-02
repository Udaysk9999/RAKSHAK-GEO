"""Aggregator for API v1 routes."""
from fastapi import APIRouter
from app.api.v1.endpoints import optimization, what_if, timeline

api_router = APIRouter()
api_router.include_router(optimization.router)
api_router.include_router(what_if.router)
api_router.include_router(timeline.router)
