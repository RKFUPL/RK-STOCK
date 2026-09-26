from uuid import uuid4
from pymongo import ReturnDocument

from .db import db
from .utils import now

STAGES = ["designing", "stitching", "embroidery", "qc", "finishing", "ready_to_dispatch", "dispatched"]


def activity(user, action, entity_type, entity_id, details=None):
    db().activity_log.insert_one({"user_id": user["_id"], "user_email": user["email"], "action": action, "entity_type": entity_type, "entity_id": str(entity_id), "details": details or {}, "created_at": now()})


def mutate_stock(*, sku, color, size, quantity, transaction_type, user, location="main", client_id=None, po_number=None, notes=None, idempotency_key=None, allow_negative=False):
    quantity = int(quantity)
    if quantity == 0:
        raise ValueError("Quantity cannot be zero")
    transaction_id = idempotency_key or str(uuid4())
    if db().stock_ledger.find_one({"transaction_id": transaction_id}):
        return db().stock_ledger.find_one({"transaction_id": transaction_id}), False
    key = {"sku": sku, "color": color, "size": size, "location": location, "client_id": client_id}
    db().stock_balances.update_one(key, {"$setOnInsert": {**key, "physical": 0, "reserved": 0, "production": 0, "consignment": 0, "available": 0, "revision": 0, "created_at": now()}}, upsert=True)
    current = db().stock_balances.find_one(key)
    field = {
        "stock_received": "physical", "opening_stock": "physical", "adjustment": "physical", "damaged": "physical",
        "dispatch": "physical", "return": "physical", "production_completion": "physical",
        "reserve": "reserved", "release": "reserved", "consignment_sent": "consignment", "consignment_sold": "consignment", "consignment_returned": "consignment",
    }.get(transaction_type)
    if not field:
        raise ValueError("Unsupported transaction type")
    updated_value = int(current.get(field, 0)) + quantity
    if updated_value < 0 and not allow_negative:
        raise ValueError(f"Insufficient {field} stock")
    result = db().stock_balances.find_one_and_update(
        {**key, "revision": current.get("revision", 0)},
        {"$inc": {field: quantity, "revision": 1}, "$set": {"updated_at": now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise RuntimeError("Stock changed concurrently; retry")
    available = int(result.get("physical", 0)) - int(result.get("reserved", 0))
    db().stock_balances.update_one({"_id": result["_id"]}, {"$set": {"available": available}})
    ledger = {"transaction_id": transaction_id, **key, "quantity": quantity, "transaction_type": transaction_type, "balance_after": {field: updated_value, "available": available}, "related_po": po_number, "user_id": user["_id"], "user_email": user["email"], "notes": notes, "created_at": now()}
    db().stock_ledger.insert_one(ledger)
    return ledger, True


def move_production(batch, from_stage, to_stage, quantity, user, notes=None, rejected=0, rework=0):
    quantity, rejected, rework = int(quantity), int(rejected), int(rework)
    if to_stage not in STAGES or (from_stage and from_stage not in STAGES):
        raise ValueError("Invalid production stage")
    buckets = batch.get("stage_quantities", {})
    if from_stage and int(buckets.get(from_stage, 0)) < quantity:
        raise ValueError("Movement exceeds quantity at source stage")
    if min(quantity, rejected, rework) < 0:
        raise ValueError("Quantities cannot be negative")
    increments = {f"stage_quantities.{to_stage}": quantity, "revision": 1}
    if from_stage:
        increments[f"stage_quantities.{from_stage}"] = -quantity
    result = db().production_batches.find_one_and_update({"_id": batch["_id"], "revision": batch.get("revision", 0)}, {"$inc": increments, "$set": {"current_stage": to_stage, "updated_at": now()}}, return_document=ReturnDocument.AFTER)
    if not result:
        raise RuntimeError("Production record changed concurrently; retry")
    movement = {"movement_id": str(uuid4()), "batch_id": batch["_id"], "order_id": batch["order_id"], "from_stage": from_stage, "to_stage": to_stage, "quantity": quantity, "rejected": rejected, "rework": rework, "notes": notes, "user_id": user["_id"], "user_email": user["email"], "created_at": now()}
    db().production_movements.insert_one(movement)
    return result, movement
