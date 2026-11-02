"""Demo seed data (fictional; local development only)."""
from datetime import date, timedelta

from . import ROOT, ledger
from .core import connect, migrate, seed_users

USERS = [("admin@demo.test", "Ada Owner", "admin"), ("accountant@demo.test", "Amara Accountant", "accountant"),
         ("clerk@demo.test", "Chen Clerk", "clerk"), ("viewer@demo.test", "Vik Viewer", "viewer")]
ACCOUNTS = [("1000", "Cash", "asset"), ("1100", "Accounts Receivable", "asset"), ("1500", "Equipment", "asset"), ("2000", "Accounts Payable", "liability"),
            ("3000", "Owner's Equity", "equity"), ("4000", "Sales Revenue", "revenue"), ("5000", "Cost of Goods Sold", "expense"),
            ("5100", "Rent Expense", "expense"), ("5200", "Utilities Expense", "expense")]
CUSTOMERS = [("Acme Hardware Ltd", "billing@acme.example"), ("Bluebird Cafe", "accounts@bluebird.example"), ("Cedar Logistics", None), ("Delta Design Studio", "pay@delta.example")]


def seed(db_path):
    migrate(db_path, ROOT / "migrations")
    c = connect(db_path)
    c.execute("BEGIN")
    if not seed_users(c, USERS):
        c.execute("ROLLBACK")
        return False
    uid = c.execute("SELECT id FROM users WHERE email='accountant@demo.test'").fetchone()[0]
    for a in ACCOUNTS:
        c.execute("INSERT INTO accounts(code,name,type) VALUES(?,?,?)", a)
    for cu in CUSTOMERS:
        c.execute("INSERT INTO customers(name,email) VALUES(?,?)", cu)
    A = {r["code"]: r["id"] for r in c.execute("SELECT id,code FROM accounts")}
    today = date.today()
    day = lambda n: (today - timedelta(days=n)).isoformat()
    ledger.post_entry(c, day(90), "Owner capital contribution", "manual", [(A["1000"], 5000000, 0), (A["3000"], 0, 5000000)], uid)
    ledger.post_entry(c, day(80), "Office rent", "manual", [(A["5100"], 150000, 0), (A["1000"], 0, 150000)], uid)
    ledger.post_entry(c, day(40), "Utilities", "manual", [(A["5200"], 42000, 0), (A["1000"], 0, 42000)], uid)
    plan = [(1, 60, 30, [("Consulting workshop", 2, 120000)], [(30, "bank_transfer", 240000)]),
            (2, 45, 15, [("Catering software setup", 1, 90000), ("Monthly support", 3, 15000)], [(10, "card", 60000)]),
            (3, 30, 10, [("Route optimisation audit", 1, 300000)], []),
            (4, 20, -10, [("Brand identity package", 1, 180000)], []),
            (1, 12, -5, [("Follow-up training", 4, 25000)], [(2, "cheque", 40000)])]
    for cust, issued, due_in, items, pays in plan:
        iid = ledger.create_invoice(c, cust, day(issued), (today + timedelta(days=due_in)).isoformat(),
                                    [{"description": d, "quantity": q, "unit_price_cents": p} for d, q, p in items], uid)
        for ago, method, amt in pays:
            ledger.record_payment(c, iid, amt, day(ago), method, uid)
    spare = ledger.create_invoice(c, 2, day(5), day(-25), [{"description": "Duplicate billing (demo void)", "quantity": 1, "unit_price_cents": 5000}], uid)
    ledger.void_invoice(c, spare, uid)
    c.execute("COMMIT")
    c.close()
    return True
