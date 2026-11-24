from tests.conftest import P


def _journal(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=0, Katla=0, Pomfret=0)
    return jid


def test_purchase_amount_due_and_examples(shop):
    jid = _journal(shop)
    a = shop.buy(jid, "Supplier A", "Rohu", 25, 200).json()  # A: nothing paid
    assert (a["amount"], a["paid_now"], a["due_created"], a["payment_mode"]) == (5000, 0, 5000, None)
    b = shop.buy(jid, "Supplier A", "Rohu", 25, 200, 2000, "upi").json()  # B: partial
    assert (b["paid_now"], b["due_created"], b["payment_mode"]) == (2000, 3000, "upi")
    c = shop.buy(jid, "Supplier B", "Katla", 10, 100.5, 1005, "cash").json()  # full
    assert (c["amount"], c["due_created"]) == (1005, 0)


def test_purchase_validation(shop):
    jid = _journal(shop)
    assert shop.buy(jid, "Supplier A", "Rohu", 1, 100, 150, "cash").status_code == 422  # paid > amount
    assert shop.buy(jid, "Supplier A", "Rohu", 1, 100, 50).status_code == 422  # mode missing
    assert shop.buy(jid, "Supplier A", "Rohu", 0, 100).status_code == 422
    assert shop.buy(jid, "Supplier A", "Rohu", 1, 100, 50, "card").status_code == 422


def test_purchase_totals(shop):
    jid = _journal(shop)
    shop.buy(jid, "Supplier A", "Rohu", 25, 200, 3000, "cash")
    shop.buy(jid, "Supplier B", "Katla", 15, 100)
    t = shop.get("/purchases", journal_id=jid).json()["totals"]
    assert t == {"total_quantity": 40, "total_amount": 6500, "total_paid_now": 3000, "total_due_created": 3500}
    d = shop.get(f"/journals/{jid}").json()
    assert d["purchases"]["totals"] == t
    assert d["supplier_info"]["paid_immediately_total"] == 3000 and d["supplier_info"]["dues_created_total"] == 3500


def test_immediate_payment_is_in_supplier_payment_ledger_once(shop):
    jid = _journal(shop)
    shop.buy(jid, "Supplier A", "Rohu", 25, 200, 3000, "cash")
    pays = shop.get("/supplier-payments", supplier_id=shop.sup["Supplier A"]).json()
    assert len(pays) == 1 and pays[0]["is_immediate"] and pays[0]["amount"] == 3000 and pays[0]["payment_mode"] == "cash"
    led = shop.get(f"/accounts/suppliers/{shop.sup['Supplier A']}/ledger").json()
    assert [e["entry_type"] for e in led["entries"]] == ["purchase", "immediate_payment"]
    assert led["closing_balance"] == 2000  # no double counting


def test_supplier_ledger_example_from_requirements(shop):
    sid = shop.sup["Supplier A"]
    j1 = shop.start("2026-11-01")
    shop.opening(j1, Rohu=0, Katla=0, Pomfret=0)
    shop.buy(j1, "Supplier A", "Rohu", 10, 200)  # previous balance 2000
    shop.post("/supplier-payments", {"supplier_id": sid, "amount": 0.01, "payment_mode": "cash", "payment_date": "2026-11-01"})
    # rebuild cleanly: delete tiny payment, make previous balance exactly 2000 via paid_now
    shop.c.delete(f"{P}/supplier-payments/1")
    shop.c.delete(f"{P}/purchases/1")
    shop.buy(j1, "Supplier A", "Rohu", 10, 200, 0)  # 2000 due
    shop.close(j1, Rohu=0, Katla=0, Pomfret=0)
    j2 = shop.start("2026-11-02")
    shop.opening(j2, Rohu=0, Katla=0, Pomfret=0)
    shop.buy(j2, "Supplier A", "Rohu", 25, 200, 3000, "cash")  # +5000 purchase, 3000 paid, 2000 due
    shop.post("/supplier-payments", {"supplier_id": sid, "amount": 500, "payment_mode": "upi", "payment_date": "2026-11-02"})
    led = shop.get(f"/accounts/suppliers/{sid}/ledger", from_date="2026-11-02").json()
    assert led["previous_balance"] == 2000
    assert led["closing_balance"] == 3500
    assert [e["running_balance"] for e in led["entries"]] == [7000, 4000, 3500]


