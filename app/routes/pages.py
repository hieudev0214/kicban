from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, PRICE_PER_JOB_VND
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
            "price_per_job_vnd": PRICE_PER_JOB_VND,
        },
    )


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@router.get("/admin")
def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html", {})
