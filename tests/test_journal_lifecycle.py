from tests.conftest import row


def test_closed_journal_is_read_only(shop):
    jid = shop.day("2026-11-02", dict(Rohu=5, Katla=0, Pomfret=0), dict(Rohu=5, Katla=0, Pomfret=0))
    assert shop.buy(jid, "Supplier A", "Rohu", 1, 100).status_code == 409
    assert shop.sell(jid, "Hotel A", "Rohu", 1).status_code == 409
    assert shop.put(f"/journals/{jid}/opening-stock", {"items": [{"fish_id": shop.fish["Rohu"], "quantity": 1}]}).status_code == 409
    assert shop.close(jid, Rohu=0, Katla=0, Pomfret=0).status_code == 409


def test_reopen_needs_warning_confirmation_then_close_again(shop):
    jid = shop.day("2026-11-02", dict(Rohu=5, Katla=0, Pomfret=0), dict(Rohu=5, Katla=0, Pomfret=0), cash=10, upi=5)
    r = shop.post(f"/journals/{jid}/reopen", {})
    assert r.status_code == 409 and r.json()["detail"]["requires_confirmation"] and r.json()["detail"]["warning"]
    assert shop.get(f"/journals/{jid}").json()["status"] == "closed"
    d = shop.post(f"/journals/{jid}/reopen", {"confirm": True}).json()
    assert d["status"] == "open" and d["money"] is None
    assert shop.buy(jid, "Supplier A", "Rohu", 2, 100).status_code == 201
    d = shop.close(jid, cash=20, upi=5, Rohu=5, Katla=0, Pomfret=0).json()
    assert d["status"] == "closed" and row(d, "Rohu")["normal_customer"] == 2


def test_reopen_recalculates_next_day_suggestion_but_keeps_confirmed_quantity(shop):
    j1 = shop.day("2026-11-01", dict(Rohu=8, Katla=0, Pomfret=0), dict(Rohu=8, Katla=0, Pomfret=0))
    j2 = shop.start("2026-11-02")
    d = shop.get(f"/journals/{j2}").json()
    assert row(d, "Rohu")["suggested_opening"] == 8
    shop.opening(j2, Rohu=6, Katla=0, Pomfret=0)
    # correct yesterday: closing becomes 9
    shop.post(f"/journals/{j1}/reopen", {"confirm": True})
    d = shop.get(f"/journals/{j2}").json()
    assert row(d, "Rohu")["suggested_opening"] is None  # previous journal not closed yet
    shop.buy(j1, "Supplier A", "Rohu", 1, 100)  # correction: 1 kg purchase had been missed
    assert shop.close(j1, Rohu=9, Katla=0, Pomfret=0).status_code == 200
    d = shop.get(f"/journals/{j2}").json()
    assert row(d, "Rohu")["suggested_opening"] == 9
    assert row(d, "Rohu")["opening_quantity"] == 6  # owner's confirmed value untouched
    d = shop.opening(j2, Rohu=9, Katla=0, Pomfret=0)  # owner can still edit
    assert row(d, "Rohu")["opening_quantity"] == 9


def test_previous_closed_journal_unchanged_when_new_journal_starts(shop):
    j1 = shop.day("2026-11-01", dict(Rohu=8, Katla=0, Pomfret=0), dict(Rohu=8, Katla=0, Pomfret=0), cash=1, upi=2)
    before = shop.get(f"/journals/{j1}").json()
    j2 = shop.start("2026-11-02")
    shop.opening(j2, Rohu=1, Katla=0, Pomfret=0)
    assert shop.get(f"/journals/{j1}").json() == before


def test_suggestion_uses_previous_journal_not_strictly_previous_calendar_day(shop):
    shop.day("2026-11-01", dict(Rohu=3, Katla=0, Pomfret=0), dict(Rohu=3, Katla=0, Pomfret=0))
    j = shop.start("2026-11-04")  # shop was shut for two days
    assert row(shop.get(f"/journals/{j}").json(), "Rohu")["suggested_opening"] == 3


def test_money_is_cash_plus_upi_only_and_ignores_hotel_payments(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=5, Katla=0, Pomfret=0)
    shop.sell(jid, "Hotel A", "Rohu", 2)
    shop.post("/hotel-payments", {"hotel_id": shop.hotel["Hotel A"], "amount": 480, "payment_mode": "cash", "payment_date": "2026-11-02"})
    shop.buy(jid, "Supplier A", "Rohu", 1, 100, 100, "cash")
    d = shop.close(jid, cash=1000, upi=250, Rohu=3, Katla=0, Pomfret=0).json()
    assert d["money"] == {"cash_amount": 1000, "upi_amount": 250, "total": 1250}


def test_no_starting_cash_field_and_no_combined_net_position(shop):
    jid = shop.start("2026-11-02")
    d = shop.get(f"/journals/{jid}").json()
    assert "starting_cash" not in d and "opening_cash" not in d
    dash = shop.get("/dashboard", business_date="2026-11-02").json()
    assert not any(k in dash for k in ("net", "net_position", "profit", "revenue"))
    assert "hotel_outstanding_total" in dash and "supplier_outstanding_total" in dash


def test_history_lists_days_newest_first(shop):
    shop.day("2026-11-01", dict(Rohu=0, Katla=0, Pomfret=0), dict(Rohu=0, Katla=0, Pomfret=0), cash=10, upi=5)
    shop.start("2026-11-02")
    h = shop.get("/history").json()
    assert [x["business_date"] for x in h] == ["2026-11-02", "2026-11-01"]
    assert h[0]["total_money"] is None and h[1]["total_money"] == 15
    assert len(shop.get("/history", from_date="2026-11-02").json()) == 1
    assert shop.get("/journals/by-date/2026-11-01").status_code == 200
    assert shop.get("/journals/by-date/2026-01-01").status_code == 404


def test_never_silently_use_older_closed_journal_when_latest_earlier_is_open(shop):
    shop.day("2026-11-01", dict(Rohu=8, Katla=0, Pomfret=0), dict(Rohu=8, Katla=0, Pomfret=0))
    j2 = shop.start("2026-11-02")  # left open, never closed
    j3 = shop.start("2026-11-03")
    d = shop.get(f"/journals/{j3}").json()
    assert all(r["suggested_opening"] is None for r in d["stock"]["rows"])  # not the 8 from 11-01
    # accepting a non-existent suggestion is refused, manual entry still works
    assert shop.put(f"/journals/{j3}/opening-stock", {"items": [{"fish_id": shop.fish["Rohu"]}]}).status_code == 422
    d = shop.opening(j3, Rohu=7, Katla=0, Pomfret=0)
    assert row(d, "Rohu")["opening_quantity"] == 7
    # once the latest earlier journal is closed its closing stock becomes the suggestion
    shop.opening(j2, Rohu=5, Katla=0, Pomfret=0)
    shop.close(j2, Rohu=4, Katla=0, Pomfret=0)
    assert row(shop.get(f"/journals/{j3}").json(), "Rohu")["suggested_opening"] == 4
