import os
import traceback
import json
import hashlib
import hmac
import secrets
import tempfile
import urllib.request
import urllib.error
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Request, Query, Body, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from services.statement_parser import (
    extract_text_from_pdf,
    extract_transactions_from_text,
)
from services.transaction_processor import categorize_transactions
from services.analyzer import analyze_transactions
from services.message_handler import handle_user_message
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
    update_transaction_category,
    get_statement_pdf,
    save_statement_pdf,
    get_user_transactions,
    list_user_statements,
    get_account_by_contact,
    get_account_by_username,
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
)
from services.transaction_processor import determine_transaction_type, extract_counterparty
from database.corrections import save_correction
from services.auth_service import (
    normalize_contact,
    normalize_username,
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
)


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
    if device_token:
        account = get_auth_device_user(device_token)
    else:
        account = get_session_user(request.cookies.get("stack_up_session"))
    if account is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return account


def set_auth_cookies(response, session_token, device_token):
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
        print(f"OTP delivery failed: {error}")
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
    set_auth_cookies(response, token, device_token)
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
    set_auth_cookies(response, token, device_token)
    return {"status": "success", "account": {"email": account.get("email"), "phone": account.get("phone"), "username": account.get("username")}}


@app.get("/auth/me")
async def auth_me(request: Request):
    account = authenticated_account(request)
    return {"email": account.get("email"), "phone": account.get("phone"), "username": account.get("username")}


@app.get("/auth/accounts")
async def auth_accounts(request: Request):
    device_token = request.cookies.get("stack_up_device")
    if device_token:
        if get_auth_device_user(device_token) is None:
            raise HTTPException(status_code=401, detail="Please sign in to continue.")
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
    set_auth_cookies(response, session_token, device_token)
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
async def receive_message(request: Request, message: str):
    user_id = authenticated_account(request)["user_id"]
    return handle_user_message(user_id, message)


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
    transaction = next(
        (item for item in get_user_transactions(user_id)
         if item.get("id") == transaction_id),
        None,
    )
    if transaction is None:
        return {"status": "error", "message": "Transaction not found."}

    transaction_type = determine_transaction_type(transaction, category)
    updated = update_transaction_category(
        user_id, transaction_id, category, transaction_type
    )
    if not updated:
        return {"status": "error", "message": "Transaction could not be updated."}

    # Remember the user's choice for this UPI counterparty so future payments
    # to the same person or merchant are categorized consistently.
    description = str(transaction.get("description") or "")
    if "upi" in description.lower():
        counterparty = extract_counterparty(description).strip()
        if counterparty:
            save_correction(user_id, counterparty, category)

    statement_id = transaction.get("statement_id")
    statement_transactions = get_statement_transactions(user_id, statement_id)
    return {
        "status": "success",
        "category": category,
        "transaction_type": transaction_type,
        "analysis": analyze_transactions(statement_transactions),
    }


@app.get("/statements")
async def statements_history(request: Request):
    user_id = authenticated_account(request)["user_id"]
    return {"statements": list_user_statements(user_id)}


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
    reprocess: bool = Query(
        False,
        description=(
            "Set true to reparse and replace transactions for this "
            "previously uploaded statement."
        ),
    ),
):
    user_id = authenticated_account(request)["user_id"]
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
