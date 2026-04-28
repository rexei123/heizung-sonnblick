"""Aggregator fuer alle v1-Router."""

from fastapi import APIRouter

from heizung.api.v1.devices import router as devices_router

router = APIRouter(prefix="/api/v1")
router.include_router(devices_router)

__all__ = ["router"]
