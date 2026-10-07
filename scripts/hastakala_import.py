"""One-time, authenticated Hastakala catalog import helper.

This script is intentionally API-only.  It never imports the Flask app, opens
MongoDB, accesses WorkDrive, or uploads to Cloudinary.  Default mode is a
catalog/media dry-run; pass --apply explicitly to perform the approved writes.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import requests


SOURCE_PDF = r"C:\Users\athul\Downloads\RK Hastakala Lookbook 1.pdf"
COLLECTION_NAME = "Hastakala"
COLLECTION_CODE = "HAS"
COLLECTION_SLUG = "collections-of-hastakala"
EXPECTED_DB = "RK_TEST_DB"
CK163 = "CK163"
MEDIA = [
    "https://workdrive.zoho.in/file/gl0saaed54485a8e944b79075d32bc059461c",
    "https://workdrive.zoho.in/file/gl0sacd9917df52794c2f9a60262dc9501d98",
    "https://workdrive.zoho.in/file/gl0sa73932dcd17e44f5ba81a450265422e1c",
]

# These are the previously verified, unambiguous PDF entries.  The PDF path
# is still checked at runtime; no alternate SKU or generated description is
# accepted by this script.
SOURCE_PRODUCTS = [
    ("CK150", "Heavy Blazer , Heavy Bell Bottom"),
    ("CK149", "Heavy Sharara , V Neck Jacket Heavy , Inner"),
    ("CK147", "Bralette, Long Jacket And Sharara"),
    ("CK166", "Heavy Jumpsuit"),
    ("CK148", "Bralette, Slit Jacket And Heavy Saree"),
    ("CK165", "Power Shoulder Jacket+Bralette+ Bell Bottom"),
    ("CK173", "Drape Saree + Blouse"),
    ("CK157", "Drape Saree + Corset"),
    ("CK172", "Fishcut Drape Saree + Blouse"),
    ("CK154", "Asymetrical Top And Drape Skirt"),
    ("CK168", "Hankerchief Top, Drape Skirt"),
    ("CK167", "Asymetrical One Shoulder Heavy Top + Drape Skirt"),
    ("CK159", "Short Slit Cape , Brallete , Sharara"),
    ("CK179", "Two Layered Jacket + Sharara + Bralette"),
    ("CK156", "Drape Saree + Blouse"),
    ("CK161", "Cut- Out Top + Drape Skirt"),
    ("CK169", "Bustier And Double Layered Lehenga With Attached Drape."),
    ("CK141", "Bustier, Slit Jacket And Saree"),
    ("CK160", "Blouse And Saree"),
    ("CK152", "Bustier, Long Jacket And Drape Skirt"),
    ("CK52A", "Bralette ,Cape And Drape Skirt"),
    ("CK171", "Bustier And Draped Saree"),
    ("CK155", "Layered Saree + Heavy Pallu + Blouse"),
]


class ImportFailure(RuntimeError):
    pass


def canonical_workdrive_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ImportFailure("invalid WorkDrive URL in import definition")
    if parsed.username or parsed.password or parsed.hostname.lower() != "workdrive.zoho.in":
        raise ImportFailure("unapproved WorkDrive URL in import definition")
    if parsed.port not in (None, 443) or not parsed.path:
        raise ImportFailure("invalid WorkDrive URL in import definition")
    return urlunsplit(("https", parsed.hostname.lower(), parsed.path, parsed.query, ""))


def safe_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(message, str) and message:
            return message[:240]
    except ValueError:
        pass
    return f"HTTP {response.status_code}"


class Api:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, **kwargs):
        try:
            response = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
        except requests.RequestException as exc:
            raise ImportFailure(f"API request failed ({type(exc).__name__})") from exc
        if not response.ok:
            raise ImportFailure(f"{method} {path}: {safe_error(response)}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ImportFailure(f"{method} {path}: invalid JSON response") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safe Hastakala API import")
    parser.add_argument("--base-url", default=os.environ.get("RK_STOCK_BASE_URL"), help="local RK-STOCK API base URL")
    parser.add_argument("--db-name", default=os.environ.get("RK_STOCK_DB_NAME"), help="must be RK_TEST_DB")
    parser.add_argument("--source-pdf", default=SOURCE_PDF)
    parser.add_argument("--apply", action="store_true", help="perform catalog/media writes; default is dry-run")
    return parser.parse_args()


def require_safe_target(args: argparse.Namespace) -> None:
    if args.db_name != EXPECTED_DB:
        raise ImportFailure("--db-name/RK_STOCK_DB_NAME must be RK_TEST_DB")
    if not args.base_url:
        raise ImportFailure("set RK_STOCK_BASE_URL or pass --base-url")
    parsed = urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port not in (None, 5006):
        raise ImportFailure("base URL must be the local RK-STOCK API on port 5006")
    if not os.path.isfile(args.source_pdf):
        raise ImportFailure("authoritative Hastakala PDF was not found")
    if len({code for code, _ in SOURCE_PRODUCTS}) != len(SOURCE_PRODUCTS) or CK163 in {code for code, _ in SOURCE_PRODUCTS}:
        raise ImportFailure("source product identity safety check failed")


def login_for_apply(api: Api) -> None:
    password = os.environ.get("RK_ADMIN_PASSWORD")
    if not password:
        raise ImportFailure("RK_ADMIN_PASSWORD is required for --apply")
    # The password and resulting token remain in process memory only.
    payload = api.call("POST", "/api/auth/login", json={"email": "aakaar-test-admin@example.com", "password": password})
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise ImportFailure("admin login did not return an authentication token")
    api.session.headers["Authorization"] = f"Bearer {token}"


def verify_admin(api: Api) -> dict:
    health = api.call("GET", "/api/health")
    if health.get("status") != "ok":
        raise ImportFailure("RK-STOCK health check did not report ok")
    identity = api.call("GET", "/api/auth/me")
    permissions = set(identity.get("effective_permissions") or [])
    if identity.get("role") != "admin" or "*" not in permissions:
        raise ImportFailure("authenticated user is not an active admin")
    return identity


def find_collection(api: Api) -> tuple[dict, list[dict]]:
    items = api.call("GET", "/api/collections").get("items") or []
    matches = [item for item in items if item.get("name", "").casefold() == COLLECTION_NAME.casefold() or item.get("code") == COLLECTION_CODE or item.get("slug") == COLLECTION_SLUG]
    if len(matches) != 1:
        raise ImportFailure(f"expected exactly one active Hastakala collection, found {len(matches)}")
    collection = matches[0]
    if not collection.get("active", True) or not collection.get("_id"):
        raise ImportFailure("Hastakala collection is not active or has no ID")
    return collection, items


def products_by_code(api: Api) -> dict[str, list[dict]]:
    items = api.call("GET", "/api/products?limit=500").get("items") or []
    result: dict[str, list[dict]] = {}
    for item in items:
        item_id = str(item.get("_id") or item.get("id") or "")
        key = item.get("product_code")
        if isinstance(key, str) and key.strip():
            bucket = result.setdefault(key.strip().upper(), [])
            if not any(str(existing.get("_id") or existing.get("id") or "") == item_id for existing in bucket):
                bucket.append(item)
    return result


def existing_media(product: dict, permalink: str) -> dict | None:
    target = canonical_workdrive_url(permalink)
    for item in product.get("images") or product.get("media") or []:
        if not isinstance(item, dict) or item.get("provider") != "zoho_workdrive":
            continue
        candidate = item.get("permalink") or item.get("url")
        if candidate and canonical_workdrive_url(candidate) == target:
            return item
    return None


def validate_ck150_media(product: dict) -> None:
    if not product:
        return
    links = []
    for item in product.get("images") or product.get("media") or []:
        if isinstance(item, dict) and item.get("provider") == "zoho_workdrive":
            candidate = item.get("permalink") or item.get("url")
            if not candidate:
                raise ImportFailure("CK150 has a WorkDrive media record without a permalink")
            links.append(canonical_workdrive_url(candidate))
    if len(links) != len(set(links)):
        raise ImportFailure("CK150 has duplicate existing WorkDrive media relationships")
    expected = {canonical_workdrive_url(value) for value in MEDIA}
    unexpected = set(links) - expected
    if unexpected:
        raise ImportFailure("CK150 has unexpected existing WorkDrive media; review before applying")


def collection_ids(product: dict, hastakala_id: str) -> list[str]:
    values = [str(value) for value in (product.get("collection_ids") or [])]
    for item in product.get("collections") or []:
        if isinstance(item, dict) and item.get("id"):
            values.append(str(item["id"]))
    if product.get("collection_id"):
        values.append(str(product["collection_id"]))
    return list(dict.fromkeys([*values, str(hastakala_id)]))


def plan(api: Api, collection: dict, products: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    actions = []
    seen_ids = set()
    for code, description in SOURCE_PRODUCTS:
        matches = [item for item in products.get(code.upper(), []) if str(item.get("_id") or item.get("id")) not in seen_ids]
        if len(matches) > 1:
            raise ImportFailure(f"duplicate existing product identity for {code}")
        product = matches[0] if matches else None
        if product:
            seen_ids.add(str(product.get("_id") or product.get("id")))
        action = {"code": code, "description": description, "product": product, "collection_ids": collection_ids(product or {}, str(collection["_id"]))}
        action["price_override"] = code == "CK150"
        if code == "CK150":
            validate_ck150_media(product)
        action["media_existing"] = [] if not product else [existing_media(product, url) for url in MEDIA]
        actions.append(action)
    return actions, {"collection": collection, "product_count": len(products)}


def apply_action(api: Api, action: dict, collection: dict) -> str:
    code, description, product = action["code"], action["description"], action["product"]
    target_sku = f"HK-{code}-A"
    fields = {"name": description, "description": description, "sku": target_sku, "product_code": code, "collection_ids": action["collection_ids"]}
    if action["price_override"]:
        fields.update({"selling_price": 262884, "base_currency": "INR", "tax_inclusive": True})
    if product:
        product_id = str(product.get("_id") or product.get("id"))
        existing_collection_ids = collection_ids(product, str(collection["_id"]))
        needs_update = (
            product.get("name") != description
            or product.get("description") != description
            or str(product.get("sku") or "").upper() != target_sku
            or str(product.get("product_code") or "") != code
            or [str(value) for value in (product.get("collection_ids") or [])] != existing_collection_ids
            or (action["price_override"] and (product.get("selling_price") != 262884 or product.get("base_currency") != "INR" or product.get("tax_inclusive") is not True))
        )
        if needs_update:
            api.call("PATCH", f"/api/products/{product_id}", json=fields)
            status = "updated"
        else:
            status = "unchanged"
    else:
        create_fields = {"name": description, "description": description, "sku": target_sku, "product_code": code, "collection_id": str(collection["_id"]), "base_currency": "INR", "tax_inclusive": True}
        if action["price_override"]:
            create_fields["selling_price"] = 262884
        product_id = str(api.call("POST", "/api/products", json=create_fields).get("id") or "")
        if not product_id:
            raise ImportFailure(f"product creation returned no ID for {code}")
        # Ensure the same collection API representation is used for all products.
        api.call("PATCH", f"/api/products/{product_id}", json={"collection_ids": action["collection_ids"]})
        status = "created"
    refreshed = next((item for item in (api.call("GET", "/api/products?limit=500").get("items") or []) if str(item.get("_id") or item.get("id")) == product_id), None)
    if not refreshed:
        raise ImportFailure(f"product {code} was not returned after write")
    if code == "CK150":
        for position, permalink in enumerate(MEDIA):
            current = existing_media(refreshed, permalink)
            if current:
                api.call("PATCH", f"/api/products/{product_id}/media/{current['id']}", json={"permalink": permalink, "position": position, "is_primary": position == 0})
            else:
                api.call("POST", f"/api/products/{product_id}/media", json={"provider": "zoho_workdrive", "type": "image", "permalink": permalink, "position": position, "is_primary": position == 0})
            refreshed = next((item for item in (api.call("GET", "/api/products?limit=500").get("items") or []) if str(item.get("_id") or item.get("id")) == product_id), refreshed)
    return status


def main() -> int:
    args = parse_args()
    try:
        require_safe_target(args)
        api = Api(args.base_url)
        if args.apply:
            login_for_apply(api)
        elif os.environ.get("RK_TEST_TOKEN"):
            api = Api(args.base_url, os.environ["RK_TEST_TOKEN"])
        else:
            raise ImportFailure("dry-run requires RK_TEST_TOKEN to avoid login/session writes; --apply uses RK_ADMIN_PASSWORD")
        identity = verify_admin(api)
        collection, _ = find_collection(api)
        products = products_by_code(api)
        actions, _ = plan(api, collection, products)
        if args.apply:
            counts = {"created": 0, "updated": 0, "unchanged": 0}
            for action in actions:
                counts[apply_action(api, action, collection)] += 1
            print(f"Hastakala import | Environment: {args.db_name} | Mode: APPLY")
            print(f"Admin authenticated | unique source products: {len(SOURCE_PRODUCTS)} | created: {counts['created']} | updated: {counts['updated']} | unchanged: {counts['unchanged']}")
            print("CK163 skipped: 1 | CK150 media: verified through structured API")
        else:
            creates = sum(1 for action in actions if action["product"] is None)
            updates = len(actions) - creates
            print(f"Environment: {args.db_name}")
            print("Mode: DRY RUN")
            print("")
            print("Products:")
            for code, description in SOURCE_PRODUCTS:
                print(f"{code} | {description}")
            print("")
            print("CK163 | SKIPPED | conflicting source descriptions")
            print("")
            print("CK150 pricing:")
            print("Price: INR 262884")
            print("Tax inclusive: true")
            print("")
            print("CK150 WorkDrive media:")
            for position, permalink in enumerate(MEDIA, start=1):
                print(f"{position}. {permalink}")
            print("")
            print("Catalog writes: 0")
            print("Media writes: 0")
            print("Collection writes: 0")
            print("Inventory writes: 0")
            print("Stock writes: 0")
            print("Product writes: 0")
            print("")
            print("DRY RUN COMPLETE — NO DATA WRITES PERFORMED")
        return 0
    except ImportFailure as exc:
        print(f"Hastakala import aborted: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
