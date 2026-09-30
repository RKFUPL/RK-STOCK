import re

from .sku import inventory_sku, linesheet_sku
from .utils import now


SUPPORTED_CURRENCIES = ("INR", "USD", "EUR", "GBP", "AED")
def _value(imported, row, field, default=None):
    index = imported.get("mapping", {}).get(field)
    values = row.get("values") or []
    return values[index] if index is not None and index < len(values) else default


def _base_code(vendor_code, color):
    vendor = str(vendor_code or "").strip()
    suffix = f"-{str(color or '').strip()}"
    if not vendor or not color or not vendor.casefold().endswith(suffix.casefold()):
        return ""
    return vendor[: -len(suffix)].strip()


def build_aakaar_projection(imported, collection, existing=None):
    """Build and validate the approved Aakaar model without database writes."""
    existing = existing or {}
    errors = []
    products = {}
    configurations = []
    variants = []
    seen_source = set()
    seen_vendor = set()
    seen_config = set()
    seen_variant = set()
    rows = [row for row in imported.get("preview", []) if not row.get("errors")]
    if not collection or collection.get("name") != "Aakaar" or collection.get("code") != "AAK" or collection.get("slug") != "aakaar":
        errors.append({"kind": "collection", "message": "Active Aakaar collection with code AAK and slug aakaar is required"})

    for row in rows:
        row_number = row.get("row_number")
        vendor_code = str(_value(imported, row, "vendor_code", "") or "").strip()
        source_sku = str(row.get("sku") or _value(imported, row, "sku", "") or "").strip()
        color = str(_value(imported, row, "color", "") or "").strip()
        base = _base_code(vendor_code, color)
        category = str(_value(imported, row, "category", "") or "").strip()
        raw_component = _value(imported, row, "component_count")
        raw_mrp = _value(imported, row, "mrp")
        try:
            component_count = int(raw_component)
        except (TypeError, ValueError):
            component_count = 0
        try:
            mrp = float(raw_mrp)
        except (TypeError, ValueError):
            mrp = -1
        if not base:
            errors.append({"row": row_number, "kind": "identity", "message": "Vendor code must end with the source colour"})
            continue
        if source_sku in seen_source:
            errors.append({"row": row_number, "kind": "duplicate_source_sku", "value": source_sku})
        seen_source.add(source_sku)
        if vendor_code in seen_vendor:
            errors.append({"row": row_number, "kind": "duplicate_vendor_code", "value": vendor_code})
        seen_vendor.add(vendor_code)
        # Approved correction: the historical source value 3 for CK-207-Ivory is not authoritative.
        if base == "CK-207" and color.casefold() in {"red", "ivory"}:
            component_count = 2
        if component_count not in range(1, 6):
            errors.append({"row": row_number, "kind": "component_count", "value": raw_component})
        if mrp < 0:
            errors.append({"row": row_number, "kind": "mrp", "value": raw_mrp})
        quantities = row.get("size_quantities") or {}
        if set(quantities) != {"M"} or quantities.get("M") is None:
            errors.append({"row": row_number, "kind": "size", "message": "Aakaar requires exactly size M"})
        source_quantity = quantities.get("M", 0)
        try:
            source_quantity = int(source_quantity)
            if source_quantity < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"row": row_number, "kind": "source_quantity", "value": quantities.get("M")})
            source_quantity = 0
        config_sku = linesheet_sku("Aakaar", base, color, component_count, "AAK")
        variant_sku = inventory_sku(config_sku, "M")
        if config_sku in seen_config:
            errors.append({"row": row_number, "kind": "duplicate_configuration", "value": config_sku})
        seen_config.add(config_sku)
        if variant_sku in seen_variant:
            errors.append({"row": row_number, "kind": "duplicate_variant", "value": variant_sku})
        seen_variant.add(variant_sku)
        if base in existing.get("product_codes", set()):
            errors.append({"row": row_number, "kind": "product_collision", "value": base})
        if config_sku in existing.get("configuration_skus", set()):
            errors.append({"row": row_number, "kind": "configuration_collision", "value": config_sku})
        if variant_sku in existing.get("inventory_skus", set()):
            errors.append({"row": row_number, "kind": "variant_collision", "value": variant_sku})
        if source_sku in existing.get("source_client_skus", set()):
            errors.append({"row": row_number, "kind": "source_sku_collision", "value": source_sku})
        if vendor_code in existing.get("source_vendor_codes", set()):
            errors.append({"row": row_number, "kind": "vendor_code_collision", "value": vendor_code})
        if base not in products:
            products[base] = {"product_code": base, "sku": f"PRODUCT-AAK-{base}", "name": base, "collection": "Aakaar", "collection_code": "AAK", "collection_slug": "aakaar", "category": category, "configuration_count": 0, "source_rows": []}
        products[base]["configuration_count"] += 1
        products[base]["source_rows"].append(row_number)
        measurements = (row.get("size_measurements") or {}).get("M", {})
        configuration = {"source_row": row_number, "product_code": base, "color": color, "source_vendor_code": vendor_code, "source_client_sku": source_sku, "component_count": component_count, "linesheet_sku": config_sku, "mrp": f"{mrp:.2f}", "currency": "INR", "tax_inclusive": True, "source_order_quantity": {"M": source_quantity}, "measurements": measurements, "category": category, "po_reference": _value(imported, row, "remark", "") or ((row.get("references") or [None])[0]), "delivery_date": _value(imported, row, "po_delivery_date"), "physical": 0, "reserved": 0, "available": 0, "location": None}
        configurations.append(configuration)
        variants.append({"source_row": row_number, "configuration_sku": config_sku, "inventory_sku": variant_sku, "size": "M", "source_order_quantity": source_quantity, "physical": 0, "reserved": 0, "available": 0, "location": None, "available_for_sale": False})

    if len(rows) != 47:
        errors.append({"kind": "row_count", "expected": 47, "actual": len(rows)})
    if len(products) != 19:
        errors.append({"kind": "product_count", "expected": 19, "actual": len(products)})
    if len(configurations) != 47:
        errors.append({"kind": "configuration_count", "expected": 47, "actual": len(configurations)})
    if len(variants) != 47:
        errors.append({"kind": "variant_count", "expected": 47, "actual": len(variants)})
    if any(configuration["currency"] not in SUPPORTED_CURRENCIES or not configuration["tax_inclusive"] for configuration in configurations):
        errors.append({"kind": "pricing", "message": "All Aakaar configurations must be INR and tax-inclusive"})
    return {"products": list(products.values()), "configurations": configurations, "variants": variants, "physical_stock_records": 0, "errors": errors, "valid": not errors}


