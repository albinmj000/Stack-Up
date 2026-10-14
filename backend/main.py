import os
import logging
import traceback
import json
import base64
import hashlib
import hmac
import secrets
import tempfile
import urllib.request
import urllib.error
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Form, Request, Query, Body, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from services.statement_parser import (
    extract_text_from_pdf,
    extract_transactions_from_text,
)
from services.transaction_processor import categorize_transactions
from services.analyzer import analyze_transactions, get_upi_activity
from services.message_handler import (
    deduplicate_overlapping_statement_transactions,
    handle_user_message,
)
from services.statement_service import check_duplicate_statement
from database.database import (
    initialize_database,
    create_user,
    user_exists,
    save_statement_with_transactions,
    replace_statement_transactions,
    get_statement_id,
    get_statement_transactions,
    get_statement,
    update_transaction_categories,
    get_statement_pdf,
    save_statement_pdf,
    get_user_transactions,
    update_transaction_income_inclusion,
    create_user_shared_bill,
    list_user_shared_bills,
    set_shared_bill_participant_paid,
    delete_user_shared_bill,
    list_user_statements,
    list_user_bank_accounts,
    create_user_bank_account,
    assign_statement_bank_account,
    delete_user_statement,
    get_account_by_contact,
    get_account_by_username,
    get_account_by_id,
    add_account_credentials,
    create_account,
    create_auth_session,
    remember_account_on_device,
    get_auth_device_user,
    list_auth_device_accounts,
    switch_auth_device_account,
    deactivate_auth_device,
    delete_auth_device,
    can_attempt_password_login,
    record_password_login_failure,
    clear_password_login_failures,
    get_session_user,
    delete_auth_session,
    update_account_username,
    update_account_contact,
    update_account_password,
    remove_auth_device_account,
    delete_user_account,
)
from services.transaction_processor import (
    determine_transaction_type,
    extract_counterparty,
    normalize_upi_category,
    transactions_for_same_counterparty,
)
from database.corrections import save_correction, list_user_corrections
from services.auth_service import (
    hash_password,
    normalize_contact,
    normalize_username,
    request_account_verification_otp,
    request_contact_change_otp,
    request_otp,
    verify_code,
    verify_password,
)

app = FastAPI(
    title="Stack Up",
    description="AI-powered personal finance analysis",
    version="1.0.0",
)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
FRONTEND_URLS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("FRONTEND_URL", "").split(",")
    if origin.strip()
]
if APP_ENV == "production" and not FRONTEND_URLS:
    raise RuntimeError("FRONTEND_URL must be set to the deployed frontend origin in production.")
if APP_ENV != "production":
    FRONTEND_URLS.extend([
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ])

COOKIE_SECURE = os.getenv(
    "COOKIE_SECURE", "true" if APP_ENV == "production" else "false"
).strip().lower() == "true"
COOKIE_SAMESITE = os.getenv(
    "COOKIE_SAMESITE", "none" if APP_ENV == "production" else "lax"
).strip().lower()
if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise RuntimeError("COOKIE_SAMESITE must be one of: lax, strict, none.")
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    raise RuntimeError("COOKIE_SECURE must be true when COOKIE_SAMESITE is none.")

if APP_ENV == "production" and not os.getenv("DATABASE_URL", "").strip():
    raise RuntimeError("DATABASE_URL must point to a persistent PostgreSQL database in production.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(set(FRONTEND_URLS)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Stack-Up-Session-Token", "X-Stack-Up-Device-Token"],
)


@app.middleware("http")
async def accept_native_app_tokens(request: Request, call_next):
    # The native app cannot rely on cross-site cookies in its WebView, so it
    # sends the same tokens in headers. They are validated exactly like cookies.
    extra = []
    for header, cookie_name in (
        ("x-stack-up-session-token", "stack_up_session"),
        ("x-stack-up-device-token", "stack_up_device"),
    ):
        value = request.headers.get(header)
        if value and cookie_name not in request.cookies:
            extra.append(f"{cookie_name}={value}")
    if extra:
        existing = request.headers.get("cookie")
        combined = "; ".join(([existing] if existing else []) + extra)
        headers = [(k, v) for k, v in request.scope["headers"] if k != b"cookie"]
        headers.append((b"cookie", combined.encode("latin-1")))
        request.scope["headers"] = headers
    return await call_next(request)


@app.middleware("http")
async def validate_browser_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/webhook":
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in FRONTEND_URLS:
            return JSONResponse(
                {"detail": "Requests from this website are not allowed."},
                status_code=403,
            )
    return await call_next(request)

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
MAX_STATEMENT_UPLOAD_BYTES = 25 * 1024 * 1024

initialize_database()

