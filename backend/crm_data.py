"""
CRM Database — 15 mock customer profiles.

Each profile is designed to hit a specific branch of the refund policy:
  - Valid refunds (standard window, gold tier, damaged item)
  - Policy violations (expired window, fraud flag, digital goods, over refund limit)
  - Edge cases (high-value item, subscription, VIP tier, international)
"""

from datetime import datetime, timedelta
from typing import Any

_TODAY = datetime.utcnow()

def _days_ago(n: int) -> str:
    return (_TODAY - timedelta(days=n)).strftime("%Y-%m-%d")


# ── Profiles ───────────────────────────────────────────────────────────────────

CUSTOMERS: dict[str, dict[str, Any]] = {

    # 1. Standard happy path — bronze tier, 12 days ago, $85
    "C001": {
        "customer_id": "C001",
        "name": "Marcus Webb",
        "email": "marcus.webb@email.com",
        "tier": "bronze",
        "phone": "+1-555-0101",
        "account_created": "2023-03-15",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-9821",
                "product": "Wireless Bluetooth Headphones",
                "category": "electronics",
                "amount": 85.00,
                "currency": "USD",
                "order_date": _days_ago(12),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 2. Expired window — bronze tier, 38 days ago (over 30-day limit)
    "C002": {
        "customer_id": "C002",
        "name": "Diana Forsythe",
        "email": "diana.forsythe@email.com",
        "tier": "bronze",
        "phone": "+1-555-0102",
        "account_created": "2022-07-20",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-4450",
                "product": "Kitchen Blender Pro",
                "category": "appliances",
                "amount": 120.00,
                "currency": "USD",
                "order_date": _days_ago(38),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 3. Fraud-flagged account — should be blocked immediately
    "C003": {
        "customer_id": "C003",
        "name": "Ethan Blackwood",
        "email": "ethan.blackwood@tempmail.xyz",
        "tier": "bronze",
        "phone": "+1-555-0103",
        "account_created": "2024-11-01",
        "account_flags": ["fraud_suspected", "chargeback_history"],
        "orders": [
            {
                "order_id": "ORD-7731",
                "product": "Smart Watch Series X",
                "category": "electronics",
                "amount": 299.00,
                "currency": "USD",
                "order_date": _days_ago(5),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [
            {
                "refund_id": "REF-001",
                "order_id": "ORD-5512",
                "amount": 180.00,
                "date": _days_ago(120),
                "reason": "item not received",
                "outcome": "approved",
            }
        ],
    },

    # 4. Digital goods — non-refundable by policy
    "C004": {
        "customer_id": "C004",
        "name": "Priya Nair",
        "email": "priya.nair@gmail.com",
        "tier": "silver",
        "phone": "+1-555-0104",
        "account_created": "2023-01-10",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-3302",
                "product": "Adobe Creative Suite Annual License",
                "category": "software",
                "amount": 599.00,
                "currency": "USD",
                "order_date": _days_ago(3),
                "status": "delivered",
                "is_digital": True,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 5. Damaged item — always eligible regardless of other rules
    "C005": {
        "customer_id": "C005",
        "name": "Leo Fitzgerald",
        "email": "leo.fitz@outlook.com",
        "tier": "silver",
        "phone": "+1-555-0105",
        "account_created": "2021-06-05",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-6610",
                "product": "Ceramic Coffee Mug Set",
                "category": "homeware",
                "amount": 45.00,
                "currency": "USD",
                "order_date": _days_ago(20),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
                "damage_reported": True,
            }
        ],
        "refund_history": [],
    },

    # 6. Gold tier — 40-day-old order (within gold 45-day window)
    "C006": {
        "customer_id": "C006",
        "name": "Sophia Hartmann",
        "email": "sophia.hartmann@company.de",
        "tier": "gold",
        "phone": "+49-30-555-0106",
        "account_created": "2020-02-14",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-1144",
                "product": "Ergonomic Office Chair",
                "category": "furniture",
                "amount": 349.00,
                "currency": "USD",
                "order_date": _days_ago(40),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 7. Already refunded order — double-refund attempt
    "C007": {
        "customer_id": "C007",
        "name": "Carlos Mendez",
        "email": "cmendez@protonmail.com",
        "tier": "bronze",
        "phone": "+1-555-0107",
        "account_created": "2023-09-01",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-2250",
                "product": "Yoga Mat Premium",
                "category": "fitness",
                "amount": 65.00,
                "currency": "USD",
                "order_date": _days_ago(15),
                "status": "refunded",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [
            {
                "refund_id": "REF-220",
                "order_id": "ORD-2250",
                "amount": 65.00,
                "date": _days_ago(8),
                "reason": "changed mind",
                "outcome": "approved",
            }
        ],
    },

    # 8. Over refund limit — 2 refunds already this year
    "C008": {
        "customer_id": "C008",
        "name": "Amara Osei",
        "email": "amara.osei@yahoo.com",
        "tier": "silver",
        "phone": "+1-555-0108",
        "account_created": "2022-04-18",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-8890",
                "product": "Running Shoes Nike Air",
                "category": "footwear",
                "amount": 110.00,
                "currency": "USD",
                "order_date": _days_ago(7),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [
            {
                "refund_id": "REF-180",
                "order_id": "ORD-7710",
                "amount": 89.00,
                "date": _days_ago(60),
                "reason": "wrong size",
                "outcome": "approved",
            },
            {
                "refund_id": "REF-195",
                "order_id": "ORD-8001",
                "amount": 55.00,
                "date": _days_ago(30),
                "reason": "defective",
                "outcome": "approved",
            },
        ],
    },

    # 9. High-value item — needs manual escalation ($650)
    "C009": {
        "customer_id": "C009",
        "name": "James Whitmore",
        "email": "j.whitmore@enterprise.com",
        "tier": "gold",
        "phone": "+1-555-0109",
        "account_created": "2019-11-30",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-5577",
                "product": "DSLR Camera Bundle",
                "category": "electronics",
                "amount": 1249.00,
                "currency": "USD",
                "order_date": _days_ago(10),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 10. Subscription cancel — within 7-day cancellation window
    "C010": {
        "customer_id": "C010",
        "name": "Nina Petrova",
        "email": "nina.petrova@mail.ru",
        "tier": "silver",
        "phone": "+7-495-555-0110",
        "account_created": "2024-01-05",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-4433",
                "product": "StreamMax Premium — Monthly",
                "category": "streaming",
                "amount": 14.99,
                "currency": "USD",
                "order_date": _days_ago(4),
                "status": "active",
                "is_digital": True,
                "is_subscription": True,
            }
        ],
        "refund_history": [],
    },

    # 11. Subscription cancel — outside 7-day window (14 days)
    "C011": {
        "customer_id": "C011",
        "name": "Tyler Nguyen",
        "email": "tyler.nguyen@gmail.com",
        "tier": "bronze",
        "phone": "+1-555-0111",
        "account_created": "2024-03-20",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-3355",
                "product": "CloudStorage Pro — Annual",
                "category": "software",
                "amount": 99.99,
                "currency": "USD",
                "order_date": _days_ago(14),
                "status": "active",
                "is_digital": True,
                "is_subscription": True,
            }
        ],
        "refund_history": [],
    },

    # 12. VIP gold — multiple orders, wants refund on oldest (45-day edge case, day 44)
    "C012": {
        "customer_id": "C012",
        "name": "Eleanor Blackstone",
        "email": "eleanor@vip-client.com",
        "tier": "gold",
        "phone": "+1-555-0112",
        "account_created": "2018-06-01",
        "account_flags": ["vip"],
        "orders": [
            {
                "order_id": "ORD-1001",
                "product": "Luxury Leather Handbag",
                "category": "fashion",
                "amount": 425.00,
                "currency": "USD",
                "order_date": _days_ago(44),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            },
            {
                "order_id": "ORD-1002",
                "product": "Silk Scarf Collection",
                "category": "fashion",
                "amount": 180.00,
                "currency": "USD",
                "order_date": _days_ago(5),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            },
        ],
        "refund_history": [],
    },

    # 13. International order — item not yet delivered
    "C013": {
        "customer_id": "C013",
        "name": "Ahmed Al-Rashidi",
        "email": "ahmed.rashidi@business.ae",
        "tier": "silver",
        "phone": "+971-4-555-0113",
        "account_created": "2023-08-15",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-7799",
                "product": "Industrial Coffee Grinder",
                "category": "appliances",
                "amount": 310.00,
                "currency": "USD",
                "order_date": _days_ago(2),
                "status": "in_transit",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 14. Silver tier — 33-day-old order (within silver 35-day window)
    "C014": {
        "customer_id": "C014",
        "name": "Rachel Summers",
        "email": "rachel.summers@hotmail.com",
        "tier": "silver",
        "phone": "+1-555-0114",
        "account_created": "2022-12-10",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-6621",
                "product": "Air Purifier HEPA 500",
                "category": "appliances",
                "amount": 189.00,
                "currency": "USD",
                "order_date": _days_ago(33),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },

    # 15. Account not found (used as default for testing unknown IDs)
    "C015": {
        "customer_id": "C015",
        "name": "Samuel Okafor",
        "email": "samuel.okafor@work.ng",
        "tier": "bronze",
        "phone": "+234-1-555-0115",
        "account_created": "2025-01-20",
        "account_flags": [],
        "orders": [
            {
                "order_id": "ORD-9999",
                "product": "USB-C Hub 7-Port",
                "category": "electronics",
                "amount": 39.99,
                "currency": "USD",
                "order_date": _days_ago(8),
                "status": "delivered",
                "is_digital": False,
                "is_subscription": False,
            }
        ],
        "refund_history": [],
    },
}

# ── Index helpers ──────────────────────────────────────────────────────────────

EMAIL_INDEX: dict[str, str] = {
    v["email"].lower(): k for k, v in CUSTOMERS.items()
}

ORDER_INDEX: dict[str, str] = {}
for _cid, _customer in CUSTOMERS.items():
    for _order in _customer["orders"]:
        ORDER_INDEX[_order["order_id"]] = _cid


def get_customer_by_id(customer_id: str) -> dict | None:
    return CUSTOMERS.get(customer_id.upper())


def get_customer_by_email(email: str) -> dict | None:
    cid = EMAIL_INDEX.get(email.lower())
    return CUSTOMERS.get(cid) if cid else None


def get_customer_by_order(order_id: str) -> dict | None:
    cid = ORDER_INDEX.get(order_id.upper())
    return CUSTOMERS.get(cid) if cid else None


def get_order(order_id: str) -> tuple[dict | None, dict | None]:
    """Return (customer, order) tuple for a given order ID."""
    cid = ORDER_INDEX.get(order_id.upper())
    if not cid:
        return None, None
    customer = CUSTOMERS[cid]
    order = next((o for o in customer["orders"] if o["order_id"] == order_id.upper()), None)
    return customer, order
