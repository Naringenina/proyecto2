from contextlib import asynccontextmanager
from pathlib import Path
from app.routers.items import router as items_router
from app.routers.pages import router as pages_router
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db.session import init_db

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


app.include_router(items_router) 
app.include_router(pages_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})