CATEGORIES = {
    "Food", "Transport", "Shopping", "Bills & Utilities",
    "Entertainment", "Healthcare", "Loan / Credit", "Bank Charges",
    "Cash Withdrawal", "Investment", "Income", "Interest Income",
    "Refund", "Transfer", "Other",
    "UPI Sent", "UPI Received",
}


def authenticated_account(request: Request):
    device_token = request.cookies.get("stack_up_device")
    account = get_auth_device_user(device_token) if device_token else None
    # A stale device cookie should not invalidate a valid login session.
    if account is None:
        account = get_session_user(request.cookies.get("stack_up_session"))
    if account is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return account


def set_auth_cookies(response, session_token, device_token, request=None):
    if request is not None and request.headers.get("x-stack-up-client") == "native":
        response.headers["X-Stack-Up-Session-Token"] = session_token
        response.headers["X-Stack-Up-Device-Token"] = device_token
    response.set_cookie(
        key="stack_up_session",
        value=session_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=30 * 24 * 3600,
        path="/",
    )
    response.set_cookie(
        key="stack_up_device",
        value=device_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=30 * 24 * 3600,
        path="/",
    )


@app.post("/auth/request-otp")
async def auth_request_otp(payload: dict = Body(...)):
    try:
        contact, channel = normalize_contact(payload.get("contact"))
        create_new_account = bool(payload.get("create_account"))
        request_otp(
            contact,
            channel,
            create_new_account,
            username=payload.get("username"),
            password=payload.get("password"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        status_code = 429 if "wait before" in str(error).lower() else 503
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except Exception as error:
        logger.error("OTP delivery failed (%s).", type(error).__name__)
        raise HTTPException(status_code=503, detail="We couldn't deliver a verification code. Check the sign-in settings and try again.") from error
    return {"status": "sent", "message": f"A verification code was sent to your {channel}."}


@app.post("/auth/verify-otp")
async def auth_verify_otp(request: Request, response: Response, payload: dict = Body(...)):
    try:
        contact, channel = normalize_contact(payload.get("contact"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    challenge = verify_code(contact, payload.get("code"))
    if challenge is None:
        raise HTTPException(status_code=400, detail="That code is invalid or expired. Request a new one and try again.")
    if challenge.get("purpose", "authentication") != "authentication":
        raise HTTPException(status_code=400, detail="That code cannot be used to sign in. Request a new sign-in code.")

    account = get_account_by_contact(contact, channel)
    if challenge["create_account"]:
        try:
            if account is None:
                account = create_account(
                    contact,
                    channel,
                    challenge.get("username"),
                    challenge.get("password_hash"),
                )
            elif add_account_credentials(
                contact,
                channel,
                challenge.get("username"),
                challenge.get("password_hash"),
            ):
                account = get_account_by_contact(contact, channel)
            else:
                raise ValueError("Credentials are already set for this account.")
        except Exception as error:
            raise HTTPException(status_code=409, detail="That username or email/phone is already in use. Request a new code and try again.") from error
    if account is None:
        raise HTTPException(status_code=404, detail="No account was found. Choose Create account to register.")

    token = secrets.token_urlsafe(32)
    create_auth_session(account["user_id"], token)
    device_token = remember_account_on_device(
        request.cookies.get("stack_up_device"),
        account["user_id"],
    )
    set_auth_cookies(response, token, device_token, request)
    return {"status": "success", "account": {"email": account.get("email"), "phone": account.get("phone"), "username": account.get("username")}}


@app.post("/auth/login")
async def auth_login(request: Request, response: Response, payload: dict = Body(...)):
    try:
        username = normalize_username(payload.get("username"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not can_attempt_password_login(username):
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Wait 15 minutes and try again.",
        )

    account = get_account_by_username(username)
    if account is None or not verify_password(payload.get("password"), account.get("password_hash")):
        record_password_login_failure(username)
        raise HTTPException(status_code=401, detail="Username or password is incorrect.")

    clear_password_login_failures(username)
    token = secrets.token_urlsafe(32)
    create_auth_session(account["user_id"], token)
    device_token = remember_account_on_device(
        request.cookies.get("stack_up_device"),
        account["user_id"],
    )
    set_auth_cookies(response, token, device_token, request)
    return {"status": "success", "account": {"email": account.get("email"), "phone": account.get("phone"), "username": account.get("username")}}


@app.get("/auth/me")
async def auth_me(request: Request):
    account = authenticated_account(request)
    return {"email": account.get("email"), "phone": account.get("phone"), "username": account.get("username")}


@app.get("/auth/settings")
async def auth_settings(request: Request):
    account = authenticated_account(request)
    device_token = request.cookies.get("stack_up_device")
    device_account = get_auth_device_user(device_token) if device_token else None
    if device_account and device_account["user_id"] == account["user_id"]:
        remembered_accounts = list_auth_device_accounts(device_token)
    else:
        remembered_accounts = [{**account, "active": 1}]
    return {
        "account": {
            "email": account.get("email"),
            "phone": account.get("phone"),
            "username": account.get("username"),
        },
        "has_password": bool(get_account_by_id(account["user_id"]).get("password_hash")),
        "remembered_accounts": remembered_accounts,
        "remembered_scope": "This device only",
    }


@app.put("/auth/settings/profile")
async def update_settings_profile(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    stored_account = get_account_by_id(account["user_id"])
    try:
        username = normalize_username(payload.get("username"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if stored_account.get("password_hash") and not verify_password(
        payload.get("current_password"), stored_account["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    try:
        updated = update_account_username(account["user_id"], username)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="That username is already in use.") from error
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"username": username}


@app.post("/auth/settings/contact/request")
async def request_settings_contact_code(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    try:
        _, channel = request_contact_change_otp(
            account["user_id"],
            payload.get("contact"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        status_code = 429 if "wait before" in str(error).lower() else 503
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except Exception as error:
        logger.error("Contact verification delivery failed (%s).", type(error).__name__)
        raise HTTPException(status_code=503, detail="We couldn't deliver a verification code. Check the sign-in settings and try again.") from error
    return {"status": "sent", "message": f"A verification code was sent to the new {channel}."}


@app.post("/auth/settings/contact/verify")
async def verify_settings_contact_code(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    try:
        contact, channel = normalize_contact(payload.get("contact"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    challenge = verify_code(contact, payload.get("code"))
    if (
        challenge is None
        or challenge.get("purpose") != "contact_change"
        or challenge.get("user_id") != account["user_id"]
    ):
        raise HTTPException(status_code=400, detail="That code is invalid or expired. Request a new one and try again.")
    try:
        updated = update_account_contact(account["user_id"], channel, contact)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="That email or phone number is already used by another account.") from error
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"status": "success", "email": contact if channel == "email" else account.get("email"),
            "phone": contact if channel == "phone" else account.get("phone")}


@app.post("/auth/settings/verification-code")
async def request_settings_verification_code(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    purpose = payload.get("purpose")
    if purpose not in {"password_change", "account_deletion"}:
        raise HTTPException(status_code=400, detail="Unsupported verification request.")
    try:
        channel = request_account_verification_otp(account["user_id"], purpose)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        status_code = 429 if "wait before" in str(error).lower() else 503
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except Exception as error:
        logger.error("Account verification delivery failed (%s).", type(error).__name__)
        raise HTTPException(status_code=503, detail="We couldn't deliver a verification code. Check the sign-in settings and try again.") from error
    return {"status": "sent", "message": f"A verification code was sent to your {channel}."}


@app.put("/auth/settings/password")
async def change_settings_password(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    stored_account = get_account_by_id(account["user_id"])
    current_hash = stored_account.get("password_hash")
    if current_hash:
        if not verify_password(payload.get("current_password"), current_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
    else:
        contact_value = stored_account.get("email") or stored_account.get("phone")
        try:
            contact, _ = normalize_contact(contact_value)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        challenge = verify_code(contact, payload.get("verification_code"))
        if (
            challenge is None
            or challenge.get("purpose") != "password_change"
            or challenge.get("user_id") != account["user_id"]
        ):
            raise HTTPException(status_code=400, detail="Request and verify a code before setting a password.")
    try:
        new_hash = hash_password(payload.get("new_password"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    token = request.cookies.get("stack_up_session")
    device_token = request.cookies.get("stack_up_device")
    if not update_account_password(account["user_id"], new_hash, token, device_token):
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"status": "success", "message": "Password updated. Other active sign-in sessions were signed out."}


@app.post("/auth/settings/remembered-accounts/remove")
async def remove_settings_remembered_account(request: Request, payload: dict = Body(...)):
    account = authenticated_account(request)
    user_id = payload.get("user_id")
    if not user_id or user_id == account["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove the currently active account.")
    device_token = request.cookies.get("stack_up_device")
    if not device_token or not remove_auth_device_account(device_token, user_id):
        raise HTTPException(status_code=404, detail="That account is not remembered on this device.")
    return {"status": "success"}


@app.get("/auth/settings/export")
async def export_settings_data(request: Request):
    user_id = authenticated_account(request)["user_id"]
    statements = list_user_statements(user_id)
    exported_statements = []
    total_pdf_bytes = 0
    for statement in statements:
        record = get_statement_pdf(user_id, statement["statement_id"])
        pdf_data = record.get("pdf_data") if record else None
        if pdf_data:
            total_pdf_bytes += len(pdf_data)
            if total_pdf_bytes > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Your statement files are too large for one export. Download them individually from Statement History.")
        exported_statements.append({
            **statement,
            "pdf_base64": base64.b64encode(pdf_data).decode("ascii") if pdf_data else None,
        })
    account_data = get_account_by_id(user_id)
    export_data = {
        "account": {
            "email": account_data.get("email"),
            "phone": account_data.get("phone"),
            "username": account_data.get("username"),
        },
        "statements": exported_statements,
        "bank_accounts": list_user_bank_accounts(user_id),
        "transactions": get_user_transactions(user_id),
        "category_corrections": list_user_corrections(user_id),
    }
    return JSONResponse(
        content=jsonable_encoder(export_data),
        headers={
            "Content-Disposition": 'attachment; filename="stack-up-account-export.json"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@app.post("/auth/settings/delete-account")
async def delete_settings_account(request: Request, response: Response, payload: dict = Body(...)):
    account = authenticated_account(request)
    stored_account = get_account_by_id(account["user_id"])
    if payload.get("confirmation") != "DELETE MY ACCOUNT":
        raise HTTPException(status_code=400, detail="Enter DELETE MY ACCOUNT to confirm.")
    password_hash = stored_account.get("password_hash")
    if password_hash:
        if not verify_password(payload.get("password"), password_hash):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
    else:
        contact = stored_account.get("email") or stored_account.get("phone")
        try:
            normalized_contact, _ = normalize_contact(contact)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        challenge = verify_code(normalized_contact, payload.get("verification_code"))
        if (
            challenge is None
            or challenge.get("purpose") != "account_deletion"
            or challenge.get("user_id") != account["user_id"]
        ):
            raise HTTPException(status_code=400, detail="Request and verify a code before deleting your account.")
    if not delete_user_account(account["user_id"]):
        raise HTTPException(status_code=404, detail="Account not found.")
    response.delete_cookie(
        "stack_up_session", path="/", httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )
    response.delete_cookie(
        "stack_up_device", path="/", httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )
    return {"status": "success"}


@app.get("/auth/accounts")
async def auth_accounts(request: Request):
    device_token = request.cookies.get("stack_up_device")
    device_account = get_auth_device_user(device_token) if device_token else None
    if device_account is not None:
        accounts = list_auth_device_accounts(device_token)
    else:
        account = get_session_user(request.cookies.get("stack_up_session"))
        if account is None:
            raise HTTPException(status_code=401, detail="Please sign in to continue.")
        accounts = [{**account, "active": 1}]
    return {"accounts": accounts}


@app.post("/auth/switch-account")
async def auth_switch_account(request: Request, response: Response, payload: dict = Body(...)):
    device_token = request.cookies.get("stack_up_device")
    user_id = payload.get("user_id")
    if not device_token or not user_id:
        raise HTTPException(status_code=400, detail="Choose an account remembered on this device.")

    account = switch_auth_device_account(device_token, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="That account is not remembered on this device.")

    delete_auth_session(request.cookies.get("stack_up_session"))
    session_token = secrets.token_urlsafe(32)
    create_auth_session(account["user_id"], session_token)
    set_auth_cookies(response, session_token, device_token, request)
    return {
        "status": "success",
        "account": {
            "email": account.get("email"),
            "phone": account.get("phone"),
            "username": account.get("username"),
        },
    }


@app.post("/auth/add-account")
async def auth_add_account(request: Request, response: Response):
    account = authenticated_account(request)
    device_token = request.cookies.get("stack_up_device")
    if not device_token:
        device_token = remember_account_on_device(None, account["user_id"])
    deactivate_auth_device(device_token)
    delete_auth_session(request.cookies.get("stack_up_session"))
    response.delete_cookie(
        "stack_up_session", path="/", httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )
    response.set_cookie(
        key="stack_up_device",
        value=device_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=30 * 24 * 3600,
        path="/",
    )
    return {"status": "success"}


@app.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    delete_auth_session(request.cookies.get("stack_up_session"))
    delete_auth_device(request.cookies.get("stack_up_device"))
    response.delete_cookie(
        "stack_up_session", path="/", httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )
    response.delete_cookie(
        "stack_up_device", path="/", httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )
    return {"status": "success"}


@app.get("/")
def home():
    return {
        "message": "Stack Up API is running!",
        "status": "success",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if (
        WHATSAPP_VERIFY_TOKEN
        and
        hub_mode == "subscribe"
        and hub_verify_token == WHATSAPP_VERIFY_TOKEN
    ):
        return hub_challenge

    return PlainTextResponse(
        "Verification failed",
        status_code=403,
    )


def send_whatsapp_message(recipient_phone_number, message):
    if not WHATSAPP_ACCESS_TOKEN:
        raise ValueError("WHATSAPP_ACCESS_TOKEN is not configured.")

    if not WHATSAPP_PHONE_NUMBER_ID:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured.")

    url = (
        "https://graph.facebook.com/v23.0/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone_number,
        "type": "text",
        "text": {"body": message},
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API error: {body}") from error


@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    if not WHATSAPP_APP_SECRET:
        raise HTTPException(
            status_code=503,
            detail="WhatsApp webhook signature verification is not configured.",
        )

    raw_body = await request.body()
    supplied_signature = request.headers.get("X-Hub-Signature-256", "")
    expected_signature = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature.")

    try:
        payload = json.loads(raw_body)

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue

                    sender = message.get("from")
                    if not sender:
                        continue

                    incoming_text = (
                        message.get("text", {})
                        .get("body", "")
                        .strip()
                    )

                    if not incoming_text:
                        continue

                    if not user_exists(sender):
                        create_user(sender)

                    result = handle_user_message(
                        sender,
                        incoming_text,
                    )
                    reply = result.get(
                        "message",
                        "I couldn't understand that request.",
                    )
                    send_whatsapp_message(sender, reply)

        return {"status": "received"}

    except Exception as error:
        traceback.print_exc()
        return {"status": "error", "error": str(error)}


@app.post("/message")
async def receive_message(
    request: Request,
    message: str,
    statement_id: int | None = None,
    statement_ids: list[int] | None = Query(default=None),
    payload: dict | None = Body(default=None),
):
    user_id = authenticated_account(request)["user_id"]
    selected_ids = list(dict.fromkeys(statement_ids or ([] if statement_id is None else [statement_id])))
    for selected_id in selected_ids:
        if get_statement(user_id, selected_id) is None:
            raise HTTPException(status_code=404, detail="Statement not found for this account.")
    history = payload.get("history") if isinstance(payload, dict) else None
    return handle_user_message(
        user_id,
        message,
        statement_ids=selected_ids or None,
        history=history,
    )


@app.patch("/transactions/{transaction_id}/category")
async def change_transaction_category(
    transaction_id: int,
    request: Request,
    payload: dict = Body(...),
):
    user_id = authenticated_account(request)["user_id"]
    category = str(payload.get("category") or "").strip()
    if category not in CATEGORIES:
        return {"status": "error", "message": "Choose a valid category."}

    # Determine the account direction first; the category decides whether
    # this movement counts as income, expense, or a transfer.
    user_transactions = get_user_transactions(user_id)
    transaction = next(
        (item for item in user_transactions
         if item.get("id") == transaction_id),
        None,
    )
    if transaction is None:
        return {"status": "error", "message": "Transaction not found."}

    matching_transactions = transactions_for_same_counterparty(
        user_transactions,
        transaction,
    )
    transaction_updates = []
    for item in matching_transactions:
        item_category = normalize_upi_category(item, category)
        transaction_updates.append((
            item["id"],
            item_category,
            determine_transaction_type(item, item_category),
        ))
    updated_count = update_transaction_categories(user_id, transaction_updates)
    if updated_count == 0:
        return {"status": "error", "message": "Transaction could not be updated."}

    description = str(transaction.get("description") or "")
    counterparty = None
    if "upi" in description.lower():
        counterparty = extract_counterparty(description).strip()
        if counterparty:
            save_correction(user_id, counterparty, category)

    statement_id = transaction.get("statement_id")
    statement_transactions = get_statement_transactions(user_id, statement_id)
    return {
        "status": "success",
        "category": normalize_upi_category(transaction, category),
        "transaction_type": determine_transaction_type(
            transaction,
            normalize_upi_category(transaction, category),
        ),
        "updated_count": updated_count,
        "updated_transaction_ids": [item[0] for item in transaction_updates],
        "updated_transaction_types": [
            {"id": item[0], "transaction_type": item[2]}
            for item in transaction_updates
        ],
        "counterparty": counterparty,
        "analysis": analyze_transactions(statement_transactions),
    }


@app.patch("/transactions/{transaction_id}/income-inclusion")
async def change_transaction_income_inclusion(
    transaction_id: int,
    request: Request,
    payload: dict = Body(...),
):
    user_id = authenticated_account(request)["user_id"]
    included = payload.get("included")
    if not isinstance(included, bool):
        raise HTTPException(status_code=400, detail="Choose whether to include this transaction in income.")

    transaction = next(
        (item for item in get_user_transactions(user_id)
         if item.get("id") == transaction_id),
        None,
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if (
        str(transaction.get("type") or "").strip().lower() != "credit"
        or get_upi_activity(transaction) != "received"
    ):
        raise HTTPException(
            status_code=400,
            detail="Only UPI Received credits can be manually included in income.",
        )
    if not update_transaction_income_inclusion(user_id, transaction_id, included):
        raise HTTPException(status_code=404, detail="Transaction not found.")

    return {
        "status": "success",
        "transaction_id": transaction_id,
        "income_included": included,
    }


def _shared_bill_cents(value):
    if isinstance(value, bool):
        raise ValueError("Enter a valid amount.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Enter a valid amount.") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amounts must be finite and cannot be negative.")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError("Use no more than two decimal places.")
    return int(cents)


@app.get("/shared-bills")
async def shared_bills(request: Request):
    user_id = authenticated_account(request)["user_id"]
    return {"shared_bills": list_user_shared_bills(user_id)}


@app.post("/shared-bills")
async def create_shared_bill(request: Request, payload: dict = Body(...)):
    user_id = authenticated_account(request)["user_id"]
    transaction_id = payload.get("transaction_id")
    if isinstance(transaction_id, bool) or not isinstance(transaction_id, int):
        raise HTTPException(status_code=400, detail="Choose a valid transaction.")

    transactions = get_user_transactions(user_id)
    transaction = next(
        (item for item in transactions if item.get("id") == transaction_id),
        None,
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if (
        str(transaction.get("type") or "").strip().lower() != "debit"
        or str(transaction.get("transaction_type") or "").strip().lower() != "expense"
        or get_upi_activity(transaction)
        or transaction.get("shared_bill_id") is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Choose an expense debit that is not already part of a shared bill.",
        )

    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 120:
        raise HTTPException(status_code=400, detail="Bill details must be 1–120 characters.")

    raw_participants = payload.get("participants")
    if not isinstance(raw_participants, list) or not 1 <= len(raw_participants) <= 19:
        raise HTTPException(
            status_code=400,
            detail="Add between 1 and 19 other people to split this bill.",
        )

    try:
        gross_cents = _shared_bill_cents(transaction.get("amount"))
        owner_cents = _shared_bill_cents(payload.get("owner_share"))
        participants = []
        for participant in raw_participants:
            if not isinstance(participant, dict):
                raise ValueError("Each person needs a name and share.")
            name = str(participant.get("name") or "").strip()
            if not name or len(name) > 80:
                raise ValueError("Each person's name must be 1–80 characters.")
            share_cents = _shared_bill_cents(participant.get("share_amount"))
            if share_cents <= 0:
                raise ValueError("Each other person's share must be greater than zero.")
            participants.append({
                "name": name,
                "share_amount": share_cents / 100,
            })
    except ValueError as validation_error:
        raise HTTPException(status_code=400, detail=str(validation_error)) from validation_error

    if owner_cents + sum(
        round(item["share_amount"] * 100) for item in participants
    ) != gross_cents:
        raise HTTPException(
            status_code=400,
            detail="Your share and everyone's share must add up to the transaction amount.",
        )

    try:
        create_user_shared_bill(
            user_id,
            transaction_id,
            title,
            owner_cents / 100,
            participants,
        )
    except ValueError as create_error:
        raise HTTPException(status_code=409, detail=str(create_error)) from create_error

    return {"status": "success", "shared_bills": list_user_shared_bills(user_id)}


@app.patch("/shared-bills/{bill_id}/participants/{participant_id}")
async def update_shared_bill_repayment(
    bill_id: int,
    participant_id: int,
    request: Request,
    payload: dict = Body(...),
):
    user_id = authenticated_account(request)["user_id"]
    is_paid = payload.get("is_paid")
    if not isinstance(is_paid, bool):
        raise HTTPException(status_code=400, detail="Choose whether this person repaid you.")
    if not set_shared_bill_participant_paid(
        user_id, bill_id, participant_id, is_paid
    ):
        raise HTTPException(status_code=404, detail="Shared bill participant not found.")
    return {"status": "success", "shared_bills": list_user_shared_bills(user_id)}


@app.delete("/shared-bills/{bill_id}")
async def remove_shared_bill(bill_id: int, request: Request):
    user_id = authenticated_account(request)["user_id"]
    if not delete_user_shared_bill(user_id, bill_id):
        raise HTTPException(status_code=404, detail="Shared bill not found.")
    return {"status": "success", "shared_bills": list_user_shared_bills(user_id)}


@app.get("/statements")
async def statements_history(request: Request):
    user_id = authenticated_account(request)["user_id"]
    return {"statements": list_user_statements(user_id)}


@app.get("/statements/combined")
async def combined_statements(request: Request):
    user_id = authenticated_account(request)["user_id"]
    transactions = deduplicate_overlapping_statement_transactions(
        get_user_transactions(user_id)
    )
    return {
        "statement_count": len(list_user_statements(user_id)),
        "transactions": transactions,
        "analysis": analyze_transactions(transactions),
    }


@app.get("/statements/selection")
async def selected_statements(
    request: Request,
    statement_ids: list[int] = Query(default=[]),
):
    user_id = authenticated_account(request)["user_id"]
    selected_ids = list(dict.fromkeys(statement_ids))
    for statement_id in selected_ids:
        if get_statement(user_id, statement_id) is None:
            raise HTTPException(status_code=404, detail="Statement not found for this account.")
    selected_id_set = set(selected_ids)
    transactions = [
        transaction
        for transaction in get_user_transactions(user_id)
        if transaction.get("statement_id") in selected_id_set
    ]
    transactions = deduplicate_overlapping_statement_transactions(transactions)
    return {
        "statement_count": len(selected_ids),
        "transactions": transactions,
        "analysis": analyze_transactions(transactions),
    }


@app.get("/bank-accounts")
async def bank_accounts(request: Request):
    user_id = authenticated_account(request)["user_id"]
    return {"bank_accounts": list_user_bank_accounts(user_id)}


@app.post("/bank-accounts")
async def add_bank_account(request: Request, payload: dict = Body(...)):
    user_id = authenticated_account(request)["user_id"]
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="Enter a bank account name up to 80 characters.")
    try:
        bank_account = create_user_bank_account(user_id, name)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"bank_account": bank_account}


@app.patch("/statements/{statement_id}/bank-account")
async def update_statement_bank_account(
    statement_id: int,
    request: Request,
    payload: dict = Body(...),
):
    user_id = authenticated_account(request)["user_id"]
    raw_account_id = payload.get("bank_account_id")
    try:
        bank_account_id = int(raw_account_id) if raw_account_id is not None else None
        if raw_account_id is not None and bank_account_id <= 0:
            raise ValueError
        updated = assign_statement_bank_account(
            user_id,
            statement_id,
            bank_account_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Bank account not found for this user.") from error
    if not updated:
        raise HTTPException(status_code=404, detail="Statement not found for this account.")
    return {"status": "success", "statement_id": statement_id, "bank_account_id": bank_account_id}


@app.get("/statements/{statement_id}/pdf")
async def download_statement_pdf(statement_id: int, request: Request):
    user_id = authenticated_account(request)["user_id"]
    statement_pdf = get_statement_pdf(user_id, statement_id)
    if statement_pdf is None or statement_pdf.get("pdf_data") is None:
        raise HTTPException(status_code=404, detail="Original PDF is not available for this statement.")

    filename = str(statement_pdf.get("filename") or "bank-statement.pdf")
    filename = filename.replace("\\", "/").split("/")[-1]
    return Response(
        content=statement_pdf["pdf_data"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
        },
    )


@app.get("/statements/{statement_id}")
async def load_statement_from_history(statement_id: int, request: Request):
    user_id = authenticated_account(request)["user_id"]
    result = build_dashboard_result(
        user_id,
        statement_id,
        filename=None,
        message="Statement loaded from history.",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Statement not found for this account.")
    return result


@app.delete("/statements/{statement_id}")
async def delete_statement_from_history(statement_id: int, request: Request):
    user_id = authenticated_account(request)["user_id"]
    if not delete_user_statement(user_id, statement_id):
        raise HTTPException(status_code=404, detail="Statement not found for this account.")
    return {"status": "success", "statement_id": statement_id}


def build_dashboard_result(
    user_id,
    statement_id,
    filename,
    message="Statement loaded successfully.",
):
    """Load saved transactions and rebuild the dashboard analysis."""
    statement = get_statement(user_id, statement_id)
    transactions = get_statement_transactions(user_id, statement_id)

    if not transactions:
        return None

    analysis = analyze_transactions(transactions)

    return {
        "status": "success",
        "message": message,
        "user_id": user_id,
        "statement_id": statement_id,
        "filename": statement.get("filename") if statement else filename,
        "transaction_count": len(transactions),
        "analysis": analysis,
        "transactions": transactions,
        "already_uploaded": True,
    }


def process_pdf(file_path, user_id):
    """Extract and categorize transactions without saving them."""
    text = extract_text_from_pdf(file_path)

    if not text or not text.strip():
        raise ValueError(
            "No readable text was extracted from this PDF. "
            "It may be scanned and require OCR."
        )

    transactions = extract_transactions_from_text(text)

    if not transactions:
        raise ValueError(
            "No transactions could be extracted from the PDF. "
            "Please check that it is a readable bank statement."
        )

    categorized = categorize_transactions(transactions, user_id)

    if not categorized:
        raise ValueError(
            "Transactions were detected but could not be categorized."
        )

    # Basic safety checks before any saved rows are replaced.
    for index, transaction in enumerate(categorized, start=1):
        try:
            amount = float(transaction.get("amount"))
        except (TypeError, ValueError):
            raise ValueError(
                f"Transaction {index} has an invalid amount. "
                "Existing saved data has not been changed."
            )

        if amount < 0:
            raise ValueError(
                f"Transaction {index} has a negative amount. "
                "Existing saved data has not been changed."
            )

        if not transaction.get("date"):
            raise ValueError(
                f"Transaction {index} has no date. "
                "Existing saved data has not been changed."
            )

    return categorized


@app.post("/upload-statement")
async def upload_statement(
    request: Request,
    file: UploadFile = File(...),
    bank_account_id: int | None = Form(default=None),
    reprocess: bool = Query(
        False,
        description=(
            "Set true to reparse and replace transactions for this "
            "previously uploaded statement."
        ),
    ),
):
    user_id = authenticated_account(request)["user_id"]
    if bank_account_id is not None and not any(
        bank_account["id"] == bank_account_id
        for bank_account in list_user_bank_accounts(user_id)
    ):
        raise HTTPException(status_code=404, detail="Bank account not found for this user.")
    if (
        not file.filename
        or not file.filename.lower().endswith(".pdf")
    ):
        return {
            "status": "error",
            "message": "Please upload a PDF bank statement.",
        }

    file_path = None

    try:
        temporary_pdf = tempfile.NamedTemporaryFile(
            prefix="stack_up_",
            suffix=".pdf",
            delete=False,
        )
        file_path = temporary_pdf.name
        temporary_pdf.close()

        if not user_exists(user_id):
            create_user(user_id)

        with open(file_path, "wb") as buffer:
            total_bytes = 0
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_STATEMENT_UPLOAD_BYTES:
                    return {
                        "status": "error",
                        "message": "PDF files must be 25 MB or smaller.",
                    }
                buffer.write(chunk)

        duplicate_check = check_duplicate_statement(
            user_id,
            file_path,
        )

        is_duplicate = duplicate_check["exists"]
        statement_id = None

        if is_duplicate:
            file_hash = duplicate_check["file_hash"]
            statement_id = get_statement_id(user_id, file_hash)

            if statement_id is None:
                return {
                    "status": "error",
                    "message": (
                        "The duplicate was detected, but its statement "
                        "record could not be retrieved."
                    ),
                }

            # Default behavior: load existing data unless reprocessing
            # was explicitly requested.
            if not reprocess:
                saved_result = build_dashboard_result(
                    user_id,
                    statement_id,
                    file.filename,
                    message="Previously uploaded statement loaded successfully.",
                )

                if saved_result is not None:
                    if bank_account_id is not None:
                        assign_statement_bank_account(
                            user_id,
                            statement_id,
                            bank_account_id,
                        )
                    with open(file_path, "rb") as uploaded_pdf:
                        save_statement_pdf(
                            user_id,
                            statement_id,
                            uploaded_pdf.read(),
                        )
                    return saved_result

        # Parse the PDF for new statements, empty saved statements,
        # or explicit reprocessing of a duplicate statement.
        categorized_transactions = process_pdf(file_path, user_id)
        with open(file_path, "rb") as uploaded_pdf:
            pdf_data = uploaded_pdf.read()

        if is_duplicate:
            # This also recovers older empty history records left behind by
            # failed uploads.
            replace_statement_transactions(
                user_id,
                statement_id,
                categorized_transactions,
                pdf_data,
            )
            success_message = (
                "Statement reprocessed successfully using the updated parser."
                if reprocess
                else "Previously registered statement recovered successfully."
            )
        else:
            statement_id, created = save_statement_with_transactions(
                user_id,
                duplicate_check["file_hash"],
                file.filename,
                categorized_transactions,
                pdf_data,
            )
            if not created:
                is_duplicate = True
                saved_result = build_dashboard_result(
                    user_id,
                    statement_id,
                    file.filename,
                    message="Previously uploaded statement loaded successfully.",
                )
                if saved_result is not None:
                    return saved_result
                raise RuntimeError("The saved statement could not be loaded.")
            success_message = "Bank statement analyzed successfully!"

        if bank_account_id is not None:
            assign_statement_bank_account(user_id, statement_id, bank_account_id)

        result = build_dashboard_result(
            user_id,
            statement_id,
            file.filename,
            message=success_message,
        )

        if result is None:
            return {
                "status": "error",
                "message": (
                    "The statement was processed, but saved transactions "
                    "could not be loaded afterward."
                ),
                "statement_id": statement_id,
            }

        result["already_uploaded"] = is_duplicate
        result["reprocessed"] = bool(is_duplicate and reprocess)
        result["recovered"] = bool(is_duplicate and not reprocess)
        return result

    except Exception as error:
        traceback.print_exc()
        return {
            "status": "error",
            "message": "An error occurred while processing the statement.",
            "error": str(error),
        }

    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        await file.close()
