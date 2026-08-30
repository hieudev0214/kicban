from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import pricing
from app.config import BASE_DIR
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
            "price_tiers": pricing.tier_display(),
            "free_trial_max_minutes": pricing.FREE_TRIAL_MAX_SECONDS // 60,
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
