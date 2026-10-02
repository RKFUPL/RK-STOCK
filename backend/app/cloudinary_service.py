import hashlib
import re
import time
from urllib.parse import quote, urlsplit

import requests


class CloudinaryConfigurationError(RuntimeError):
    pass


class CloudinaryUploadError(RuntimeError):
    pass


def _config(app):
    values = {name: app.config.get(name, "") for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")}
    if not all(values.values()):
        raise CloudinaryConfigurationError("Cloudinary upload is not configured")
    return values


def _public_id_from_url(url):
    path = urlsplit(str(url or "")).path
    if "/upload/" not in path:
        return ""
    tail = path.split("/upload/", 1)[1]
    parts = [part for part in tail.split("/") if part]
    if parts and re.fullmatch(r"v\d+", parts[0]):
        parts.pop(0)
    if not parts:
        return ""
    parts[-1] = parts[-1].rsplit(".", 1)[0]
    return "/".join(parts)


def product_asset_folder(app, product):
    values = _config(app)
    for media in product.get("images") or []:
        if isinstance(media, dict) and media.get("asset_folder"):
            return str(media["asset_folder"])
        url = media if isinstance(media, str) else media.get("secure_url") or media.get("url") if isinstance(media, dict) else ""
        public_id = _public_id_from_url(url)
        if not public_id:
            continue
        endpoint = f"https://api.cloudinary.com/v1_1/{values['CLOUDINARY_CLOUD_NAME']}/resources/image/upload/{quote(public_id, safe='')}"
        try:
            response = requests.get(endpoint, auth=(values["CLOUDINARY_API_KEY"], values["CLOUDINARY_API_SECRET"]), timeout=20)
            payload = response.json() if response.ok else {}
        except (requests.RequestException, ValueError, TypeError):
            continue
        if payload.get("asset_folder"):
            return str(payload["asset_folder"])
    label = str(product.get("name") or product.get("product_code") or product.get("sku") or "Product").strip()
    label = re.sub(r"\s*-\s*", "-", label)
    label = re.sub(r"[^A-Za-z0-9 _-]+", "-", label).strip(" -") or "Product"
    return f"Products/{label}"


def upload_image(app, stream, filename, content_type, asset_folder):
    values = _config(app)
    timestamp = int(time.time())
    params = {"asset_folder": asset_folder, "timestamp": timestamp}
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    signature = hashlib.sha1((canonical + values["CLOUDINARY_API_SECRET"]).encode()).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{values['CLOUDINARY_CLOUD_NAME']}/image/upload"
    endpoint = urlsplit(url)
    started = time.perf_counter()
    app.logger.info("Cloudinary upload target host=%s path=%s cloud_name_configured=%s cloud_name_length=%d signed_parameter_names=%s timestamp_present=%s", endpoint.hostname, endpoint.path, bool(values["CLOUDINARY_CLOUD_NAME"]), len(values["CLOUDINARY_CLOUD_NAME"]), sorted(params), "timestamp" in params)
    try:
        response = requests.post(url, data={**params, "api_key": values["CLOUDINARY_API_KEY"], "signature": signature}, files={"file": (filename, stream, content_type)}, timeout=60)
    except requests.RequestException as exc:
        app.logger.warning("Cloudinary upload transport failure status=unavailable host=%s path=%s exception=%s elapsed_ms=%d", endpoint.hostname, endpoint.path, type(exc).__name__, round((time.perf_counter() - started) * 1000))
        raise CloudinaryUploadError("Cloudinary upload failed") from exc
    if not response.ok:
        try:
            provider = response.json().get("error", {})
            provider_code = str(provider.get("code", ""))[:80]
            provider_message = str(provider.get("message", ""))[:240]
        except (ValueError, AttributeError, TypeError):
            provider_code, provider_message = "", response.text[:240] if getattr(response, "text", "") else ""
        for secret in (values["CLOUDINARY_CLOUD_NAME"], values["CLOUDINARY_API_KEY"], values["CLOUDINARY_API_SECRET"]):
            if secret:
                provider_message = provider_message.replace(secret, "[redacted]")
        status_code = getattr(response, "status_code", "unknown")
        app.logger.warning("Cloudinary upload rejected status=%s code=%s message=%s host=%s path=%s exception=%s elapsed_ms=%d", status_code, provider_code or "unknown", provider_message or "non-json response", endpoint.hostname, endpoint.path, "CloudinaryUploadError", round((time.perf_counter() - started) * 1000))
        raise CloudinaryUploadError(f"Cloudinary rejected the image upload: {provider_message or 'provider returned a non-JSON error'}")
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        app.logger.warning("Cloudinary upload invalid response status=%s host=%s path=%s exception=%s elapsed_ms=%d", getattr(response, "status_code", "unknown"), endpoint.hostname, endpoint.path, type(exc).__name__, round((time.perf_counter() - started) * 1000))
        raise CloudinaryUploadError("Cloudinary returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise CloudinaryUploadError("Cloudinary returned an invalid response")
    if not payload.get("secure_url"):
        raise CloudinaryUploadError("Cloudinary returned no image URL")
    return {"secure_url": payload["secure_url"], "public_id": payload.get("public_id")}


def delete_image(app, public_id, resource_type="image", delivery_type="upload"):
    values = _config(app)
    timestamp = int(time.time())
    params = {"public_id": public_id, "timestamp": timestamp, "type": delivery_type}
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    signature = hashlib.sha1((canonical + values["CLOUDINARY_API_SECRET"]).encode()).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{values['CLOUDINARY_CLOUD_NAME']}/{resource_type}/destroy"
    endpoint = urlsplit(url)
    started = time.perf_counter()
    try:
        response = requests.post(url, data={**params, "api_key": values["CLOUDINARY_API_KEY"], "signature": signature}, timeout=30)
    except requests.RequestException as exc:
        app.logger.warning("Cloudinary delete transport failure status=unavailable host=%s path=%s exception=%s elapsed_ms=%d", endpoint.hostname, endpoint.path, type(exc).__name__, round((time.perf_counter() - started) * 1000))
        raise CloudinaryUploadError("Cloudinary image deletion failed") from exc
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise CloudinaryUploadError("Cloudinary returned an invalid deletion response") from exc
    result = str(payload.get("result", "")).lower() if isinstance(payload, dict) else ""
    if response.ok and result in {"ok", "not found"}:
        app.logger.info("Cloudinary delete completed status=%s result=%s host=%s path=%s elapsed_ms=%d", response.status_code, result, endpoint.hostname, endpoint.path, round((time.perf_counter() - started) * 1000))
        return {"result": result, "already_missing": result == "not found"}
    app.logger.warning("Cloudinary delete rejected status=%s result=%s host=%s path=%s exception=%s elapsed_ms=%d", getattr(response, "status_code", "unknown"), result or "unknown", endpoint.hostname, endpoint.path, "CloudinaryUploadError", round((time.perf_counter() - started) * 1000))
    raise CloudinaryUploadError("Cloudinary rejected the image deletion")
