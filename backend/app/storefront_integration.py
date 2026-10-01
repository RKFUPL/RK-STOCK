import requests
from flask import current_app

from .db import db
from .utils import now


class StorefrontIntegrationError(RuntimeError):
    def __init__(self, message, kind="connection_failed"):
        super().__init__(message)
        self.kind = kind


class StorefrontIntegrationClient:
    record_id = "rk_storefront_integration"

    @property
    def base_url(self):
        return str(current_app.config.get("RK_STOREFRONT_URL") or "").strip().rstrip("/")

    @property
    def client_id(self):
        return str(current_app.config.get("RK_STOREFRONT_CLIENT_ID") or "rk-stock-linesheets").strip()

    @property
    def bootstrap_secret(self):
        return str(current_app.config.get("RK_STOREFRONT_BOOTSTRAP_SECRET") or "")

    @property
    def record(self):
        return db().settings.find_one({"_id": self.record_id}) or {}

    @property
    def missing_configuration(self):
        values = {
            "RK_STOREFRONT_URL": self.base_url,
            "RK_STOREFRONT_BOOTSTRAP_SECRET": self.bootstrap_secret,
        }
        return [key for key, value in values.items() if not value]

    @property
    def configured(self):
        return not self.missing_configuration

    def _request(self, method, path, token, payload=None):
        try:
            response = requests.request(method, f"{self.base_url}{path}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, json=payload, timeout=10)
        except requests.RequestException as exc:
            raise StorefrontIntegrationError("Unable to reach RK-WEB", "unreachable") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code in {401, 403}:
            raise StorefrontIntegrationError("RK-WEB rejected the service credential", "credential_rejected")
        if not response.ok:
            raise StorefrontIntegrationError(str(data.get("error") or f"RK-WEB connection failed ({response.status_code})"))
        return data

    def connect(self, actor_id):
        if not self.configured:
            error = StorefrontIntegrationError("Storefront integration configuration is incomplete", "configuration_error")
            error.missing = self.missing_configuration
            raise error
        issued = self._request("POST", "/api/integrations/stock/connect", self.bootstrap_secret, {"client_id": self.client_id})
        try:
            verified = self._request("GET", "/api/integrations/stock/status", self.bootstrap_secret)
            if verified.get("status") != "connected" or verified.get("client_id") != self.client_id:
                raise StorefrontIntegrationError("RK-WEB did not confirm the service connection")
        except StorefrontIntegrationError:
            try:
                self._request("POST", "/api/integrations/stock/disconnect", self.bootstrap_secret)
            except StorefrontIntegrationError:
                pass
            raise
        timestamp = now()
        db().settings.update_one({"_id": self.record_id}, {"$set": {"storefront_url": self.base_url, "client_id": self.client_id, "connection_id": issued.get("connection_id"), "status": "connected", "connected_at": timestamp, "verified_at": timestamp, "updated_at": timestamp, "updated_by": actor_id}, "$unset": {"service_token_encrypted": "", "last_error": "", "error_kind": "", "disconnected_at": ""}}, upsert=True)
        return self.status_payload()

    def check(self):
        if self.record.get("status") not in {"connected", "error"} or not self.configured:
            return self.status_payload()
        try:
            self._request("GET", "/api/integrations/stock/status", self.bootstrap_secret)
            timestamp = now()
            db().settings.update_one({"_id": self.record_id}, {"$set": {"status": "connected", "verified_at": timestamp, "updated_at": timestamp}, "$unset": {"last_error": "", "error_kind": ""}})
            return self.status_payload()
        except StorefrontIntegrationError as exc:
            db().settings.update_one({"_id": self.record_id}, {"$set": {"status": "error", "last_error": str(exc), "error_kind": exc.kind, "failed_at": now()}})
            return self.status_payload()

    def disconnect(self, actor_id):
        if self.record.get("status") in {"connected", "error"}:
            self._request("POST", "/api/integrations/stock/disconnect", self.bootstrap_secret)
        timestamp = now()
        db().settings.update_one({"_id": self.record_id}, {"$set": {"status": "disconnected", "disconnected_at": timestamp, "updated_at": timestamp, "updated_by": actor_id}, "$unset": {"service_token_encrypted": "", "verified_at": "", "last_error": "", "error_kind": ""}}, upsert=True)
        return self.status_payload()

    def catalog_snapshot(self):
        if not self.configured:
            error = StorefrontIntegrationError("Storefront integration configuration is incomplete", "configuration_error")
            error.missing = self.missing_configuration
            raise error
        return {
            "products": self._request("GET", "/api/integrations/stock/catalog/products", self.bootstrap_secret),
            "categories": self._request("GET", "/api/integrations/stock/catalog/categories", self.bootstrap_secret),
            "collections": self._request("GET", "/api/integrations/stock/catalog/collections", self.bootstrap_secret),
        }

    def status_payload(self):
        record = self.record
        return {"status": record.get("status") or "not_connected", "configured": self.configured, "storefront_url": self.base_url or record.get("storefront_url"), "connected_at": record.get("connected_at"), "last_successful_check": record.get("verified_at"), "last_error": record.get("last_error"), "error_kind": record.get("error_kind"), "missing": self.missing_configuration, "catalog_sync": {"status": record.get("catalog_sync_status") or "not_synchronized", "last_successful_sync": record.get("catalog_last_successful_sync"), "last_result": record.get("catalog_last_result")}, "mapping": {"implemented": True, "mapped": None, "unmapped": None}}
