from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db.session import init_db
from app.routers.pages import router as pages_router
from app.routers.items import router as items_router
from app.routers.tags import router as tags_router

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Cards Inventory", lifespan=lifespan)

(BASE_DIR / "static").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "media").mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static", check_dir=False), name="static")
app.mount("/media", StaticFiles(directory=BASE_DIR / "media", check_dir=False), name="media")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates = templates

def _thumb_path_filter(image_path: str | None) -> str | None:
    if not image_path:
        return None
    p = Path(image_path)
    thumb_rel = Path("items") / "_thumbs" / f"{p.stem}_thumb{p.suffix}"
    thumb_abs = BASE_DIR / "media" / thumb_rel
    return str(thumb_rel.as_posix()) if thumb_abs.exists() else None

templates.env.filters["thumb_path"] = _thumb_path_filter

app.include_router(items_router)
app.include_router(tags_router)
app.include_router(pages_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})
