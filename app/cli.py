"""Owner account management.   python -m app.cli create-owner --username owner"""
import argparse
import getpass

from sqlalchemy import select

from . import models as m
from . import security as sec
from .database import SessionLocal


def create_owner(username: str, password: str):
    sec.check_password_strength(password)
    with SessionLocal() as db:
        owner = db.scalar(select(m.OwnerAccount).where(m.OwnerAccount.username == username))
        if owner is None:
            owner = m.OwnerAccount(username=username, password_hash=sec.hash_password(password))
            db.add(owner)
            print(f"Owner '{username}' created.")
        else:
            owner.password_hash = sec.hash_password(password)
            owner.token_version += 1
            sec.revoke_all_refresh_tokens(db, owner.id)
            print(f"Password for '{username}' reset. All sessions logged out.")
        db.commit()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-owner", help="create the owner login or reset its password")
    c.add_argument("--username", required=True)
    args = ap.parse_args()
    pw = getpass.getpass("Password (min 10 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    create_owner(args.username, pw)


if __name__ == "__main__":
    main()
