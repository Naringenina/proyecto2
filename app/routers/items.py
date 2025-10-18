from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.inventory import (
    InventoryItem,
    Rarity, Condition, Language, ComercialCondition
)

router = APIRouter()


def _normalize_str(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 else None


def _enum_from_value(enum_cls, value: str):
    """
    Accepts both the .value and .name of the Enum (robust in forms).
    """
    try:
        return enum_cls(value)          
    except ValueError:
        return enum_cls[value]          


@router.post("/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    name: str = Form(...),
    game: str = Form(...),
    set_name: str = Form(...),
    number_set: int = Form(...),
    rarity: str = Form(...),
    condition: str = Form(...),
    language: str = Form(...),
    quantity: int = Form(...),
    set_code: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    comercial_condition: str = Form(ComercialCondition.COLLECTION.value),
    variant: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """
    Create an InventoryItem with basic validations and handle duplicates
    (UniqueConstraint) returning the form with errors if applicable.
    """
    errors = []

    name = _normalize_str(name)
    game = _normalize_str(game)
    set_name = _normalize_str(set_name)
    set_code = _normalize_str(set_code)
    location = _normalize_str(location)
    variant = _normalize_str(variant)
    notes = _normalize_str(notes)

    if not name:
        errors.append("The name is required.")
    if not game:
        errors.append("The game is required.")
    if not set_name:
        errors.append("The set is required.")
    if number_set is None:
        errors.append("The number in set is required.")
    if quantity is None or quantity < 0:
        errors.append("The quantity must be a integer > 0")

    try:
        rarity_e = _enum_from_value(Rarity, rarity)
    except Exception:
        errors.append("Invalid Rarity.")
        rarity_e = None
    try:
        condition_e = _enum_from_value(Condition, condition)
    except Exception:
        errors.append("Invalid Condition.")
        condition_e = None
    try:
        language_e = _enum_from_value(Language, language)
    except Exception:
        errors.append("Invalid Language.")
        language_e = None
    try:
        comercial_condition_e = _enum_from_value(ComercialCondition, comercial_condition)
    except Exception:
        errors.append("Invalid Comercial Condition.")
        comercial_condition_e = None

    if errors:
        context: Dict[str, Any] = {
            "request": request,
            "errors": errors,
            "form": {
                "name": name or "",
                "game": game or "",
                "set_name": set_name or "",
                "set_code": set_code or "",
                "number_set": number_set or 0,
                "rarity": rarity,
                "condition": condition,
                "language": language,
                "quantity": quantity or 0,
                "location": location or "",
                "comercial_condition": comercial_condition,
                "variant": variant or "",
                "notes": notes or "",
            },
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        }
        return request.app.state.templates.TemplateResponse(
            "items/new.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )

    item = InventoryItem(
        name=name,
        game=game,
        set_name=set_name,
        set_code=set_code,
        number_set=number_set,
        rarity=rarity_e,
        condition=condition_e,
        language=language_e,
        quantity=quantity,
        location=location,
        comercial_condition=comercial_condition_e,
        variant=variant,
        notes=notes,
    )
    try:
        session.add(item)
        session.commit()
    except IntegrityError:
        session.rollback()
        conds = [
            InventoryItem.game == game,
            InventoryItem.set_code == set_code,
            InventoryItem.set_name == set_name,
            InventoryItem.number_set == number_set,
            InventoryItem.language == language_e,
            InventoryItem.condition == condition_e,
            InventoryItem.variant == variant,
        ]
        existing = session.exec(select(InventoryItem).where(and_(*conds))).first()

        errors.append("There is already a card with the same key (duplicate variant).")
        context = {
            "request": request,
            "errors": errors,
            "form": {
                "name": name or "",
                "game": game or "",
                "set_name": set_name or "",
                "set_code": set_code or "",
                "number_set": number_set or 0,
                "rarity": rarity_e.value if rarity_e else "",
                "condition": condition_e.value if condition_e else "",
                "language": language_e.value if language_e else "",
                "quantity": quantity or 0,
                "location": location or "",
                "comercial_condition": comercial_condition_e.value if comercial_condition_e else "",
                "variant": variant or "",
                "notes": notes or "",
            },
            "existing": existing,
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        }
        return request.app.state.templates.TemplateResponse(
            "items/new.html", context, status_code=status.HTTP_409_CONFLICT
        )

    url = request.url_for("items_page")
    if name:
        url = f"{url}?q={name}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/items/{item_id}/edit", response_class=HTMLResponse)
def update_item(
    request: Request,
    item_id: int,
    name: str = Form(...),
    game: str = Form(...),
    set_name: str = Form(...),
    number_set: int = Form(...),
    rarity: str = Form(...),
    condition: str = Form(...),
    language: str = Form(...),
    quantity: int = Form(...),
    set_code: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    comercial_condition: str = Form(ComercialCondition.COLLECTION.value),
    variant: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    templates = request.app.state.templates
    errors = []

    item = session.get(InventoryItem, item_id)
    if not item:
        return templates.TemplateResponse(
            "items/edit.html",
            {
                "request": request,
                "item": None,
                "errors": ["The item didn't exist."],
                "rarities": list(Rarity),
                "conditions": list(Condition),
                "languages": list(Language),
                "comercial_conditions": list(ComercialCondition),
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    name = _normalize_str(name)
    game = _normalize_str(game)
    set_name = _normalize_str(set_name)
    set_code = _normalize_str(set_code)
    location = _normalize_str(location)
    variant = _normalize_str(variant)
    notes = _normalize_str(notes)

    if not name: errors.append("The name is required.")
    if not game: errors.append("The game is required.")
    if not set_name: errors.append("The set is required.")
    if number_set is None: errors.append("The number set is required.")
    if quantity is None or quantity < 0: errors.append("The quantity must be a integer ≥ 0.")

    try: rarity_e = _enum_from_value(Rarity, rarity)
    except Exception: errors.append("Rareza inválida."); rarity_e = None
    try: condition_e = _enum_from_value(Condition, condition)
    except Exception: errors.append("Condición inválida."); condition_e = None
    try: language_e = _enum_from_value(Language, language)
    except Exception: errors.append("Idioma inválido."); language_e = None
    try: comercial_condition_e = _enum_from_value(ComercialCondition, comercial_condition)
    except Exception: errors.append("Estado comercial inválido."); comercial_condition_e = None

    if errors:
        return templates.TemplateResponse(
            "items/edit.html",
            {
                "request": request,
                "item": item,
                "errors": errors,
                "rarities": list(Rarity),
                "conditions": list(Condition),
                "languages": list(Language),
                "comercial_conditions": list(ComercialCondition),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    item.name = name
    item.game = game
    item.set_name = set_name
    item.set_code = set_code
    item.number_set = number_set
    item.rarity = rarity_e
    item.condition = condition_e
    item.language = language_e
    item.quantity = quantity
    item.location = location
    item.comercial_condition = comercial_condition_e
    item.variant = variant
    item.notes = notes

    try:
        session.add(item)
        session.commit()
    except IntegrityError:
        session.rollback()
        conds = [
            InventoryItem.id != item_id,
            InventoryItem.game == game,
            InventoryItem.set_code == set_code,
            InventoryItem.set_name == set_name,
            InventoryItem.number_set == number_set,
            InventoryItem.language == language_e,
            InventoryItem.condition == condition_e,
            InventoryItem.variant == variant,
        ]
        existing = session.exec(select(InventoryItem).where(and_(*conds))).first()

        return templates.TemplateResponse(
            "items/edit.html",
            {
                "request": request,
                "item": item,
                "errors": ["Already Exist."],
                "existing": existing,
                "rarities": list(Rarity),
                "conditions": list(Condition),
                "languages": list(Language),
                "comercial_conditions": list(ComercialCondition),
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    return RedirectResponse(
        url=request.url_for("item_detail_page", item_id=item_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if item:
        session.delete(item)
        session.commit()
    return RedirectResponse(
        url=request.url_for("items_page"),
        status_code=status.HTTP_303_SEE_OTHER,
    )