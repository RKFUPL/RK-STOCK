import os
from io import BytesIO
from html import unescape
from cryptography.fernet import Fernet
import requests
from .db import db
from .utils import now


class WorkDriveError(RuntimeError):
    def __init__(self, message, kind="workdrive_error"):
        super().__init__(message)
        self.kind = kind


class WorkDriveClient:
    """Server-only Zoho WorkDrive adapter. Credentials never leave Flask."""

    def __init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET")
        api_base = (os.getenv("ZOHO_API_BASE_URL") or "https://www.zohoapis.com").rstrip("/")
        self.api_base = api_base if api_base.endswith("/workdrive/api/v1") else f"{api_base}/workdrive/api/v1"
        accounts_base = os.getenv("ZOHO_ACCOUNTS_BASE_URL")
        if not accounts_base:
            accounts_base = "https://accounts.zoho.in" if ".zohoapis.in" in self.api_base else "https://accounts.zoho.com"
        self.accounts_base = accounts_base
        self.team_id = os.getenv("ZOHO_WORKDRIVE_TEAM_ID")
        self.environment_root_folder_id = os.getenv("ZOHO_WORKDRIVE_ROOT_FOLDER_ID")
        self.root_folder_name = "STOCK&LINESHEET"
        self.redirect_uri = os.getenv("ZOHO_REDIRECT_URI")
        self.scopes = os.getenv("ZOHO_WORKDRIVE_SCOPES", "WorkDrive.files.CREATE,WorkDrive.files.READ,WorkDrive.files.UPDATE,WorkDrive.teamfolders.READ")

    @property
    def oauth_record(self):
        return db().settings.find_one({"_id": "workdrive_oauth"}) or {}

    @property
    def root_folder_id(self):
        return self.oauth_record.get("root_folder_id") or self.environment_root_folder_id

    @property
    def configured(self):
        return all((self.client_id, self.client_secret, self.team_id, self.root_folder_configured, self.redirect_uri, self.encryption_key, self.encrypted_refresh_token))

    @property
    def root_folder_configured(self):
        value = (self.root_folder_id or "").strip()
        return bool(value and value.lower() not in {"folder-id", "<folder-id>", "your-folder-id"} and not (value.startswith("<") and value.endswith(">")))

    @property
    def missing_configuration(self):
        values = {"client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "refresh_token": self.encrypted_refresh_token, "team_id": self.team_id, "root_folder_id": self.root_folder_configured, "token_encryption_key": self.encryption_key}
        return [key for key, value in values.items() if not value]

    @property
    def encryption_key(self):
        return os.getenv("ZOHO_TOKEN_ENCRYPTION_KEY")

    @property
    def encrypted_refresh_token(self):
        return self.oauth_record.get("refresh_token_encrypted")

    def _cipher(self):
        if not self.encryption_key:
            raise WorkDriveError("ZOHO_TOKEN_ENCRYPTION_KEY is not configured", "missing_encryption_key")
        try:
            return Fernet(self.encryption_key.encode())
        except Exception as exc:
            raise WorkDriveError("ZOHO_TOKEN_ENCRYPTION_KEY is invalid", "missing_encryption_key") from exc

    def store_refresh_token(self, refresh_token):
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise WorkDriveError("Zoho returned an empty refresh token; the existing token was preserved", "missing_refresh_token")
        encrypted = self._cipher().encrypt(refresh_token.encode()).decode()
        db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"refresh_token_encrypted": encrypted, "updated_at": now(), "provider": "zoho_workdrive"}}, upsert=True)

    def authorization_url(self, state):
        from urllib.parse import urlencode
        if not all((self.client_id, self.redirect_uri)):
            raise WorkDriveError("Zoho client ID and callback URL are not configured")
        params = urlencode({"client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri, "scope": self.scopes, "access_type": "offline", "prompt": "consent", "state": state})
        return f"{self.accounts_base}/oauth/v2/auth?{params}"

    def access_token(self):
        if not all((self.client_id, self.client_secret, self.redirect_uri)):
            raise WorkDriveError("Zoho OAuth client configuration is incomplete", "incomplete_configuration")
        if not self.encryption_key:
            raise WorkDriveError("ZOHO_TOKEN_ENCRYPTION_KEY is not configured", "missing_encryption_key")
        if not self.encrypted_refresh_token:
            raise WorkDriveError("Zoho refresh token is missing", "missing_refresh_token")
        refresh_token = self._cipher().decrypt(self.encrypted_refresh_token.encode()).decode()
        try:
            response = requests.post(f"{self.accounts_base}/oauth/v2/token", data={"refresh_token": refresh_token, "client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "refresh_token"}, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho OAuth token service", "token_exchange_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"Zoho OAuth failed ({response.status_code})", "token_exchange_failure")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError("Zoho OAuth returned an invalid response", "token_exchange_failure") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise WorkDriveError("Zoho OAuth did not return an access token", "token_exchange_failure")
        return payload["access_token"]

    def exchange_code(self, code):
        try:
            response = requests.post(f"{self.accounts_base}/oauth/v2/token", data={"code": code, "client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "grant_type": "authorization_code"}, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho OAuth token service", "token_exchange_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"Zoho authorization-code exchange failed ({response.status_code})", "token_exchange_failure")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError("Zoho authorization-code exchange returned an invalid response", "token_exchange_failure") from exc
        if not isinstance(payload, dict):
            raise WorkDriveError("Zoho authorization-code exchange returned an invalid response", "token_exchange_failure")
        if not payload.get("refresh_token"):
            existing = db().settings.find_one({"_id": "workdrive_oauth", "refresh_token_encrypted": {"$exists": True}})
            if existing:
                db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"refresh_token_reused_at": now()}})
                return payload
            raise WorkDriveError("Zoho did not return a refresh token; grant offline access and consent again", "missing_refresh_token")
        self.store_refresh_token(payload["refresh_token"])
        return payload

    def _headers(self, token):
        return {"Authorization": f"Zoho-oauthtoken {token}", "Accept": "application/vnd.api+json"}

    def _response_data(self, response, operation, kind):
        if not response.ok:
            raise WorkDriveError(f"{operation} failed ({response.status_code})", kind)
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError(f"{operation} returned an invalid response", kind) from exc
        if not isinstance(payload, dict):
            raise WorkDriveError(f"{operation} returned an invalid response", kind)
        return payload.get("data")

    @staticmethod
    def _folder_name(item):
        attributes = item.get("attributes") or {}
        return unescape(attributes.get("name") or attributes.get("display_attr_name") or attributes.get("display_html_name") or "").strip()

    def discover_root_folder(self):
        if not self.team_id:
            raise WorkDriveError("ZOHO_WORKDRIVE_TEAM_ID is not configured", "incomplete_configuration")
        token = self.access_token()
        try:
            response = requests.get(
                f"{self.api_base}/teams/{self.team_id}/teamfolders",
                headers=self._headers(token),
                params={"page[limit]": "50", "page[offset]": "0"},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho WorkDrive team-folder service", "folder_verification_failure") from exc
        items = self._response_data(response, "WorkDrive team-folder discovery", "folder_verification_failure")
        if not isinstance(items, list):
            raise WorkDriveError("WorkDrive team-folder discovery returned an invalid response", "folder_verification_failure")
        matches = [item for item in items if item.get("type") == "teamfolders" and self._folder_name(item).casefold() == self.root_folder_name.casefold()]
        if not matches:
            raise WorkDriveError(f"WorkDrive team folder {self.root_folder_name} was not found in the configured team", "folder_verification_failure")
        if len(matches) > 1:
            raise WorkDriveError(f"Multiple WorkDrive team folders named {self.root_folder_name} were found", "folder_verification_failure")
        folder_id = matches[0].get("id")
        if not folder_id:
            raise WorkDriveError("WorkDrive team-folder discovery returned a folder without an ID", "folder_verification_failure")
        return self.verify_root_folder(folder_id=folder_id, token=token)

    def verify_root_folder(self, folder_id=None, token=None):
        folder_id = folder_id or self.root_folder_id
        if not self.root_folder_configured and not folder_id:
            raise WorkDriveError("WorkDrive root folder is not configured", "folder_verification_failure")
        token = token or self.access_token()
        try:
            response = requests.get(f"{self.api_base}/teamfolders/{folder_id}", headers=self._headers(token), timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho WorkDrive root-folder service", "folder_verification_failure") from exc
        data = self._response_data(response, "WorkDrive root-folder verification", "folder_verification_failure")
        item = data[0] if isinstance(data, list) and data else data
        if not isinstance(item, dict) or item.get("id") != folder_id or item.get("type") != "teamfolders":
            raise WorkDriveError("WorkDrive root-folder verification returned the wrong resource", "folder_verification_failure")
        attributes = item.get("attributes") or {}
        parent_id = attributes.get("parent_id")
        if parent_id and parent_id != self.team_id:
            raise WorkDriveError("WorkDrive root folder does not belong to the configured team", "folder_verification_failure")
        if self._folder_name(item).casefold() != self.root_folder_name.casefold():
            raise WorkDriveError(f"Verified WorkDrive folder is not named {self.root_folder_name}", "folder_verification_failure")
        if (attributes.get("capabilities") or {}).get("can_read") is False:
            raise WorkDriveError("Authorized Zoho account cannot read the configured WorkDrive folder", "folder_verification_failure")
        return {"id": folder_id, "name": self.root_folder_name, "team_id": self.team_id}

    def upload(self, path, parent_id=None, filename=None):
        token = self.access_token()
        with open(path, "rb") as stream:
            try:
                response = requests.post(f"{self.api_base}/upload", headers={"Authorization": f"Zoho-oauthtoken {token}"}, data={"parent_id": parent_id or self.root_folder_id, "override-name-exist": "false"}, files={"content": (filename or os.path.basename(path), stream)}, timeout=120)
            except requests.RequestException as exc:
                raise WorkDriveError("Unable to reach Zoho WorkDrive upload service") from exc
        if not response.ok:
            raise WorkDriveError(f"WorkDrive upload failed ({response.status_code})")
        return response.json()

    def upload_bytes(self, content, parent_id, filename, content_type="application/octet-stream"):
        token = self.access_token()
        try:
            response = requests.post(f"{self.api_base}/upload", headers={"Authorization": f"Zoho-oauthtoken {token}"}, data={"parent_id": parent_id, "override-name-exist": "true"}, files={"content": (filename, BytesIO(content), content_type)}, timeout=120)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho WorkDrive upload service", "file_upload_failure") from exc
        if not response.ok:
            raise WorkDriveError(f"WorkDrive upload failed ({response.status_code})", "file_upload_failure")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkDriveError("WorkDrive upload returned an invalid response", "file_upload_failure") from exc
        return payload

    def create_folder(self, name, parent_id):
        token = self.access_token()
        payload = {"data": {"type": "files", "attributes": {"name": name, "parent_id": parent_id, "type": "folder"}}}
        try:
            response = requests.post(f"{self.api_base}/files", headers={**self._headers(token), "Content-Type": "application/vnd.api+json"}, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise WorkDriveError("Unable to reach Zoho WorkDrive folder service", "folder_creation_failure") from exc
        data = self._response_data(response, "WorkDrive folder creation", "folder_creation_failure")
        item = data[0] if isinstance(data, list) and data else data
        if not isinstance(item, dict) or not item.get("id"):
            raise WorkDriveError("WorkDrive folder creation returned an invalid response", "folder_creation_failure")
        return item

    def ensure_folder_path(self, names):
        parent = self.root_folder_id
        folder_ids = []
        for name in names:
            item = self.create_folder(name, parent)
            parent = item.get("id")
            folder_ids.append(parent)
        return parent, folder_ids

    def ensure_managed_folder(self, key, name, parent_id):
        record = db().workdrive_folders.find_one({"key": key})
        if record and record.get("folder_id"):
            return record["folder_id"]
        item = self.create_folder(name, parent_id)
        folder_id = item["id"]
        db().workdrive_folders.update_one({"key": key}, {"$setOnInsert": {"key": key, "created_at": now()}, "$set": {"folder_id": folder_id, "name": name, "parent_id": parent_id, "verified_at": now()}}, upsert=True)
        return folder_id
