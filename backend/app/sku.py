import re


COLLECTION_CODES = {
    "inaara": "INA",
    "hastakala": "HAS",
    "aakar": "AAK",
    "aakaar": "AAK",
    "anamika": "ANA",
    "naqab": "NAQ",
    "sandook": "SAN",
}
ALLOWED_SIZES = ("XS", "S", "M", "L", "XL")


def normalize_sku_part(value):
    return re.sub(r"[^A-Z0-9]+", "-", str(value or "").strip().upper()).strip("-")


def collection_code(name, configured_code=None):
    if configured_code:
        code = normalize_sku_part(configured_code).replace("-", "")
    else:
        normalized = str(name or "").strip().casefold()
        code = COLLECTION_CODES.get(normalized) or normalize_sku_part(name).replace("-", "")[:3]
    if len(code) not in (2, 3):
        raise ValueError("Collection code must contain two or three letters")
    return code


def linesheet_sku(collection, product_code, color, set_of, configured_collection_code=None):
    product = normalize_sku_part(product_code)
    normalized_color = normalize_sku_part(color)
    try:
        set_count = int(set_of)
    except (TypeError, ValueError) as exc:
        raise ValueError("Set of must be between 1 and 5") from exc
    if not product or not normalized_color or set_count not in range(1, 6):
        raise ValueError("Product code, color and set of 1 to 5 are required")
    return f"RK-{collection_code(collection, configured_collection_code)}-{product}-{normalized_color}-{set_count}"


def inventory_sku(base_sku, size):
    normalized_size = normalize_sku_part(size)
    if normalized_size not in ALLOWED_SIZES:
        raise ValueError("Inventory size must be XS, S, M, L or XL")
    return f"{base_sku}-{normalized_size}"
