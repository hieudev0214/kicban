from urllib.parse import quote

from app.config import BANK_ACCOUNT_NAME, BANK_ACCOUNT_NO, BANK_ID


def build_qr_url(amount_vnd: int, note: str) -> str:
    """VietQR's public 'quick link' image API - a free, standardized QR format
    that any Vietnamese banking app can scan, no API key or registration
    needed. Points at whatever bank account is configured in BANK_ID/
    BANK_ACCOUNT_NO; `note` is the transfer content the admin matches the
    incoming transfer against when approving the top-up."""
    return (
        f"https://img.vietqr.io/image/{BANK_ID}-{BANK_ACCOUNT_NO}-compact2.png"
        f"?amount={amount_vnd}&addInfo={quote(note)}&accountName={quote(BANK_ACCOUNT_NAME)}"
    )
