from __future__ import annotations

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.models.plaid import Transaction, PlaidItem
from backend.app.core.security import hash_password

# Desired mapping of id -> (email, full_name)
TARGET_USERS = {
    1: ("apoorv@example.com", "Apoorv"),
    2: ("aarya@example.com", "Aarya"),
    3: ("kartavya@example.com", "Kartavya"),
    4: ("modak@example.com", "Modak"),
    5: ("nikhil@example.com", "Nikhil"),
}


def main() -> None:
    with SessionLocal() as db:
        # 1) Delete existing data for users with ids 1..5 or matching emails
        target_ids = list(TARGET_USERS.keys())
        target_emails = [email for _, (email, _) in TARGET_USERS.items()]

        # Find actual user ids to delete (by id or email)
        users_to_delete = db.query(User).filter(
            (User.id.in_(target_ids)) | (User.email.in_(target_emails))
        ).all()
        ids_to_delete = [u.id for u in users_to_delete]

        if ids_to_delete:
            # Delete dependent rows first
            db.query(Transaction).filter(Transaction.user_id.in_(ids_to_delete)).delete(synchronize_session=False)
            db.query(PlaidItem).filter(PlaidItem.user_id.in_(ids_to_delete)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(ids_to_delete)).delete(synchronize_session=False)
            db.commit()

        # 2) Create fresh users with fixed IDs
        for uid, (email, name) in TARGET_USERS.items():
            # Ensure no conflicting row
            db.query(User).filter((User.id == uid) | (User.email == email)).delete(synchronize_session=False)
            user = User(id=uid, email=email, full_name=name, hashed_password=hash_password("password123"))
            db.add(user)
        db.commit()

        # 3) Verify
        created = db.query(User).filter(User.id.in_(target_ids)).order_by(User.id).all()
        print({u.id: (u.email, u.full_name) for u in created})


if __name__ == "__main__":
    main()