def existing_aakaar_identities(database):
    return {
        "product_codes": {value for value in database.products.distinct("product_code") if value},
        "configuration_skus": {value for value in database.product_configurations.distinct("linesheet_sku") if value},
        "inventory_skus": {value for value in database.inventory_variants.distinct("inventory_sku") if value},
        "source_client_skus": {value for value in database.product_configurations.distinct("source_client_sku") if value},
        "source_vendor_codes": {value for value in database.product_configurations.distinct("source_vendor_code") if value},
    }


def commit_aakaar_projection(database, projection, imported, collection, client, data, user):
    """Persist an already-validated Aakaar projection with compensation on failure.

    The caller must validate the projection before calling this function. It never
    creates stock balances or ledger entries.
    """
    if not projection.get("valid"):
        raise ValueError("Aakaar projection contains validation errors")
    created_products, created_configurations, created_variants = [], [], []
    linesheet_id = None
    try:
        product_ids = {}
        for product in projection["products"]:
            result = database.products.insert_one({"sku": product["sku"], "product_code": product["product_code"], "name": product["name"], "description": product["name"], "collection": "Aakaar", "collection_id": collection["_id"], "category": product["category"], "base_currency": "INR", "tax_inclusive": True, "active": True, "created_at": now(), "updated_at": now()})
            created_products.append(result.inserted_id)
            product_ids[product["product_code"]] = result.inserted_id
        configuration_ids = {}
        for configuration in projection["configurations"]:
            doc = {"product_id": product_ids[configuration["product_code"]], "collection_id": collection["_id"], "product_code": configuration["product_code"], "color": configuration["color"], "set_of": configuration["component_count"], "linesheet_sku": configuration["linesheet_sku"], "description": configuration["product_code"], "mrp": configuration["mrp"], "currency": "INR", "tax_inclusive": True, "source_vendor_code": configuration["source_vendor_code"], "source_client_sku": configuration["source_client_sku"], "source_order_quantities": configuration["source_order_quantity"], "measurements": {"M": configuration["measurements"]}, "category": configuration["category"], "po_reference": configuration["po_reference"], "delivery_date": configuration["delivery_date"], "source_import_id": imported["import_id"], "created_at": now(), "updated_at": now()}
            result = database.product_configurations.insert_one(doc)
            created_configurations.append(result.inserted_id)
            configuration_ids[configuration["linesheet_sku"]] = result.inserted_id
        for variant in projection["variants"]:
            configuration = next(item for item in projection["configurations"] if item["linesheet_sku"] == variant["configuration_sku"])
            database.inventory_variants.insert_one({"configuration_id": configuration_ids[variant["configuration_sku"]], "product_id": product_ids[configuration["product_code"]], "linesheet_sku": variant["configuration_sku"], "inventory_sku": variant["inventory_sku"], "product_code": configuration["product_code"], "color": configuration["color"], "set_of": configuration["component_count"], "size": "M", "source_client_sku": configuration["source_client_sku"], "source_vendor_code": configuration["source_vendor_code"], "source_order_quantity": variant["source_order_quantity"], "physical": 0, "reserved": 0, "available": 0, "location": None, "available_for_sale": False, "source_import_id": imported["import_id"], "created_at": now(), "updated_at": now()})
            created_variants.append(variant["inventory_sku"])
        sheet = {"linesheet_number": f"AAKAAR-{imported['import_id'][:8]}", "name": data["name"], "collection": "Aakaar", "client_id": client["_id"], "client_name": client["name"], "type": data.get("type", "mds_outright"), "items": projection["configurations"], "total_quantity": sum(item["source_order_quantity"].get("M", 0) for item in projection["configurations"]), "status": data.get("status", "draft"), "source_import_id": imported["import_id"], "created_by": user["_id"], "created_at": now(), "updated_at": now()}
        linesheet_id = database.linesheets.insert_one(sheet).inserted_id
        return {"linesheet_id": linesheet_id, "products_created": len(created_products), "configurations_created": len(created_configurations), "variants_created": len(created_variants), "physical_stock_created": 0}
    except Exception:
        if linesheet_id:
            database.linesheets.delete_one({"_id": linesheet_id})
        if created_variants:
            database.inventory_variants.delete_many({"inventory_sku": {"$in": created_variants}})
        if created_configurations:
            database.product_configurations.delete_many({"_id": {"$in": created_configurations}})
        if created_products:
            database.products.delete_many({"_id": {"$in": created_products}})
        raise
