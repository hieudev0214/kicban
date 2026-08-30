from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import auth, db, vietqr
from app.config import (
    BANK_ACCOUNT_NAME,
    BANK_ACCOUNT_NO,
    BANK_ID,
    MANUAL_TOPUP_ENABLED,
    MIN_TOPUP_VND,
)

router = APIRouter(prefix="/api/wallet")


class TopupRequestBody(BaseModel):
    amount_vnd: int


@router.post("/topup-request")
def create_topup_request(body: TopupRequestBody, user: dict = Depends(auth.require_user)):
    if not MANUAL_TOPUP_ENABLED:
        raise HTTPException(400, "Chức năng nạp tiền chưa được cấu hình trên server.")
    if body.amount_vnd < MIN_TOPUP_VND:
        raise HTTPException(400, f"Số tiền nạp tối thiểu là {MIN_TOPUP_VND:,} VND.")

    # Placeholder note first, then rewritten to include the topup's own id so
    # it's short, unique, and easy for the admin to match against the
    # incoming bank transfer.
    topup_id = db.create_topup(user["id"], body.amount_vnd, note="_")
    note = f"NAP {topup_id[:8].upper()}"
    db.update_topup(topup_id, note=note)

    return {
        "topup_id": topup_id,
        "amount_vnd": body.amount_vnd,
        "note": note,
        "bank_id": BANK_ID,
        "bank_account_no": BANK_ACCOUNT_NO,
        "bank_account_name": BANK_ACCOUNT_NAME,
        "qr_image_url": vietqr.build_qr_url(body.amount_vnd, note),
    }


@router.get("/my-topups")
def my_topups(user: dict = Depends(auth.require_user)):
    return db.list_topups_for_user(user["id"])
