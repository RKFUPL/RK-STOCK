"""Dedicated RK-STOCK catalog outbox worker."""
import logging
import os
import signal
import time
from uuid import uuid4

from app import create_app
from app.catalog_outbox import deliver_due_with_leases
from app.storefront_integration import StorefrontIntegrationClient


logger = logging.getLogger("rk-stock.catalog-worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
stopping = False


def _required_database_name(environment=None):
    values = os.environ if environment is None else environment
    database_name = str(values.get("MONGO_DB") or "").strip()
    if not database_name:
        raise RuntimeError("MONGO_DB must be explicitly configured for the catalog worker")
    return database_name


def _stop(_signum, _frame):
    global stopping
    stopping = True


def main():
    global stopping
    _required_database_name()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    app = create_app()
    worker_id = f"catalog-worker-{uuid4()}"
    interval = max(1.0, float(os.getenv("CATALOG_WORKER_INTERVAL_SECONDS", "2")))
    with app.app_context():
        client = StorefrontIntegrationClient()
        logger.info("catalog outbox worker started")
        while not stopping:
            result = deliver_due_with_leases(client, limit=20, worker_id=worker_id)
            if result["attempted"]:
                logger.info("catalog outbox batch attempted=%s completed=%s failed=%s", result["attempted"], result["completed"], result["failed"])
            if not result["attempted"] and not stopping:
                time.sleep(interval)
        logger.info("catalog outbox worker stopped")


if __name__ == "__main__":
    main()
