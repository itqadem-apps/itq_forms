"""estate:AD-17 — surveys and collections are priced in EGP only."""

SHOP_CURRENCY = "EGP"


def is_shop_currency(currency) -> bool:
    return str(currency or "").strip().upper() == SHOP_CURRENCY
