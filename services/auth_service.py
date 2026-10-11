import os
import re
import json
import base64
import hashlib
import secrets
import logging
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parseaddr

from database.database import (
    can_request_otp,
    create_otp_challenge,
    get_account_by_contact,
    get_account_by_username,
    invalidate_otp_challenge,
    verify_otp_challenge,
)

logger = logging.getLogger(__name__)


def _safe_resend_error_field(value, api_key, otp_code, limit=400):
    """Return a short provider error field with credentials and identifiers removed."""
    if not isinstance(value, str):
        return "Unknown provider error"

    safe_value = value.replace(api_key, "[redacted]") if api_key else value
    if otp_code:
        safe_value = safe_value.replace(otp_code, "[redacted]")
    safe_value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", safe_value)
    safe_value = re.sub(r"\bre_[A-Za-z0-9_-]+\b", "[redacted]", safe_value)
    safe_value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[email redacted]",
        safe_value,
        flags=re.IGNORECASE,
    )
    safe_value = re.sub(r"[\r\n\t]+", " ", safe_value).strip()
    return safe_value[:limit] or "Unknown provider error"


def _read_resend_error(error, api_key, otp_code):
    """Extract structured error fields or a short sanitized excerpt from the response."""
    headers = getattr(error, "headers", None)
    content_type = headers.get("Content-Type", "unknown") if hasattr(headers, "get") else "unknown"
    content_type = _safe_resend_error_field(str(content_type), api_key, otp_code, limit=120)

    body = ""
    try:
        body = error.read(4_096).decode("utf-8", errors="replace")
        data = json.loads(body)
    except Exception:
        data = None

    if not isinstance(data, dict):
        excerpt = _safe_resend_error_field(body, api_key, otp_code, limit=300) if body else "[empty response]"
        return None, None, content_type, excerpt

    if isinstance(data.get("error"), dict):
        data = data["error"]

    if not isinstance(data, dict):
        excerpt = _safe_resend_error_field(body, api_key, otp_code, limit=300) if body else "[empty response]"
        return None, None, content_type, excerpt

    name = _safe_resend_error_field(data.get("name"), api_key, otp_code, limit=100)
    message = _safe_resend_error_field(data.get("message"), api_key, otp_code)
    return name, message, content_type, None


def normalize_contact(value):
    value = str(value or "").strip()
    if "@" in value:
        email = value.lower()
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address.")
        return email, "email"

    phone = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise ValueError("Enter a phone number with country code, such as +91 98765 43210.")
    return phone, "phone"


def normalize_username(value):
    username = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,24}", username):
        raise ValueError("Username must be 3–24 characters using letters, numbers, dot, dash, or underscore.")
    return username


def hash_password(password):
    password = str(password or "")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise ValueError("Password must be 128 characters or fewer.")
    salt = secrets.token_bytes(16)
    iterations = 600_000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt_hex, expected_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", str(password or "").encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return secrets.compare_digest(actual.hex(), expected_hex)
    except (AttributeError, TypeError, ValueError):
        return False


