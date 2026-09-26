import os
from cryptography.fernet import Fernet
import requests

from .db import db
from .utils import now
from .workdrive import WorkDriveError


class ZohoMailClient:
    """Server-only Zoho Mail OAuth and account verification adapter."""

    record_id = "zoho_mail_oauth"

    def __init__(self):
        self.client_id = os.getenv("ZOHO_MAIL_CLIENT_ID") or os.getenv("ZOHO_CLIENT_ID")
        self.client_secret = os.getenv("ZOHO_MAIL_CLIENT_SECRET") or os.getenv("ZOHO_CLIENT_SECRET")
        self.redirect_uri = os.getenv("ZOHO_MAIL_REDIRECT_URI") or os.getenv("ZOHO_REDIRECT_URI")
        self.encryption_key = os.getenv("ZOHO_MAIL_TOKEN_ENCRYPTION_KEY") or os.getenv("ZOHO_TOKEN_ENCRYPTION_KEY")
        self.accounts_base = os.getenv("ZOHO_ACCOUNTS_BASE_URL") or "https://accounts.zoho.in"
        self.api_base = os.getenv("ZOHO_MAIL_API_BASE_URL") or "https://mail.zoho.in/api"
        self.scopes = os.getenv("ZOHO_MAIL_SCOPES", "ZohoMail.accounts.READ,ZohoMail.messages.CREATE")

    @property
    def record(self):
        return db().settings.find_one({"_id": self.record_id}) or {}

    @property
    def encrypted_refresh_token(self):
        return self.record.get("refresh_token_encrypted")

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.encryption_key and self.encrypted_refresh_token and self.record.get("account_id"))

    @property
    def missing(self):
        values = {"client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "token_encryption_key": self.encryption_key, "refresh_token": self.encrypted_refresh_token, "account_id": self.record.get("account_id")}
        return [key for key, value in values.items() if not value]

    def _cipher(self):
        if not self.encryption_key:
            raise WorkDriveError("ZOHO_MAIL_TOKEN_ENCRYPTION_KEY is not configured", "mail_missing_encryption_key")
        try:
            return Fernet(self.encryption_key.encode())
        except Exception as exc:
            raise WorkDriveError("Zoho Mail token encryption key is invalid", "mail_missing_encryption_key") from exc

    def authorization_url(self, state):
        from urllib.parse import urlencode
        if not self.client_id or not self.redirect_uri:
            raise WorkDriveError("Zoho Mail client ID and callback URL are not configured", "mail_incomplete_configuration")
        params = urlencode({"client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri, "scope": self.scopes, "access_type": "offline", "prompt": "consent", "state": state})
        return f"{self.accounts_base}/oauth/v2/auth?{params}"

    def _token_request(self, data):
        try:
            response = requests.post(f"{self.accounts_base}/oauth/v2/token", data=data, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho Mail OAuth service", "mail_token_exchange_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"Zoho Mail OAuth failed ({response.status_code})", "mail_token_exchange_failure")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError("Zoho Mail OAuth returned an invalid response", "mail_token_exchange_failure") from exc
        if not isinstance(payload, dict):
            raise WorkDriveError("Zoho Mail OAuth returned an invalid response", "mail_token_exchange_failure")
        return payload

    def exchange_code(self, code):
        payload = self._token_request({"code": code, "client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "grant_type": "authorization_code"})
        if payload.get("refresh_token"):
            encrypted = self._cipher().encrypt(payload["refresh_token"].encode()).decode()
            db().settings.update_one({"_id": self.record_id}, {"$set": {"refresh_token_encrypted": encrypted, "provider": "zoho_mail", "updated_at": now()}}, upsert=True)
        elif not self.encrypted_refresh_token:
            raise WorkDriveError("Zoho Mail did not return a refresh token; grant offline access and consent again", "mail_missing_refresh_token")
        return payload

    def access_token(self):
        if not self.client_id or not self.client_secret or not self.encrypted_refresh_token:
            raise WorkDriveError("Zoho Mail refresh-token configuration is incomplete", "mail_missing_refresh_token")
        refresh_token = self._cipher().decrypt(self.encrypted_refresh_token.encode()).decode()
        payload = self._token_request({"refresh_token": refresh_token, "client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "refresh_token"})
        if not payload.get("access_token"):
            raise WorkDriveError("Zoho Mail did not return an access token", "mail_token_exchange_failure")
        return payload["access_token"]

    def verify_account(self):
        token = self.access_token()
        try:
            response = requests.get(f"{self.api_base}/accounts", headers={"Authorization": f"Zoho-oauthtoken {token}"}, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho Mail account service", "mail_verification_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"Zoho Mail account verification failed ({response.status_code})", "mail_verification_failure")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError("Zoho Mail account verification returned an invalid response", "mail_verification_failure") from exc
        accounts = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(accounts, list) or not accounts:
            raise WorkDriveError("Zoho Mail returned no accessible account", "mail_verification_failure")
        account = accounts[0]
        account_id = account.get("accountId") or account.get("account_id") or account.get("id")
        email = account.get("emailAddress") or account.get("email") or account.get("mailId")
        if not account_id:
            raise WorkDriveError("Zoho Mail account response did not include an account ID", "mail_verification_failure")
        organization = account.get("organizationName") or account.get("organization")
        connected_at = self.record.get("connected_at") or now()
        db().settings.update_one({"_id": self.record_id}, {"$set": {"account_id": str(account_id), "account_email": email if isinstance(email, str) else None, "organization": organization if isinstance(organization, str) else None, "connected_at": connected_at, "verified_at": now(), "provider": "zoho_mail"}}, upsert=True)
        return {"account_id": str(account_id), "email": email if isinstance(email, str) else None, "organization": organization if isinstance(organization, str) else None}

    def send_message(self, to_address, subject, content, sender_name=None, reply_to=None):
        """Send one message through the verified account; callers own workflow decisions."""
        record = self.record
        account_id = record.get("account_id")
        from_address = record.get("account_email")
        if not account_id or not from_address:
            raise WorkDriveError("Zoho Mail account has not been verified", "mail_verification_failure")
        payload = {"fromAddress": from_address, "toAddress": to_address, "subject": subject, "content": content, "mailFormat": "html"}
        if sender_name:
            payload["fromName"] = sender_name
        if reply_to:
            payload["replyTo"] = reply_to
        try:
            response = requests.post(f"{self.api_base}/accounts/{account_id}/messages", headers={"Authorization": f"Zoho-oauthtoken {self.access_token()}", "Content-Type": "application/json"}, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho Mail send service", "mail_send_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"Zoho Mail send failed ({response.status_code})", "mail_send_failure")
        try:
            result = response.json()
        except ValueError as exc:
            raise WorkDriveError("Zoho Mail send returned an invalid response", "mail_send_failure") from exc
        db().settings.update_one({"_id": self.record_id}, {"$set": {"last_sent_at": now()}})
        return {"accepted": True, "provider_message_id": (result.get("data") or {}).get("messageId") if isinstance(result, dict) and isinstance(result.get("data"), dict) else None}
