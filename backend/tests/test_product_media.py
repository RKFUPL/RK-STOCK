from io import BytesIO

import pytest
from bson import ObjectId
from werkzeug.datastructures import MultiDict
from app.cloudinary_service import CloudinaryUploadError, delete_image, product_asset_folder, upload_image


def _files(*items):
    return MultiDict([( "files", (BytesIO(content), filename, content_type)) for filename, content, content_type in items])


def _product(app):
    product_id = ObjectId()
    app.extensions["mongo_db"].products.insert_one({"_id": product_id, "sku": "MEDIA-001", "name": "Media test", "images": []})
    return str(product_id)


def test_cloudinary_upload_multiple_and_primary(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes.upload_image", lambda *args, **kwargs: {"secure_url": "https://res.cloudinary.com/test/image/upload/a.jpg", "public_id": "rk-stock/a"})
    response = client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("a.jpg", b"data", "image/jpeg"), ("b.jpg", b"data", "image/jpeg")), content_type="multipart/form-data")
    assert response.status_code == 201
    images = app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"]
    assert len(images) == 2 and images[0]["source"] == "rk-stock" and images[0]["is_primary"] is True


def test_media_reorder_remove_and_invalid_file(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes.upload_image", lambda *args, **kwargs: {"secure_url": "https://res.cloudinary.com/test/image/upload/a.jpg", "public_id": "a"})
    created = client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("a.jpg", b"data", "image/jpeg"), ("b.jpg", b"data", "image/jpeg")), content_type="multipart/form-data").json["items"]
    ids = [item["id"] for item in created]
    assert client.patch(f"/api/products/{product_id}/images", headers=headers, json={"order": ids[::-1], "primary_id": ids[0]}).status_code == 200
    deleted = []
    monkeypatch.setattr("app.routes.delete_image", lambda _app, public_id, *_args: deleted.append(public_id) or {"result": "ok", "already_missing": False})
    response = client.delete(f"/api/products/{product_id}/images/{ids[0]}", headers=headers)
    assert response.status_code == 200
    assert response.json["cloudinary_deleted"] is True
    assert deleted == ["a"]
    invalid = client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("bad.gif", b"data", "image/gif")), content_type="multipart/form-data")
    assert invalid.status_code == 400


def _set_media(app, product_id, images):
    app.extensions["mongo_db"].products.update_one({"_id": ObjectId(product_id)}, {"$set": {"images": images}})


def _stored_media(app, product_id):
    return app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"]


def test_rk_stock_delete_failure_preserves_relationship(client, app, headers, monkeypatch):
    product_id = _product(app)
    media = {"id": "stock-1", "url": "https://res.cloudinary.com/test/image/upload/stock-1.jpg", "public_id": "stock-1", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [media])
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: (_ for _ in ()).throw(CloudinaryUploadError("Cloudinary rejected the image deletion")))

    response = client.delete(f"/api/products/{product_id}/images/stock-1", headers=headers)

    assert response.status_code == 502
    assert _stored_media(app, product_id) == [media]


def test_rk_stock_not_found_is_idempotent_success_and_promotes_primary(client, app, headers, monkeypatch):
    product_id = _product(app)
    first = {"id": "stock-1", "url": "https://res.cloudinary.com/test/image/upload/stock-1.jpg", "public_id": "stock-1", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    second = {"id": "web-2", "url": "https://res.cloudinary.com/test/image/upload/web-2.jpg", "source": "rk-web", "position": 1, "is_primary": False, "is_main": False}
    _set_media(app, product_id, [first, second])
    calls = []
    monkeypatch.setattr("app.routes.delete_image", lambda _app, public_id, *_args: calls.append(public_id) or {"result": "not found", "already_missing": True})

    response = client.delete(f"/api/products/{product_id}/images/stock-1", headers=headers)

    assert response.status_code == 200
    assert response.json["cloudinary_already_missing"] is True
    assert calls == ["stock-1"]
    remaining = _stored_media(app, product_id)
    assert len(remaining) == 1 and remaining[0]["id"] == "web-2"
    assert remaining[0]["is_primary"] is True and remaining[0]["position"] == 0
    assert client.delete(f"/api/products/{product_id}/images/stock-1", headers=headers).status_code == 404
    assert calls == ["stock-1"]


@pytest.mark.parametrize("source", ["rk-web", "legacy", None])
def test_non_rk_stock_delete_removes_only_relationship(client, app, headers, monkeypatch, source):
    product_id = _product(app)
    media = {"id": "external-1", "url": "https://res.cloudinary.com/external/image/upload/external-1.jpg", "public_id": "external-1", "position": 0, "is_primary": True, "is_main": True}
    if source is not None:
        media["source"] = source
    _set_media(app, product_id, [media])
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("external media must not be destroyed"))

    response = client.delete(f"/api/products/{product_id}/images/external-1", headers=headers)

    assert response.status_code == 200
    assert response.json["remote_asset_preserved"] is True
    assert _stored_media(app, product_id) == []


def test_media_delete_requires_authentication(client, app, monkeypatch):
    product_id = _product(app)
    _set_media(app, product_id, [{"id": "stock-1", "public_id": "stock-1", "source": "rk-stock"}])
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("unauthorized deletion must not reach Cloudinary"))
    assert client.delete(f"/api/products/{product_id}/images/stock-1").status_code == 401
    assert len(_stored_media(app, product_id)) == 1