def test_supplier_payments_independent_of_purchases(shop):
    sid = shop.sup["Supplier A"]
    jid = _journal(shop)
    shop.buy(jid, "Supplier A", "Rohu", 25, 200)  # 5000 due, nothing paid
    before = shop.get("/purchases").json()
    # several partial payments on different dates, then clear
    for amt, day, mode in ((1000, "2026-11-03", "cash"), (1500, "2026-11-10", "upi"), (2500, "2026-12-01", "cash")):
        r = shop.post("/supplier-payments", {"supplier_id": sid, "amount": amt, "payment_mode": mode, "payment_date": day})
        assert r.status_code == 201 and r.json()["purchase_id"] is None
    assert shop.get("/purchases").json() == before  # no new purchase, quantities unchanged
    bal = {b["id"]: b["outstanding"] for b in shop.get("/accounts/suppliers").json()}
    assert bal[sid] == 0
    led = shop.get(f"/accounts/suppliers/{sid}/ledger").json()
    assert [(e["date"], e["payment_mode"]) for e in led["entries"] if e["entry_type"] == "payment"] == [
        ("2026-11-03", "cash"), ("2026-11-10", "upi"), ("2026-12-01", "cash")]


def test_later_payment_shows_in_that_days_journal(shop):
    sid = shop.sup["Supplier A"]
    j1 = _journal(shop)
    shop.buy(j1, "Supplier A", "Rohu", 10, 100)
    shop.post("/supplier-payments", {"supplier_id": sid, "amount": 400, "payment_mode": "cash", "payment_date": "2026-11-02"})
    d = shop.get(f"/journals/{j1}").json()
    assert [p["amount"] for p in d["supplier_info"]["later_payments"]] == [400]
    assert d["supplier_info"]["outstanding_balances"] == [{"id": sid, "name": "Supplier A", "outstanding": 600}]


def test_edit_and_delete_purchase_keep_payment_ledger_in_sync(shop):
    jid = _journal(shop)
    p = shop.buy(jid, "Supplier A", "Rohu", 10, 100, 400, "cash").json()
    body = {"supplier_id": shop.sup["Supplier A"], "fish_id": shop.fish["Rohu"], "quantity": 10, "rate": 100,
            "paid_now": 700, "payment_mode": "upi"}
    r = shop.put(f"/purchases/{p['id']}", body).json()
    assert (r["paid_now"], r["due_created"]) == (700, 300)
    pays = shop.get("/supplier-payments").json()
    assert [(x["amount"], x["payment_mode"]) for x in pays] == [(700, "upi")]
    body["paid_now"] = 0
    shop.put(f"/purchases/{p['id']}", body)
    assert shop.get("/supplier-payments").json() == []
    shop.put(f"/purchases/{p['id']}", {**body, "paid_now": 100, "payment_mode": "cash"})
    assert shop.c.delete(f"{P}/purchases/{p['id']}").status_code == 204
    assert shop.get("/supplier-payments").json() == []
    assert shop.get("/purchases").json()["entries"] == []


def test_immediate_payment_cannot_be_edited_directly(shop):
    jid = _journal(shop)
    shop.buy(jid, "Supplier A", "Rohu", 10, 100, 400, "cash")
    pid = shop.get("/supplier-payments").json()[0]["id"]
    assert shop.c.delete(f"{P}/supplier-payments/{pid}").status_code == 409


def test_payments_never_create_purchases_or_stock(shop):
    jid = _journal(shop)
    shop.buy(jid, "Supplier A", "Rohu", 1, 100)
    shop.post("/supplier-payments", {"supplier_id": shop.sup["Supplier A"], "amount": 100, "payment_mode": "cash"})
    d = shop.get(f"/journals/{jid}").json()
    assert d["stock"]["totals"]["purchased"] == 1 and len(d["purchases"]["entries"]) == 1
