import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db, jobs
from app.config import BASE_DIR, LOG_PATH
from app.routes import api, pages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    jobs.start_worker()
    yield


app = FastAPI(title="kicban", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(api.router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
