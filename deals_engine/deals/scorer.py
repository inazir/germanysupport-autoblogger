from .models import DealItem

PRIORITY_CATEGORIES = {"banking", "telecom", "insurance", "utilities", "travel", "tax"}
PRIORITY_MERCHANTS = {"n26", "c24", "lebara", "check24", "verivox", "wise"}

def score_deal(item: DealItem) -> int:
    score = 0
    merchant = (item.merchant or "").lower()
    category = (item.category or "").lower()

    if category in PRIORITY_CATEGORIES:
        score += 25

    if merchant in PRIORITY_MERCHANTS:
        score += 20

    if item.old_price and item.new_price and item.old_price > item.new_price:
        discount_pct = round((item.old_price - item.new_price) / item.old_price * 100)
        score += min(discount_pct, 30)

    if item.promo_text:
        promo = item.promo_text.lower()
        if any(word in promo for word in ["bonus", "cashback", "gutschein", "rabatt", "discount"]):
            score += 15

    if item.internal_url:
        score += 10

    if item.availability == "active":
        score += 10

    return score
