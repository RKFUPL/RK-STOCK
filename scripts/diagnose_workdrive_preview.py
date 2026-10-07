"""Read-only local diagnostic for the existing WorkDrive preview flow.

Run this from the repository root on the machine that has the local OAuth
configuration and RK_TEST_DB. This script deliberately refuses other database
names and never prints credentials, tokens, headers, or .env contents.
"""

import base64
import json
import os
import re
import sys
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
load_dotenv(os.path.join(ROOT, ".env"), override=False)

from app.config import Config  # noqa: E402
from app.workdrive import WorkDriveClient, WorkDriveError  # noqa: E402


RESOURCE_IDS = (
    "gl0saeed54485a8e944f5fac8aee1bafcfd68a",
    "gl0sa9dc0ab6361f1415f846d788c40abe4c1",
    "gl0sa73932dcd17e44f5ba81a450265422e1c",
    "gl0sacd9917df52794c2f9a60262dc9501d98",
)


def yes(value):
    return "yes" if value else "no"


def safe_text(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:300] or "none"


def error_fields(payload):
    code = "none"
    message = "none"
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first = errors[0]
            code = first.get("id") or first.get("code") or "none"
            message = first.get("title") or first.get("detail") or first.get("message") or "none"
        elif payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                code = error.get("code") or error.get("id") or "none"
                message = error.get("message") or error.get("description") or "none"
            else:
                message = error
        elif payload.get("message"):
            message = payload["message"]
    return safe_text(code), safe_text(message)


def approved_preview_host(hostname):
    return bool(
        hostname
        and (
            hostname in {
                "zoho.com", "zoho.in", "zohoapis.com", "zohoapis.in",
                "www.zohoapis.com", "www.zohoapis.in",
                "in-previewengine.nimbuspop.com",
                "in-previewenginepublic.nimbuspop.com",
            }
            or hostname.endswith(".zoho.com")
            or hostname.endswith(".zoho.in")
        )
    )


def print_error(exc):
    status = getattr(exc, "status_code", None) or "unavailable"
    code = getattr(exc, "provider_code", None) or getattr(exc, "kind", None) or "none"
    print("AUTHENTICATION FAILED" if getattr(exc, "kind", "") in {"incomplete_configuration", "missing_encryption_key", "missing_refresh_token", "token_exchange_failure"} else "PREVIEWINFO ERROR")
    print(f"HTTP STATUS: {status}")
    print(f"SAFE ERROR CODE: {safe_text(code)}")
    print(f"SAFE ERROR MESSAGE: {safe_text(exc)}")


def main():
    if os.getenv("MONGO_DB", Config.MONGO_DB) != "RK_TEST_DB":
        print("SAFE CONFIGURATION CHECK FAILED: MONGO_DB must be RK_TEST_DB")
        return 2
    # Match Flask Config: MONGO_URI has a safe local default, while the
    # WorkDrive client itself validates the OAuth prerequisites below.
    required = ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_TOKEN_ENCRYPTION_KEY")
    if any(not os.getenv(name) for name in required):
        print("AUTHENTICATION FAILED")
        print("HTTP STATUS: unavailable")
        print("SAFE ERROR CODE: incomplete_configuration")
        print("SAFE ERROR MESSAGE: required local test configuration is missing")
        return 2

    # Attach the existing configured database to a minimal Flask context. This
    # does not call create_app(), ensure_indexes(), or perform any DB writes.
    app = Flask(__name__)
    app.config.from_object(Config)
    mongo = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=app.config.get("MONGO_SERVER_SELECTION_TIMEOUT_MS", 30000))
    app.extensions["mongo_client"] = mongo
    app.extensions["mongo_db"] = mongo["RK_TEST_DB"]

    try:
        with app.app_context():
            client = WorkDriveClient()
            token = client.access_token()
            for resource_id in RESOURCE_IDS:
                diagnose_resource(client, token, resource_id)
    except WorkDriveError as exc:
        print_error(exc)
        return 1
    except requests.RequestException as exc:
        print("AUTHENTICATION FAILED")
        print("HTTP STATUS: unavailable")
        print("SAFE ERROR CODE: network_failure")
        print(f"SAFE ERROR MESSAGE: {type(exc).__name__}")
        return 1
    finally:
        mongo.close()
    return 0


