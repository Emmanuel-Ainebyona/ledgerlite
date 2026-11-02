"""Accounting service layer: all ledger postings go through here (used by the API and the seeder)."""
from datetime import date

from .core import err

CASH, AR, REVENUE = "1000", "1100", "4000"
MAX_CENTS = 10**12


def acct(c, code):
    row = c.execute("SELECT id FROM accounts WHERE code=? AND active=1", (code,)).fetchone()
    if not row:
        err(500, "config_error", f"Required system account {code} is missing or inactive")
    return row[0]


def post_entry(c, entry_date, memo, source, lines, user_id, reverses_id=None):
    """lines: [(account_id, debit_cents, credit_cents)]. Enforces balance; must run inside a transaction."""
    if sum(l[1] for l in lines) != sum(l[2] for l in lines) or not lines:
        err(422, "validation_error", "Validation failed", {"lines": "Debits must equal credits"})
    eid = c.execute("INSERT INTO journal_entries(entry_date,memo,source,reverses_id,created_by) VALUES(?,?,?,?,?)",
                    (entry_date, memo, source, reverses_id, user_id)).lastrowid
    for a, d, cr in lines:
        c.execute("INSERT INTO journal_lines(entry_id,account_id,debit_cents,credit_cents) VALUES(?,?,?,?)", (eid, a, d, cr))
    return eid


def reverse_entry(c, entry_id, user_id, source="reversal", memo=None):
    e = c.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
    if not e:
        err(404, "not_found", "Record not found")
    if e["source"] in ("reversal", "void") or e["reverses_id"]:
        err(409, "conflict", "A reversing entry cannot itself be reversed")
    if c.execute("SELECT 1 FROM journal_entries WHERE reverses_id=?", (entry_id,)).fetchone():
        err(409, "conflict", "This entry has already been reversed")
    lines = [(r["account_id"], r["credit_cents"], r["debit_cents"]) for r in c.execute("SELECT * FROM journal_lines WHERE entry_id=?", (entry_id,))]
    return post_entry(c, date.today().isoformat(), memo or f"Reversal of entry #{entry_id}", source, lines, user_id, reverses_id=entry_id)


def create_invoice(c, customer_id, issue_date, due_date, items, user_id):
    total = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    if total <= 0 or total > MAX_CENTS:
        err(422, "validation_error", "Validation failed", {"items": "Invoice total must be greater than zero"})
    if due_date < issue_date:
        err(422, "validation_error", "Validation failed", {"due_date": "Due date cannot be before the issue date"})
    n = c.execute("SELECT COALESCE(MAX(id),0)+1 FROM invoices").fetchone()[0]
    inv = c.execute("INSERT INTO invoices(number,customer_id,issue_date,due_date,total_cents,created_by) VALUES(?,?,?,?,?,?)",
                    (f"INV-{n:05d}", customer_id, issue_date, due_date, total, user_id)).lastrowid
    for i in items:
        c.execute("INSERT INTO invoice_items(invoice_id,description,quantity,unit_price_cents) VALUES(?,?,?,?)", (inv, i["description"], i["quantity"], i["unit_price_cents"]))
    eid = post_entry(c, issue_date, f"Invoice INV-{n:05d}", "invoice", [(acct(c, AR), total, 0), (acct(c, REVENUE), 0, total)], user_id)
    c.execute("UPDATE invoices SET entry_id=? WHERE id=?", (eid, inv))
    return inv


def record_payment(c, invoice_id, amount, paid_on, method, user_id):
    inv = c.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        err(404, "not_found", "Record not found")
    if inv["status"] == "void":
        err(409, "conflict", "Cannot record a payment against a void invoice")
    if amount > inv["total_cents"] - inv["paid_cents"]:
        err(422, "validation_error", "Validation failed", {"amount_cents": "Exceeds the outstanding balance"})
    eid = post_entry(c, paid_on, f"Payment for {inv['number']}", "payment", [(acct(c, CASH), amount, 0), (acct(c, AR), 0, amount)], user_id)
    pid = c.execute("INSERT INTO payments(invoice_id,amount_cents,paid_on,method,entry_id,created_by) VALUES(?,?,?,?,?,?)",
                    (invoice_id, amount, paid_on, method, eid, user_id)).lastrowid
    paid = inv["paid_cents"] + amount
    c.execute("UPDATE invoices SET paid_cents=?, status=? WHERE id=?", (paid, "paid" if paid == inv["total_cents"] else "partial", invoice_id))
    return pid


def void_invoice(c, invoice_id, user_id):
    inv = c.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        err(404, "not_found", "Record not found")
    if inv["status"] == "void" or inv["paid_cents"] > 0:
        err(409, "conflict", "Only unpaid, non-void invoices can be voided")
    reverse_entry(c, inv["entry_id"], user_id, source="void", memo=f"Void {inv['number']}")
    c.execute("UPDATE invoices SET status='void' WHERE id=?", (invoice_id,))


BALANCES_SQL = """
SELECT a.id, a.code, a.name, a.type,
       COALESCE(SUM(l.debit_cents),0) AS debit_cents, COALESCE(SUM(l.credit_cents),0) AS credit_cents
FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
LEFT JOIN journal_entries e ON e.id=l.entry_id
WHERE (? IS NULL OR e.entry_date >= ?) AND (? IS NULL OR e.entry_date <= ?) OR l.id IS NULL
GROUP BY a.id ORDER BY a.code"""


def balances(c, start=None, end=None):
    rows = []
    for r in c.execute(BALANCES_SQL, (start, start, end, end)):
        r = dict(r)
        r["balance_cents"] = r["debit_cents"] - r["credit_cents"] if r["type"] in ("asset", "expense") else r["credit_cents"] - r["debit_cents"]
        rows.append(r)
    return rows
