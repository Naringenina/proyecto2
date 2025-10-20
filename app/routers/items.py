from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import secrets
import shutil
import io
import csv
from datetime import datetime
import re

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, PlainTextResponse
from starlette import status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, delete

from app.db.session import get_session
from app.models.inventory import (
    InventoryItem,
    Rarity, Condition, Language, ComercialCondition,
    Tag, ItemTag,
)

router = APIRouter(tags=["items"])

MEDIA_ROOT = Path(__file__).resolve().parents[1] / "media"
MEDIA_ITEMS_DIR = MEDIA_ROOT / "items"
MEDIA_THUMBS_DIR = MEDIA_ITEMS_DIR / "_thumbs"


def _normalize_str(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 else None


def _enum_from_value(enum_cls, value: str):
    try:
        return enum_cls(value)
    except Exception:
        return enum_cls[value]


def _find_duplicate_ci(
    session: Session,
    *,
    game: str,
    set_code: Optional[str],
    set_name: str,
    number_set: int,
    language_e: Language,
    condition_e: Condition,
    variant: Optional[str],
) -> Optional[InventoryItem]:
    g = (game or "").strip().lower()
    sc = (set_code or "").strip().lower()
    sn = (set_name or "").strip().lower()
    v = (variant or "").strip().lower()
    stmt = select(InventoryItem).where(
        func.lower(InventoryItem.game) == g,
        func.lower(func.coalesce(InventoryItem.set_code, "")) == sc,
        func.lower(InventoryItem.set_name) == sn,
        InventoryItem.number_set == number_set,
        InventoryItem.language == language_e,
        InventoryItem.condition == condition_e,
        func.lower(func.coalesce(InventoryItem.variant, "")) == v,
    )
    return session.exec(stmt).first()

def _thumb_path_for(original_path: Path) -> Path:
    return MEDIA_THUMBS_DIR / f"{original_path.stem}_thumb{original_path.suffix}"

def _make_thumbnail(src_path: Path, max_px: int = 360) -> bool:
    try:
        from PIL import Image, ImageOps
    except Exception:
        return False

    try:
        MEDIA_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        dst_path = _thumb_path_for(src_path)

        with Image.open(src_path) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_px, max_px))
            save_kwargs = {}
            ext = src_path.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                save_kwargs.update({"quality": 85, "optimize": True, "progressive": True})
            elif ext == ".webp":
                save_kwargs.update({"quality": 80, "method": 6})
            img.save(dst_path, **save_kwargs)

        return True
    except Exception:
        return False

def _delete_thumbnail_for(original_rel: str) -> None:
    try:
        p = Path(original_rel)
        thumb_abs = MEDIA_THUMBS_DIR / f"{p.stem}_thumb{p.suffix}"
        if thumb_abs.exists():
            thumb_abs.unlink()
    except Exception:
        pass

