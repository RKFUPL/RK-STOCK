"""Guarded local API correction for imported no-colour Hastakala products."""

from __future__ import annotations

import os
import sys

import requests


BASE_URL = "http://127.0.0.1:5006"
DB_NAME = "RK_TEST_DB"
EXPECTED = [
    "CK150", "CK149", "CK147", "CK166", "CK148", "CK165", "CK173", "CK157",
    "CK172", "CK154", "CK168", "CK167", "CK159", "CK179", "CK156", "CK161",
    "CK169", "CK141", "CK160", "CK152", "CK52A", "CK171", "CK155",
]


def abort(message: str) -> None:
    print(f"SKU correction aborted: {message}", file=sys.stderr)
    raise SystemExit(2)


def call(session: requests.Session, method: str, path: str, **kwargs):
    try:
        response = session.request(method, f"{BASE_URL}{path}", timeout=20, **kwargs)
    except requests.RequestException as exc:
        abort(f"{path} request failed ({type(exc).__name__})")
    if not response.ok:
        try:
            detail = response.json().get("error", f"HTTP {response.status_code}")
        except ValueError:
            detail = f"HTTP {response.status_code}"
        abort(f"{method} {path}: {str(detail)[:240]}")
    try:
        return response.json() if response.content else {}
    except ValueError:
        abort(f"{path}: invalid JSON response")


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    if os.environ.get("RK_STOCK_DB_NAME") != DB_NAME:
        abort("RK_STOCK_DB_NAME must be RK_TEST_DB")
    token = os.environ.get("RK_TEST_TOKEN")
    if not token:
        abort("RK_TEST_TOKEN is missing")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    health = call(session, "GET", "/api/health")
    if health.get("status") != "ok":
        abort("local RK-STOCK health check failed")
    identity = call(session, "GET", "/api/auth/me")
    if identity.get("role") != "admin" or "*" not in set(identity.get("effective_permissions") or []):
        abort("authenticated identity is not an active admin")
    products = call(session, "GET", "/api/products?limit=500").get("items") or []
    by_code: dict[str, list[dict]] = {}
    for product in products:
        code = str(product.get("product_code") or "").strip().upper()
        if code in EXPECTED:
            by_code.setdefault(code, []).append(product)
    missing = [code for code in EXPECTED if code not in by_code]
    duplicates = {code: len(items) for code, items in by_code.items() if len(items) != 1}
    if missing or duplicates:
        abort(f"safe identity check failed; missing={','.join(missing) or 'none'} duplicates={duplicates or 'none'}")
    if any(str(product.get("product_code") or "").strip().upper() == "CK163" for product in products):
        print("CK163 exists separately and will not be modified", file=sys.stderr)

    target_owners = {}
    for product in products:
        sku = str(product.get("sku") or "").strip().upper()
        if sku.startswith("HK-") and sku.endswith("-A"):
            target_owners.setdefault(sku, set()).add(str(product.get("_id")))

    planned = 0
    for code in EXPECTED:
        product = by_code[code][0]
        target = f"HK-{code}-A"
        owners = target_owners.get(target, set()) - {str(product["_id"])}
        if owners:
            abort(f"target SKU {target} already belongs to another product")
        if product.get("sku") != target:
            planned += 1
            if apply:
                call(session, "PATCH", f"/api/products/{product['_id']}", json={"sku": target})

    if not apply:
        print("Hastakala SKU correction plan")
        print(f"Environment: {DB_NAME}")
        print(f"Planned corrections: {planned}")
        print("No writes performed. Re-run with --apply to execute the approved in-place SKU corrections.")
        return 0

    verified = call(session, "GET", "/api/products?limit=500").get("items") or []
    expected_records = [item for item in verified if str(item.get("product_code") or "").strip().upper() in EXPECTED]
    remaining_old = [item for item in expected_records if str(item.get("sku") or "").strip().upper() in {code.upper() for code in EXPECTED}]
    target_skus = [f"HK-{code}-A" for code in EXPECTED]
    duplicate_skus = sorted({sku for sku in target_skus if sum(1 for item in expected_records if item.get("sku") == sku) > 1})
    print("Hastakala SKU correction")
    print(f"Environment: {DB_NAME}")
    print(f"Expected: {len(EXPECTED)}")
    print(f"Corrected or already correct: {len(expected_records)}")
    print(f"Changed: {planned}")
    print(f"Remaining old CK-as-SKU records: {len(remaining_old)}")
    print(f"Duplicate corrected SKUs: {', '.join(duplicate_skus) if duplicate_skus else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