def test_media_upload_requires_permission_and_preserves_existing_rk_web_url(client, app, headers, monkeypatch):
    product_id = _product(app)
    existing = {"id": "web-1", "url": "https://res.cloudinary.com/rk-web/image/upload/existing.jpg", "is_main": True, "is_primary": True, "source": "rk-web"}
    app.extensions["mongo_db"].products.update_one({"_id": ObjectId(product_id)}, {"$set": {"images": [existing]}})
    assert client.post(f"/api/products/{product_id}/images", data=_files(("a.jpg", b"data", "image/jpeg")), content_type="multipart/form-data").status_code == 401
    monkeypatch.setattr("app.routes.upload_image", lambda *args, **kwargs: {"secure_url": "https://res.cloudinary.com/test/image/upload/new.jpg", "public_id": "new"})
    assert client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("a.jpg", b"data", "image/jpeg")), content_type="multipart/form-data").status_code == 201
    images = app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"]
    assert images[0]["url"] == existing["url"] and images[0]["source"] == "rk-web"


def test_oversized_and_cloudinary_failure_do_not_create_media(client, app, headers, monkeypatch):
    product_id = _product(app)
    oversized = client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("large.jpg", b"x" * (10 * 1024 * 1024 + 1), "image/jpeg")), content_type="multipart/form-data")
    assert oversized.status_code == 502
    monkeypatch.setattr("app.routes.upload_image", lambda *args, **kwargs: (_ for _ in ()).throw(CloudinaryUploadError("Cloudinary rejected the image upload")))
    failed = client.post(f"/api/products/{product_id}/images", headers=headers, data=_files(("a.jpg", b"data", "image/jpeg")), content_type="multipart/form-data")
    assert failed.status_code == 502
    assert app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"] == []


def test_cloudinary_response_error_and_malformed_response_are_sanitized(app, monkeypatch):
    app.config.update(CLOUDINARY_CLOUD_NAME="test-cloud", CLOUDINARY_API_KEY="test-key", CLOUDINARY_API_SECRET="test-secret")
    class Response:
        ok = False
        def json(self): return {"error": {"message": "Invalid Signature"}}
    monkeypatch.setattr("app.cloudinary_service.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(CloudinaryUploadError, match="Invalid Signature"):
        upload_image(app, BytesIO(b"data"), "test.jpg", "image/jpeg", "rk-stock/test")

    class Malformed:
        ok = True
        def json(self): raise ValueError("not json")
    monkeypatch.setattr("app.cloudinary_service.requests.post", lambda *args, **kwargs: Malformed())
    with pytest.raises(CloudinaryUploadError, match="invalid response"):
        upload_image(app, BytesIO(b"data"), "test.jpg", "image/jpeg", "rk-stock/test")


def test_hastakala_product_reuses_existing_dynamic_asset_folder(app, monkeypatch):
    app.config.update(CLOUDINARY_CLOUD_NAME="test-cloud", CLOUDINARY_API_KEY="test-key", CLOUDINARY_API_SECRET="test-secret")
    class Response:
        ok = True
        def json(self): return {"asset_folder": "HASTHKALA/Products/173-Hot Pink"}
    monkeypatch.setattr("app.cloudinary_service.requests.get", lambda *args, **kwargs: Response())
    product = {"sku": "HK-173-HP", "name": "173 - Hot Pink", "images": [{"url": "https://res.cloudinary.com/test/image/upload/v1/H17_2259_l1kc3d.jpg", "source": "rk-web"}]}
    assert product_asset_folder(app, product) == "HASTHKALA/Products/173-Hot Pink"


def test_upload_signs_and_sends_asset_folder_not_legacy_folder(app, monkeypatch):
    app.config.update(CLOUDINARY_CLOUD_NAME="test-cloud", CLOUDINARY_API_KEY="test-key", CLOUDINARY_API_SECRET="test-secret")
    captured = {}
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"secure_url": "https://res.cloudinary.com/test/image/upload/new.jpg", "public_id": "new"}
    def post(url, **kwargs):
        captured.update(kwargs["data"])
        return Response()
    monkeypatch.setattr("app.cloudinary_service.requests.post", post)
    upload_image(app, BytesIO(b"data"), "test.jpg", "image/jpeg", "HASTHKALA/Products/173-Hot Pink")
    assert captured["asset_folder"] == "HASTHKALA/Products/173-Hot Pink"
    assert "folder" not in captured
    assert captured.get("timestamp") and captured.get("signature") and captured.get("api_key")


def test_cloudinary_delete_signs_exact_destroy_parameters(app, monkeypatch):
    app.config.update(CLOUDINARY_CLOUD_NAME="test-cloud", CLOUDINARY_API_KEY="test-key", CLOUDINARY_API_SECRET="test-secret")
    captured = {}
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"result": "ok"}
    def post(url, **kwargs):
        captured["url"] = url
        captured["data"] = kwargs["data"]
        return Response()
    monkeypatch.setattr("app.cloudinary_service.requests.post", post)

    result = delete_image(app, "rk-stock/test-asset")

    assert result == {"result": "ok", "already_missing": False}
    assert captured["url"].endswith("/test-cloud/image/destroy")
    assert set(captured["data"]) == {"public_id", "timestamp", "type", "api_key", "signature"}
    assert captured["data"]["public_id"] == "rk-stock/test-asset"
    assert captured["data"]["type"] == "upload"
