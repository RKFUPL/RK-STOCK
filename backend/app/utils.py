from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from bson import ObjectId
from pymongo import ReturnDocument


def now():
    return datetime.now(timezone.utc)


def utc_datetime(value):
    """Return a datetime normalized to timezone-aware UTC.

    MongoDB/PyMongo may deserialize UTC values as naive datetimes. Treat those
    values as UTC; convert aware values instead of comparing mixed types.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def oid(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def money(value):
    try:
        return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))
    except InvalidOperation as exc:
        raise ValueError("Invalid monetary value") from exc


def serialize(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def page_args(request):
    page = max(int(request.args.get("page", 1)), 1)
    limit = min(max(int(request.args.get("limit", 25)), 1), 100)
    return page, limit


def next_number(database, key, prefix):
    year = now().year
    result = database.counters.find_one_and_update(
        {"_id": f"{key}:{year}"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return f"{prefix}-{year}-{result['value']:04d}"
