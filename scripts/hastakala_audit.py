"""Read-only post-import audit for the local Hastakala API state."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import requests


BASE_URL = "http://127.0.0.1:5006"
EXPECTED_DB = "RK_TEST_DB"
EXPECTED = {
    "CK150": "Heavy Blazer , Heavy Bell Bottom",
    "CK149": "Heavy Sharara , V Neck Jacket Heavy , Inner",
    "CK147": "Bralette, Long Jacket And Sharara",
    "CK166": "Heavy Jumpsuit",
    "CK148": "Bralette, Slit Jacket And Heavy Saree",
    "CK165": "Power Shoulder Jacket+Bralette+ Bell Bottom",
    "CK173": "Drape Saree + Blouse",
    "CK157": "Drape Saree + Corset",
    "CK172": "Fishcut Drape Saree + Blouse",
    "CK154": "Asymetrical Top And Drape Skirt",
    "CK168": "Hankerchief Top, Drape Skirt",
    "CK167": "Asymetrical One Shoulder Heavy Top + Drape Skirt",
    "CK159": "Short Slit Cape , Brallete , Sharara",
    "CK179": "Two Layered Jacket + Sharara + Bralette",
    "CK156": "Drape Saree + Blouse",
    "CK161": "Cut- Out Top + Drape Skirt",
    "CK169": "Bustier And Double Layered Lehenga With Attached Drape.",
    "CK141": "Bustier, Slit Jacket And Saree",
    "CK160": "Blouse And Saree",
    "CK152": "Bustier, Long Jacket And Drape Skirt",
    "CK52A": "Bralette ,Cape And Drape Skirt",
    "CK171": "Bustier And Draped Saree",
    "CK155": "Layered Saree + Heavy Pallu + Blouse",
}
MEDIA = [
    "https://workdrive.zoho.in/file/gl0saaed54485a8e944b79075d32bc059461c",
    "https://workdrive.zoho.in/file/gl0sacd9917df52794c2f9a60262dc9501d98",
    "https://workdrive.zoho.in/file/gl0sa73932dcd17e44f5ba81a450265422e1c",
]


def canonical(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        return value.strip()
    return urlunsplit(("https", parsed.hostname.lower(), parsed.path, parsed.query, ""))


def fail(message: str) -> None:
    print(f"Audit aborted: {message}", file=sys.stderr)
    raise SystemExit(2)


def get(session: requests.Session, path: str):
    try:
        response = session.get(f"{BASE_URL}{path}", timeout=20)
    except requests.RequestException as exc:
        fail(f"{path} request failed ({type(exc).__name__})")
    if not response.ok:
        try:
            message = response.json().get("error", f"HTTP {response.status_code}")
        except ValueError:
            message = f"HTTP {response.status_code}"
        fail(f"{path}: {str(message)[:240]}")
    try:
        return response.json()
    except ValueError:
        fail(f"{path}: invalid JSON response")


def product_code(product: dict) -> str:
    return str(product.get("product_code") or "").strip().upper()


def expected_sku(code: str) -> str:
    return f"HK-{code}-A"


def collection_ids(product: dict) -> set[str]:
    values = {str(value) for value in (product.get("collection_ids") or [])}
    values.update(str(item["id"]) for item in product.get("collections") or [] if isinstance(item, dict) and item.get("id"))
    if product.get("collection_id"):
        values.add(str(product["collection_id"]))
    return values


def price_state(product: dict) -> str:
    value = product.get("selling_price", product.get("price"))
    currency = product.get("base_currency", product.get("currency")) or "unset"
    return f"{value if value is not None else 'unset'} {currency} tax_inclusive={product.get('tax_inclusive')}"


def main() -> int:
    if os.environ.get("RK_STOCK_DB_NAME") != EXPECTED_DB:
        fail("RK_STOCK_DB_NAME must be RK_TEST_DB")
    token = os.environ.get("RK_TEST_TOKEN")
    if not token:
        fail("RK_TEST_TOKEN is missing")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    products = get(session, "/api/products?limit=500").get("items") or []
    collections = get(session, "/api/collections?include_archived=true").get("items") or []
    variants = get(session, "/api/inventory/variants?limit=500").get("items") or []
    balances = get(session, "/api/stock?limit=500").get("items") or []
    ledger = get(session, "/api/stock/ledger?limit=500").get("items") or []

    hastakala = [item for item in collections if item.get("name", "").casefold() == "hastakala" or item.get("code") == "HAS" or item.get("slug") == "collections-of-hastakala"]
    if len(hastakala) != 1:
        fail(f"expected one Hastakala collection, found {len(hastakala)}")
    collection_id = str(hastakala[0].get("_id") or hastakala[0].get("id"))
    by_code: dict[str, list[dict]] = {}
    for product in products:
        key = product_code(product)
        if key:
            by_code.setdefault(key, []).append(product)

    missing = sorted(set(EXPECTED) - set(by_code))
    duplicate = {key: len(value) for key, value in by_code.items() if key in EXPECTED and len(value) > 1}
    unexpected = sorted({key for key in by_code if key.startswith("CK")} - set(EXPECTED) - {"CK163"})
    ck163 = "PRESENT" if "CK163" in by_code else "ABSENT"
    membership_missing = [key for key in EXPECTED if not by_code.get(key) or collection_id not in collection_ids(by_code[key][0])]
    sku_mismatches = {
        key: by_code[key][0].get("sku")
        for key in EXPECTED
        if by_code.get(key) and by_code[key][0].get("sku") != expected_sku(key)
    }
    duplicate_skus = {
        sku: sum(1 for product in products if str(product.get("sku") or "").strip().upper() == sku)
        for sku in {expected_sku(key) for key in EXPECTED}
        if sum(1 for product in products if str(product.get("sku") or "").strip().upper() == sku) > 1
    }

    ck150 = by_code.get("CK150", [None])[0]
    media = []
    if ck150:
        media = [item for item in (ck150.get("images") or ck150.get("media") or []) if isinstance(item, dict) and item.get("provider") == "zoho_workdrive"]
    canonical_media = [canonical(str(item.get("permalink") or item.get("url") or "")) for item in media]
    expected_media = [canonical(value) for value in MEDIA]
    media_duplicates = len(canonical_media) != len(set(canonical_media))
    media_ok = (
        len(media) == 3
        and canonical_media == expected_media
        and all(item.get("type") == "image" and int(item.get("position", -1)) == index for index, item in enumerate(media))
        and sum(bool(item.get("is_primary") or item.get("is_main")) for item in media) == 1
        and bool(media[0].get("is_primary") or media[0].get("is_main"))
        and not media_duplicates
    )

    other_prices = {key: price_state(by_code[key][0]) for key in EXPECTED if key != "CK150" and by_code.get(key)}
    reused_ck150_price = [key for key, product_list in by_code.items() if key != "CK150" and any(product.get("selling_price", product.get("price")) == 262884 for product in product_list)]
    planned_creates = sorted(set(EXPECTED) - set(by_code))
    planned_media_adds = [] if not ck150 else [url for url in expected_media if url not in canonical_media]
    planned_updates = [key for key in EXPECTED if by_code.get(key) and (by_code[key][0].get("name") != EXPECTED[key] or by_code[key][0].get("description") != EXPECTED[key])]
    idempotency = "PASS" if not planned_creates and not planned_media_adds and not duplicate and not duplicate_skus and not membership_missing and not media_duplicates and not sku_mismatches else "FAIL"

    print("HASTAKALA POST-IMPORT AUDIT")
    print(f"Environment: {EXPECTED_DB}")
    print("")
    print("Products:")
    print(f"Expected: 23")
    print(f"Found: {len(set(EXPECTED) & set(by_code))}")
    print(f"Missing: {', '.join(missing) if missing else 'none'}")
    print(f"Duplicates: {duplicate if duplicate else 'none'}")
    print(f"Unexpected CK product codes: {', '.join(unexpected) if unexpected else 'none'}")
    print(f"SKU mismatches: {sku_mismatches if sku_mismatches else 'none'}")
    print(f"Duplicate expected SKUs: {duplicate_skus if duplicate_skus else 'none'}")
    print(f"CK163: {ck163}")
    print(f"Hastakala collection: {'PASS' if not membership_missing else 'FAIL'}")
    print(f"Duplicate collection: {'YES' if len(hastakala) > 1 else 'NO'}")
    print("")
    print("CK150:")
    print(f"Product code: {ck150.get('product_code') if ck150 else 'missing'}")
    print(f"SKU: {ck150.get('sku') if ck150 else 'missing'} (expected {expected_sku('CK150')})")
    print(f"Description: {ck150.get('description') if ck150 else 'missing'}")
    print(f"Price: {price_state(ck150) if ck150 else 'missing'}")
    print(f"Currency: {(ck150.get('base_currency', ck150.get('currency')) if ck150 else 'missing')}")
    print(f"Tax inclusive: {(ck150.get('tax_inclusive') if ck150 else 'missing')}")
    print(f"Media count: {len(media)}")
    print(f"Media positions: {[item.get('position') for item in media]}")
    print(f"Primary: {'PASS' if media_ok else 'FAIL'}")
    print(f"Media duplicates: {'YES' if media_duplicates else 'NO'}")
    print("")
    print("Other product prices:")
    for key in EXPECTED:
        if key != "CK150":
            print(f"{key}: {other_prices.get(key, 'missing')}")
    print(f"CK150 price reused by other expected products: {', '.join(reused_ck150_price) if reused_ck150_price else 'none'}")
    print("")
    print("Inventory preservation (current read-only state; no pre-import snapshot supplied):")
    print(f"Variants: {len(variants)}")
    print("Configurations: NOT EXPOSED BY CURRENT READ API")
    print(f"Stock balances: {len(balances)}")
    print(f"Stock ledger: {len(ledger)}")
    print("")
    print("Idempotency assessment:")
    print(f"{idempotency}")
    print(f"Planned creates on another apply: {len(planned_creates)}")
    print(f"Planned CK150 media additions on another apply: {len(planned_media_adds)}")
    print(f"Potential product field updates: {len(planned_updates)}")
    print("")
    print("Audit writes: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