def diagnose_resource(client, token, resource_id):
    endpoint = f"{client.api_base}/files/{resource_id}/previewinfo"
    print(f"RESOURCE: {resource_id}")
    try:
        response = requests.get(endpoint, headers=client._headers(token), timeout=30)
    except requests.RequestException as exc:
        print("PREVIEWINFO STATUS: unavailable")
        print("CONTENT TYPE: none")
        print("JSON KEYS: []")
        print("ERROR CODE: network_failure")
        print(f"ERROR MESSAGE: {type(exc).__name__}")
        return
    content_type = response.headers.get("Content-Type", "none").split(";", 1)[0]
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    attrs = data.get("attributes") if isinstance(data, dict) else {}
    if not isinstance(attrs, dict):
        attrs = {}
    code, message = error_fields(payload)
    print(f"PREVIEWINFO STATUS: {response.status_code}")
    print(f"CONTENT TYPE: {content_type}")
    print(f"JSON KEYS: {sorted(payload.keys()) if isinstance(payload, dict) else []}")
    print(f"HAS preview_url: {yes(bool(attrs.get('preview_url')))}")
    print(f"HAS preview_data_url: {yes(bool(attrs.get('preview_data_url')))}")
    print(f"HAS thumbnail_url: {yes(bool(attrs.get('thumbnail_url')))}")
    print(f"ERROR CODE: {code}")
    print(f"ERROR MESSAGE: {message}")

    for field in ("preview_url", "thumbnail_url"):
        candidate = attrs.get(field)
        if not candidate or not isinstance(candidate, str):
            continue
        parsed = urlsplit(candidate)
        print(f"{field} HOST APPROVED: {yes(parsed.scheme == 'https' and approved_preview_host(parsed.hostname) and not parsed.username and not parsed.password)}")
        if parsed.scheme != "https" or not approved_preview_host(parsed.hostname) or parsed.username or parsed.password:
            continue
        try:
            fetched = requests.get(candidate, headers=client._headers(token), timeout=30)
            fetched_type = fetched.headers.get("Content-Type", "none").split(";", 1)[0]
            print(f"{field.upper()} FETCH STATUS: {fetched.status_code}")
            print(f"{field.upper()} CONTENT TYPE: {fetched_type}")
            print(f"{field.upper()} CONTENT LENGTH: {fetched.headers.get('Content-Length', len(fetched.content or b''))}")
            print(f"{field.upper()} IS IMAGE: {yes(fetched.ok and fetched_type.startswith('image/'))}")
        except requests.RequestException as exc:
            print(f"{field.upper()} FETCH STATUS: unavailable")
            print(f"{field.upper()} CONTENT TYPE: none")
            print(f"{field.upper()} CONTENT LENGTH: none")
            print(f"{field.upper()} IS IMAGE: no ({type(exc).__name__})")

    data_url = attrs.get("preview_data_url")
    if isinstance(data_url, str) and data_url.startswith("data:"):
        header, encoded = data_url.split(",", 1) if "," in data_url else ("", "")
        mime = header[5:].split(";", 1)[0] if header.startswith("data:") else "none"
        try:
            decoded = base64.b64decode(encoded, validate=True)
            is_image = mime.startswith("image/") and bool(decoded)
            print("PREVIEW DATA URL PRESENT: yes")
            print(f"DATA MIME TYPE: {mime}")
            print(f"DECODED BYTES: {len(decoded)}")
            print(f"IS IMAGE: {yes(is_image)}")
        except (ValueError, TypeError):
            print("PREVIEW DATA URL PRESENT: yes")
            print(f"DATA MIME TYPE: {mime}")
            print("DECODED BYTES: invalid")
            print("IS IMAGE: no")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
