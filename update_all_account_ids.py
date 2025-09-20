from backend.app.db.session import SessionLocal
from backend.app.models.plaid import Transaction

def main():
    with SessionLocal() as db:
        updated = db.query(Transaction).update({Transaction.account_id: "Capital One"}, synchronize_session=False)
        db.commit()
        print(f"Updated {updated} transactions to account_id='Capital One'")

if __name__ == "__main__":
    main()
