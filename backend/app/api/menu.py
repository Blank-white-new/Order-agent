from __future__ import annotations

from fastapi import APIRouter, Header, Query

from app.runtime import database
from app.services.menu_service import MenuService


router = APIRouter()
@router.get("/menu")
def get_menu(
    restaurant_id: str | None = Query(default=None, alias="restaurantId"),
    branch_id: str | None = Query(default=None, alias="branchId"),
    restaurant_header: str | None = Header(default=None, alias="X-Restaurant-Id"),
    branch_header: str | None = Header(default=None, alias="X-Branch-Id"),
) -> dict:
    restaurant_code = restaurant_id or restaurant_header
    branch_code = branch_id or branch_header
    menu_service = MenuService(
        restaurant_code=restaurant_code,
        branch_code=branch_code,
        database=database,
    )
    menu_service.refresh()
    return {"items": menu_service.all_items_as_dicts(), "categories": menu_service.get_all_categories()}

