import sqlite3
import threading
from datetime import date, timedelta

from tests.base import ADMIN, Base

ACCT, CLERK, VIEWER = "accountant@demo.test", "clerk@demo.test", "viewer@demo.test"
TODAY = date.today().isoformat()


class LedgerBase(Base):
    def acc(self, code):
        return self.data(self.get(f"/api/accounts?q={code}", ACCT), 200)[0]["id"]

    def tb(self):
        rows = self.data(self.get("/api/trial-balance", ACCT), 200)
        return rows[:-1], rows[-1]

    def balance(self, code):
        return next(r["balance_cents"] for r in self.tb()[0] if r["code"] == code)

    def invoice(self, qty=2, price=5000, cust=1, user=CLERK):
        return self.data(self.post("/api/invoices", user, json={"customer_id": cust, "issue_date": TODAY, "due_date": TODAY,
                                                                 "items": [{"description": "Widget", "quantity": qty, "unit_price_cents": price}]}), 201)

    def pay(self, iid, amount, user=CLERK):
        return self.post(f"/api/invoices/{iid}/payments", user, json={"amount_cents": amount, "paid_on": TODAY, "method": "cash"})


class AccountTests(LedgerBase):
    def test_crud_rbac_validation(self):
        body = {"code": "6100", "name": "Marketing", "type": "expense"}
        self.assertEqual(self.post("/api/accounts", CLERK, json=body).status_code, 403)
        a = self.data(self.post("/api/accounts", ACCT, json=body), 201)
        self.assertEqual(a["active"], 1)
        self.assertEqual(self.post("/api/accounts", ACCT, json=body).status_code, 409)
        for bad in ({**body, "code": "12"}, {**body, "code": "abcd"}, {**body, "type": "bogus"}):
            self.assertEqual(self.post("/api/accounts", ACCT, json={**bad, "code": bad["code"] if bad["code"] != "6100" else "6101"}).status_code, 422)
        self.assertEqual(self.delete(f"/api/accounts/{a['id']}", ACCT).status_code, 403)
        self.assertEqual(self.delete(f"/api/accounts/{a['id']}", ADMIN).status_code, 200)

    def test_system_and_posted_accounts_protected(self):
        cash = self.acc("1000")
        self.assertEqual(self.put(f"/api/accounts/{cash}", ACCT, json={"active": False}).status_code, 409)
        self.assertEqual(self.put(f"/api/accounts/{cash}", ACCT, json={"code": "9999"}).status_code, 409)
        rent = self.acc("5100")
        self.assertEqual(self.put(f"/api/accounts/{rent}", ACCT, json={"type": "asset"}).status_code, 409)
        self.assertEqual(self.delete(f"/api/accounts/{rent}", ADMIN).status_code, 409)


