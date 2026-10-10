import os
import re
import json
import base64
import hashlib
import secrets
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from database.database import (
    can_request_otp,
    create_otp_challenge,
    get_account_by_contact,
    get_account_by_username,
    invalidate_otp_challenge,
    verify_otp_challenge,
)


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
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM_EMAIL") or username
    if not all((host, username, password, sender)):
        raise RuntimeError("Email OTP delivery is not configured on the server.")

    message = EmailMessage()
    message["Subject"] = "Your Stack Up sign-in code"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"Your Stack Up verification code is {code}. It expires in 10 minutes."
    )
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(message)


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
