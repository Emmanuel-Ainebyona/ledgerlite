"""LedgerLite: double-entry accounting and invoicing API."""
from datetime import date
from pathlib import Path

from flask import g, jsonify, request

from . import ledger
from .core import Resource, audit, db, err, make_app, page_meta, require, tx, validate

ROOT = Path(__file__).resolve().parent.parent
ROLES = ("admin", "accountant", "clerk", "viewer")
DEFAULT_ROLE = "viewer"
ACCT = ("admin", "accountant")
BILLING = ("admin", "accountant", "clerk")
SYSTEM_CODES = (ledger.CASH, ledger.AR, ledger.REVENUE)
TYPES = ["asset", "liability", "equity", "revenue", "expense"]


def parse_lines(raw):
    if not isinstance(raw, list) or not 2 <= len(raw) <= 50:
        err(422, "validation_error", "Validation failed", {"lines": "Provide between 2 and 50 lines"})
    out = []
    for i, l in enumerate(raw, 1):
        ln = validate({"account_id": {"type": "int", "required": True},
                       "debit_cents": {"type": "int", "min": 0, "max": ledger.MAX_CENTS},
                       "credit_cents": {"type": "int", "min": 0, "max": ledger.MAX_CENTS}}, l)
        dr, cr = ln.get("debit_cents") or 0, ln.get("credit_cents") or 0
        if (dr > 0) == (cr > 0):
            err(422, "validation_error", "Validation failed", {"lines": f"Line {i}: enter either a debit or a credit amount"})
        if not db().execute("SELECT 1 FROM accounts WHERE id=? AND active=1", (ln["account_id"],)).fetchone():
            err(422, "validation_error", "Validation failed", {"lines": f"Line {i}: account does not exist or is inactive"})
        out.append((ln["account_id"], dr, cr))
    if sum(l[1] for l in out) != sum(l[2] for l in out):
        err(422, "validation_error", "Validation failed", {"lines": "Total debits must equal total credits"})
    return out


