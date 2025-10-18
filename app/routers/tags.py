from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette import status
from sqlmodel import Session, select, delete, col
from sqlalchemy import func

from app.db.session import get_session
from app.models.inventory import Tag, InventoryItem, ItemTag

router = APIRouter(tags=["tags"])


@router.post("/tags", name="create_tag", response_class=HTMLResponse)
def create_tag(
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    name = (name or "").strip()
    if not name:
        url = request.url_for("tags_page").include_query_params(err="Name is required")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    existing = session.exec(select(Tag).where(Tag.name == name)).first()
    if existing:
        url = request.url_for("tags_page").include_query_params(err="The tag already exists")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    
    t = Tag(name=name)
    session.add(t)
    session.commit()
    url = request.url_for("tags_page").include_query_params(msg="Tag created")
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tags/{tag_id}/rename", name="rename_tag", response_class=HTMLResponse)
def rename_tag(
    request: Request,
    tag_id: int,
    new_name: str = Form(...),
    session: Session = Depends(get_session),
):
    new_name = (new_name or "").strip()
    if not new_name:
        url = request.url_for("tags_page").include_query_params(err="New name is required")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    tag = session.get(Tag, tag_id)
    if not tag:
        url = request.url_for("tags_page").include_query_params(err="Tag not found")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    clash = session.exec(select(Tag).where(Tag.name == new_name, Tag.id != tag_id)).first()
    if clash:
        url = request.url_for("tags_page").include_query_params(err="Another tag with that name exists")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    tag.name = new_name
    session.add(tag)
    session.commit()
    url = request.url_for("tags_page").include_query_params(msg="Tag renamed")
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tags/{tag_id}/delete", name="delete_tag", response_class=HTMLResponse)
def delete_tag(
    request: Request,
    tag_id: int,
    session: Session = Depends(get_session),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        url = request.url_for("tags_page").include_query_params(err="Tag not found")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    used = session.scalar(
        select(func.count()).select_from(ItemTag).where(ItemTag.tag_id == tag_id)
    ) or 0
    if used > 0:
        url = request.url_for("tags_page").include_query_params(err="Tag in use, detach from items first")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    session.delete(tag)
    session.commit()
    return RedirectResponse(
        url=request.url_for("tags_page") + "?msg=Tag%20deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/items/{item_id}/tags/attach", name="attach_tag_to_item", response_class=HTMLResponse)
def attach_tag_to_item(
    request: Request,
    item_id: int,
    tag_name: Optional[str] = Form(None),
    tag_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
):
    item = session.get(InventoryItem, item_id)
    if not item:
        url = request.url_for("items_page").include_query_params(err="Item not found")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    tag: Optional[Tag] = None
    if tag_id:
        tag = session.get(Tag, tag_id)
    elif tag_name:
        tag_name = tag_name.strip()
        if tag_name:
            tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
            if not tag:
                tag = Tag(name=tag_name)
                session.add(tag)
                session.commit()
                session.refresh(tag)

    if not tag:
        url = request.url_for("item_detail_page", item_id=item_id).include_query_params(err="Invalid tag")
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    exists = session.exec(
        select(ItemTag).where(ItemTag.item_id == item_id, ItemTag.tag_id == tag.id)
    ).first()
    if not exists:
        link = ItemTag(item_id=item_id, tag_id=tag.id)
        session.add(link)
        session.commit()

    url = request.url_for("item_detail_page", item_id=item_id).include_query_params(msg="Tag attached")
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/items/{item_id}/tags/detach", name="detach_tag_from_item", response_class=HTMLResponse)
def detach_tag_from_item(
    request: Request,
    item_id: int,
    tag_id: int = Form(...),
    session: Session = Depends(get_session),
):
    session.exec(
        delete(ItemTag).where(ItemTag.item_id == item_id, ItemTag.tag_id == tag_id)
    )
    session.commit()
    url = request.url_for("item_detail_page", item_id=item_id).include_query_params(msg="Tag removed")
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