@router.post("/items", name="create_item", response_class=HTMLResponse)
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
    templates = request.app.state.templates
    errors = []

    name = _normalize_str(name)
    game = _normalize_str(game)
    set_name = _normalize_str(set_name)
    set_code = _normalize_str(set_code)
    location = _normalize_str(location)
    variant = _normalize_str(variant)
    notes = _normalize_str(notes)

    if not name:
        errors.append("The name is Required")
    if not game:
        errors.append("The game is Required")
    if not set_name:
        errors.append("The set Required")
    if number_set is None:
        errors.append("the number in set Required")
    if quantity is None or quantity < 0:
        errors.append("The quantity must be a integer ≥ 0.")

    try:
        rarity_e = _enum_from_value(Rarity, rarity)
    except Exception:
        errors.append("Invalid Rarity."); rarity_e = None
    try:
        condition_e = _enum_from_value(Condition, condition)
    except Exception:
        errors.append("Invalid Condition."); condition_e = None
    try:
        language_e = _enum_from_value(Language, language)
    except Exception:
        errors.append("Invalid Language."); language_e = None
    try:
        comercial_condition_e = _enum_from_value(ComercialCondition, comercial_condition)
    except Exception:
        errors.append("Invalid Comercial Condition."); comercial_condition_e = None

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
        return templates.TemplateResponse("items/new.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    existing = _find_duplicate_ci(
        session,
        game=game,
        set_code=set_code,
        set_name=set_name,
        number_set=number_set,
        language_e=language_e,
        condition_e=condition_e,
        variant=variant,
    )
    if existing:
        errors.append("Already exist a card with the same key(duplicated variant).")
        context = {
            "request": request,
            "errors": errors,
            "form": {
                "name": name or "",
                "game": game or "",
                "set_name": set_name or "",
                "set_code": set_code or "",
                "number_set": number_set or 0,
                "rarity": rarity_e.value,
                "condition": condition_e.value,
                "language": language_e.value,
                "quantity": quantity or 0,
                "location": location or "",
                "comercial_condition": comercial_condition_e.value,
                "variant": variant or "",
                "notes": notes or "",
            },
            "existing": existing,
            "rarities": list(Rarity),
            "conditions": list(Condition),
            "languages": list(Language),
            "comercial_conditions": list(ComercialCondition),
        }
        return templates.TemplateResponse("items/new.html", context, status_code=status.HTTP_409_CONFLICT)

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
        existing = _find_duplicate_ci(
            session,
            game=game,
            set_code=set_code,
            set_name=set_name,
            number_set=number_set,
            language_e=language_e,
            condition_e=condition_e,
            variant=variant,
        )
        context = {
            "request": request,
            "errors": ["Already exist a card with the same key(duplicated variant)."],
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
        return templates.TemplateResponse("items/new.html", context, status_code=status.HTTP_409_CONFLICT)

    url = request.url_for("items_page")
    if name:
        url = f"{url}?q={name}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/item/{item_id}/merge-add", name="merge_item_quantity", response_class=HTMLResponse)