def _send_email_otp(email, code):
    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not resend_api_key:
        raise RuntimeError("Email OTP delivery is not configured. Set RESEND_API_KEY on the backend.")

    sender = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    if not sender:
        sender = "onboarding@resend.dev"

    # Resend's shared testing sender is restricted to the one address configured
    # for this app, so the test setup cannot send codes to arbitrary users.
    sender_address = parseaddr(sender)[1].lower()
    if sender_address == "onboarding@resend.dev":
        test_recipient = os.getenv("RESEND_TEST_RECIPIENT", "").strip().lower()
        if not test_recipient:
            raise RuntimeError(
                "Set RESEND_TEST_RECIPIENT to the email address registered with Resend."
            )
        if email.strip().lower() != test_recipient:
            raise RuntimeError(
                "Email verification is currently restricted to the configured Resend test recipient."
            )

    payload = json.dumps({
        "from": sender,
        "to": [email],
        "subject": "Your Stack Up sign-in code",
        "text": f"Your Stack Up verification code is {code}. It expires in 10 minutes.",
    }).encode()
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                logger.warning(
                    "Resend rejected an OTP email (HTTP %s, name=unknown, message=non-success response).",
                    response.status,
                )
                raise RuntimeError("Resend could not send the verification email. Check the Resend dashboard.")
    except urllib.error.HTTPError as error:
        error_name, error_message, content_type, excerpt = _read_resend_error(
            error, resend_api_key, code
        )
        if excerpt is not None:
            logger.warning(
                "Resend rejected an OTP email (HTTP %s, content_type=%s, response_excerpt=%s).",
                error.code,
                content_type,
                excerpt,
            )
        else:
            logger.warning(
                "Resend rejected an OTP email (HTTP %s, content_type=%s, name=%s, message=%s).",
                error.code,
                content_type,
                error_name,
                error_message,
            )
        raise RuntimeError(
            f"Resend could not send the verification email (HTTP {error.code}). "
            "Check the sender configuration and Resend dashboard."
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None)
        error_number = getattr(error, "errno", None) or getattr(reason, "errno", None)
        if error_number is None:
            logger.error("Resend OTP request failed because of a network error (%s).", type(error).__name__)
        else:
            logger.error("Resend OTP request failed because of a network error (errno=%s).", error_number)
        raise RuntimeError(
            "The email provider could not be reached. Check the backend network and Resend configuration."
        ) from None


def _send_sms_otp(phone, code):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    if not all((account_sid, auth_token, from_number)):
        raise RuntimeError("SMS OTP delivery is not configured on the server.")

    normalized_sender = re.sub(r"[\s().-]", "", from_number)
    if phone == normalized_sender:
        raise RuntimeError(
            "Enter your personal phone number. It must be different from the Twilio sender number."
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = urllib.parse.urlencode({
        "From": from_number,
        "To": phone,
        "Body": f"Your Stack Up verification code is {code}. It expires in 10 minutes.",
    }).encode()
    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    request.add_header("Authorization", "Basic " + base64.b64encode(
        f"{account_sid}:{auth_token}".encode()
    ).decode())
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError("SMS provider rejected the OTP message.")
    except urllib.error.HTTPError as error:
        try:
            provider_error = json.loads(error.read().decode("utf-8"))
            error_code = str(provider_error.get("code", ""))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            error_code = ""

        if error_code == "21266":
            message = "Enter your personal phone number. It must be different from the Twilio sender number."
        elif error_code in {"21608", "14111"}:
            message = "This Twilio trial account can only send OTPs to verified recipient numbers. Verify this number in Twilio Console, or upgrade the account."
        elif error_code in {"21606", "21607", "21660", "21661"}:
            message = "Twilio rejected the sender number. Check that TWILIO_PHONE_NUMBER is an SMS-capable number assigned to this Twilio account."
        elif error_code:
            message = f"Twilio could not send the OTP (error {error_code}). Check Twilio Console under Monitor > Logs > Messaging."
        else:
            message = "Twilio could not send the OTP. Check Twilio Console under Monitor > Logs > Messaging."
        raise RuntimeError(message) from error


def request_otp(contact, channel, create_account=False, username=None, password=None):
    if not can_request_otp(contact):
        raise RuntimeError("Please wait before requesting another code. You can request up to five codes per hour.")

    password_hash = hash_password(password) if create_account else None
    if create_account:
        username = normalize_username(username)
        if get_account_by_username(username):
            raise ValueError("That username is already in use. Choose another one.")
        existing_account = get_account_by_contact(contact, channel)
        if existing_account and (
            existing_account.get("username") or existing_account.get("password_hash")
        ):
            raise ValueError("An account already uses that email or phone number. Sign in instead.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = create_otp_challenge(
        contact, channel, code, create_account, username, password_hash
    )
    try:
        if channel == "email":
            _send_email_otp(contact, code)
        else:
            _send_sms_otp(contact, code)
    except Exception:
        invalidate_otp_challenge(challenge_id)
        raise


def verify_code(contact, code):
    return verify_otp_challenge(contact, str(code or "").strip())
