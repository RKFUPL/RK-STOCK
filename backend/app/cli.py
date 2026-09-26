import getpass
import os
import click

from . import create_app
from .auth import hash_password
from .db import db
from .utils import now


@click.group()
def cli():
    pass


@cli.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--name", prompt=True)
def create_admin(email, name):
    app = create_app()
    with app.app_context():
        password = os.getenv("RK_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        if len(password) < 12:
            raise click.ClickException("Password must be at least 12 characters")
        normalized_email = email.strip().lower()
        changes = {"name": name.strip(), "password_hash": hash_password(password), "role": "admin", "active": True, "updated_at": now()}
        matching = list(db().users.find({"email": {"$regex": f"^{normalized_email}\\s*$", "$options": "i"}}, {"_id": 1}))
        if matching:
            db().users.update_many({"_id": {"$in": [item["_id"] for item in matching]}}, {"$set": changes})
            db().users.update_one({"_id": matching[0]["_id"]}, {"$set": {"email": normalized_email}})
            if len(matching) > 1:
                db().users.delete_many({"_id": {"$in": [item["_id"] for item in matching[1:]]}})
        else:
            db().users.insert_one({"email": normalized_email, **changes, "created_at": now()})
        click.echo("Administrator created or updated.")


if __name__ == "__main__":
    cli()
