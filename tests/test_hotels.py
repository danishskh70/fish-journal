from tests.conftest import P


def _journal(shop, day="2026-11-02", **opening):
    jid = shop.start(day)
    shop.opening(jid, **(opening or dict(Rohu=50, Katla=50, Pomfret=50)))
    return jid


def test_sale_loads_agreed_rate_and_amount(shop):
    jid = _journal(shop)
    s = shop.sell(jid, "Hotel A", "Rohu", 5).json()
    assert (s["rate"], s["amount"], s["rate_overridden"]) == (240, 1200, False)


def test_rate_override_for_single_sale_keeps_default(shop):
    jid = _journal(shop)
    s = shop.sell(jid, "Hotel A", "Rohu", 5, rate=250).json()
    assert (s["rate"], s["amount"], s["rate_overridden"]) == (250, 1250, True)
    hotel = shop.get(f"/hotels/{shop.hotel['Hotel A']}").json()
    assert {r["fish_name"]: r["rate"] for r in hotel["rates"]}["Rohu"] == 240
    assert shop.sell(jid, "Hotel A", "Rohu", 1).json()["rate"] == 240


def test_changing_default_rate_does_not_change_past_sales(shop):
    jid = _journal(shop)
    shop.sell(jid, "Hotel A", "Rohu", 5)
    shop.put(f"/hotels/{shop.hotel['Hotel A']}/rates/{shop.fish['Rohu']}", {"rate": 300})
    assert shop.get("/hotel-sales", journal_id=jid).json()["entries"][0]["rate"] == 240
    assert shop.get(f"/accounts/hotels/{shop.hotel['Hotel A']}/ledger").json()["closing_balance"] == 1200


def test_no_rate_anywhere_is_rejected(shop):
    shop.post("/fish", {"name": "Surmai"})
    jid = _journal(shop)
    fid = shop.get("/fish").json()
    surmai = next(f["id"] for f in fid if f["name"] == "Surmai")
    body = {"journal_id": jid, "hotel_id": shop.hotel["Hotel A"], "fish_id": surmai, "quantity": 1}
    assert shop.post("/hotel-sales", body).status_code == 422
    assert shop.post("/hotel-sales", {**body, "rate": 500}).status_code == 201


def test_requirements_sales_example_totals(shop):
    jid = _journal(shop)
    shop.sell(jid, "Hotel A", "Rohu", 5)
    shop.sell(jid, "Hotel A", "Katla", 3)
    shop.sell(jid, "Hotel B", "Rohu", 4)
    r = shop.get("/hotel-sales", journal_id=jid).json()
    assert (r["total_quantity"], r["total_amount"]) == (12, 2960)
    assert [e["amount"] for e in r["entries"]] == [1200, 840, 920]


def test_unpaid_sales_stay_in_hotel_account(shop):
    jid = _journal(shop)
    shop.sell(jid, "Hotel A", "Rohu", 5)
    bal = {b["name"]: b["outstanding"] for b in shop.get("/accounts/hotels").json()}
    assert bal["Hotel A"] == 1200 and bal["Hotel B"] == 0


def test_hotel_payment_reduces_balance_without_creating_sale(shop):
    jid = _journal(shop)
    hid = shop.hotel["Hotel A"]
    shop.sell(jid, "Hotel A", "Rohu", 5)
    r = shop.post("/hotel-payments", {"hotel_id": hid, "amount": 500, "payment_mode": "upi", "payment_date": "2026-11-05"})
    assert r.status_code == 201
    led = shop.get(f"/accounts/hotels/{hid}/ledger").json()
    assert [(e["entry_type"], e["running_balance"]) for e in led["entries"]] == [("sale", 1200), ("payment", 700)]
    assert shop.get("/hotel-sales", journal_id=jid).json()["total_amount"] == 1200  # unchanged
    assert shop.get(f"/journals/{jid}").json()["stock"]["totals"]["hotel_sold"] == 5


def test_full_and_partial_hotel_payments_any_date(shop):
    jid = _journal(shop)
    hid = shop.hotel["Hotel A"]
    shop.sell(jid, "Hotel A", "Rohu", 5)
    for amt, day in ((200, "2026-11-03"), (1000, "2026-12-20")):
        shop.post("/hotel-payments", {"hotel_id": hid, "amount": amt, "payment_mode": "cash", "payment_date": day})
    assert shop.get(f"/accounts/hotels/{hid}/ledger").json()["closing_balance"] == 0
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 0, "payment_mode": "cash"}).status_code == 422
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 5, "payment_mode": "cheque"}).status_code == 422


