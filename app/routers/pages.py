from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.inventory import (
    InventoryItem, Rarity, Condition, Language, ComercialCondition
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/items", response_class=HTMLResponse)
def items_page(
    request: Request,
    q: Optional[str] = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=5, le=100),
    session: Session = Depends(get_session),
):
    """
    List of cards with text search and pagination.
    - Search in: name, set_name, game, variant, notes (case-insensitive).
    - Order: name ASC, set_name ASC (stable for pagination).
    """
    filters = None
    if q:
        term = f"%{q.strip().lower()}%"
        filters = or_(
            func.lower(InventoryItem.name).like(term),
            func.lower(InventoryItem.set_name).like(term),
            func.lower(InventoryItem.game).like(term),
            func.lower(InventoryItem.variant).like(term),
            func.lower(InventoryItem.notes).like(term),
        )

    count_stmt = select(func.count()).select_from(InventoryItem)
    if filters is not None:
        count_stmt = count_stmt.where(filters)
    total: int = session.scalar(count_stmt)

    total_pages = max(1, (total + size - 1) // size)
    if page > total_pages:
        page = total_pages

    stmt = select(InventoryItem)
    if filters is not None:
        stmt = stmt.where(filters)

    stmt = (
        stmt.order_by(InventoryItem.name.asc(), InventoryItem.set_name.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = session.exec(stmt).all()

    display_from = 0 if total == 0 else (page - 1) * size + 1
    display_to = min(total, page * size)

    return templates.TemplateResponse(
        "items/list.html",
        {
            "request": request,
            "items": items,
            "q": q or "",
            "page": page,
            "size": size,
            "total": total,
            "total_pages": total_pages,
            "display_from": display_from,
            "display_to": display_to,
        },
    )
##########################################
@router.get("/items/new", response_class=HTMLResponse)
def new_item_page(request: Request):
    return templates.TemplateResponse(
        "items/new.html",
        {
            "request": request,
            "errors": [],
            "form": {},
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        },
    )

@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail_page(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if not item:
        return templates.TemplateResponse(
            "items/detail.html",
            {"request": request, "item": None},
            status_code=404,
        )
    return templates.TemplateResponse(
        "items/detail.html",
        {"request": request, "item": item},
    )

@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
def edit_item_page(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if not item:
        return templates.TemplateResponse(
            "items/edit.html",
            {
                "request": request,
                "item": None,
                "errors": ["The item didn't exits."],
                "rarities": list(Rarity),
                "conditions": list(Condition),
                "languages": list(Language),
                "comercial_conditions": list(ComercialCondition),
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "items/edit.html",
        {
            "request": request,
            "item": item,
            "errors": [],
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        },
    )


@router.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request):
    return templates.TemplateResponse("tags.html", {"request": request})


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})


@router.get("/export", response_class=HTMLResponse)
def export_page(request: Request):
    return templates.TemplateResponse("export.html", {"request": request})