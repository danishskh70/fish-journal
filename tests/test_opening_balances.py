from tests.conftest import P


def test_new_accounts_default_to_zero(shop):
    h = shop.get(f"/hotels/{shop.hotel['Hotel A']}").json()
    s = shop.get(f"/suppliers/{shop.sup['Supplier A']}").json()
    assert (h["opening_balance"], h["opening_balance_date"]) == (0, None)
    assert (s["opening_balance"], s["opening_balance_date"]) == (0, None)
    assert shop.get(f"/accounts/hotels/{shop.hotel['Hotel A']}/ledger").json()["entries"] == []


def test_set_on_registration_and_via_endpoint(shop):
    h = shop.post("/hotels", {"name": "Hotel D", "opening_balance": 3500, "opening_balance_date": "2026-11-01"}).json()
    assert (h["opening_balance"], h["opening_balance_date"]) == (3500, "2026-11-01")
    sid = shop.sup["Supplier A"]
    r = shop.put(f"/suppliers/{sid}/opening-balance", {"amount": 2000, "balance_date": "2026-11-01"})
    assert r.json() == {"amount": 2000, "balance_date": "2026-11-01"}
    assert shop.get(f"/suppliers/{sid}").json()["opening_balance"] == 2000
    assert shop.put(f"/suppliers/{sid}/opening-balance", {"amount": -1}).status_code == 422


def test_opening_balance_is_its_own_ledger_entry_not_a_sale_or_purchase(shop):
    hid, sid = shop.hotel["Hotel A"], shop.sup["Supplier A"]
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 4000, "balance_date": "2026-11-01"})
    shop.put(f"/suppliers/{sid}/opening-balance", {"amount": 2500, "balance_date": "2026-11-01"})
    hl = shop.get(f"/accounts/hotels/{hid}/ledger").json()
    sl = shop.get(f"/accounts/suppliers/{sid}/ledger").json()
    assert [(e["entry_type"], e["amount"], e["running_balance"]) for e in hl["entries"]] == [("opening_balance", 4000, 4000)]
    assert [(e["entry_type"], e["amount"], e["running_balance"]) for e in sl["entries"]] == [("opening_balance", 2500, 2500)]
    assert shop.get("/hotel-sales").json()["entries"] == [] and shop.get("/purchases").json()["entries"] == []
    d = shop.start("2026-11-02")
    shop.opening(d, Rohu=0, Katla=0, Pomfret=0)
    j = shop.get(f"/journals/{d}").json()
    assert j["stock"]["totals"]["purchased"] == 0 and j["stock"]["totals"]["hotel_sold"] == 0


def test_balances_ledger_and_payments_include_opening(shop):
    hid = shop.hotel["Hotel A"]
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 4000, "balance_date": "2026-11-01"})
    j = shop.start("2026-11-02")
    shop.opening(j, Rohu=50, Katla=0, Pomfret=0)
    shop.sell(j, "Hotel A", "Rohu", 5)  # +1200
    assert {b["id"]: b["outstanding"] for b in shop.get("/accounts/hotels").json()}[hid] == 5200
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 5200, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 201
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 1, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 422
    led = shop.get(f"/accounts/hotels/{hid}/ledger").json()
    assert [e["entry_type"] for e in led["entries"]] == ["opening_balance", "sale", "payment"]
    assert led["closing_balance"] == 0


def test_opening_balance_can_be_paid_without_any_sale(shop):
    sid = shop.sup["Supplier A"]
    shop.put(f"/suppliers/{sid}/opening-balance", {"amount": 2000, "balance_date": "2026-11-01"})
    r = shop.post("/supplier-payments", {"supplier_id": sid, "amount": 500, "payment_mode": "upi", "payment_date": "2026-11-05"})
    assert r.status_code == 201
    assert shop.get(f"/accounts/suppliers/{sid}/ledger").json()["closing_balance"] == 1500


def test_supplier_ledger_requirements_example_with_opening_balance(shop):
    """Previous 2000 (opening) + purchase 5000, paid 3000, later payment 500 => 3500."""
    sid = shop.sup["Supplier A"]
    shop.put(f"/suppliers/{sid}/opening-balance", {"amount": 2000, "balance_date": "2026-11-01"})
    j = shop.start("2026-11-02")
    shop.opening(j, Rohu=0, Katla=0, Pomfret=0)
    shop.buy(j, "Supplier A", "Rohu", 25, 200, 3000, "cash")
    shop.post("/supplier-payments", {"supplier_id": sid, "amount": 500, "payment_mode": "cash", "payment_date": "2026-11-02"})
    led = shop.get(f"/accounts/suppliers/{sid}/ledger", from_date="2026-11-02").json()
    assert led["previous_balance"] == 2000 and led["closing_balance"] == 3500


