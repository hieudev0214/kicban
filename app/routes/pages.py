from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, OPENAI_ENABLED
from app.transcribe import LANGUAGE_CHOICES

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "languages": LANGUAGE_CHOICES,
            "openai_enabled": OPENAI_ENABLED,
        },
    )