def merge_item_quantity(
    request: Request,
    item_id: int,
    add_qty: int = Form(..., ge=0),
    session: Session = Depends(get_session),
):
    if add_qty is None or add_qty < 0:
        return RedirectResponse(
            url=request.url_for("items_page"), status_code=status.HTTP_303_SEE_OTHER
        )

    item = session.get(InventoryItem, item_id)
    if not item:
        return RedirectResponse(
            url=request.url_for("items_page"), status_code=status.HTTP_303_SEE_OTHER
        )

    item.quantity = (item.quantity or 0) + add_qty
    session.add(item)
    session.commit()
    return RedirectResponse(
        url=request.url_for("item_detail_page", item_id=item_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/item/{item_id}/edit", name="update_item", response_class=HTMLResponse)
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
    except Exception: errors.append("Invalid rarity."); rarity_e = None
    try: condition_e = _enum_from_value(Condition, condition)
    except Exception: errors.append("Invalid condition."); condition_e = None
    try: language_e = _enum_from_value(Language, language)
    except Exception: errors.append("Invalid language."); language_e = None
    try: comercial_condition_e = _enum_from_value(ComercialCondition, comercial_condition)
    except Exception: errors.append("Invalid comercial condition."); comercial_condition_e = None

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

    existing = _find_duplicate_ci(
        session,
        game=game, set_code=set_code, set_name=set_name, number_set=number_set,
        language_e=language_e, condition_e=condition_e, variant=variant
    )
    if existing and existing.id != item_id:
        return templates.TemplateResponse(
            "items/edit.html",
            {
                "request": request,
                "item": item,
                "errors": ["Already exist a card with the same key (duplicated variant)."],
                "existing": existing,
                "rarities": list(Rarity),
                "conditions": list(Condition),
                "languages": list(Language),
                "comercial_conditions": list(ComercialCondition),
            },
            status_code=status.HTTP_409_CONFLICT,
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

    session.add(item)
    session.commit()

    return RedirectResponse(
        url=request.url_for("item_detail_page", item_id=item_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/item/{item_id}/delete", name="delete_item", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if item:
        session.exec(delete(ItemTag).where(ItemTag.item_id == item_id))
        if item.image_path:
            try:
                fp = MEDIA_ROOT / item.image_path
                if fp.exists():
                    fp.unlink()
                _delete_thumbnail_for(item.image_path)
            except Exception:
                pass
        session.delete(item)
        session.commit()
    return RedirectResponse(
        url=request.url_for("items_page"),
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/item/{item_id}/image", name="upload_item_image", response_class=HTMLResponse)
def upload_item_image(
    request: Request,
    item_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if not item:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Item not found")),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    ALLOWED = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED:
        return RedirectResponse(
            url=str(request.url_for("item_detail_page", item_id=item_id).include_query_params(err="Unsupported image type")),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    ext = ALLOWED[content_type]
    token = secrets.token_hex(8)
    filename = f"{item_id}_{token}.{ext}"

    MEDIA_ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = MEDIA_ITEMS_DIR / filename

    with dest_path.open("wb") as out_f:
        shutil.copyfileobj(file.file, out_f)

    if item.image_path:
        try:
            old_fp = MEDIA_ROOT / item.image_path
            if old_fp.exists():
                old_fp.unlink()
            _delete_thumbnail_for(item.image_path)
        except Exception:
            pass

    _make_thumbnail(dest_path)

    rel_path = Path("items") / filename
    item.image_path = rel_path.as_posix()
    session.add(item)
    session.commit()

    return RedirectResponse(
        url=str(request.url_for("item_detail_page", item_id=item_id).include_query_params(msg="Image updated")),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/item/{item_id}/image/delete", name="delete_item_image", response_class=HTMLResponse)
def delete_item_image(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if not item:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Item not found")),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if item.image_path:
        try:
            fp = MEDIA_ROOT / item.image_path
            if fp.exists():
                fp.unlink()
            _delete_thumbnail_for(item.image_path)
        except Exception:
            pass
        item.image_path = None
        session.add(item)
        session.commit()

    return RedirectResponse(
        url=str(request.url_for("item_detail_page", item_id=item_id).include_query_params(msg="Image removed")),
        status_code=status.HTTP_303_SEE_OTHER,
    )

_FIELD_SYNONYMS: Dict[str, List[str]] = {
    "name": ["name", "card_name", "nombre"],
    "game": ["game", "juego"],
    "set_name": ["set_name", "set", "collection", "coleccion", "colección"],
    "set_code": ["set_code", "code", "setcode", "codigo_set", "código_set"],
    "number_set": ["number_set", "set_number", "number", "no", "número"],
    "rarity": ["rarity", "rareza"],
    "condition": ["condition", "estado"],
    "language": ["language", "lang", "idioma"],
    "quantity": ["quantity", "qty", "cantidad", "stock"],
    "location": ["location", "ubicacion", "ubicación", "where"],
    "comercial_condition": ["comercial_condition", "status", "estado_comercial", "commercial_status"],
    "variant": ["variant", "variante", "finish", "foil"],
    "notes": ["notes", "nota", "observaciones", "comments"],
    "tags": ["tags", "etiquetas", "labels"],
}


def _index_for(field: str, headers: List[str]) -> Optional[int]:
    want = field.lower()
    for i, h in enumerate(headers):
        hl = (h or "").strip().lower()
        if not hl:
            continue
        if hl == want:
            return i
    for syn in _FIELD_SYNONYMS.get(field, []):
        for i, h in enumerate(headers):
            if (h or "").strip().lower() == syn:
                return i
    return None


def _decode_upload(upload: UploadFile) -> Tuple[str, str]:
    raw = upload.file.read()
    text = None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        delim = dialect.delimiter
    except Exception:
        delim = ","
    return text, delim


def _split_tags(value: str) -> List[str]:
    if not value:
        return []
    parts = re.split(r"[;,]", value)
    return [p.strip() for p in parts if p.strip()]


def _apply_items_filters_from_query(
    stmt,
    *,
    q: Optional[str],
    game: Optional[str],
    set_name: Optional[str],
    rarity: Optional[str],
    condition: Optional[str],
    language: Optional[str],
    comercial_condition: Optional[str],
    number_set: Optional[int],
    quantity_min: Optional[int],
    quantity_max: Optional[int],
    tag: Optional[str],
):
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

    if number_set is not None:
        filters.append(InventoryItem.number_set == number_set)
    if quantity_min is not None:
        filters.append(InventoryItem.quantity >= quantity_min)
    if quantity_max is not None:
        filters.append(InventoryItem.quantity <= quantity_max)

    if tag:
        stmt = stmt.join(InventoryItem.tags).where(Tag.name == tag)

    for f in filters:
        stmt = stmt.where(f)
    return stmt

@router.get("/export/csv", name="export_csv")
def export_csv(
    request: Request,
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    game: Optional[str] = Query(default=None),
    set_name: Optional[str] = Query(default=None),
    rarity: Optional[str] = Query(default=None),
    condition: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    comercial_condition: Optional[str] = Query(default=None),
    number_set: Optional[int] = Query(default=None),
    quantity_min: Optional[int] = Query(default=None),
    quantity_max: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
):
    stmt = select(InventoryItem).options(selectinload(InventoryItem.tags))
    stmt = _apply_items_filters_from_query(
        stmt,
        q=q, game=game, set_name=set_name, rarity=rarity, condition=condition,
        language=language, comercial_condition=comercial_condition,
        number_set=number_set, quantity_min=quantity_min, quantity_max=quantity_max,
        tag=tag,
    ).order_by(InventoryItem.name.asc(), InventoryItem.set_name.asc(), InventoryItem.number_set.asc())

    rows: List[InventoryItem] = session.exec(stmt).all()

    def _gen():
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        header = [
            "name", "game", "set_name", "set_code", "number_set",
            "rarity", "condition", "language",
            "quantity", "location", "comercial_condition",
            "variant", "notes", "tags", "image_path",
        ]
        writer.writerow(header)
        yield out.getvalue()
        out.seek(0); out.truncate(0)

        for it in rows:
            tags_txt = ", ".join([t.name for t in it.tags]) if getattr(it, "tags", None) else ""
            writer.writerow([
                it.name,
                it.game,
                it.set_name,
                it.set_code or "",
                it.number_set,
                it.rarity.value,
                it.condition.value,
                it.language.value,
                it.quantity,
                it.location or "",
                it.comercial_condition.value,
                it.variant or "",
                it.notes or "",
                tags_txt,
                it.image_path or "",
            ])
            yield out.getvalue()
            out.seek(0); out.truncate(0)

    filename = f"cards_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/export/sample", name="export_sample_csv")
def export_sample_csv():
    sample = io.StringIO(newline="")
    w = csv.writer(sample)
    w.writerow([
        "name","game","set_name","set_code","number_set",
        "rarity","condition","language",
        "quantity","location","comercial_condition",
        "variant","notes","tags"
    ])
    w.writerow([
        "Pikachu","Pokemon","Base Set","BS",25,
        "Common","NM","EN",
        2,"Binder A-1","Collection",
        "Holo","First edition","electric, mascot"
    ])
    data = sample.getvalue()
    return PlainTextResponse(
        data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cards_sample.csv"'}
    )

@router.post("/import/csv", name="import_csv", response_class=HTMLResponse)
def import_csv(
    request: Request,
    file: UploadFile = File(...),
    dup_policy: str = Form("merge"),
    create_missing_tags: bool = Form(True),
    session: Session = Depends(get_session),
):
    templates = request.app.state.templates
    text, delim = _decode_upload(file)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    try:
        headers = next(reader)
    except StopIteration:
        return templates.TemplateResponse(
            "import.html",
            {"request": request, "err": "Empty CSV file.", "result": None},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    headers_norm = [(h or "").strip() for h in headers]
    idx: Dict[str, Optional[int]] = {f: _index_for(f, headers_norm) for f in _FIELD_SYNONYMS.keys()}

    required = ["name", "game", "set_name", "number_set", "rarity", "condition", "language"]
    missing = [f for f in required if idx.get(f) is None]
    if missing:
        return templates.TemplateResponse(
            "import.html",
            {
                "request": request,
                "err": f"Missing required columns: {', '.join(missing)}",
                "result": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    created = 0
    updated = 0
    skipped = 0
    errors: List[str] = []

    line_no = 1
    for row in reader:
        line_no += 1
        def get(field: str) -> Optional[str]:
            i = idx.get(field)
            if i is None or i >= len(row):
                return None
            val = row[i]
            return (val if val is not None else "").strip()

        try:
            name = _normalize_str(get("name"))
            game = _normalize_str(get("game"))
            set_name = _normalize_str(get("set_name"))
            set_code = _normalize_str(get("set_code"))
            number_set_str = get("number_set")
            rarity_s = get("rarity") or ""
            condition_s = get("condition") or ""
            language_s = get("language") or ""
            quantity_str = get("quantity")
            location = _normalize_str(get("location"))
            comercial_condition_s = get("comercial_condition") or ComercialCondition.COLLECTION.value
            variant = _normalize_str(get("variant"))
            notes = _normalize_str(get("notes"))
            tags_s = get("tags")

            if not all([name, game, set_name, number_set_str, rarity_s, condition_s, language_s]):
                skipped += 1
                errors.append(f"Line {line_no}: missing required values.")
                continue

            try:
                number_set = int(number_set_str)
            except ValueError:
                skipped += 1
                errors.append(f"Line {line_no}: number_set must be integer.")
                continue

            try:
                rarity_e = _enum_from_value(Rarity, rarity_s)
                condition_e = _enum_from_value(Condition, condition_s)
                language_e = _enum_from_value(Language, language_s)
                comercial_e = _enum_from_value(ComercialCondition, comercial_condition_s)
            except Exception:
                skipped += 1
                errors.append(f"Line {line_no}: invalid enum in rarity/condition/language/comercial_condition.")
                continue

            quantity = 0
            if quantity_str not in (None, ""):
                try:
                    quantity = int(quantity_str)
                    if quantity < 0:
                        raise ValueError()
                except ValueError:
                    skipped += 1
                    errors.append(f"Line {line_no}: quantity must be integer ≥ 0.")
                    continue

            existing = _find_duplicate_ci(
                session,
                game=game,
                set_code=set_code,
                set_name=set_name,
                number_set=number_set,
                language_e=language_e,
                condition_e=condition_e,
                variant=variant,
            )

            if existing:
                if dup_policy == "skip":
                    skipped += 1
                    continue
                elif dup_policy == "merge":
                    existing.quantity = (existing.quantity or 0) + quantity
                    session.add(existing)
                    session.commit()
                    item = existing
                    updated += 1
                else:
                    existing.name = name
                    existing.game = game
                    existing.set_name = set_name
                    existing.set_code = set_code
                    existing.number_set = number_set
                    existing.rarity = rarity_e
                    existing.condition = condition_e
                    existing.language = language_e
                    existing.quantity = quantity
                    existing.location = location
                    existing.comercial_condition = comercial_e
                    existing.variant = variant
                    existing.notes = notes
                    session.add(existing)
                    session.commit()
                    item = existing
                    updated += 1
            else:
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
                    comercial_condition=comercial_e,
                    variant=variant,
                    notes=notes,
                )
                session.add(item)
                session.commit()
                created += 1

            if tags_s:
                tag_names = _split_tags(tags_s)
                for tname in tag_names:
                    tag = session.exec(select(Tag).where(Tag.name == tname)).first()
                    if not tag:
                        if not create_missing_tags:
                            continue
                        tag = Tag(name=tname)
                        session.add(tag)
                        session.commit()
                        session.refresh(tag)
                    exists_link = session.exec(
                        select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id == tag.id)
                    ).first()
                    if not exists_link:
                        link = ItemTag(item_id=item.id, tag_id=tag.id)
                        session.add(link)
                        session.commit()

        except Exception as e:
            skipped += 1
            errors.append(f"Line {line_no}: unexpected error: {e!r}")

    result = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "delimiter": delim,
        "total_rows": created + updated + skipped,
    }
    return templates.TemplateResponse("import.html", {"request": request, "err": None, "result": result})

def _safe_redirect(return_to: Optional[str], request: Request) -> str:
    try:
        if return_to and return_to.startswith(str(request.base_url).rstrip("/")):
            return return_to
    except Exception:
        pass
    return str(request.url_for("items_page"))

@router.post("/items/bulk/adjust-qty", name="bulk_adjust_qty", response_class=HTMLResponse)
def bulk_adjust_qty(
    request: Request,
    ids: Optional[List[int]] = Form(None),
    delta: Optional[int] = Form(None),
    return_to: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not ids:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="No items selected")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if delta is None:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Missing delta")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    stmt = select(InventoryItem).where(InventoryItem.id.in_(ids))
    items = session.exec(stmt).all()
    for it in items:
        new_q = (it.quantity or 0) + delta
        it.quantity = max(0, new_q)
        session.add(it)
    session.commit()
    dest = _safe_redirect(return_to, request)
    return RedirectResponse(
        url=str(dest) + ("&" if "?" in dest else "?") + "msg=Quantities updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/items/bulk/set-status", name="bulk_set_status", response_class=HTMLResponse)
def bulk_set_status(
    request: Request,
    ids: Optional[List[int]] = Form(None),
    status_value: Optional[str] = Form(None),
    return_to: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not ids:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="No items selected")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not status_value:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Missing status value")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        status_e = _enum_from_value(ComercialCondition, status_value)
    except Exception:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Invalid status")),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    items = session.exec(select(InventoryItem).where(InventoryItem.id.in_(ids))).all()
    for it in items:
        it.comercial_condition = status_e
        session.add(it)
    session.commit()

    dest = _safe_redirect(return_to, request)
    return RedirectResponse(
        url=str(dest) + ("&" if "?" in dest else "?") + "msg=Status updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    
@router.post("/items/bulk/add-tag", name="bulk_add_tag", response_class=HTMLResponse)
def bulk_add_tag(
    request: Request,
    ids: Optional[List[int]] = Form(None),
    tag_name: Optional[str] = Form(None),
    create_missing: Optional[bool] = Form(True),
    return_to: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    tag_name = (tag_name or "").strip()
    if not ids or not tag_name:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Select items and a tag")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
    if not tag:
        if create_missing:
            tag = Tag(name=tag_name)
            session.add(tag)
            session.commit()
            session.refresh(tag)
        else:
            return RedirectResponse(
                url=str(request.url_for("items_page").include_query_params(err="Tag not found")),
                status_code=status.HTTP_303_SEE_OTHER,
            )
    for iid in ids:
        exists_link = session.exec(
            select(ItemTag).where(ItemTag.item_id == iid, ItemTag.tag_id == tag.id)
        ).first()
        if not exists_link:
            session.add(ItemTag(item_id=iid, tag_id=tag.id))
    session.commit()

    dest = _safe_redirect(return_to, request)
    return RedirectResponse(
        url=str(dest) + ("&" if "?" in dest else "?") + f"msg=Tag '{tag_name}' attached",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    
@router.post("/items/bulk/remove-tag", name="bulk_remove_tag", response_class=HTMLResponse)
def bulk_remove_tag(
    request: Request,
    ids: Optional[List[int]] = Form(None),
    tag_name: Optional[str] = Form(None),
    return_to: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    tag_name = (tag_name or "").strip()
    if not ids or not tag_name:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="Select items and a tag")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
    if tag:
        session.exec(delete(ItemTag).where(ItemTag.item_id.in_(ids), ItemTag.tag_id == tag.id))
        session.commit()

    dest = _safe_redirect(return_to, request)
    return RedirectResponse(
        url=str(dest) + ("&" if "?" in dest else "?") + f"msg=Tag '{tag_name}' removed",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/items/bulk-delete", name="bulk_delete", response_class=HTMLResponse)
def bulk_delete(
    request: Request,
    ids: Optional[List[int]] = Form(None),
    return_to: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not ids:
        return RedirectResponse(
            url=str(request.url_for("items_page").include_query_params(err="No items selected")),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    items = session.exec(select(InventoryItem).where(InventoryItem.id.in_(ids))).all()
    for it in items:
        session.exec(delete(ItemTag).where(ItemTag.item_id == it.id))
        if it.image_path:
            try:
                fp = MEDIA_ROOT / it.image_path
                if fp.exists():
                    fp.unlink()
                _delete_thumbnail_for(it.image_path)
            except Exception:
                pass
        session.delete(it)
    session.commit()

    dest = _safe_redirect(return_to, request)
    return RedirectResponse(
        url=str(dest) + ("&" if "?" in dest else "?") + "msg=Items deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )