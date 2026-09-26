from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import hashlib
import os
from urllib.parse import quote

from bson import ObjectId
from flask import Blueprint, current_app, g, jsonify, request, send_file, redirect
from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Font, PatternFill
from pymongo import DESCENDING
from werkzeug.utils import secure_filename

from .auth import auth_required, check_password, hash_password, permission_required, token_for
from .db import db
from .services import STAGES, activity, move_production, mutate_stock
from .utils import money, next_number, now, oid, page_args, serialize, utc_datetime
from .workdrive import WorkDriveClient, WorkDriveError
from .mail import ZohoMailClient

api = Blueprint("api", __name__)


def body(required=()):
    data = request.get_json(silent=True) or {}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        raise ValueError("Missing fields: " + ", ".join(missing))
    return data


def json_error(exc, code=400):
    return jsonify(error=str(exc)), code


def list_response(collection, query, sort=("created_at", DESCENDING)):
    page, limit = page_args(request)
    total = collection.count_documents(query)
    items = list(collection.find(query).sort(*sort).skip((page - 1) * limit).limit(limit))
    return jsonify(items=serialize(items), page=page, limit=limit, total=total)


def search_query(fields):
    query = {}
    value = request.args.get("q", "").strip()
    if value:
        query["$or"] = [{field: {"$regex": value, "$options": "i"}} for field in fields]
    for field in request.args:
        if field in fields and request.args[field]:
            query[field] = request.args[field]
    return query


@api.get("/health")
def health():
    try:
        db().command("ping")
        return jsonify(status="ok", database="connected")
    except Exception:
        return jsonify(status="degraded", database="unavailable"), 503


@api.post("/auth/login")
def login():
    try:
        data = body(("password",))
        identifier = (data.get("identifier") or data.get("email") or "").strip()
        user = db().users.find_one({"$or": [{"email": identifier.lower()}, {"name": {"$regex": f"^{identifier}$", "$options": "i"}}], "active": True}) if identifier else None
        if not user or not check_password(data["password"], user["password_hash"]):
            return jsonify(error="Invalid email or password"), 401
        db().users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now()}})
        return jsonify(token=token_for(user), user=serialize({k: v for k, v in user.items() if k != "password_hash"}))
    except ValueError as exc:
        return json_error(exc)


@api.get("/auth/me")
@auth_required
def me():
    return jsonify(serialize({k: v for k, v in g.user.items() if k != "password_hash"}))


@api.route("/users", methods=["GET", "POST"])
@permission_required("users:write")
def users():
    if request.method == "GET":
        return list_response(db().users, {}, ("name", 1))
    try:
        data = body(("name", "email", "password", "role"))
        if data["role"] not in {"admin", "sales", "production_inventory"}:
            raise ValueError("Invalid role")
        doc = {"name": data["name"], "email": data["email"].strip().lower(), "password_hash": hash_password(data["password"]), "role": data["role"], "active": True, "created_at": now()}
        result = db().users.insert_one(doc)
        activity(g.user, "create", "user", result.inserted_id)
        return jsonify(id=str(result.inserted_id)), 201
    except Exception as exc:
        return json_error(exc)


@api.route("/clients", methods=["GET", "POST"])
@auth_required
def clients():
    if request.method == "GET":
        query = search_query(["name", "client_code", "category", "status"])
        return list_response(db().clients, query, ("name", 1))
    if g.user["role"] not in {"admin", "sales"}:
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("name", "client_code", "category"))
        if data["category"] not in {"mds", "direct"}:
            raise ValueError("Client category must be mds or direct")
        business_types = data.get("business_types", ["outright"] if data["category"] == "direct" else [])
        if data["category"] == "mds" and not set(business_types).issubset({"outright", "consignment"}):
            raise ValueError("Invalid MDS business type")
        doc = {**data, "client_code": data["client_code"].strip().upper(), "business_types": business_types, "status": data.get("status", "active"), "created_at": now(), "updated_at": now()}
        result = db().clients.insert_one(doc)
        activity(g.user, "create", "client", result.inserted_id)
        return jsonify(id=str(result.inserted_id)), 201
    except Exception as exc:
        return json_error(exc)


@api.route("/clients/<client_id>", methods=["GET", "PATCH"])
@auth_required
def client_detail(client_id):
    client = db().clients.find_one({"_id": oid(client_id)})
    if not client:
        return jsonify(error="Client not found"), 404
    if request.method == "PATCH":
        if g.user["role"] not in {"admin", "sales"}:
            return jsonify(error="Permission denied"), 403
        changes = body()
        for protected in ("_id", "created_at"):
            changes.pop(protected, None)
        changes["updated_at"] = now()
        db().clients.update_one({"_id": client["_id"]}, {"$set": changes})
        activity(g.user, "update", "client", client_id, changes)
        client.update(changes)
    orders = list(db().orders.find({"client_id": client["_id"]}).sort("created_at", DESCENDING))
    documents = list(db().documents.find({"client_id": client["_id"]}).sort("created_at", DESCENDING))
    return jsonify(client=serialize(client), orders=serialize(orders), documents=serialize(documents))


@api.route("/products", methods=["GET", "POST"])
@auth_required
def products():
    if request.method == "GET":
        return list_response(db().products, search_query(["name", "sku", "vendor_code", "category", "collection", "season"]), ("name", 1))
    if g.user["role"] != "admin":
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("name", "sku"))
        doc = {**data, "sku": data["sku"].strip().upper(), "cost_price": money(data.get("cost_price")), "selling_price": money(data.get("selling_price")), "colors": data.get("colors", []), "sizes": data.get("sizes", []), "active": data.get("active", True), "created_at": now(), "updated_at": now()}
        result = db().products.insert_one(doc)
        activity(g.user, "create", "product", result.inserted_id)
        return jsonify(id=str(result.inserted_id)), 201
    except Exception as exc:
        return json_error(exc)


@api.route("/linesheets", methods=["GET", "POST"])
@auth_required
def linesheets():
    if request.method == "GET":
        return list_response(db().linesheets, search_query(["linesheet_number", "client_name", "type", "status", "collection", "season"]))
    if g.user["role"] not in {"admin", "sales"}:
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("client_id", "type", "items"))
        client = db().clients.find_one({"_id": oid(data["client_id"])})
        if not client:
            raise ValueError("Client not found")
        if data["type"] not in {"mds_outright", "mds_consignment", "direct"}:
            raise ValueError("Invalid linesheet type")
        if data.get("collection") and not db().collections.find_one({"name": data["collection"], "active": True}):
            raise ValueError("Invalid or archived collection")
        items, total_qty, total_value = [], 0, 0.0
        for item in data["items"]:
            quantity = sum(int(v) for v in item.get("size_quantities", {}).values())
            unit_price = money(item.get("unit_price"))
            items.append({**item, "total_quantity": quantity, "unit_price": unit_price, "total_price": money(quantity * float(unit_price))})
            total_qty += quantity
            total_value += quantity * float(unit_price)
        requested_status = data.get("status", "draft")
        if requested_status not in {"draft", "confirmed"}:
            raise ValueError("New linesheets must be draft or confirmed")
        doc = {**data, "client_id": client["_id"], "client_name": client["name"], "linesheet_number": next_number(db(), "linesheet", "LS"), "items": items, "total_quantity": total_qty, "total_value": money(total_value), "status": requested_status, "workdrive_status": "not_uploaded", "created_by": g.user["_id"], "created_at": now(), "updated_at": now()}
        result = db().linesheets.insert_one(doc)
        activity(g.user, "create", "linesheet", result.inserted_id)
        return jsonify(id=str(result.inserted_id), linesheet_number=doc["linesheet_number"]), 201
    except Exception as exc:
        return json_error(exc)


@api.post("/linesheets/<linesheet_id>/convert")
@permission_required("orders:write")
def convert_linesheet(linesheet_id):
    sheet = db().linesheets.find_one({"_id": oid(linesheet_id)})
    if not sheet:
        return jsonify(error="Linesheet not found"), 404
    if sheet["status"] not in {"confirmed", "shared"}:
        return jsonify(error="Only shared or confirmed linesheets can be converted"), 409
    existing = db().orders.find_one({"source_linesheet_id": sheet["_id"]})
    if existing:
        return jsonify(id=str(existing["_id"]), po_number=existing["po_number"], existing=True)
    order_type = sheet["type"]
    doc = {"po_number": next_number(db(), "po", "RK"), "client_id": sheet["client_id"], "client_name": sheet["client_name"], "order_type": order_type, "source_linesheet_id": sheet["_id"], "items": sheet["items"], "total_quantity": sheet["total_quantity"], "total_amount": sheet["total_value"], "status": "draft", "production_status": "not_started", "po_date": now(), "created_by": g.user["_id"], "created_at": now(), "updated_at": now()}
    result = db().orders.insert_one(doc)
    db().linesheets.update_one({"_id": sheet["_id"]}, {"$set": {"status": "converted_to_order", "order_id": result.inserted_id, "updated_at": now()}})
    activity(g.user, "convert", "linesheet", linesheet_id, {"order_id": str(result.inserted_id)})
    return jsonify(id=str(result.inserted_id), po_number=doc["po_number"]), 201


@api.route("/orders", methods=["GET", "POST"])
@auth_required
def orders():
    if request.method == "GET":
        query = search_query(["po_number", "client_name", "order_type", "status", "production_status", "collection"])
        return list_response(db().orders, query)
    if g.user["role"] not in {"admin", "sales"}:
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("client_id", "order_type", "items"))
        client = db().clients.find_one({"_id": oid(data["client_id"])})
        if not client:
            raise ValueError("Client not found")
        if data["order_type"] not in {"mds_outright", "mds_consignment", "direct"}:
            raise ValueError("Invalid order type")
        po_number = data.get("po_number") or next_number(db(), "po", "RK")
        items, total_qty, total_amount = [], 0, 0.0
        for index, item in enumerate(data["items"]):
            qty = int(item.get("quantity", 0))
            if qty <= 0:
                raise ValueError("Order item quantity must be positive")
            price = money(item.get("unit_price"))
            items.append({**item, "line_id": item.get("line_id", str(uuid4())), "quantity": qty, "completed_quantity": 0, "dispatched_quantity": 0, "unit_price": price, "line_total": money(qty * float(price))})
            total_qty += qty
            total_amount += qty * float(price)
        doc = {**data, "po_number": po_number.strip().upper(), "client_id": client["_id"], "client_name": client["name"], "items": items, "total_quantity": total_qty, "total_amount": money(total_amount), "status": data.get("status", "po_received"), "production_status": "not_started", "created_by": g.user["_id"], "created_at": now(), "updated_at": now()}
        result = db().orders.insert_one(doc)
        activity(g.user, "create", "order", result.inserted_id)
        return jsonify(id=str(result.inserted_id), po_number=doc["po_number"]), 201
    except Exception as exc:
        return json_error(exc)


@api.get("/orders/<order_id>")
@auth_required
def order_detail(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    payload = {
        "order": order,
        "client": db().clients.find_one({"_id": order["client_id"]}),
        "documents": list(db().documents.find({"order_id": order["_id"]}).sort("version", DESCENDING)),
        "production": list(db().production_batches.find({"order_id": order["_id"]})),
        "stock_ledger": list(db().stock_ledger.find({"related_po": order["po_number"]}).sort("created_at", DESCENDING)),
        "activity": list(db().activity_log.find({"entity_id": order_id}).sort("created_at", DESCENDING)),
    }
    return jsonify(serialize(payload))


@api.post("/orders/<order_id>/confirm")
@permission_required("orders:write")
def confirm_order(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    if order["status"] not in {"draft", "po_received"}:
        return jsonify(error="Order cannot be confirmed from its current status"), 409
    db().orders.update_one({"_id": order["_id"]}, {"$set": {"status": "confirmed", "confirmed_at": now(), "updated_at": now()}})
    activity(g.user, "confirm", "order", order_id)
    return jsonify(status="confirmed")


@api.post("/orders/<order_id>/production")
@permission_required("production:write")
def create_production(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    try:
        data = body(("line_id", "quantity"))
        line = next((item for item in order["items"] if item["line_id"] == data["line_id"]), None)
        if not line:
            raise ValueError("Order line not found")
        allocated = sum(item.get("quantity", 0) for item in db().production_batches.find({"order_id": order["_id"], "line_id": data["line_id"]}))
        quantity = int(data["quantity"])
        if quantity <= 0 or allocated + quantity > line["quantity"]:
            raise ValueError("Production allocation exceeds outstanding order quantity")
        doc = {"order_id": order["_id"], "po_number": order["po_number"], "client_name": order["client_name"], "order_type": order["order_type"], "line_id": line["line_id"], "sku": line["sku"], "product_name": line.get("product_name"), "color": line.get("color"), "size": line.get("size"), "quantity": quantity, "stage_quantities": {"designing": quantity}, "current_stage": "designing", "completed_quantity": 0, "revision": 0, "expected_completion_date": data.get("expected_completion_date"), "created_at": now(), "updated_at": now()}
        result = db().production_batches.insert_one(doc)
        db().orders.update_one({"_id": order["_id"]}, {"$set": {"status": "in_production", "production_status": "designing", "updated_at": now()}})
        activity(g.user, "create_production", "order", order_id, {"batch_id": str(result.inserted_id), "quantity": quantity})
        return jsonify(id=str(result.inserted_id)), 201
    except Exception as exc:
        return json_error(exc)


@api.get("/production")
@auth_required
def production():
    query = search_query(["po_number", "client_name", "order_type", "sku", "product_name", "current_stage"])
    if request.args.get("delayed") == "true":
        query["expected_completion_date"] = {"$lt": now().date().isoformat()}
        query["current_stage"] = {"$ne": "dispatched"}
    return list_response(db().production_batches, query)


@api.post("/production/<batch_id>/move")
@permission_required("production:write")
def production_move(batch_id):
    batch = db().production_batches.find_one({"_id": oid(batch_id)})
    if not batch:
        return jsonify(error="Production batch not found"), 404
    try:
        data = body(("to_stage", "quantity"))
        updated, movement = move_production(batch, data.get("from_stage", batch.get("current_stage")), data["to_stage"], data["quantity"], g.user, data.get("notes"), data.get("rejected", 0), data.get("rework", 0))
        activity(g.user, "move_stage", "production_batch", batch_id, {"from": movement["from_stage"], "to": movement["to_stage"], "quantity": movement["quantity"]})
        return jsonify(batch=serialize(updated), movement=serialize(movement))
    except Exception as exc:
        return json_error(exc, 409 if isinstance(exc, RuntimeError) else 400)


@api.route("/stock", methods=["GET", "POST"])
@auth_required
def stock():
    if request.method == "GET":
        query = search_query(["sku", "color", "size", "location"])
        if request.args.get("low"):
            query["available"] = {"$lte": int(request.args["low"])}
        return list_response(db().stock_balances, query, ("sku", 1))
    if g.user["role"] not in {"admin", "production_inventory"}:
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("sku", "color", "size", "quantity", "transaction_type"))
        ledger, created = mutate_stock(**{k: data.get(k) for k in ("sku", "color", "size", "quantity", "transaction_type", "location", "client_id", "po_number", "notes", "idempotency_key", "allow_negative") if data.get(k) is not None}, user=g.user)
        activity(g.user, data["transaction_type"], "stock", ledger["transaction_id"], {"sku": data["sku"], "quantity": data["quantity"]})
        return jsonify(transaction=serialize(ledger), created=created), 201 if created else 200
    except Exception as exc:
        return json_error(exc, 409 if isinstance(exc, RuntimeError) else 400)


@api.get("/stock/ledger")
@auth_required
def stock_ledger():
    return list_response(db().stock_ledger, search_query(["transaction_id", "sku", "color", "size", "transaction_type", "related_po", "user_email"]))


@api.post("/orders/<order_id>/reserve")
@permission_required("stock:write")
def reserve_order(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    try:
        data = body(("line_id", "quantity"))
        line = next((item for item in order["items"] if item["line_id"] == data["line_id"]), None)
        if not line:
            raise ValueError("Order line not found")
        qty = int(data["quantity"])
        if qty <= 0 or qty > line["quantity"] - int(line.get("reserved_quantity", 0)):
            raise ValueError("Reservation exceeds outstanding line quantity")
        balance = db().stock_balances.find_one({"sku": line["sku"], "color": line.get("color"), "size": line.get("size"), "location": "main", "client_id": None})
        if not balance or int(balance.get("available", balance.get("physical", 0) - balance.get("reserved", 0))) < qty:
            raise ValueError("Insufficient available stock")
        mutate_stock(sku=line["sku"], color=line.get("color"), size=line.get("size"), quantity=qty, transaction_type="reserve", user=g.user, po_number=order["po_number"], idempotency_key=request.headers.get("Idempotency-Key"))
        db().orders.update_one({"_id": order["_id"], "items.line_id": line["line_id"]}, {"$inc": {"items.$.reserved_quantity": qty}, "$set": {"updated_at": now()}})
        return jsonify(reserved=qty)
    except Exception as exc:
        return json_error(exc)


@api.post("/orders/<order_id>/dispatch")
@permission_required("stock:write")
def dispatch_order(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    try:
        data = body(("line_id", "quantity"))
        line = next((item for item in order["items"] if item["line_id"] == data["line_id"]), None)
        if not line:
            raise ValueError("Order line not found")
        qty = int(data["quantity"])
        outstanding = line["quantity"] - int(line.get("dispatched_quantity", 0))
        if qty <= 0 or qty > outstanding or qty > int(line.get("reserved_quantity", 0)):
            raise ValueError("Dispatch exceeds reserved or outstanding quantity")
        key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
        if not key:
            raise ValueError("Idempotency-Key header is required")
        ledger, created = mutate_stock(sku=line["sku"], color=line.get("color"), size=line.get("size"), quantity=-qty, transaction_type="dispatch", user=g.user, po_number=order["po_number"], idempotency_key=key)
        if created:
            mutate_stock(sku=line["sku"], color=line.get("color"), size=line.get("size"), quantity=-qty, transaction_type="release", user=g.user, po_number=order["po_number"], idempotency_key=f"{key}:release")
            db().orders.update_one({"_id": order["_id"], "items.line_id": line["line_id"]}, {"$inc": {"items.$.dispatched_quantity": qty, "items.$.reserved_quantity": -qty}, "$set": {"updated_at": now()}})
            refreshed = db().orders.find_one({"_id": order["_id"]})
            dispatched = sum(i.get("dispatched_quantity", 0) for i in refreshed["items"])
            status = "executed" if dispatched == refreshed["total_quantity"] else "partially_dispatched"
            db().orders.update_one({"_id": order["_id"]}, {"$set": {"status": status, "executed_at": now() if status == "executed" else None}})
            activity(g.user, "dispatch", "order", order_id, {"line_id": line["line_id"], "quantity": qty})
        return jsonify(dispatched=qty, created=created)
    except Exception as exc:
        return json_error(exc)


@api.route("/orders/<order_id>/documents", methods=["GET", "POST"])
@auth_required
def order_documents(order_id):
    order = db().orders.find_one({"_id": oid(order_id)})
    if not order:
        return jsonify(error="Order not found"), 404
    if request.method == "GET":
        return jsonify(items=serialize(list(db().documents.find({"order_id": order["_id"]}).sort("version", DESCENDING))))
    if g.user["role"] not in {"admin", "sales"}:
        return jsonify(error="Permission denied"), 403
    uploaded = request.files.get("file")
    if not uploaded or uploaded.mimetype != "application/pdf":
        return jsonify(error="A PDF file is required"), 400
    data = uploaded.read()
    if not data.startswith(b"%PDF"):
        return jsonify(error="Uploaded file is not a valid PDF"), 400
    family_id = request.form.get("family_id") or str(uuid4())
    previous = db().documents.find_one({"family_id": family_id}, sort=[("version", DESCENDING)])
    version = int(previous["version"]) + 1 if previous else 1
    folder = Path(current_app.config["UPLOAD_DIR"]) / str(order["_id"])
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{family_id}-v{version}.pdf"
    (folder / stored_name).write_bytes(data)
    doc = {"family_id": family_id, "version": version, "order_id": order["_id"], "client_id": order["client_id"], "kind": "purchase_order", "original_name": secure_filename(uploaded.filename or "purchase-order.pdf"), "stored_path": str(folder / stored_name), "content_type": "application/pdf", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "uploaded_by": g.user["_id"], "uploaded_by_email": g.user["email"], "created_at": now()}
    result = db().documents.insert_one(doc)
    activity(g.user, "upload_document", "order", order_id, {"document_id": str(result.inserted_id), "version": version})
    return jsonify(id=str(result.inserted_id), family_id=family_id, version=version), 201


@api.get("/documents/<document_id>/download")
@auth_required
def download_document(document_id):
    doc = db().documents.find_one({"_id": oid(document_id)})
    if not doc or not os.path.exists(doc["stored_path"]):
        return jsonify(error="Document not found"), 404
    return send_file(doc["stored_path"], mimetype=doc["content_type"], as_attachment=request.args.get("preview") != "true", download_name=doc["original_name"])


@api.get("/dashboard")
@auth_required
def dashboard():
    period = request.args.get("period", "month")
    start = {"today": now() - timedelta(days=1), "week": now() - timedelta(days=7), "month": now() - timedelta(days=30)}.get(period)
    base = {"created_at": {"$gte": start}} if start else {}
    sections = {}
    for key, order_type in (("mds_outright", "mds_outright"), ("mds_consignment", "mds_consignment"), ("direct", "direct")):
        query = {**base, "order_type": order_type}
        sections[key] = {
            "received": db().orders.count_documents(query),
            "executed": db().orders.count_documents({**query, "status": "executed"}),
            "pending": db().orders.count_documents({**query, "status": {"$nin": ["executed", "cancelled"]}}),
            "ready_to_dispatch": db().orders.count_documents({**query, "status": "ready_to_dispatch"}),
            "outstanding_quantity": sum(max(0, item.get("total_quantity", 0) - sum(line.get("dispatched_quantity", 0) for line in item.get("items", []))) for item in db().orders.find(query, {"total_quantity": 1, "items.dispatched_quantity": 1})),
        }
    consignment = list(db().stock_ledger.aggregate([{"$match": {"transaction_type": {"$in": ["consignment_sent", "consignment_sold", "consignment_returned"]}}}, {"$group": {"_id": "$transaction_type", "quantity": {"$sum": "$quantity"}}}]))
    sections["mds_consignment"]["stock"] = {item["_id"]: item["quantity"] for item in consignment}
    production_metrics = {stage: 0 for stage in STAGES}
    for item in db().production_batches.aggregate([{"$project": {"entries": {"$objectToArray": "$stage_quantities"}}}, {"$unwind": "$entries"}, {"$group": {"_id": "$entries.k", "quantity": {"$sum": "$entries.v"}}}]):
        production_metrics[item["_id"]] = item["quantity"]
    return jsonify(sections=sections, production=production_metrics, generated_at=now().isoformat())


@api.get("/reports/<report_name>.xlsx")
@auth_required
def report(report_name):
    allowed = {
        "orders": (db().orders, ["po_number", "client_name", "order_type", "status", "total_quantity", "total_amount"]),
        "production": (db().production_batches, ["po_number", "client_name", "sku", "color", "size", "quantity", "current_stage", "expected_completion_date"]),
        "stock": (db().stock_balances, ["sku", "color", "size", "location", "physical", "reserved", "available", "consignment"]),
        "stock-ledger": (db().stock_ledger, ["transaction_id", "sku", "color", "size", "quantity", "transaction_type", "related_po", "user_email", "created_at"]),
    }
    if report_name not in allowed:
        return jsonify(error="Unknown report"), 404
    collection, columns = allowed[report_name]
    records = collection.find(search_query(columns))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report_name[:31]
    sheet.append(columns)
    for record in records:
        sheet.append([str(serialize(record.get(column, ""))) for column in columns])
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"rk-{report_name}-{now().date().isoformat()}.xlsx")


@api.get("/settings")
@auth_required
def settings():
    configured = db().settings.find_one({"_id": "global"}) or {}
    return jsonify(serialize({"sizes": configured.get("sizes", ["XS", "S", "M", "L", "XL", "XXL"]), "production_stages": configured.get("production_stages", STAGES), "categories": configured.get("categories", [])}))


@api.patch("/settings")
@permission_required("settings:write")
def update_settings():
    changes = body()
    db().settings.update_one({"_id": "global"}, {"$set": {**changes, "updated_at": now(), "updated_by": g.user["_id"]}}, upsert=True)
    activity(g.user, "update", "settings", "global", changes)
    return jsonify(ok=True)


@api.route("/collections", methods=["GET", "POST"])
@auth_required
def collections():
    if request.method == "GET":
        query = {} if request.args.get("include_archived") == "true" else {"active": True}
        return jsonify(items=serialize(list(db().collections.find(query).sort("position", 1))))
    if g.user["role"] != "admin":
        return jsonify(error="Permission denied"), 403
    try:
        data = body(("name",))
        slug = "-".join(data["name"].strip().lower().split())
        position = data.get("position", db().collections.count_documents({}) + 1)
        result = db().collections.insert_one({"name": data["name"].strip(), "slug": slug, "position": int(position), "active": True, "created_at": now()})
        activity(g.user, "create", "collection", result.inserted_id)
        return jsonify(id=str(result.inserted_id)), 201
    except Exception as exc:
        return json_error(exc)


@api.patch("/collections/<collection_id>")
@permission_required("settings:write")
def collection_update(collection_id):
    changes = body()
    allowed = {key: value for key, value in changes.items() if key in {"name", "position", "active"}}
    if "name" in allowed:
        allowed["slug"] = "-".join(allowed["name"].strip().lower().split())
    allowed["updated_at"] = now()
    result = db().collections.update_one({"_id": oid(collection_id)}, {"$set": allowed})
    if not result.matched_count:
        return jsonify(error="Collection not found"), 404
    activity(g.user, "update", "collection", collection_id, allowed)
    return jsonify(ok=True)


@api.get("/linesheets/dashboard")
@auth_required
def linesheet_dashboard():
    totals = {"total": db().linesheets.count_documents({})}
    for status in ("draft", "confirmed", "converted_to_order", "archived"):
        totals[status] = db().linesheets.count_documents({"status": status})
    by_collection = list(db().linesheets.aggregate([{"$group": {"_id": "$collection", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]))
    by_client = list(db().linesheets.aggregate([{"$group": {"_id": "$client_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]))
    sync = list(db().linesheets.aggregate([{"$group": {"_id": {"$ifNull": ["$workdrive_status", "not_uploaded"]}, "count": {"$sum": 1}}}]))
    imports = list(db().imports.find({}, {"filename": 1, "status": 1, "created_at": 1, "summary": 1}).sort("created_at", DESCENDING).limit(8))
    return jsonify(serialize({"totals": totals, "by_collection": by_collection, "by_client": by_client, "workdrive": sync, "recent_imports": imports}))


@api.route("/linesheets/<linesheet_id>", methods=["GET", "PATCH"])
@auth_required
def linesheet_detail(linesheet_id):
    sheet = db().linesheets.find_one({"_id": oid(linesheet_id)})
    if not sheet:
        return jsonify(error="Linesheet not found"), 404
    if request.method == "PATCH":
        if g.user["role"] not in {"admin", "sales"}:
            return jsonify(error="Permission denied"), 403
        changes = body()
        allowed = {k: v for k, v in changes.items() if k in {"name", "reference_number", "collection", "season", "status", "items", "purchase_order_id"}}
        if "items" in allowed:
            total_qty, total_value = 0, 0
            for item in allowed["items"]:
                qty = sum(int(v or 0) for v in item.get("size_quantities", {}).values())
                item["total_quantity"] = qty
                item["unit_price"] = money(item.get("unit_price") or item.get("mrp"))
                item["total_price"] = money(qty * float(item["unit_price"]))
                total_qty += qty
                total_value += qty * float(item["unit_price"])
            allowed.update(total_quantity=total_qty, total_value=money(total_value))
        allowed["updated_at"] = now()
        db().linesheets.update_one({"_id": sheet["_id"]}, {"$set": allowed})
        activity(g.user, "update", "linesheet", linesheet_id, {"fields": list(allowed)})
        sheet = db().linesheets.find_one({"_id": sheet["_id"]})
    related_order = db().orders.find_one({"source_linesheet_id": sheet["_id"]})
    documents = list(db().documents.find({"linesheet_id": sheet["_id"]}).sort("created_at", DESCENDING))
    return jsonify(serialize({"linesheet": sheet, "related_order": related_order, "documents": documents}))


def _normalized_header(value):
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _excel_mapping(headers):
    aliases = {"serial_number": {"sr no", "sr. no", "serial number"}, "vendor_code": {"vendor code"}, "sku": {"sku", "product sku"}, "color": {"color", "colour"}, "category": {"category"}, "component_count": {"no of components", "component count"}, "mrp": {"mrp"}, "remark": {"remark", "remarks"}, "reference_image_1": {"reference image 1"}, "reference_image_2": {"reference image 2"}, "po_delivery_date": {"po deliverydate", "po delivery date", "delivery date"}}
    mapping, sizes = {}, []
    for index, header in enumerate(headers):
        normalized = _normalized_header(header)
        for field, names in aliases.items():
            if normalized in names:
                mapping[field] = index
        first = normalized.split(" ")[0].upper() if normalized else ""
        if first in {"XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "FREE", "OS"}:
            sizes.append({"name": first, "column": index, "header": str(header)})
    return mapping, sizes


@api.post("/linesheets/import/inspect")
@permission_required("linesheets:write")
def inspect_linesheet_import():
    uploaded = request.files.get("file")
    if not uploaded or not (uploaded.filename or "").lower().endswith(".xlsx"):
        return jsonify(error="An .xlsx workbook is required"), 400
    raw = uploaded.read()
    if len(raw) > 25 * 1024 * 1024:
        return jsonify(error="Workbook exceeds the 25 MB limit"), 413
    import_id = str(uuid4())
    folder = Path(current_app.config["UPLOAD_DIR"]) / "imports" / import_id
    folder.mkdir(parents=True, exist_ok=True)
    source_path = folder / secure_filename(uploaded.filename or "linesheet.xlsx")
    source_path.write_bytes(raw)
    try:
        workbook = load_workbook(source_path, data_only=True)
    except Exception:
        return jsonify(error="Workbook could not be opened"), 400
    worksheet_name = request.form.get("worksheet") or workbook.sheetnames[0]
    if worksheet_name not in workbook.sheetnames:
        return jsonify(error="Worksheet not found", worksheets=workbook.sheetnames), 400
    worksheet = workbook[worksheet_name]
    headers = [cell.value for cell in worksheet[1]]
    mapping, size_columns = _excel_mapping(headers)
    preview, errors, seen = [], [], set()
    embedded_by_row = {}
    for number, image in enumerate(getattr(worksheet, "_images", []), 1):
        try:
            row_number = image.anchor._from.row + 1
            image_path = folder / f"embedded-{number}.png"
            image_path.write_bytes(image._data())
            embedded_by_row.setdefault(row_number, []).append(str(image_path))
        except Exception:
            continue
    for row_number, cells in enumerate(worksheet.iter_rows(min_row=2, values_only=True), 2):
        if not any(value not in (None, "") for value in cells):
            continue
        sku = str(cells[mapping["sku"]]).strip() if mapping.get("sku") is not None and cells[mapping["sku"]] is not None else ""
        row_errors = []
        if not sku:
            row_errors.append("Missing SKU")
        if sku and sku in seen:
            row_errors.append("Duplicate SKU")
        seen.add(sku)
        quantities = {}
        for size in size_columns:
            value = cells[size["column"]]
            try:
                quantities[size["name"]] = int(value or 0)
                if quantities[size["name"]] < 0:
                    raise ValueError()
            except (ValueError, TypeError):
                row_errors.append(f"Invalid quantity for {size['name']}")
        record = {"row_number": row_number, "values": [serialize(v) for v in cells], "sku": sku, "size_quantities": quantities, "images": embedded_by_row.get(row_number, []), "errors": row_errors}
        preview.append(record)
        errors.extend({"row": row_number, "message": message} for message in row_errors)
    doc = {"import_id": import_id, "filename": source_path.name, "source_path": str(source_path), "worksheet": worksheet_name, "worksheets": workbook.sheetnames, "headers": [str(v or "") for v in headers], "mapping": mapping, "size_columns": size_columns, "preview": preview, "status": "preview", "created_by": g.user["_id"], "created_at": now()}
    db().imports.insert_one(doc)
    return jsonify(serialize({"import_id": import_id, "filename": source_path.name, "worksheets": workbook.sheetnames, "worksheet": worksheet_name, "headers": doc["headers"], "mapping": mapping, "size_columns": size_columns, "rows": preview[:100], "summary": {"total": len(preview), "valid": len(preview)-len({e['row'] for e in errors}), "invalid": len({e['row'] for e in errors}), "errors": len(errors)}}))


@api.post("/linesheets/import/<import_id>/commit")
@permission_required("linesheets:write")
def commit_linesheet_import(import_id):
    imported = db().imports.find_one({"import_id": import_id})
    if not imported:
        return jsonify(error="Import preview not found"), 404
    try:
        data = body(("client_id", "collection", "type", "name"))
        client = db().clients.find_one({"_id": oid(data["client_id"])})
        collection = db().collections.find_one({"name": data["collection"], "active": True})
        if not client or not collection:
            raise ValueError("Valid client and collection are required")
        mapping, items, skipped, created_products = imported["mapping"], [], 0, 0
        for row in imported["preview"]:
            if row["errors"]:
                skipped += 1
                continue
            values = row["values"]
            def value(field, default=None):
                index = mapping.get(field)
                return values[index] if index is not None and index < len(values) else default
            sku = str(row["sku"])
            product = db().products.find_one({"sku": sku})
            item = {"sku": sku, "vendor_code": str(value("vendor_code", "") or ""), "product_name": product.get("name") if product else sku, "color": value("color", ""), "category": value("category", ""), "component_count": value("component_count", 0), "mrp": money(value("mrp", 0)), "unit_price": money(value("mrp", 0)), "remark": value("remark", ""), "po_delivery_date": value("po_delivery_date"), "size_quantities": row["size_quantities"], "images": row["images"]}
            items.append(item)
            if not product and data.get("create_products", True):
                db().products.insert_one({"name": item["product_name"], "sku": sku, "vendor_code": item["vendor_code"], "collection": data["collection"], "category": item["category"], "colors": [item["color"]], "sizes": list(item["size_quantities"]), "selling_price": item["mrp"], "images": row["images"], "active": True, "created_at": now(), "updated_at": now()})
                created_products += 1
        total_qty = sum(sum(int(v) for v in item["size_quantities"].values()) for item in items)
        total_value = sum(sum(int(v) for v in item["size_quantities"].values()) * float(item["unit_price"]) for item in items)
        sheet = {"linesheet_number": next_number(db(), "linesheet", "LS"), "name": data["name"], "reference_number": data.get("reference_number"), "collection": data["collection"], "client_id": client["_id"], "client_name": client["name"], "type": data["type"], "items": items, "total_quantity": total_qty, "total_value": money(total_value), "status": data.get("status", "draft"), "source_import_id": import_id, "original_workbook": {"filename": imported["filename"], "path": imported["source_path"], "worksheet": imported["worksheet"], "headers": imported["headers"]}, "workdrive_status": "not_uploaded", "created_by": g.user["_id"], "created_at": now(), "updated_at": now()}
        result = db().linesheets.insert_one(sheet)
        summary = {"products_imported": len(items), "rows_skipped": skipped, "errors": sum(len(row["errors"]) for row in imported["preview"]), "new_products_created": created_products, "existing_products_matched": len(items)-created_products}
        db().imports.update_one({"_id": imported["_id"]}, {"$set": {"status": "imported", "linesheet_id": result.inserted_id, "summary": summary, "completed_at": now()}})
        activity(g.user, "import", "linesheet", result.inserted_id, summary)
        return jsonify(id=str(result.inserted_id), linesheet_number=sheet["linesheet_number"], summary=summary), 201
    except Exception as exc:
        return json_error(exc)


@api.get("/linesheets/<linesheet_id>/export.xlsx")
@auth_required
def export_linesheet_excel(linesheet_id):
    sheet_doc = db().linesheets.find_one({"_id": oid(linesheet_id)})
    if not sheet_doc:
        return jsonify(error="Linesheet not found"), 404
    original = request.args.get("format") == "original" and sheet_doc.get("original_workbook")
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = (sheet_doc.get("collection") or "Linesheet")[:31]
    size_names = []
    for item in sheet_doc.get("items", []):
        for size in item.get("size_quantities", {}):
            if size not in size_names:
                size_names.append(size)
    standard_headers = ["Sr No", "Image", "Vendor Code", "Sku", "Color", "Category", "No of Components", "MRP", *size_names, "Remark", "Reference Image 1", "Reference Image 2", "Po DeliveryDate"]
    headers = sheet_doc.get("original_workbook", {}).get("headers") if original else standard_headers
    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(fill_type="solid", fgColor="2A2622")
    for index, item in enumerate(sheet_doc.get("items", []), 1):
        values = {"Sr No": index, "Vendor Code": item.get("vendor_code"), "Sku": item.get("sku"), "Color": item.get("color"), "Category": item.get("category"), "No of Components": item.get("component_count"), "MRP": float(item.get("mrp") or item.get("unit_price") or 0), "Remark": item.get("remark"), "Reference Image 1": item.get("reference_image_1"), "Reference Image 2": item.get("reference_image_2"), "Po DeliveryDate": item.get("po_delivery_date")}
        values.update(item.get("size_quantities", {}))
        worksheet.append([values.get(header, values.get(str(header).split(" ")[0].upper(), "")) for header in headers])
        image_paths = item.get("images") or []
        if image_paths and os.path.exists(image_paths[0]) and "Image" in headers:
            try:
                excel_image = ExcelImage(image_paths[0]); excel_image.width = 72; excel_image.height = 88
                worksheet.add_image(excel_image, f"{chr(65 + headers.index('Image'))}{index+1}")
                worksheet.row_dimensions[index+1].height = 70
            except Exception:
                pass
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for column in worksheet.columns:
        worksheet.column_dimensions[column[0].column_letter].width = min(max(12, max(len(str(cell.value or "")) for cell in column) + 2), 35)
    output = BytesIO(); workbook.save(output); output.seek(0)
    db().documents.insert_one({"family_id": str(uuid4()), "version": 1, "linesheet_id": sheet_doc["_id"], "kind": "linesheet_excel_export", "original_name": f"{sheet_doc['linesheet_number']}.xlsx", "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size": output.getbuffer().nbytes, "storage_provider": "generated", "upload_status": "not_uploaded", "uploaded_by": g.user["_id"], "created_at": now()})
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"{sheet_doc['linesheet_number']}.xlsx")


@api.post("/products/<product_id>/images")
@permission_required("linesheets:write")
def upload_product_images(product_id):
    product = db().products.find_one({"_id": oid(product_id)})
    if not product:
        return jsonify(error="Product not found"), 404
    files = request.files.getlist("files")
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if not files or any(item.mimetype not in allowed for item in files):
        return jsonify(error="JPG, PNG or WebP images are required"), 400
    folder = Path(current_app.config["UPLOAD_DIR"]) / "products" / product["sku"]
    folder.mkdir(parents=True, exist_ok=True)
    metadata = []
    for position, uploaded in enumerate(files, len(product.get("images", []))):
        data = uploaded.read()
        if len(data) > 10 * 1024 * 1024:
            return jsonify(error=f"{uploaded.filename} exceeds 10 MB"), 413
        filename = f"{uuid4()}-{secure_filename(uploaded.filename or 'image')}"
        path = folder / filename; path.write_bytes(data)
        metadata.append({"id": str(uuid4()), "path": str(path), "filename": filename, "content_type": uploaded.mimetype, "view": request.form.get("view", "detail"), "description": request.form.get("description", ""), "collection": request.form.get("collection", product.get("collection")), "position": position, "is_main": position == 0 and not product.get("images"), "created_at": now()})
    db().products.update_one({"_id": product["_id"]}, {"$push": {"images": {"$each": metadata}}, "$set": {"updated_at": now()}})
    activity(g.user, "upload_images", "product", product_id, {"count": len(metadata)})
    return jsonify(items=serialize(metadata)), 201


@api.get("/workdrive/status")
@auth_required
def workdrive_status():
    client = WorkDriveClient()
    stored = db().settings.find_one({"_id": "workdrive_oauth"}) or {}
    verified = bool(stored.get("verified_at") and client.root_folder_configured and stored.get("verified_folder_id") == client.root_folder_id)
    if verified:
        status = "connected"
    elif "token_encryption_key" in client.missing_configuration:
        status = "missing_encryption_key"
    elif "refresh_token" in client.missing_configuration:
        status = "missing_refresh_token"
    else:
        status = stored.get("error_kind") or "incomplete"
    sync_counts = {item["_id"]: item["count"] for item in db().documents.aggregate([{"$group": {"_id": {"$ifNull": ["$upload_status", "not_uploaded"]}, "count": {"$sum": 1}}}])}
    return jsonify(configured=client.configured, missing=client.missing_configuration, root_folder_configured=client.root_folder_configured, verified=verified, status=status, verification_error=stored.get("verification_error"), connected_at=stored.get("connected_at") if verified else None, verified_at=stored.get("verified_at") if verified else None, connected_account_email=stored.get("account_email"), root_folder_name=stored.get("root_folder_name") if verified else None, team_id=stored.get("team_id") if verified else None, storage_structure=([{"name": stored.get("root_folder_name"), "type": "team_folder", "verified": True}] if verified and stored.get("root_folder_name") else []), synchronization={"counts": sync_counts, "last_successful_sync": stored.get("last_successful_sync")})


@api.post("/workdrive/test")
@permission_required("settings:write")
def workdrive_test():
    try:
        client = WorkDriveClient()
        folder = client.verify_root_folder()
        db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"verified_at": now(), "verified_folder_id": folder["id"], "root_folder_name": folder["name"], "team_id": folder["team_id"]}, "$unset": {"verification_error": "", "error_kind": ""}}, upsert=True)
        return jsonify(ok=True, verified=True, verified_at=now(), root_folder_name=folder["name"])
    except WorkDriveError as exc:
        db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"verification_error": str(exc), "error_kind": exc.kind, "failed_at": now()}}, upsert=True)
        return jsonify(error=str(exc), status=exc.kind), 503


@api.post("/workdrive/disconnect")
@permission_required("settings:write")
def workdrive_disconnect():
    db().settings.delete_one({"_id": "workdrive_oauth"})
    return jsonify(ok=True)


def _mail_status_payload():
    client = ZohoMailClient()
    stored = client.record
    verified = bool(stored.get("verified_at") and stored.get("account_id") and client.encrypted_refresh_token)
    if verified:
        status = "connected"
    elif "token_encryption_key" in client.missing:
        status = "missing_encryption_key"
    elif "refresh_token" in client.missing:
        status = "missing_refresh_token"
    else:
        status = stored.get("error_kind") or "incomplete"
    settings = db().settings.find_one({"_id": "zoho_mail_settings"}) or {}
    return {"configured": client.configured, "missing": client.missing, "verified": verified, "status": status, "verification_error": stored.get("verification_error"), "account_email": stored.get("account_email") if verified else None, "account_id": stored.get("account_id") if verified else None, "organization": stored.get("organization") if verified else None, "connected_at": stored.get("connected_at") if verified else None, "verified_at": stored.get("verified_at") if verified else None, "last_sent_at": stored.get("last_sent_at") if verified else None, "scopes": [scope.strip() for scope in client.scopes.split(",") if scope.strip()], "email_settings": {"sender_display_name": settings.get("sender_display_name", ""), "reply_to_email": settings.get("reply_to_email", ""), "default_signature": settings.get("default_signature", ""), "notifications_enabled": bool(settings.get("notifications_enabled", False))}}


@api.get("/mail/status")
@auth_required
def mail_status():
    return jsonify(_mail_status_payload())


@api.post("/mail/connect")
@permission_required("settings:write")
def mail_connect():
    try:
        state = str(uuid4())
        db().settings.insert_one({"_id": f"mail_state:{state}", "state": state, "user_id": g.user["_id"], "expires_at": now() + timedelta(minutes=10), "created_at": now()})
        return jsonify(authorization_url=ZohoMailClient().authorization_url(state))
    except WorkDriveError as exc:
        return jsonify(error=str(exc), status=exc.kind), 503


@api.post("/mail/disconnect")
@permission_required("settings:write")
def mail_disconnect():
    db().settings.delete_one({"_id": ZohoMailClient.record_id})
    return jsonify(ok=True)


@api.post("/mail/test")
@permission_required("settings:write")
def mail_test():
    try:
        account = ZohoMailClient().verify_account()
        return jsonify(ok=True, verified=True, account_email=account.get("email"), organization=account.get("organization"), verified_at=now())
    except WorkDriveError as exc:
        db().settings.update_one({"_id": ZohoMailClient.record_id}, {"$set": {"verification_error": str(exc), "error_kind": exc.kind, "failed_at": now()}}, upsert=True)
        return jsonify(error=str(exc), status=exc.kind), 503


@api.patch("/mail/settings")
@permission_required("settings:write")
def mail_settings_update():
    data = body()
    allowed = {"sender_display_name", "reply_to_email", "default_signature", "notifications_enabled"}
    changes = {key: data[key] for key in allowed if key in data}
    if "reply_to_email" in changes and changes["reply_to_email"] and "@" not in changes["reply_to_email"]:
        return jsonify(error="Reply-to email address is invalid"), 400
    changes["updated_at"] = now()
    changes["updated_by"] = g.user["_id"]
    db().settings.update_one({"_id": "zoho_mail_settings"}, {"$set": changes}, upsert=True)
    return jsonify(ok=True, settings=_mail_status_payload()["email_settings"])


@api.post("/mail/test-email")
@permission_required("settings:write")
def mail_test_email():
    try:
        data = body(("to",))
        if "@" not in data["to"]:
            return jsonify(error="Recipient email address is invalid"), 400
        settings = db().settings.find_one({"_id": "zoho_mail_settings"}) or {}
        result = ZohoMailClient().send_message(data["to"], "RK Fashion portal test email", "<p>Your Zoho Mail connection to the RK Fashion Operations Portal is working.</p>", settings.get("sender_display_name"), settings.get("reply_to_email"))
        return jsonify(ok=True, accepted=result["accepted"])
    except (ValueError, WorkDriveError) as exc:
        kind = exc.kind if isinstance(exc, WorkDriveError) else "validation_error"
        return jsonify(error=str(exc), status=kind), 503 if isinstance(exc, WorkDriveError) else 400


@api.get("/integrations/zoho/mail/callback")
def mail_callback():
    frontend = current_app.config["FRONTEND_ORIGIN"]
    state = request.args.get("state", "")
    state_doc = db().settings.find_one({"_id": f"mail_state:{state}", "state": state})
    expires_at = utc_datetime(state_doc.get("expires_at")) if state_doc else None
    if not state_doc or (expires_at or utc_datetime(now())) < utc_datetime(now()):
        return redirect(f"{frontend}/workspace/mail?mail=error&message=Invalid%20or%20expired%20OAuth%20state")
    db().settings.delete_one({"_id": state_doc["_id"]})
    if request.args.get("error"):
        return redirect(f"{frontend}/workspace/mail?mail=error&message=Zoho%20authorization%20was%20cancelled")
    try:
        client = ZohoMailClient()
        client.exchange_code(request.args.get("code", ""))
        client.verify_account()
        db().settings.update_one({"_id": client.record_id}, {"$unset": {"verification_error": "", "error_kind": ""}, "$set": {"verified_by": state_doc["user_id"]}}, upsert=True)
        return redirect(f"{frontend}/workspace/mail?mail=connected")
    except WorkDriveError as exc:
        db().settings.update_one({"_id": ZohoMailClient.record_id}, {"$set": {"verification_error": str(exc), "error_kind": exc.kind, "failed_at": now()}, "$unset": {"verified_at": "", "account_id": ""}}, upsert=True)
        return redirect(f"{frontend}/workspace/mail?mail=error&message={quote(str(exc))}")


@api.post("/workdrive/connect")
@permission_required("settings:write")
def workdrive_connect():
    try:
        state = str(uuid4())
        db().settings.insert_one({"_id": f"workdrive_state:{state}", "state": state, "user_id": g.user["_id"], "expires_at": now() + timedelta(minutes=10), "created_at": now()})
        return jsonify(authorization_url=WorkDriveClient().authorization_url(state))
    except WorkDriveError as exc:
        return jsonify(error=str(exc)), 503


@api.get("/integrations/zoho/callback")
def workdrive_callback():
    frontend = current_app.config["FRONTEND_ORIGIN"]
    state = request.args.get("state", "")
    state_doc = db().settings.find_one({"_id": f"workdrive_state:{state}", "state": state})
    expires_at = utc_datetime(state_doc.get("expires_at")) if state_doc else None
    if not state_doc or (expires_at or utc_datetime(now())) < utc_datetime(now()):
        return redirect(f"{frontend}/workspace/settings?workdrive=error&message=Invalid%20or%20expired%20OAuth%20state")
    db().settings.delete_one({"_id": state_doc["_id"]})
    if request.args.get("error"):
        return redirect(f"{frontend}/workspace/settings?workdrive=error&message=Zoho%20authorization%20was%20cancelled")
    try:
        client = WorkDriveClient()
        client.exchange_code(request.args.get("code", ""))
        folder = client.discover_root_folder()
        connected_at = (db().settings.find_one({"_id": "workdrive_oauth"}) or {}).get("connected_at") or now()
        db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"root_folder_id": folder["id"], "root_folder_name": folder["name"], "team_id": folder["team_id"], "connected_at": connected_at, "verified_at": now(), "verified_by": state_doc["user_id"], "verified_folder_id": folder["id"]}, "$unset": {"verification_error": "", "error_kind": ""}}, upsert=True)
        return redirect(f"{frontend}/workspace/settings?workdrive=connected")
    except WorkDriveError as exc:
        db().settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"verification_error": str(exc), "error_kind": exc.kind, "failed_at": now()}, "$unset": {"verified_at": "", "verified_folder_id": ""}}, upsert=True)
        return redirect(f"{frontend}/workspace/settings?workdrive=error&message={quote(str(exc))}")


@api.post("/documents/<document_id>/sync-workdrive")
@permission_required("documents:write")
def sync_document_workdrive(document_id):
    document = db().documents.find_one({"_id": oid(document_id)})
    if not document:
        return jsonify(error="Document not found"), 404
    if document.get("workdrive_file_id") and document.get("upload_status") == "synced":
        return jsonify(document=serialize(document), duplicate_prevented=True)
    if not document.get("stored_path") or not os.path.exists(document["stored_path"]):
        return jsonify(error="This generated document must be downloaded and retained locally before synchronization"), 409
    db().documents.update_one({"_id": document["_id"]}, {"$set": {"upload_status": "upload_pending", "sync_attempted_at": now()}})
    try:
        result = WorkDriveClient().upload(document["stored_path"], document.get("workdrive_folder_id"), document.get("original_name"))
        file_data = (result.get("data") or [{}])[0]
        attributes = file_data.get("attributes", {})
        db().documents.update_one({"_id": document["_id"]}, {"$set": {"upload_status": "synced", "storage_provider": "local_and_workdrive", "workdrive_file_id": file_data.get("id"), "workdrive_link": attributes.get("permalink"), "synced_at": now()}, "$unset": {"sync_error": ""}})
    except WorkDriveError as exc:
        db().documents.update_one({"_id": document["_id"]}, {"$set": {"upload_status": "failed", "sync_error": str(exc), "updated_at": now()}})
        return jsonify(error=str(exc), status="failed"), 503
    return jsonify(document=serialize(db().documents.find_one({"_id": document["_id"]})))
