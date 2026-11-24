from tests.conftest import row


def test_one_journal_per_date(shop):
    shop.start("2026-11-01")
    assert shop.post("/journals", {"business_date": "2026-11-01"}).status_code == 409


def test_first_journal_opening_entered_manually_and_can_be_zero(shop):
    jid = shop.start("2026-11-01")
    d = shop.get(f"/journals/{jid}").json()
    assert all(r["suggested_opening"] is None and not r["opening_confirmed"] for r in d["stock"]["rows"])
    # accepting a suggestion that does not exist is refused; manual zero is fine
    r = shop.put(f"/journals/{jid}/opening-stock", {"items": [{"fish_id": shop.fish["Rohu"]}]})
    assert r.status_code == 422
    d = shop.opening(jid, Rohu=0, Katla=0, Pomfret=0)
    assert all(r["opening_confirmed"] and r["opening_quantity"] == 0 for r in d["stock"]["rows"])


def test_available_stock_example_from_requirements(shop):
    shop.day("2026-11-01", dict(Rohu=8, Katla=6, Pomfret=2), dict(Rohu=8, Katla=6, Pomfret=2))
    jid = shop.start("2026-11-02")
    d = shop.get(f"/journals/{jid}").json()
    assert [row(d, n)["suggested_opening"] for n in ("Rohu", "Katla", "Pomfret")] == [8, 6, 2]
    assert d["stock"]["totals"]["previous_closing"] == 16
    shop.opening(jid, Rohu=6, Katla=6, Pomfret=1)  # owner edits: found less
    shop.buy(jid, "Supplier A", "Rohu", 25, 200)
    shop.buy(jid, "Supplier A", "Katla", 15, 200)
    shop.buy(jid, "Supplier B", "Pomfret", 5, 200)
    d = shop.get(f"/journals/{jid}").json()
    assert [row(d, n)["available"] for n in ("Rohu", "Katla", "Pomfret")] == [31, 21, 6]
    t = d["stock"]["totals"]
    assert (t["previous_closing"], t["opening_quantity"], t["purchased"], t["available"]) == (16, 13, 45, 58)


def test_suggested_opening_can_be_accepted_without_typing(shop):
    shop.day("2026-11-01", dict(Rohu=8, Katla=6, Pomfret=2), dict(Rohu=8, Katla=6, Pomfret=2))
    jid = shop.start("2026-11-02")
    items = [{"fish_id": f} for f in shop.fish.values()]
    d = shop.put(f"/journals/{jid}/opening-stock", {"items": items}).json()
    assert [row(d, n)["opening_quantity"] for n in ("Rohu", "Katla", "Pomfret")] == [8, 6, 2]


def test_normal_customer_quantity_formula(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=6, Katla=0, Pomfret=0)
    shop.buy(jid, "Supplier A", "Rohu", 25, 200)
    shop.sell(jid, "Hotel A", "Rohu", 5)
    shop.sell(jid, "Hotel B", "Rohu", 4)
    d = shop.close(jid, cash=100, upi=50, Rohu=0, Katla=0, Pomfret=0).json()
    r = row(d, "Rohu")
    assert (r["available"], r["hotel_sold"], r["remaining"], r["normal_customer"]) == (31, 9, 0, 22)
    assert d["sales"]["total_normal_customer_quantity"] == 22
    assert [n["quantity"] for n in d["sales"]["normal_customer"] if n["fish_name"] == "Rohu"] == [22]


def test_opening_difference_is_not_counted_as_normal_sales(shop):
    shop.day("2026-11-01", dict(Rohu=8, Katla=0, Pomfret=0), dict(Rohu=8, Katla=0, Pomfret=0))
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=6, Katla=0, Pomfret=0)  # 2 kg missing vs yesterday
    d = shop.close(jid, Rohu=6, Katla=0, Pomfret=0).json()
    assert row(d, "Rohu")["normal_customer"] == 0  # not 2


def test_zero_remaining_not_forced_and_non_zero_allowed(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=10, Katla=0, Pomfret=0)
    d = shop.close(jid, Rohu=4, Katla=0, Pomfret=0).json()
    assert row(d, "Rohu")["remaining"] == 4 and row(d, "Rohu")["normal_customer"] == 6


def test_cannot_close_without_required_data(shop):
    jid = shop.start("2026-11-02")
    # opening not confirmed
    r = shop.close(jid, Rohu=0, Katla=0, Pomfret=0)
    assert r.status_code == 422 and any("not confirmed" in p for p in r.json()["detail"])
    shop.opening(jid, Rohu=1, Katla=1, Pomfret=1)
    # remaining missing for a fish
    r = shop.close(jid, Rohu=0, Katla=0)
    assert r.status_code == 422 and any("Pomfret" in p for p in r.json()["detail"])
    # cash / upi missing -> schema validation
    body = shop.close_body(dict(Rohu=0, Katla=0, Pomfret=0))
    del body["upi_amount"]
    assert shop.post(f"/journals/{jid}/close", body).status_code == 422
    del body["cash_amount"]
    assert shop.post(f"/journals/{jid}/close", body).status_code == 422
    assert shop.get(f"/journals/{jid}").json()["status"] == "open"


def test_remaining_cannot_exceed_available_minus_hotel_sales(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=5, Katla=0, Pomfret=0)
    shop.sell(jid, "Hotel A", "Rohu", 3)
    r = shop.close(jid, Rohu=3, Katla=0, Pomfret=0)  # 5 - 3 - 3 < 0
    assert r.status_code == 422


def test_close_preview_saves_nothing(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=10, Katla=0, Pomfret=0)
    shop.sell(jid, "Hotel A", "Rohu", 2)
    r = shop.post(f"/journals/{jid}/close-preview", shop.close_body(dict(Rohu=1, Katla=0, Pomfret=0), 100, 20)).json()
    assert r["can_close"] and r["money"]["total"] == 120
    assert [n["quantity"] for n in r["sales_normal_customer"] if n["fish_name"] == "Rohu"] == [7]
    assert shop.get(f"/journals/{jid}").json()["status"] == "open"


def test_new_fish_added_mid_day_joins_open_journal(shop):
    jid = shop.start("2026-11-02")
    shop.post("/fish", {"name": "Surmai"})
    d = shop.get(f"/journals/{jid}").json()
    assert "Surmai" in [r["fish_name"] for r in d["stock"]["rows"]]
