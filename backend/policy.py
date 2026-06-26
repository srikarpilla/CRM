"""
Refund Policy — structured rules used by the agent's eligibility tool.

This is the single source of truth. The agent is instructed to always
reference these rules by name when explaining a decision.
"""

from typing import Final

# ── Tier-based return windows ───────────────────────────────────────────────

RETURN_WINDOW_DAYS: Final[dict[str, int]] = {
    "bronze": 30,
    "silver": 35,
    "gold":   45,
}

# ── Financial thresholds ─────────────────────────────────────────────────────

# Refunds at or below this amount are auto-approved (no manual review needed)
AUTO_APPROVE_CEILING: Final[float] = 500.00

# Refunds above this amount must be escalated to a human agent
MANUAL_REVIEW_THRESHOLD: Final[float] = 500.00

# ── Per-customer limits ──────────────────────────────────────────────────────

# Maximum number of refunds a customer can receive in any rolling 12-month window
MAX_REFUNDS_PER_YEAR: Final[int] = 2

# ── Category-specific rules ──────────────────────────────────────────────────

# Digital goods (software, downloads, licenses) are never refundable
DIGITAL_GOODS_REFUNDABLE: Final[bool] = False

# Subscriptions have a shorter cancellation window regardless of tier
SUBSCRIPTION_CANCEL_WINDOW_DAYS: Final[int] = 7

# Physical items reported as damaged/defective are always eligible (overrides window)
DAMAGED_ITEM_ALWAYS_ELIGIBLE: Final[bool] = True

# Orders that haven't been delivered yet cannot be refunded (must be cancelled instead)
REFUND_REQUIRES_DELIVERED_STATUS: Final[bool] = True

# ── Account flags that block refunds ────────────────────────────────────────

BLOCKING_ACCOUNT_FLAGS: Final[list[str]] = [
    "fraud_suspected",
    "chargeback_history",
    "account_suspended",
]

# ── Policy document (human-readable, used in denial messages) ────────────────

POLICY_TEXT = """
REFUND POLICY — EFFECTIVE 2024-01-01

1. RETURN WINDOWS
   - Bronze tier customers: 30 days from delivery date
   - Silver tier customers: 35 days from delivery date
   - Gold tier customers:   45 days from delivery date

2. DIGITAL GOODS
   Digital products (software licenses, downloads, streaming subscriptions
   purchased more than 7 days ago) are non-refundable once access has been granted.

3. SUBSCRIPTIONS
   Subscription plans may be cancelled and refunded within 7 days of purchase,
   regardless of customer tier. After 7 days, no refund is issued for the
   current billing period.

4. DAMAGED / DEFECTIVE ITEMS
   Items that arrive damaged or are found to be defective are eligible for a
   full refund at any time, regardless of the standard return window.

5. HIGH-VALUE ORDERS
   Refund requests for orders exceeding $500.00 require manual review by
   a senior support agent and cannot be processed automatically.

6. REFUND FREQUENCY LIMITS
   Customers are limited to 2 refunds in any rolling 12-month period.
   Requests beyond this limit will be denied and escalated to management.

7. ACCOUNT FLAGS
   Accounts flagged for suspected fraud, chargeback abuse, or suspension
   are ineligible for refunds until the flag is resolved by the Trust & Safety team.

8. UNDELIVERED ORDERS
   Orders with status "in_transit" or "processing" cannot receive a refund.
   Customers should contact support to request an order cancellation instead.

9. PREVIOUSLY REFUNDED ORDERS
   An order that has already been refunded cannot be refunded a second time.
"""

# ── Helper: human-readable policy rule name lookup ───────────────────────────

POLICY_RULES: Final[dict[str, str]] = {
    "RETURN_WINDOW":          "Policy §1 — Return Windows",
    "DIGITAL_GOODS":          "Policy §2 — Digital Goods",
    "SUBSCRIPTION_WINDOW":    "Policy §3 — Subscriptions",
    "DAMAGED_ITEM":           "Policy §4 — Damaged/Defective Items",
    "HIGH_VALUE":             "Policy §5 — High-Value Orders",
    "REFUND_LIMIT":           "Policy §6 — Refund Frequency Limits",
    "ACCOUNT_FLAG":           "Policy §7 — Account Flags",
    "UNDELIVERED":            "Policy §8 — Undelivered Orders",
    "ALREADY_REFUNDED":       "Policy §9 — Previously Refunded Orders",
}