class JournalTests(LedgerBase):
    def entry(self, lines, user=ACCT):
        return self.post("/api/journal", user, json={"entry_date": TODAY, "memo": "Test entry", "lines": lines})

    def test_balanced_entry_posts_and_trial_balance_stays_balanced(self):
        rent, cash = self.acc("5100"), self.acc("1000")
        before = self.balance("5100")
        eid = self.data(self.entry([{"account_id": rent, "debit_cents": 12345}, {"account_id": cash, "credit_cents": 12345}]), 201)["id"]
        self.assertEqual(self.balance("5100"), before + 12345)
        rows, total = self.tb()
        self.assertEqual(total["debit_cents"], total["credit_cents"])
        detail = self.data(self.get(f"/api/journal/{eid}", VIEWER), 200)
        self.assertEqual(len(detail["lines"]), 2)

    def test_invalid_entries_rejected_and_nothing_posted(self):
        rent, cash = self.acc("5100"), self.acc("1000")
        count = self.get("/api/journal", ACCT).get_json()["meta"]["total"]
        bad = [[{"account_id": rent, "debit_cents": 100}, {"account_id": cash, "credit_cents": 99}],
               [{"account_id": rent, "debit_cents": 100}],
               [{"account_id": rent, "debit_cents": 100, "credit_cents": 100}, {"account_id": cash, "credit_cents": 0, "debit_cents": 0}],
               [{"account_id": 9999, "debit_cents": 5}, {"account_id": cash, "credit_cents": 5}],
               [{"account_id": rent, "debit_cents": -5}, {"account_id": cash, "credit_cents": -5}],
               "not-a-list"]
        for lines in bad:
            self.assertEqual(self.entry(lines).status_code, 422, lines)
        self.assertEqual(self.get("/api/journal", ACCT).get_json()["meta"]["total"], count)

    def test_rbac(self):
        rent, cash = self.acc("5100"), self.acc("1000")
        lines = [{"account_id": rent, "debit_cents": 1}, {"account_id": cash, "credit_cents": 1}]
        self.assertEqual(self.entry(lines, CLERK).status_code, 403)
        self.assertEqual(self.entry(lines, VIEWER).status_code, 403)
        self.assertEqual(self.get("/api/journal", VIEWER).status_code, 200)

    def test_database_enforces_immutability(self):
        con = sqlite3.connect(self.app.config["DATABASE_PATH"])
        for sql in ("UPDATE journal_lines SET debit_cents=1 WHERE id=1", "DELETE FROM journal_lines WHERE id=1",
                    "UPDATE journal_entries SET memo='x' WHERE id=1", "DELETE FROM journal_entries WHERE id=1"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                con.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):  # a line must be either debit or credit
            con.execute("INSERT INTO journal_lines(entry_id,account_id,debit_cents,credit_cents) VALUES(1,1,5,5)")

    def test_reversal_nets_to_zero_and_only_once(self):
        rent, cash = self.acc("5100"), self.acc("1000")
        before = self.balance("5100")
        eid = self.data(self.entry([{"account_id": rent, "debit_cents": 777}, {"account_id": cash, "credit_cents": 777}]), 201)["id"]
        rid = self.data(self.post(f"/api/journal/{eid}/reverse", ACCT), 201)["id"]
        self.assertEqual(self.balance("5100"), before)
        self.assertEqual(self.post(f"/api/journal/{eid}/reverse", ACCT).status_code, 409)
        self.assertEqual(self.post(f"/api/journal/{rid}/reverse", ACCT).status_code, 409)
        self.assertEqual(self.post("/api/journal/9999/reverse", ACCT).status_code, 404)


