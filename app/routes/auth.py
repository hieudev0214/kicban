import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app import auth, db
from app.config import ADMIN_EMAILS, SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS

router = APIRouter(prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterBody(BaseModel):
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


def _user_public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "wallet_balance_vnd": user["wallet_balance_vnd"],
    }


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        auth.create_session_token(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )


@router.post("/register")
def register(body: RegisterBody, response: Response):
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Email không hợp lệ.")
    if len(body.password) < 6:
        raise HTTPException(400, "Mật khẩu phải có ít nhất 6 ký tự.")
    if db.get_user_by_email(email):
        raise HTTPException(400, "Email này đã được đăng ký.")

    role = "admin" if email in ADMIN_EMAILS else "user"
    user_id = db.create_user(email, auth.hash_password(body.password), role=role)
    _set_session_cookie(response, user_id)
    return _user_public(db.get_user_by_id(user_id))


@router.post("/login")
def login(body: LoginBody, response: Response):
    email = body.email.strip().lower()
    user = db.get_user_by_email(email)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email hoặc mật khẩu không đúng.")
    if user["is_locked"]:
        raise HTTPException(403, "Tài khoản đã bị khoá.")

    # Emails added to ADMIN_EMAILS after registration are promoted on next login.
    if email in ADMIN_EMAILS and user["role"] != "admin":
        db.update_user(user["id"], role="admin")
        user = db.get_user_by_id(user["id"])

    _set_session_cookie(response, user["id"])
    return _user_public(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(401, "Chưa đăng nhập.")
    return _user_public(user)
