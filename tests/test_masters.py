from tests.conftest import P


def test_fish_supplier_hotel_crud_and_unique(shop):
    assert shop.post("/fish", {"name": "rohu"}).status_code == 409  # case-insensitive unique
    r = shop.c.patch(f"{P}/fish/{shop.fish['Rohu']}", json={"is_active": False})
    assert r.json()["is_active"] is False
    assert "Rohu" not in [f["name"] for f in shop.get("/fish").json()]
    assert "Rohu" in [f["name"] for f in shop.get("/fish", include_inactive=True).json()]
    assert shop.post("/suppliers", {"name": "Supplier A"}).status_code == 409
    assert shop.post("/hotels", {"name": ""}).status_code == 422


def test_hotel_rates_are_per_hotel_and_fish(shop):
    h = shop.get(f"/hotels/{shop.hotel['Hotel B']}").json()
    rates = {r["fish_name"]: r["rate"] for r in h["rates"]}
    assert rates == {"Rohu": 230, "Katla": 270, "Pomfret": 400}
    r = shop.put(f"/hotels/{shop.hotel['Hotel A']}/rates/{shop.fish['Rohu']}", {"rate": 245.5})
    assert {x["fish_name"]: x["rate"] for x in r.json()["rates"]}["Rohu"] == 245.5
    assert shop.put(f"/hotels/{shop.hotel['Hotel A']}/rates/{shop.fish['Rohu']}", {"rate": 0}).status_code == 422
