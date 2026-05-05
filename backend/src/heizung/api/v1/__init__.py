"""Aggregator fuer alle v1-Router."""

from fastapi import APIRouter

from heizung.api.v1.devices import router as devices_router
from heizung.api.v1.global_config import router as global_config_router
from heizung.api.v1.heating_zones import router as heating_zones_router
from heizung.api.v1.occupancies import router as occupancies_router
from heizung.api.v1.room_types import router as room_types_router
from heizung.api.v1.rooms import router as rooms_router

router = APIRouter(prefix="/api/v1")
router.include_router(devices_router)
router.include_router(room_types_router)
router.include_router(rooms_router)
router.include_router(heating_zones_router)
router.include_router(occupancies_router)
router.include_router(global_config_router)

__all__ = ["router"]