def test_monthly_summary_and_carry_forward(shop):
    hid = shop.hotel["Hotel A"]
    j = _journal(shop, "2026-11-10", Rohu=100, Katla=0, Pomfret=0)
    shop.sell(j, "Hotel A", "Rohu", 50, rate=200)  # 10,000
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 8000, "payment_mode": "cash", "payment_date": "2026-11-28"})
    nov = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=11).json()
    assert (nov["opening_outstanding"], nov["fish_taken"], nov["payments_received"], nov["closing_outstanding"]) == (0, 10000, 8000, 2000)
    dec = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=12).json()
    assert (dec["opening_outstanding"], dec["closing_outstanding"]) == (2000, 2000)  # carried forward
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 2000, "payment_mode": "upi", "payment_date": "2026-12-15"})
    dec = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=12).json()
    assert (dec["payments_received"], dec["closing_outstanding"]) == (2000, 0)
    nov_again = shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=11).json()
    assert nov_again["closing_outstanding"] == 2000  # history stays
    allm = shop.get("/accounts/hotels/monthly-summary", year=2026, month=11).json()
    assert len(allm) == 3
    assert shop.get(f"/accounts/hotels/{hid}/monthly-summary", year=2026, month=13).status_code == 422


def test_hotel_info_in_daily_journal(shop):
    j = _journal(shop)
    hid = shop.hotel["Hotel A"]
    shop.sell(j, "Hotel A", "Rohu", 5)
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 300, "payment_mode": "cash", "payment_date": "2026-11-02"})
    d = shop.get(f"/journals/{j}").json()
    assert d["sales"]["total_hotel_quantity"] == 5 and d["sales"]["total_hotel_amount"] == 1200
    assert [p["amount"] for p in d["hotel_info"]["payments_received"]] == [300]
    assert d["hotel_info"]["outstanding_balances"] == [{"id": hid, "name": "Hotel A", "outstanding": 900}]


def test_balances_as_of_date_in_historical_journal(shop):
    hid = shop.hotel["Hotel A"]
    j1 = shop.day("2026-11-01", dict(Rohu=10, Katla=0, Pomfret=0), dict(Rohu=5, Katla=0, Pomfret=0), sells=[("Hotel A", "Rohu", 5)])
    j2 = _journal(shop, "2026-11-02", Rohu=5, Katla=0, Pomfret=0)
    shop.sell(j2, "Hotel A", "Rohu", 1)
    d1 = shop.get(f"/journals/{j1}").json()
    assert d1["hotel_info"]["outstanding_balances"][0]["outstanding"] == 1200  # as of day 1, not day 2
    assert shop.get(f"/accounts/hotels/{hid}/ledger", to_date="2026-11-01").json()["closing_balance"] == 1200


def test_dashboard_keeps_hotel_and_supplier_totals_separate(shop):
    j = _journal(shop)
    shop.sell(j, "Hotel A", "Rohu", 5)
    shop.buy(j, "Supplier A", "Rohu", 10, 100, 400, "cash")
    d = shop.get("/dashboard", business_date="2026-11-02").json()
    assert d["hotel_outstanding_total"] == 1200 and d["supplier_outstanding_total"] == 600
    assert d["journal"]["status"] == "open"
    rohu = next(r for r in d["stock_overview"] if r["fish_name"] == "Rohu")
    assert rohu["current_stock"] == 50 + 10 - 5
    empty = shop.get("/dashboard", business_date="2030-01-01").json()
    assert empty["journal"] is None


def test_hotel_sale_edit_delete_only_when_open(shop):
    j = _journal(shop)
    s = shop.sell(j, "Hotel A", "Rohu", 5).json()
    upd = {"hotel_id": shop.hotel["Hotel A"], "fish_id": shop.fish["Rohu"], "quantity": 6}
    assert shop.put(f"/hotel-sales/{s['id']}", upd).json()["amount"] == 1440
    shop.close(j, Rohu=0, Katla=0, Pomfret=0)
    assert shop.put(f"/hotel-sales/{s['id']}", upd).status_code == 409
    assert shop.c.delete(f"{P}/hotel-sales/{s['id']}").status_code == 409


def test_inactive_fish_rejected_for_new_hotel_sale_but_allowed_for_existing_edit(shop):
    jid = _journal(shop)
    fid = shop.fish["Rohu"]
    hid = shop.hotel["Hotel A"]

    sale = shop.sell(jid, "Hotel A", "Rohu", 5).json()

    deactivated = shop.c.patch(f"{P}/fish/{fid}", json={"is_active": False})
    assert deactivated.status_code == 200

    # A new hotel sale using inactive fish must be rejected.
    assert shop.sell(jid, "Hotel A", "Rohu", 2).status_code == 422

    # Editing an existing sale without changing its fish remains allowed.
    body = {"hotel_id": hid, "fish_id": fid, "quantity": 6}
    updated = shop.put(f"/hotel-sales/{sale['id']}", body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["quantity"] == 6
