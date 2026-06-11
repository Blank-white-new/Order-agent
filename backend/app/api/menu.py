from __future__ import annotations

from fastapi import APIRouter

from app.services.menu_service import MenuService


router = APIRouter()
menu_service = MenuService()


@router.get("/menu")
def get_menu() -> dict:
    return {"items": menu_service.all_items_as_dicts(), "categories": menu_service.get_all_categories()}

