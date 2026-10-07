from io import BytesIO
import threading

import pytest
from bson import ObjectId
from werkzeug.datastructures import MultiDict
from app.auth import hash_password
from app.cloudinary_service import CloudinaryUploadError, delete_image, product_asset_folder, upload_image
from app.storefront_integration import StorefrontIntegrationClient
from app.utils import now
from app.workdrive import WorkDriveClient, WorkDriveError


def _files(*items):
    return MultiDict([( "files", (BytesIO(content), filename, content_type)) for filename, content, content_type in items])


def _product(app):
    product_id = ObjectId()
    app.extensions["mongo_db"].products.insert_one({"_id": product_id, "sku": "MEDIA-001", "name": "Media test", "images": []})
    return str(product_id)


def _headers_without_media_permission(client, app):
    app.extensions["mongo_db"].users.insert_one({"name": "Viewer", "email": "viewer@rk.test", "password_hash": hash_password("viewer-test-password"), "role": "production_inventory", "active": True, "created_at": now()})
    response = client.post("/api/auth/login", json={"email": "viewer@rk.test", "password": "viewer-test-password"})
    assert response.status_code == 200
    client.delete_cookie("rk_stock_session")
    return {"Authorization": f"Bearer {response.json['token']}"}


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


def test_external_workdrive_media_is_structured_and_primary(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    response = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/test-one", "position": 0, "is_primary": True, "alt_text": "Lookbook one"})
    assert response.status_code == 201
    item = response.json["item"]
    assert item["provider"] == "zoho_workdrive" and item["permalink"].endswith("test-one")
    assert item["source"] == "rk-stock"
    assert item["is_primary"] is True
    assert app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"][0]["url"] == item["permalink"]


def test_workdrive_embed_media_preserves_authoritative_permalink(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    permalink = "https://workdrive.zohoexternal.in/embed/test-preview"
    response = client.post(
        f"/api/products/{product_id}/media",
        headers=headers,
        json={"provider": "zoho_workdrive", "type": "embed", "permalink": permalink},
    )
    assert response.status_code == 201
    item = response.json["item"]
    assert item["provider"] == "zoho_workdrive"
    assert item["type"] == "embed"
    assert item["permalink"] == permalink
    assert item["url"] == permalink


def test_workdrive_preview_uses_provider_metadata_without_replacing_permalink(client, app, headers, monkeypatch):
    product_id = _product(app)
    media = {"id": "wd-preview", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/preview-resource", "url": "https://workdrive.zoho.in/file/preview-resource", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [media])

    class PreviewClient:
        def preview_metadata(self, resource_id):
            assert resource_id == "preview-resource"
            return {"preview_url": "https://previewengine.zoho.in/preview/preview-resource"}

    monkeypatch.setattr("app.routes.WorkDriveClient", PreviewClient)
    response = client.get(f"/api/products/{product_id}/media/wd-preview/preview", headers=headers)
    assert response.status_code == 200
    assert response.json["preview"]["preview_url"].endswith("preview-resource")
    assert "token" not in response.get_data(as_text=True).lower()
    assert app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"][0]["permalink"] == media["permalink"]


def test_workdrive_preview_image_endpoint_returns_provider_image_bytes(client, app, headers, monkeypatch):
    product_id = _product(app)
    media = {"id": "wd-image", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/preview-resource", "url": "https://workdrive.zoho.in/file/preview-resource", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [media])

    class PreviewClient:
        def preview_content(self, resource_id):
            assert resource_id == "preview-resource"
            return b"preview-image", "image/jpeg"

    monkeypatch.setattr("app.routes.WorkDriveClient", PreviewClient)
    response = client.get(f"/api/products/{product_id}/media/wd-image/preview/image", headers=headers)
    assert response.status_code == 200
    assert response.data == b"preview-image"
    assert response.content_type.startswith("image/jpeg")
    assert "token" not in response.headers


def test_workdrive_preview_content_prefers_preview_data_url_over_html_preview_url(monkeypatch):
    class Response:
        def __init__(self, content, content_type):
            self.ok = True
            self.status_code = 200
            self.content = content
            self.headers = {"Content-Type": content_type}

    workdrive = WorkDriveClient()
    monkeypatch.setattr(workdrive, "preview_metadata", lambda _resource_id: {"preview_url": "https://www.zohoapis.in/workdrive/preview/test", "preview_data_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="})
    monkeypatch.setattr(workdrive, "access_token", lambda: "private-test-token")
    responses = iter([Response(b"<html>preview</html>", "text/html")])
    monkeypatch.setattr("app.workdrive.requests.get", lambda *_args, **_kwargs: next(responses))
    content, content_type = workdrive.preview_content("preview-resource")
    assert content == b"image-bytes"
    assert content_type == "image/png"


def test_workdrive_preview_content_falls_back_to_thumbnail_after_invalid_data_url(monkeypatch):
    class Response:
        ok = True
        status_code = 200
        content = b"thumbnail-bytes"
        headers = {"Content-Type": "image/webp"}

    workdrive = WorkDriveClient()
    monkeypatch.setattr(workdrive, "preview_metadata", lambda _resource_id: {"preview_data_url": "data:image/png;base64:not-valid", "thumbnail_url": "https://www.zohoapis.in/workdrive/thumb/test", "preview_url": "https://www.zohoapis.in/workdrive/html/test"})
    monkeypatch.setattr(workdrive, "access_token", lambda: "private-test-token")
    monkeypatch.setattr("app.workdrive.requests.get", lambda *_args, **_kwargs: Response())
    content, content_type = workdrive.preview_content("preview-resource")
    assert content == b"thumbnail-bytes"
    assert content_type == "image/webp"


def test_workdrive_preview_content_accepts_provider_data_image(monkeypatch):
    workdrive = WorkDriveClient()
    monkeypatch.setattr(workdrive, "preview_metadata", lambda _resource_id: {"preview_data_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="})
    monkeypatch.setattr(workdrive, "access_token", lambda: "private-test-token")
    content, content_type = workdrive.preview_content("preview-resource")
    assert content == b"image-bytes"
    assert content_type == "image/png"


def test_workdrive_preview_content_rejects_non_image_provider_response(monkeypatch):
    class Response:
        ok = True
        status_code = 200
        content = b"<html>preview</html>"
        headers = {"Content-Type": "text/html"}

    workdrive = WorkDriveClient()
    monkeypatch.setattr(workdrive, "preview_metadata", lambda _resource_id: {"preview_url": "https://www.zohoapis.in/workdrive/preview/test"})
    monkeypatch.setattr(workdrive, "access_token", lambda: "private-test-token")
    monkeypatch.setattr("app.workdrive.requests.get", lambda *_args, **_kwargs: Response())
    with pytest.raises(WorkDriveError, match="preview is unavailable"):
        workdrive.preview_content("preview-resource")


def test_workdrive_access_token_reuses_valid_cache(app, monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ZOHO_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("ZOHO_TOKEN_ENCRYPTION_KEY", "unused")
    app.extensions["mongo_db"].settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"refresh_token_encrypted": "encrypted"}}, upsert=True)
    class Cipher:
        def decrypt(self, _value): return b"refresh"
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"access_token": "cached-token", "expires_in": 3600}
    calls = []
    monkeypatch.setattr(WorkDriveClient, "_cipher", lambda _self: Cipher())
    monkeypatch.setattr("app.workdrive.requests.post", lambda *args, **kwargs: (calls.append(1) or Response()))
    WorkDriveClient.clear_access_token_cache()
    with app.app_context():
        assert WorkDriveClient().access_token() == "cached-token"
        assert WorkDriveClient().access_token() == "cached-token"
    assert len(calls) == 1
    WorkDriveClient.clear_access_token_cache()


def test_workdrive_access_token_single_flight_for_concurrent_callers(app, monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ZOHO_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("ZOHO_TOKEN_ENCRYPTION_KEY", "unused")
    app.extensions["mongo_db"].settings.update_one({"_id": "workdrive_oauth"}, {"$set": {"refresh_token_encrypted": "encrypted"}}, upsert=True)
    class Cipher:
        def decrypt(self, _value): return b"refresh"
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"access_token": "single-flight-token", "expires_in": 3600}
    calls = []
    def post(*_args, **_kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(WorkDriveClient, "_cipher", lambda _self: Cipher())
    monkeypatch.setattr("app.workdrive.requests.post", post)
    WorkDriveClient.clear_access_token_cache()
    results = []
    def call():
        with app.app_context():
            results.append(WorkDriveClient().access_token())
    threads = [threading.Thread(target=call) for _ in range(3)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert results == ["single-flight-token"] * 3
    assert len(calls) == 1
    WorkDriveClient.clear_access_token_cache()


def test_workdrive_previewinfo_retries_once_after_provider_401(monkeypatch):
    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.ok = status < 400
            self._payload = payload
        def json(self): return self._payload
    client = WorkDriveClient()
    tokens = iter(["stale-token", "fresh-token"])
    monkeypatch.setattr(client, "access_token", lambda force_refresh=False: next(tokens))
    invalidated = []
    monkeypatch.setattr(client, "invalidate_access_token", lambda token=None: invalidated.append(token))
    responses = iter([
        Response(401, {"errors": [{"id": "R008"}]}),
        Response(200, {"data": {"attributes": {"preview_data_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="}}}),
    ])
    monkeypatch.setattr("app.workdrive.requests.get", lambda *_args, **_kwargs: next(responses))
    result = client.preview_metadata("preview-resource")
    assert result["preview_data_url"].startswith("data:image/png")
    assert invalidated == ["stale-token"]


def test_external_media_validation_duplicates_and_safe_delete(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    payload = {"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/test-two", "position": 0, "is_primary": True}
    assert client.post(f"/api/products/{product_id}/media", headers=headers, json=payload).status_code == 201
    assert client.post(f"/api/products/{product_id}/media", headers=headers, json=payload).status_code == 409
    assert client.post(f"/api/products/{product_id}/media", headers=headers, json={**payload, "permalink": "http://evil.test/file"}).status_code == 400
    media_id = app.extensions["mongo_db"].products.find_one({"_id": ObjectId(product_id)})["images"][0]["id"]
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("WorkDrive media must never be deleted remotely"))
    assert client.delete(f"/api/products/{product_id}/images/{media_id}", headers=headers).status_code == 200


def test_external_media_primary_update_demotes_previous_item(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    first = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/first", "is_primary": True}).json["item"]
    second = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/second", "is_primary": False}).json["item"]
    changed = client.patch(f"/api/products/{product_id}/media/{second['id']}", headers=headers, json={"is_primary": True})
    assert changed.status_code == 200
    images = _stored_media(app, product_id)
    assert next(item for item in images if item["id"] == second["id"])["is_primary"] is True
    assert next(item for item in images if item["id"] == first["id"])["is_primary"] is False


def test_external_media_post_and_patch_require_authentication_and_permission(client, app):
    product_id = _product(app)
    payload = {"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/auth-test"}
    assert client.post(f"/api/products/{product_id}/media", json=payload).status_code == 401
    assert client.patch(f"/api/products/{product_id}/media/missing", json={"description": "Nope"}).status_code == 401
    denied = _headers_without_media_permission(client, app)
    assert client.post(f"/api/products/{product_id}/media", headers=denied, json=payload).status_code == 403
    assert client.patch(f"/api/products/{product_id}/media/missing", headers=denied, json={"description": "Nope"}).status_code == 403


@pytest.mark.parametrize("payload", [
    {"provider": "zoho_workdrive", "type": "image", "permalink": "https://example.com/file/one"},
    {"provider": "unknown", "type": "image", "permalink": "https://workdrive.zoho.in/file/one"},
    {"provider": "zoho_workdrive", "type": "video", "permalink": "https://workdrive.zoho.in/file/one"},
    {"provider": "zoho_workdrive", "type": "image", "permalink": "https://user@workdrive.zoho.in/file/one"},
])
def test_external_media_rejects_unapproved_provider_type_host_and_userinfo(client, app, headers, payload):
    assert client.post(f"/api/products/{_product(app)}/media", headers=headers, json=payload).status_code == 400


def test_workdrive_permalink_is_canonical_and_equivalent_urls_are_duplicates(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    first = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "HTTPS://WORKDRIVE.ZOHO.IN/file/canonical#preview"})
    assert first.status_code == 201
    assert first.json["item"]["permalink"] == "https://workdrive.zoho.in/file/canonical"
    duplicate = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/canonical#another"})
    assert duplicate.status_code == 409
    assert len(_stored_media(app, product_id)) == 1


def test_external_media_patch_rejects_duplicate_but_same_canonical_url_is_idempotent(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    first = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/patch-one"}).json["item"]
    second = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/patch-two"}).json["item"]
    same = client.patch(f"/api/products/{product_id}/media/{first['id']}", headers=headers, json={"permalink": "HTTPS://WORKDRIVE.ZOHO.IN/file/patch-one#preview"})
    assert same.status_code == 200
    duplicate = client.patch(f"/api/products/{product_id}/media/{second['id']}", headers=headers, json={"permalink": "https://workdrive.zoho.in/file/patch-one#other"})
    assert duplicate.status_code == 409
    assert len(_stored_media(app, product_id)) == 2


def test_external_media_conflict_fails_closed_without_lost_update(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    competing = {"id": "other-request", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/race", "url": "https://workdrive.zoho.in/file/race", "position": 0, "is_primary": True, "is_main": True, "source": "rk-stock"}
    def lose_compare_and_swap(product, _images):
        app.extensions["mongo_db"].products.update_one({"_id": product["_id"]}, {"$set": {"images": [competing]}})
        return False
    monkeypatch.setattr("app.routes._replace_product_media", lose_compare_and_swap)
    response = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/race"})
    assert response.status_code == 409
    assert _stored_media(app, product_id) == [competing]


def test_external_media_patch_conflict_preserves_concurrent_update(client, app, headers, monkeypatch):
    product_id = _product(app)
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    created = client.post(f"/api/products/{product_id}/media", headers=headers, json={"provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/patch-race"}).json["item"]
    competing = {**created, "description": "Concurrent winner"}
    def lose_compare_and_swap(product, _images):
        app.extensions["mongo_db"].products.update_one({"_id": product["_id"]}, {"$set": {"images": [competing]}})
        return False
    monkeypatch.setattr("app.routes._replace_product_media", lose_compare_and_swap)
    response = client.patch(f"/api/products/{product_id}/media/{created['id']}", headers=headers, json={"description": "Stale writer"})
    assert response.status_code == 409
    assert _stored_media(app, product_id) == [competing]


def test_media_reorder_conflict_preserves_concurrent_update(client, app, headers, monkeypatch):
    product_id = _product(app)
    original = {"id": "original", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/original", "url": "https://workdrive.zoho.in/file/original", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    competing = {**original, "description": "Concurrent winner"}
    _set_media(app, product_id, [original])
    def lose_compare_and_swap(product, _images):
        app.extensions["mongo_db"].products.update_one({"_id": product["_id"]}, {"$set": {"images": [competing]}})
        return False
    monkeypatch.setattr("app.routes._replace_product_media", lose_compare_and_swap)
    response = client.patch(f"/api/products/{product_id}/images", headers=headers, json={"order": ["original"]})
    assert response.status_code == 409
    assert _stored_media(app, product_id) == [competing]


def test_workdrive_delete_preserves_remote_asset_and_cloudinary_delete_is_unchanged(client, app, headers, monkeypatch):
    product_id = _product(app)
    workdrive = {"id": "workdrive-1", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/delete-test", "url": "https://workdrive.zoho.in/file/delete-test", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [workdrive])
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("WorkDrive media must never enter Cloudinary deletion"))
    removed = client.delete(f"/api/products/{product_id}/images/workdrive-1", headers=headers)
    assert removed.status_code == 200
    assert removed.json["remote_asset_preserved"] is True
    assert _stored_media(app, product_id) == []

    cloudinary = {"id": "cloudinary-1", "url": "https://res.cloudinary.com/test/image/upload/cloudinary-1.jpg", "public_id": "cloudinary-1", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [cloudinary])
    deleted = []
    monkeypatch.setattr("app.routes.delete_image", lambda _app, public_id, *_args: deleted.append(public_id) or {"result": "ok", "already_missing": False})
    removed = client.delete(f"/api/products/{product_id}/images/cloudinary-1", headers=headers)
    assert removed.status_code == 200 and removed.json["cloudinary_deleted"] is True
    assert deleted == ["cloudinary-1"]


def test_workdrive_delete_reorders_remaining_media_without_false_conflict(client, app, headers, monkeypatch):
    product_id = _product(app)
    first = {"id": "workdrive-1", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/one", "url": "https://workdrive.zoho.in/file/one", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    second = {"id": "workdrive-2", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/two", "url": "https://workdrive.zoho.in/file/two", "source": "rk-stock", "position": 1, "is_primary": False, "is_main": False}
    _set_media(app, product_id, [first, second])
    monkeypatch.setattr("app.routes._sync_product_to_storefront", lambda *_args: {"status": "not_connected"})
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("WorkDrive media must never enter Cloudinary deletion"))
    response = client.delete(f"/api/products/{product_id}/images/workdrive-1", headers=headers)
    assert response.status_code == 200
    assert response.json["remote_asset_preserved"] is True
    assert _stored_media(app, product_id) == [{**second, "position": 0, "is_primary": True, "is_main": True}]


def test_workdrive_delete_real_concurrent_change_returns_conflict(client, app, headers, monkeypatch):
    product_id = _product(app)
    media = {"id": "workdrive-1", "provider": "zoho_workdrive", "type": "image", "permalink": "https://workdrive.zoho.in/file/one", "url": "https://workdrive.zoho.in/file/one", "source": "rk-stock", "position": 0, "is_primary": True, "is_main": True}
    _set_media(app, product_id, [media])
    monkeypatch.setattr("app.routes._replace_product_media", lambda *_args: False)
    monkeypatch.setattr("app.routes.delete_image", lambda *_args: pytest.fail("WorkDrive media must never enter Cloudinary deletion"))
    response = client.delete(f"/api/products/{product_id}/images/workdrive-1", headers=headers)
    assert response.status_code == 409
    assert response.json["conflict"] is True
    assert _stored_media(app, product_id) == [media]


def test_storefront_payload_preserves_structured_workdrive_media(app, monkeypatch):
    media = {"url": "https://workdrive.zoho.in/file/catalog", "permalink": "https://workdrive.zoho.in/file/catalog", "provider": "zoho_workdrive", "type": "image", "position": 2, "is_primary": True, "source": "rk-stock", "description": "Editorial image", "alt_text": "Lookbook image"}
    product = {"_id": ObjectId(), "source_id": "rk-web-product", "sku": "CK150", "name": "CK150", "images": [media]}
    captured = {}
    client = StorefrontIntegrationClient()
    monkeypatch.setattr(client, "_request", lambda method, path, secret, payload=None: captured.update({"method": method, "path": path, "payload": payload}) or {"status": "synced"})
    with app.app_context():
        client.sync_product(product)
    assert captured["payload"]["media"] == [media]
