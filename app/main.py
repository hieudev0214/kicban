import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import BASE_DIR, LOG_PATH
from app.routes import admin, api, auth, pages, wallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="kicban", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(api.router)
app.include_router(auth.router)
app.include_router(wallet.router)
app.include_router(admin.router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
