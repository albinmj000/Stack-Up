# Account sign-in setup

Stack Up accounts use a unique username and password to sign in. Account
creation also verifies an email address or international phone number with a
one-time code. Email delivery uses SMTP; SMS delivery uses Twilio. Configure
at least one provider in the backend environment before users create accounts.

## Email (SMTP)

Set these backend environment variables:

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM_EMAIL=your-verified-sender@example.com
```

## SMS (Twilio)

Set these backend environment variables:

```text
TWILIO_ACCOUNT_SID=your-account-sid
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+12345678900
```

Phone numbers entered by users must include the country code, for example
`+91 98765 43210`.

## Cookie security

For local HTTP development, leave `COOKIE_SECURE` unset or set it to `false`.
For an HTTPS deployment, set:

```text
COOKIE_SECURE=true
```

The Vite development server forwards `/api` requests to the FastAPI server at
`http://127.0.0.1:8000`. Production deployments need to route `/api` to the
backend as well.

## WhatsApp webhook verification

If you use the WhatsApp integration, configure both values in the backend
environment. `WHATSAPP_VERIFY_TOKEN` is the value you choose and enter in
Meta's webhook setup. `WHATSAPP_APP_SECRET` is the App Secret from your Meta
developer app; the backend uses it to verify Meta's `X-Hub-Signature-256`
header before processing messages.

```text
WHATSAPP_VERIFY_TOKEN=choose-a-long-random-value
WHATSAPP_APP_SECRET=your-meta-app-secret
```

The WhatsApp POST webhook is rejected until `WHATSAPP_APP_SECRET` is
configured. Keep both values private and restart the backend after changing
them.

Codes expire after 10 minutes, allow up to five verification attempts, and
requesting a new code is limited to once per minute and five times per hour.
Only a salted hash of each code and a hash of each login session token are
stored in SQLite. Each email and each phone number can belong to only one
account. Passwords are stored as salted PBKDF2 hashes. Usernames are unique,
case-insensitively, and must be 3–24 letters, numbers, dots, underscores, or
dashes. Passwords must be 8–128 characters. Existing OTP-only accounts can
choose **Create account**, enter their already verified email or phone, and
set a username and password to add those credentials to the account.

Uploaded PDFs (up to 25 MB) and their parsed transactions are stored with the
account's statement record in SQLite. The Statement History page can download
the original PDF for statements uploaded after PDF storage was added. Keep
`stack_up.db` private; it contains both statements and account data.
