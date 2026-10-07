"""Read-only audit of the Hastakala product-SKU convention."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import requests


BASE_URL = "http://127.0.0.1:5006"
EXPECTED_DB = "RK_TEST_DB"
CK_CODES = [
    "CK150", "CK149", "CK147", "CK166", "CK148", "CK165", "CK173", "CK157",
    "CK172", "CK154", "CK168", "CK167", "CK159", "CK179", "CK156", "CK161",
    "CK169", "CK141", "CK160", "CK152", "CK52A", "CK171", "CK155",
]


def abort(message: str) -> None:
    print(f"Audit aborted: {message}", file=sys.stderr)
    raise SystemExit(2)


def get(session: requests.Session, path: str) -> dict:
    try:
        response = session.get(f"{BASE_URL}{path}", timeout=20)
    except requests.RequestException as exc:
        abort(f"{path} request failed ({type(exc).__name__})")
    if not response.ok:
        try:
            detail = response.json().get("error", f"HTTP {response.status_code}")
        except ValueError:
            detail = f"HTTP {response.status_code}"
        abort(f"{path}: {str(detail)[:240]}")
    try:
        return response.json()
    except ValueError:
        abort(f"{path}: invalid JSON response")


def code_of(product: dict) -> str:
    return str(product.get("product_code") or "").strip()


def sku_of(product: dict) -> str:
    return str(product.get("sku") or "").strip()


def colour_of(product: dict) -> str:
    values = product.get("colors") or product.get("colours")
    if isinstance(values, list):
        return ", ".join(str(value).strip() for value in values if str(value).strip())
    return str(product.get("color") or product.get("colour") or "").strip()


def product_collection_ids(product: dict) -> set[str]:
    values = {str(value) for value in (product.get("collection_ids") or [])}
    values.update(str(item.get("id")) for item in product.get("collections") or [] if isinstance(item, dict) and item.get("id"))
    for field in ("collection_id",):
        if product.get(field):
            values.add(str(product[field]))
    return values


def main() -> int:
    if os.environ.get("RK_STOCK_DB_NAME") != EXPECTED_DB:
        abort("RK_STOCK_DB_NAME must be RK_TEST_DB")
    token = os.environ.get("RK_TEST_TOKEN")
    if not token:
        abort("RK_TEST_TOKEN is missing")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    collections = get(session, "/api/collections?include_archived=true").get("items") or []
    products = get(session, "/api/products?limit=500").get("items") or []
    hastakala = [item for item in collections if item.get("name", "").casefold() == "hastakala" or item.get("code") == "HAS" or item.get("slug") == "collections-of-hastakala"]
    if len(hastakala) != 1:
        abort(f"expected one Hastakala collection, found {len(hastakala)}")
    hastakala_id = str(hastakala[0].get("_id") or hastakala[0].get("id"))
    products = [item for item in products if hastakala_id in product_collection_ids(item) or str(item.get("collection") or "").casefold() == "hastakala"]
    ck_products = [item for item in products if code_of(item).upper().startswith("CK")]
    no_colour = [item for item in ck_products if not colour_of(item)]
    colour_specific = [item for item in ck_products if colour_of(item)]

    no_colour_formats = {
        sku_of(item): code_of(item)
        for item in no_colour
        if sku_of(item) and code_of(item)
    }
    recommended_prefix = None
    if no_colour_formats:
        prefixes = {sku[:-len(code)].rstrip("-") for sku, code in no_colour_formats.items() if sku.endswith(code)}
        if len(prefixes) == 1 and all(sku == f"{next(iter(prefixes))}-{code}" for sku, code in no_colour_formats.items()):
            recommended_prefix = next(iter(prefixes))

    print("HASTAKALA SKU CONVENTION AUDIT")
    print("")
    print("No-colour examples:")
    if no_colour:
        for item in no_colour:
            print(f"{code_of(item)} | {sku_of(item)} | colour={colour_of(item) or 'empty'} | name={item.get('name', '')}")
    else:
        print("none found")
    print("")
    print("Colour-specific examples:")
    if colour_specific:
        for item in colour_specific:
            print(f"{code_of(item)} | {sku_of(item)} | colour={colour_of(item)} | name={item.get('name', '')}")
    else:
        print("none found")
    print("")
    print("Observed patterns:")
    if no_colour_formats:
        print(f"No-colour records found: {len(no_colour_formats)}")
        print("Colour-specific records show the stored SKU values above.")
    else:
        print("No authoritative no-colour CK SKU examples were found in RK_TEST_DB.")
    print(f"Recommended no-colour format: {f'{recommended_prefix}-<CK code>' if recommended_prefix else 'NOT DETERMINABLE'}")
    print("")
    print("23 imported products:")
    by_code: dict[str, list[dict]] = {}
    for item in ck_products:
        by_code.setdefault(code_of(item).upper(), []).append(item)
    for code in CK_CODES:
        matches = by_code.get(code, [])
        if not recommended_prefix:
            for item in matches or [{}]:
                print(f"{code} | {sku_of(item) or 'missing'} | {colour_of(item) or 'empty'} | proposed corrected SKU: NOT DETERMINABLE")
        else:
            proposed = f"{recommended_prefix}-{code}"
            for item in matches or [{}]:
                print(f"{code} | {sku_of(item) or 'missing'} | {colour_of(item) or 'empty'} | proposed corrected SKU: {proposed}")
    print("")
    print("Audit writes: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
