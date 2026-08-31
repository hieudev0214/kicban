from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import auth, db
from app.config import COOKIE_HEALTHCHECK_URL
from app.media import check_cookie_health

router = APIRouter(prefix="/api/admin")


def _user_public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "wallet_balance_vnd": user["wallet_balance_vnd"],
        "is_locked": bool(user["is_locked"]),
        "created_at": user["created_at"],
    }


class CreditBody(BaseModel):
    amount_vnd: int


class LockBody(BaseModel):
    locked: bool


@router.get("/users")
def list_users(admin: dict = Depends(auth.require_admin)):
    return [_user_public(u) for u in db.list_users()]


@router.get("/users/{user_id}/jobs")
def user_jobs(user_id: str, limit: int = 50, admin: dict = Depends(auth.require_admin)):
    if not db.get_user_by_id(user_id):
        raise HTTPException(404, "User not found.")
    return db.list_jobs_for_user(user_id, limit=limit)


@router.post("/users/{user_id}/credit")
def credit_user(user_id: str, body: CreditBody, admin: dict = Depends(auth.require_admin)):
    if not db.get_user_by_id(user_id):
        raise HTTPException(404, "User not found.")
    db.adjust_wallet_balance(user_id, body.amount_vnd)
    return _user_public(db.get_user_by_id(user_id))


@router.post("/users/{user_id}/lock")
def lock_user(user_id: str, body: LockBody, admin: dict = Depends(auth.require_admin)):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if target["id"] == admin["id"] and body.locked:
        raise HTTPException(400, "Không thể tự khoá tài khoản của chính mình.")
    db.update_user(user_id, is_locked=1 if body.locked else 0)
    return _user_public(db.get_user_by_id(user_id))


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(auth.require_admin)):
    if not db.get_user_by_id(user_id):
        raise HTTPException(404, "User not found.")
    if user_id == admin["id"]:
        raise HTTPException(400, "Không thể tự xoá tài khoản của chính mình.")
    db.delete_user(user_id)
    return {"ok": True}


@router.get("/cookie-health")
def cookie_health(admin: dict = Depends(auth.require_admin)):
    """Live-tests the configured yt-dlp cookies against COOKIE_HEALTHCHECK_URL
    so a stale TikTok cookie (see CLAUDE.md - they expire quickly in
    practice) shows up here instead of only being found via a customer's
    failed job or the server log."""
    if not COOKIE_HEALTHCHECK_URL:
        return {"configured": False}
    result = check_cookie_health(COOKIE_HEALTHCHECK_URL)
    return {
        "configured": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }


@router.get("/topups")
def list_topups(status: str = "pending", admin: dict = Depends(auth.require_admin)):
    return db.list_topups(status=status or None)


@router.post("/topups/{topup_id}/approve")
def approve_topup(topup_id: str, admin: dict = Depends(auth.require_admin)):
    topup = db.get_topup(topup_id)
    if not topup:
        raise HTTPException(404, "Topup not found.")
    if topup["status"] != "pending":
        raise HTTPException(400, "Yêu cầu này đã được xử lý rồi.")
    db.update_topup(topup_id, status="approved")
    db.adjust_wallet_balance(topup["user_id"], topup["amount_vnd"])
    return db.get_topup(topup_id)


@router.post("/topups/{topup_id}/reject")
def reject_topup(topup_id: str, admin: dict = Depends(auth.require_admin)):
    topup = db.get_topup(topup_id)
    if not topup:
        raise HTTPException(404, "Topup not found.")
    if topup["status"] != "pending":
        raise HTTPException(400, "Yêu cầu này đã được xử lý rồi.")
    db.update_topup(topup_id, status="rejected")
    return db.get_topup(topup_id)