def test_historical_balances_as_of_date(shop):
    hid = shop.hotel["Hotel A"]
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 1000, "balance_date": "2026-11-05"})
    j1 = shop.day("2026-11-03", dict(Rohu=10, Katla=0, Pomfret=0), dict(Rohu=5, Katla=0, Pomfret=0), sells=[("Hotel A", "Rohu", 5)])
    j2 = shop.start("2026-11-06")
    shop.opening(j2, Rohu=0, Katla=0, Pomfret=0)
    bal = lambda d: {b["id"]: b["outstanding"] for b in shop.get("/accounts/hotels", as_of=d).json()}[hid]
    assert bal("2026-11-04") == 1200  # opening balance not yet effective
    assert bal("2026-11-05") == 2200
    d1 = shop.get(f"/journals/{j1}").json()["hotel_info"]["outstanding_balances"]
    d2 = shop.get(f"/journals/{j2}").json()["hotel_info"]["outstanding_balances"]
    assert d1[0]["outstanding"] == 1200 and d2[0]["outstanding"] == 2200
    ledger_before = shop.get(f"/accounts/hotels/{hid}/ledger", from_date="2026-11-06").json()
    assert ledger_before["previous_balance"] == 2200


def test_monthly_summary_with_opening_balance(shop):
    hid = shop.hotel["Hotel A"]
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 1500, "balance_date": "2026-10-20"})
    j = shop.start("2026-11-10")
    shop.opening(j, Rohu=100, Katla=0, Pomfret=0)
    shop.sell(j, "Hotel A", "Rohu", 50, rate=200)
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 8000, "payment_mode": "cash", "payment_date": "2026-11-28"})
    nov = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=11).json()
    assert (nov["opening_outstanding"], nov["fish_taken"], nov["payments_received"], nov["closing_outstanding"]) == (1500, 10000, 8000, 3500)
    # opening balance dated inside the month is brought forward as that month's opening, never as fish taken
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 1500, "balance_date": "2026-11-02"})
    nov = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=11).json()
    assert (nov["opening_outstanding"], nov["fish_taken"], nov["closing_outstanding"]) == (1500, 10000, 3500)


def test_dashboard_totals_include_opening_balances_separately(shop):
    shop.put(f"/hotels/{shop.hotel['Hotel A']}/opening-balance", {"amount": 700, "balance_date": "2026-11-01"})
    shop.put(f"/suppliers/{shop.sup['Supplier A']}/opening-balance", {"amount": 300, "balance_date": "2026-11-01"})
    d = shop.get("/dashboard", business_date="2026-11-02").json()
    assert (d["hotel_outstanding_total"], d["supplier_outstanding_total"]) == (700, 300)


def test_cannot_lower_opening_balance_below_payments_and_zero_removes_entry(shop):
    hid = shop.hotel["Hotel A"]
    shop.put(f"/hotels/{hid}/opening-balance", {"amount": 1000, "balance_date": "2026-11-01"})
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 600, "payment_mode": "cash", "payment_date": "2026-11-02"})
    assert shop.put(f"/hotels/{hid}/opening-balance", {"amount": 500, "balance_date": "2026-11-01"}).status_code == 422
    assert shop.get(f"/hotels/{hid}").json()["opening_balance"] == 1000
    shop.c.delete(f"{P}/hotel-payments/1")
    r = shop.put(f"/hotels/{hid}/opening-balance", {"amount": 0, "balance_date": "2026-11-01"})
    assert r.json()["amount"] == 0
    assert shop.get(f"/accounts/hotels/{hid}/ledger").json()["entries"] == []


def test_opening_balance_does_not_affect_daily_money(shop):
    shop.put(f"/hotels/{shop.hotel['Hotel A']}/opening-balance", {"amount": 700, "balance_date": "2026-11-01"})
    j = shop.start("2026-11-02")
    shop.opening(j, Rohu=0, Katla=0, Pomfret=0)
    d = shop.close(j, cash=10, upi=5, Rohu=0, Katla=0, Pomfret=0).json()
    assert d["money"]["total"] == 15