class InvoiceTests(LedgerBase):
    def test_invoice_posts_to_ledger(self):
        ar, rev = self.balance("1100"), self.balance("4000")
        inv = self.invoice(qty=3, price=10000)
        self.assertEqual((inv["total_cents"], inv["status"], inv["balance_cents"]), (30000, "open", 30000))
        self.assertEqual((self.balance("1100"), self.balance("4000")), (ar + 30000, rev + 30000))
        nxt = self.invoice()
        self.assertEqual(int(nxt["number"][4:]), int(inv["number"][4:]) + 1)
        d = self.data(self.get(f"/api/invoices/{inv['id']}", VIEWER), 200)
        self.assertEqual(d["items"][0]["quantity"], 3)

    def test_invoice_validation_and_rbac(self):
        base = {"customer_id": 1, "issue_date": TODAY, "due_date": TODAY, "items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}]}
        bad = [{**base, "items": []}, {**base, "items": [{"description": "x", "quantity": 0, "unit_price_cents": 5}]},
               {**base, "items": [{"description": "x", "quantity": 1, "unit_price_cents": 0}]}, {**base, "customer_id": 999},
               {**base, "due_date": (date.today() - timedelta(days=1)).isoformat()}, {**base, "issue_date": "31-12-2026"}]
        for b in bad:
            self.assertEqual(self.post("/api/invoices", CLERK, json=b).status_code, 422, b)
        self.assertEqual(self.post("/api/invoices", VIEWER, json=base).status_code, 403)
        self.assertEqual(self.post("/api/invoices", json=base).status_code, 401)

    def test_payments_partial_full_overpay(self):
        inv = self.invoice(qty=1, price=10000)
        cash = self.balance("1000")
        self.assertEqual(self.data(self.pay(inv["id"], 4000), 201)["status"], "partial")
        self.assertEqual(self.pay(inv["id"], 6001).status_code, 422)
        paid = self.data(self.pay(inv["id"], 6000), 201)
        self.assertEqual((paid["status"], paid["balance_cents"]), ("paid", 0))
        self.assertEqual(self.balance("1000"), cash + 10000)
        self.assertEqual(self.pay(inv["id"], 1).status_code, 422)
        self.assertEqual(self.post(f"/api/invoices/{inv['id']}/payments", CLERK, json={"amount_cents": 1, "paid_on": TODAY, "method": "bitcoin"}).status_code, 422)
        self.assertEqual(self.pay(inv["id"], 1, VIEWER).status_code, 403)

    def test_void_rules(self):
        ar = self.balance("1100")
        inv = self.invoice()
        self.assertEqual(self.post(f"/api/invoices/{inv['id']}/void", CLERK).status_code, 403)
        self.assertEqual(self.data(self.post(f"/api/invoices/{inv['id']}/void", ACCT), 200)["status"], "void")
        self.assertEqual(self.balance("1100"), ar)
        self.assertEqual(self.post(f"/api/invoices/{inv['id']}/void", ACCT).status_code, 409)
        self.assertEqual(self.pay(inv["id"], 100).status_code, 409)
        paid = self.invoice()
        self.pay(paid["id"], 100)
        self.assertEqual(self.post(f"/api/invoices/{paid['id']}/void", ACCT).status_code, 409)

    def test_customer_with_invoices_cannot_be_deleted(self):
        self.assertEqual(self.delete("/api/customers/1", ADMIN).status_code, 409)
        new = self.data(self.post("/api/customers", CLERK, json={"name": "Temp Co"}), 201)
        self.assertEqual(self.delete(f"/api/customers/{new['id']}", ADMIN).status_code, 200)
        self.assertEqual(self.post("/api/customers", CLERK, json={"name": "X", "email": "bad"}).status_code, 422)

    def test_concurrent_payments_cannot_overpay(self):
        inv = self.invoice(qty=1, price=10000)
        codes, tokens = [], self.tok(CLERK)

        def attempt():
            c = self.app.test_client()
            r = c.post(f"/api/invoices/{inv['id']}/payments", headers={"Authorization": "Bearer " + tokens},
                       json={"amount_cents": 10000, "paid_on": TODAY, "method": "card"})
            codes.append(r.status_code)
        ts = [threading.Thread(target=attempt) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(codes), [201, 422, 422, 422])
        self.assertEqual(self.data(self.get(f"/api/invoices/{inv['id']}", ACCT), 200)["paid_cents"], 10000)


class InvariantTests(LedgerBase):
    def test_books_balance_and_ar_matches_open_invoices(self):
        rows, total = self.tb()
        self.assertEqual(total["debit_cents"], total["credit_cents"])
        invs = self.data(self.get("/api/invoices?per_page=100", ACCT), 200)
        a = self.invoice(qty=2, price=2500)
        b = self.invoice(qty=1, price=9900)
        self.pay(a["id"], 1500)
        self.pay(b["id"], 9900)
        self.post(f"/api/invoices/{self.invoice()['id']}/void", ACCT)
        rows, total = self.tb()
        self.assertEqual(total["debit_cents"], total["credit_cents"])
        outstanding = sum(i["balance_cents"] for i in self.data(self.get("/api/invoices?per_page=100", ACCT), 200) if i["status"] != "void")
        self.assertEqual(self.balance("1100"), outstanding)
        self.assertGreaterEqual(len(invs), 5)

    def test_income_statement_and_stats(self):
        rows = self.data(self.get("/api/income-statement", ACCT), 200)
        rev = sum(r["balance_cents"] for r in rows if r["type"] == "revenue")
        exp = sum(r["balance_cents"] for r in rows if r["type"] == "expense")
        self.assertEqual(rows[-1]["balance_cents"], rev - exp)
        cards = {c["label"]: c["value"] for c in self.data(self.get("/api/stats", VIEWER), 200)["cards"]}
        self.assertEqual(cards["Revenue to date"], self.balance("4000"))
        self.assertEqual(cards["Receivables outstanding"], self.balance("1100"))
        self.assertGreaterEqual(cards["Overdue invoices"], 1)
        self.assertEqual(self.get("/api/trial-balance?from=bad", ACCT).status_code, 422)
