import mongomock
import pytest

from app import create_app
from app.auth import hash_password
from app.utils import now


@pytest.fixture()
def app():
    application = create_app({
        "TESTING": True,
        "MONGO_CLIENT": mongomock.MongoClient(),
        "MONGO_DB": "rk_test",
        "JWT_SECRET": "test-secret-that-is-long-enough-for-tests",
        "UPLOAD_DIR": "tests/uploads",
    })
    database = application.extensions["mongo_db"]
    database.users.insert_one({"name": "Admin", "email": "admin@rk.test", "password_hash": hash_password("strong-test-password"), "role": "admin", "active": True, "created_at": now()})
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def headers(client):
    response = client.post("/api/auth/login", json={"email": "admin@rk.test", "password": "strong-test-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json['token']}"}