def create_app(config=None):
    app = make_app(ROOT, roles=ROLES, default_role=DEFAULT_ROLE, audit_roles=("admin", "accountant"), config=config)

    def acct_update(clean, existing):
        if existing["code"] in SYSTEM_CODES and (clean.get("active") == 0 or clean.get("code", existing["code"]) != existing["code"] or clean.get("type", existing["type"]) != existing["type"]):
            err(409, "conflict", "System accounts cannot be deactivated, renumbered or retyped")
        if clean.get("type", existing["type"]) != existing["type"] and db().execute("SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1", (existing["id"],)).fetchone():
            err(409, "conflict", "Cannot change the type of an account that has postings")

    Resource("accounts", "accounts", {"code": {"required": True, "max": 6, "pattern": r"\d{3,6}", "pattern_msg": "3 to 6 digits"}, "name": {"required": True, "max": 120},
             "type": {"type": "enum", "choices": TYPES, "required": True}, "active": {"type": "bool"}},
             write=ACCT, delete=("admin",), search=("t.code", "t.name"), filters=("type",), default_sort="t.code ASC", hook_update=acct_update,
             hook_create=lambda c: c.update(active=1 if c.get("active") is None else c["active"]),
             sortable={"code": "t.code", "name": "t.name"}, select="t.*, t.code || ' - ' || t.name AS label").register(app)
    Resource("customers", "customers", {"name": {"required": True, "max": 120}, "email": {"max": 254, "pattern": r"[^@\s]+@[^@\s]+\.[^@\s]+", "pattern_msg": "Invalid email address"}},
             write=BILLING, delete=("admin",), search=("t.name", "t.email"), sortable={"name": "t.name", "created_at": "t.id"}).register(app)

    # ----- journal -----
    Resource("journal", "journal_entries", {}, allow=("list",), search=("t.memo",), filters=("source",), default_sort="t.entry_date DESC, t.id DESC",
             sortable={"entry_date": "t.entry_date"},
             select="t.*, (SELECT COALESCE(SUM(debit_cents),0) FROM journal_lines l WHERE l.entry_id=t.id) AS total_cents, u.name AS created_by_name",
             joins="LEFT JOIN users u ON u.id=t.created_by").register(app)

    @app.post("/api/journal")
    @require(*ACCT)
    def post_journal():
        body = request.get_json(silent=True)
        d = validate({"entry_date": {"type": "date", "required": True}, "memo": {"required": True, "max": 300}}, body)
        lines = parse_lines(body.get("lines"))
        with tx() as c:
            eid = ledger.post_entry(c, d["entry_date"], d["memo"], "manual", lines, g.user["id"])
            audit("create", "journal", eid)
        return jsonify(data={"id": eid}), 201

    @app.get("/api/journal/<int:eid>")
    @require()
    def get_journal(eid):
        e = db().execute("SELECT * FROM journal_entries WHERE id=?", (eid,)).fetchone()
        if not e:
            err(404, "not_found", "Record not found")
        lines = db().execute("SELECT a.code, a.name, l.debit_cents, l.credit_cents FROM journal_lines l JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=? ORDER BY l.id", (eid,)).fetchall()
        return jsonify(data={**dict(e), "lines": [dict(l) for l in lines]})

    @app.post("/api/journal/<int:eid>/reverse")
    @require(*ACCT)
    def reverse(eid):
        with tx() as c:
            new = ledger.reverse_entry(c, eid, g.user["id"])
            audit("reverse", "journal", eid, f"new entry {new}")
        return jsonify(data={"id": new}), 201

    # ----- invoices -----
    inv_res = Resource("invoices", "invoices", {}, allow=("list",), search=("t.number", "c.name"), filters=("status", "customer_id"),
                       sortable={"issue_date": "t.issue_date", "due_date": "t.due_date", "total_cents": "t.total_cents", "number": "t.number"},
                       select="t.*, c.name AS customer_name, t.total_cents - t.paid_cents AS balance_cents, "
                              "CASE WHEN t.status IN ('open','partial') AND t.due_date < date('now') THEN 1 ELSE 0 END AS overdue",
                       joins="JOIN customers c ON c.id=t.customer_id")
    inv_res.register(app)

    @app.post("/api/invoices")
    @require(*BILLING)
    def create_invoice():
        body = request.get_json(silent=True)
        d = validate({"customer_id": {"type": "int", "required": True, "fk": "customers"}, "issue_date": {"type": "date", "required": True}, "due_date": {"type": "date", "required": True}}, body)
        raw = body.get("items")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
            err(422, "validation_error", "Validation failed", {"items": "Provide between 1 and 100 line items"})
        items = [validate({"description": {"required": True, "max": 200}, "quantity": {"type": "int", "required": True, "min": 1, "max": 100000},
                           "unit_price_cents": {"type": "int", "required": True, "min": 0, "max": ledger.MAX_CENTS}}, i) for i in raw]
        with tx() as c:
            iid = ledger.create_invoice(c, d["customer_id"], d["issue_date"], d["due_date"], items, g.user["id"])
            audit("create", "invoices", iid)
        return jsonify(data=inv_res._one(iid, scoped=False)), 201

    @app.get("/api/invoices/<int:iid>")
    @require()
    def get_invoice(iid):
        inv = inv_res._one(iid)
        items = db().execute("SELECT description, quantity, unit_price_cents FROM invoice_items WHERE invoice_id=? ORDER BY id", (iid,)).fetchall()
        pays = db().execute("SELECT amount_cents, paid_on, method FROM payments WHERE invoice_id=? ORDER BY id", (iid,)).fetchall()
        return jsonify(data={**inv, "items": [dict(i) for i in items], "payments": [dict(p) for p in pays]})

    @app.post("/api/invoices/<int:iid>/payments")
    @require(*BILLING)
    def pay(iid):
        d = validate({"amount_cents": {"type": "int", "required": True, "min": 1, "max": ledger.MAX_CENTS}, "paid_on": {"type": "date", "required": True},
                      "method": {"type": "enum", "choices": ["cash", "bank_transfer", "card", "cheque"], "required": True}}, request.get_json(silent=True))
        with tx() as c:
            pid = ledger.record_payment(c, iid, d["amount_cents"], d["paid_on"], d["method"], g.user["id"])
            audit("payment", "invoices", iid, f"payment {pid}")
        return jsonify(data=inv_res._one(iid, scoped=False)), 201

    @app.post("/api/invoices/<int:iid>/void")
    @require(*ACCT)
    def void(iid):
        with tx() as c:
            ledger.void_invoice(c, iid, g.user["id"])
            audit("void", "invoices", iid)
        return jsonify(data=inv_res._one(iid, scoped=False))

    # ----- reports -----
    def date_arg(name):
        v = request.args.get(name)
        if v:
            validate({name: {"type": "date"}}, {name: v})
        return v or None

    def as_list(rows):
        return jsonify(data=rows, meta=page_meta(1, max(1, len(rows)), len(rows)))

    @app.get("/api/trial-balance")
    @require()
    def trial_balance():
        rows = [r for r in ledger.balances(db(), date_arg("from"), date_arg("to")) if r["debit_cents"] or r["credit_cents"]]
        td, tc = sum(r["debit_cents"] for r in rows), sum(r["credit_cents"] for r in rows)
        rows.append({"id": 0, "code": "", "name": "TOTAL" + ("" if td == tc else " (OUT OF BALANCE)"), "type": "", "debit_cents": td, "credit_cents": tc, "balance_cents": td - tc})
        return as_list(rows)

    @app.get("/api/income-statement")
    @require()
    def income_statement():
        rows = [r for r in ledger.balances(db(), date_arg("from"), date_arg("to")) if r["type"] in ("revenue", "expense") and r["balance_cents"]]
        rev = sum(r["balance_cents"] for r in rows if r["type"] == "revenue")
        exp = sum(r["balance_cents"] for r in rows if r["type"] == "expense")
        rows.append({"id": 0, "code": "", "name": "NET INCOME", "type": "", "debit_cents": 0, "credit_cents": 0, "balance_cents": rev - exp})
        return as_list(rows)

    @app.get("/api/stats")
    @require()
    def stats():
        bal = {r["code"]: r["balance_cents"] for r in ledger.balances(db())}
        by_type = {}
        for r in ledger.balances(db()):
            by_type[r["type"]] = by_type.get(r["type"], 0) + r["balance_cents"]
        q = lambda sql: db().execute(sql).fetchone()[0]
        overdue = q("SELECT COUNT(*) FROM invoices WHERE status IN ('open','partial') AND due_date < date('now')")
        st = {r["status"]: r["n"] for r in db().execute("SELECT status, COUNT(*) n FROM invoices GROUP BY status")}
        return jsonify(data={
            "cards": [{"label": "Cash balance", "value": bal.get(ledger.CASH, 0), "format": "money"},
                      {"label": "Receivables outstanding", "value": bal.get(ledger.AR, 0), "format": "money"},
                      {"label": "Revenue to date", "value": bal.get(ledger.REVENUE, 0), "format": "money", "tone": "green"},
                      {"label": "Overdue invoices", "value": overdue, "tone": "red" if overdue else "green"}],
            "breakdowns": [{"title": "Invoices by status", "items": [{"label": s, "value": st.get(s, 0)} for s in ("open", "partial", "paid", "void")]},
                           {"title": "Entries by source", "items": [{"label": r["source"], "value": r["n"]} for r in db().execute("SELECT source, COUNT(*) n FROM journal_entries GROUP BY source")]}]})

    return app
