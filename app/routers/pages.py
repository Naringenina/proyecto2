from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query

from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.inventory import (
    InventoryItem, Rarity, Condition, Language, ComercialCondition, Tag, ItemTag
)

router = APIRouter(tags=["pages"])

def _enum_opt(enum_cls, value: Optional[str]):
    if not value:
        return None
    try:
        return enum_cls(value)
    except Exception:
        try:
            return enum_cls[value]
        except Exception:
            return None

def _to_int_or_none(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None


@router.get("/items", name="items_page", response_class=HTMLResponse)
def items_page(
    request: Request,
    q: Optional[str] = Query(default=None, min_length=1),
    tag: Optional[str] = Query(default=None),

    game: Optional[str] = Query(default=None),
    set_name: Optional[str] = Query(default=None),
    rarity: Optional[str] = Query(default=None),
    condition: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    comercial_condition: Optional[str] = Query(default=None),

    number_set: Optional[str] = Query(default=None),
    quantity_min: Optional[str] = Query(default=None),
    quantity_max: Optional[str] = Query(default=None),

    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=5, le=100),
    msg: Optional[str] = Query(default=None),
    err: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    templates = request.app.state.templates

    filters = []
    if q:
        term = f"%{q.strip().lower()}%"
        filters.append(or_(
            func.lower(InventoryItem.name).like(term),
            func.lower(InventoryItem.set_name).like(term),
            func.lower(InventoryItem.game).like(term),
            func.lower(InventoryItem.variant).like(term),
            func.lower(InventoryItem.notes).like(term),
        ))

    if game:
        g = f"%{game.strip().lower()}%"
        filters.append(func.lower(InventoryItem.game).like(g))
    if set_name:
        s = f"%{set_name.strip().lower()}%"
        filters.append(func.lower(InventoryItem.set_name).like(s))

    rarity_e = _enum_opt(Rarity, rarity)
    condition_e = _enum_opt(Condition, condition)
    language_e = _enum_opt(Language, language)
    comercial_condition_e = _enum_opt(ComercialCondition, comercial_condition)

    if rarity_e:
        filters.append(InventoryItem.rarity == rarity_e)
    if condition_e:
        filters.append(InventoryItem.condition == condition_e)
    if language_e:
        filters.append(InventoryItem.language == language_e)
    if comercial_condition_e:
        filters.append(InventoryItem.comercial_condition == comercial_condition_e)

    number_set_i = _to_int_or_none(number_set)
    quantity_min_i = _to_int_or_none(quantity_min)
    quantity_max_i = _to_int_or_none(quantity_max)

    if number_set_i is not None:
        filters.append(InventoryItem.number_set == number_set_i)
    if quantity_min_i is not None:
        filters.append(InventoryItem.quantity >= quantity_min_i)
    if quantity_max_i is not None:
        filters.append(InventoryItem.quantity <= quantity_max_i)

    base = select(InventoryItem)
    count_sel = select(func.count(func.distinct(InventoryItem.id))).select_from(InventoryItem)

    if tag:
        base = base.join(InventoryItem.tags).where(Tag.name == tag)
        count_sel = count_sel.join(InventoryItem.tags).where(Tag.name == tag)

    for f in filters:
        base = base.where(f)
        count_sel = count_sel.where(f)

    total = session.scalar(count_sel) or 0

    SORT_MAP = {
        "name": InventoryItem.name,
        "set_name": InventoryItem.set_name,
        "game": InventoryItem.game,
        "quantity": InventoryItem.quantity,
        "number_set": InventoryItem.number_set,
        "rarity": InventoryItem.rarity,
        "condition": InventoryItem.condition,
        "language": InventoryItem.language,
    }
    col = SORT_MAP.get(sort_by, InventoryItem.name)
    order = col.asc() if sort_dir.lower() != "desc" else col.desc()

    total_pages = max(1, (total + size - 1) // size)
    if page > total_pages:
        page = total_pages

    stmt = (
        base.order_by(order, InventoryItem.id.asc())
            .offset((page - 1) * size)
            .limit(size)
    )
    items = session.exec(stmt).all()

    display_from = 0 if total == 0 else (page - 1) * size + 1
    display_to = min(total, page * size)

    all_tags = session.exec(select(Tag).order_by(Tag.name.asc())).all()

    return templates.TemplateResponse(
        "items/list.html",
        {
            "request": request,
            "items": items,

            "q": q or "",
            "tag": tag or "",
            "game": game or "",
            "set_name": set_name or "",
            "rarity": rarity or "",
            "condition": condition or "",
            "language": language or "",
            "comercial_conditions": list(ComercialCondition),
            "number_set": number_set_i,
            "quantity_min": quantity_min_i,
            "quantity_max": quantity_max_i,
            "msg": msg,
            "err": err,
            "sort_by": sort_by,
            "sort_dir": "desc" if sort_dir.lower() == "desc" else "asc",

            "page": page,
            "size": size,
            "total": total,
            "total_pages": total_pages,
            "display_from": display_from,
            "display_to": display_to,

            "all_tags": all_tags,
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        },
    )


@router.get("/items/new", name="new_item_page", response_class=HTMLResponse)
def new_item_page(request: Request):
    templates = request.app.state.templates
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

@router.get("/item/{item_id}", name="item_detail_page", response_class=HTMLResponse)
def item_detail_page(request: Request, item_id: int, session: Session = Depends(get_session)):
    templates = request.app.state.templates
    item = session.exec(
        select(InventoryItem)
        .options(selectinload(InventoryItem.tags))
        .where(InventoryItem.id == item_id)
    ).first()
    if not item:
        return templates.TemplateResponse(
            "items/detail.html",
            {"request": request, "item": None},
            status_code=404,
        )
    return templates.TemplateResponse("items/detail.html", {"request": request, "item": item})

@router.get("/item/{item_id}/edit", name="edit_item_page", response_class=HTMLResponse)
def edit_item_page(request: Request, item_id: int, session: Session = Depends(get_session)):
    templates = request.app.state.templates
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

@router.get("/tags", name="tags_page", response_class=HTMLResponse)
def tags_page(request: Request, msg: Optional[str] = Query(default=None), err: Optional[str] = Query(default=None), session: Session = Depends(get_session)):
    templates = request.app.state.templates
    rows = session.exec(
        select(Tag, func.count(ItemTag.item_id))
        .select_from(Tag)
        .join(ItemTag, Tag.id == ItemTag.tag_id, isouter=True)
        .group_by(Tag.id)
        .order_by(Tag.name.asc())
    ).all()
    tags = [{"tag": r[0], "count": int(r[1])} for r in rows]

    return templates.TemplateResponse("tags.html", {"request": request, "tags": tags, "msg": msg, "err": err})

@router.get("/import", name="import_page", response_class=HTMLResponse)
def import_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("import.html", {"request": request})

@router.get("/export", name="export_page", response_class=HTMLResponse)
def export_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("export.html", {"request": request})