"""
Agent tools — the 6 functions the LLM can call during the refund loop.

Each tool function:
  1. Performs its operation against the mock CRM / policy engine
  2. Returns a structured dict the agent can reason about
  3. Emits a ReasoningEvent so the admin panel shows what happened

Tool schemas are defined as Cohere-compatible tool definitions (OpenAI-compatible format).
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from backend.crm_data import (
    get_customer_by_id,
    get_customer_by_email,
    get_order,
    CUSTOMERS,
)
from backend import policy


# ── In-memory refund ledger (resets on server restart — this is intentional) ──

_refund_ledger: dict[str, dict] = {}


# ── Tool execution dispatcher ─────────────────────────────────────────────────

def execute_tool(name: str, arguments: dict) -> dict:
    """Route a tool call from the agent to the correct function."""
    handlers = {
        "lookup_customer":         _lookup_customer,
        "get_order_details":       _get_order_details,
        "check_refund_eligibility": _check_refund_eligibility,
        "process_refund":          _process_refund,
        "deny_refund":             _deny_refund,
        "escalate_to_human":       _escalate_to_human,
    }
    handler = handlers.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(**arguments)
    except TypeError as e:
        return {"error": f"Invalid arguments for {name}: {e}"}


# ── Individual tool implementations ───────────────────────────────────────────

def _lookup_customer(
    customer_id: str | None = None,
    email: str | None = None,
) -> dict:
    """
    Fetch a customer profile from the CRM.
    Caller must provide either customer_id or email.
    """
    customer = None

    if customer_id:
        customer = get_customer_by_id(customer_id)
    elif email:
        customer = get_customer_by_email(email)

    if not customer:
        identifier = customer_id or email or "unknown"
        return {
            "found": False,
            "error": f"No customer found for identifier: {identifier}",
        }

    # Return a safe summary (no internal flags leaked in full)
    return {
        "found": True,
        "customer_id": customer["customer_id"],
        "name": customer["name"],
        "email": customer["email"],
        "tier": customer["tier"],
        "account_flags": customer["account_flags"],
        "order_count": len(customer["orders"]),
        "refund_count_12m": _count_recent_refunds(customer),
        "orders": [
            {
                "order_id": o["order_id"],
                "product": o["product"],
                "amount": o["amount"],
                "order_date": o["order_date"],
                "status": o["status"],
                "is_digital": o.get("is_digital", False),
                "is_subscription": o.get("is_subscription", False),
            }
            for o in customer["orders"]
        ],
    }


def _get_order_details(order_id: str) -> dict:
    """Retrieve full details for a specific order."""
    customer, order = get_order(order_id)

    if not order:
        return {"found": False, "error": f"Order {order_id} not found in CRM."}

    return {
        "found": True,
        "order_id": order["order_id"],
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "customer_tier": customer["tier"],
        "product": order["product"],
        "category": order.get("category", "unknown"),
        "amount": order["amount"],
        "currency": order.get("currency", "USD"),
        "order_date": order["order_date"],
        "status": order["status"],
        "is_digital": order.get("is_digital", False),
        "is_subscription": order.get("is_subscription", False),
        "damage_reported": order.get("damage_reported", False),
        "days_since_order": _days_since(order["order_date"]),
    }


def _check_refund_eligibility(order_id: str) -> dict:
    """
    Run the full policy rulebook against an order and return a verdict.
    This is the core policy engine — every rule is checked in priority order.
    """
    customer, order = get_order(order_id)

    if not order:
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": f"Order {order_id} does not exist.",
            "policy_rule": None,
        }

    days = _days_since(order["order_date"])
    tier = customer["tier"]
    flags = customer["account_flags"]

    # ── Rule 1: Account flags block everything ───────────────────────────────
    blocking = [f for f in flags if f in policy.BLOCKING_ACCOUNT_FLAGS]
    if blocking:
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": (
                f"Account has active flags ({', '.join(blocking)}) that block "
                "all refund processing. Customer must contact Trust & Safety."
            ),
            "policy_rule": policy.POLICY_RULES["ACCOUNT_FLAG"],
        }

    # ── Rule 2: Already refunded ─────────────────────────────────────────────
    if order["status"] == "refunded":
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": f"Order {order_id} has already been refunded.",
            "policy_rule": policy.POLICY_RULES["ALREADY_REFUNDED"],
        }

    # ── Rule 3: Order not yet delivered ─────────────────────────────────────
    if order["status"] in ("in_transit", "processing", "pending"):
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": (
                f"Order {order_id} is currently {order['status']} and cannot "
                "be refunded. Please contact support to request a cancellation instead."
            ),
            "policy_rule": policy.POLICY_RULES["UNDELIVERED"],
        }

    # ── Rule 4: Refund frequency limit ──────────────────────────────────────
    recent_refunds = _count_recent_refunds(customer)
    if recent_refunds >= policy.MAX_REFUNDS_PER_YEAR:
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": (
                f"Customer has already received {recent_refunds} refund(s) in the "
                f"past 12 months (limit: {policy.MAX_REFUNDS_PER_YEAR}). "
                "This request has been flagged for management review."
            ),
            "policy_rule": policy.POLICY_RULES["REFUND_LIMIT"],
        }

    # ── Rule 5: Damaged item — always approve (before window check) ──────────
    if order.get("damage_reported"):
        verdict = "approved"
        if order["amount"] > policy.MANUAL_REVIEW_THRESHOLD:
            verdict = "escalate"
        return {
            "eligible": True,
            "verdict": verdict,
            "reason": (
                "Item was reported as damaged/defective. Policy guarantees eligibility "
                "regardless of return window."
            ),
            "policy_rule": policy.POLICY_RULES["DAMAGED_ITEM"],
            "amount": order["amount"],
        }

    # ── Rule 6: Digital goods — subscriptions have short cancel window ───────
    if order.get("is_subscription"):
        window = policy.SUBSCRIPTION_CANCEL_WINDOW_DAYS
        if days > window:
            return {
                "eligible": False,
                "verdict": "denied",
                "reason": (
                    f"Subscription was purchased {days} days ago. "
                    f"The cancellation window is {window} days. No refund can be issued "
                    "for the current billing period."
                ),
                "policy_rule": policy.POLICY_RULES["SUBSCRIPTION_WINDOW"],
            }
        return {
            "eligible": True,
            "verdict": "approved",
            "reason": (
                f"Subscription cancellation requested within the {window}-day window "
                f"({days} days ago). Eligible for refund."
            ),
            "policy_rule": policy.POLICY_RULES["SUBSCRIPTION_WINDOW"],
            "amount": order["amount"],
        }

    if order.get("is_digital") and not order.get("is_subscription"):
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": (
                "This is a digital product (non-subscription). "
                "Digital goods are non-refundable once access has been granted."
            ),
            "policy_rule": policy.POLICY_RULES["DIGITAL_GOODS"],
        }

    # ── Rule 7: Return window check ──────────────────────────────────────────
    window = policy.RETURN_WINDOW_DAYS.get(tier, 30)
    if days > window:
        return {
            "eligible": False,
            "verdict": "denied",
            "reason": (
                f"Order {order_id} was placed {days} days ago. "
                f"{tier.capitalize()} tier customers have a {window}-day return window. "
                "The window has expired."
            ),
            "policy_rule": policy.POLICY_RULES["RETURN_WINDOW"],
        }

    # ── Rule 8: High-value — escalate ────────────────────────────────────────
    if order["amount"] > policy.MANUAL_REVIEW_THRESHOLD:
        return {
            "eligible": True,
            "verdict": "escalate",
            "reason": (
                f"Order value ${order['amount']:.2f} exceeds the ${policy.MANUAL_REVIEW_THRESHOLD:.2f} "
                "auto-approval ceiling. Must be reviewed by a senior agent."
            ),
            "policy_rule": policy.POLICY_RULES["HIGH_VALUE"],
            "amount": order["amount"],
        }

    # ── All checks passed — approve ──────────────────────────────────────────
    return {
        "eligible": True,
        "verdict": "approved",
        "reason": (
            f"Order {order_id} meets all policy requirements. "
            f"Placed {days} days ago (within {window}-day {tier} tier window), "
            f"${order['amount']:.2f} within auto-approval limit."
        ),
        "policy_rule": policy.POLICY_RULES["RETURN_WINDOW"],
        "amount": order["amount"],
    }


def _process_refund(order_id: str, reason: str) -> dict:
    """
    Execute a refund for an order. Should only be called after
    check_refund_eligibility returns verdict='approved'.
    """
    customer, order = get_order(order_id)

    if not order:
        return {"success": False, "error": f"Order {order_id} not found."}

    # Idempotency check
    if order_id in _refund_ledger:
        existing = _refund_ledger[order_id]
        return {
            "success": False,
            "error": f"Refund {existing['refund_id']} was already processed for this order.",
        }

    refund_id = f"REF-{uuid.uuid4().hex[:6].upper()}"
    refund_record = {
        "refund_id": refund_id,
        "order_id": order_id,
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "amount": order["amount"],
        "currency": order.get("currency", "USD"),
        "reason": reason,
        "processed_at": datetime.utcnow().isoformat(),
        "estimated_return": "3-5 business days",
        "status": "completed",
    }

    _refund_ledger[order_id] = refund_record

    # Mutate the in-memory CRM so status reflects the refund
    order["status"] = "refunded"

    # Append the refund to the customer's refund history
    customer.setdefault("refund_history", []).append({
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": order["amount"],
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "reason": reason,
        "outcome": "approved",
    })

    return {
        "success": True,
        "refund_id": refund_id,
        "amount": order["amount"],
        "currency": order.get("currency", "USD"),
        "message": (
            f"Refund of ${order['amount']:.2f} successfully initiated. "
            f"Reference: {refund_id}. Funds will arrive in 3-5 business days."
        ),
    }


def _deny_refund(order_id: str, reason: str, policy_rule: str) -> dict:
    """
    Record a refund denial. Always include the specific policy rule being cited.
    """
    denial_id = f"DEN-{uuid.uuid4().hex[:6].upper()}"
    return {
        "success": True,
        "denial_id": denial_id,
        "order_id": order_id,
        "reason": reason,
        "policy_rule": policy_rule,
        "message": (
            f"Refund request for order {order_id} has been denied. "
            f"Denial reference: {denial_id}."
        ),
    }


def _escalate_to_human(order_id: str, reason: str) -> dict:
    """
    Flag a refund request for manual review by a senior agent.
    Used for high-value orders or complex edge cases.
    """
    ticket_id = f"TKT-{uuid.uuid4().hex[:6].upper()}"
    return {
        "success": True,
        "ticket_id": ticket_id,
        "order_id": order_id,
        "reason": reason,
        "assigned_to": "Senior Support Team",
        "estimated_response": "Within 1 business day",
        "message": (
            f"Your refund request for order {order_id} has been escalated for "
            f"manual review. Ticket: {ticket_id}. "
            "A senior agent will contact you within 1 business day."
        ),
    }


# ── Utilities ─────────────────────────────────────────────────────────────────

def _days_since(date_str: str) -> int:
    """Calculate days elapsed since a date string (YYYY-MM-DD)."""
    try:
        order_date = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.utcnow() - order_date).days
    except ValueError:
        return 0


def _count_recent_refunds(customer: dict) -> int:
    """Count refunds issued in the past 12 months for a customer."""
    cutoff = datetime.utcnow() - timedelta(days=365)
    count = 0
    for r in customer.get("refund_history", []):
        try:
            refund_date = datetime.strptime(r["date"], "%Y-%m-%d")
            if refund_date >= cutoff:
                count += 1
        except (ValueError, KeyError):
            continue
    return count


# ── Cohere-compatible tool schema definitions ─────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": (
                "Look up a customer in the CRM database by their customer ID or email address. "
                "Always call this first before checking any order or eligibility."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer's unique ID (e.g. C001). Use if provided.",
                    },
                    "email": {
                        "type": "string",
                        "description": "The customer's email address. Use if no ID is provided.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": (
                "Fetch full details for a specific order by order ID. "
                "Use this to confirm order information before running eligibility checks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to look up (e.g. ORD-9821).",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_refund_eligibility",
            "description": (
                "Run the full policy rulebook against an order to determine if a refund "
                "is eligible. Returns a verdict: 'approved', 'denied', or 'escalate'. "
                "ALWAYS call this before process_refund or deny_refund."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to evaluate.",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_refund",
            "description": (
                "Execute a refund for an order. Only call this when "
                "check_refund_eligibility returned verdict='approved'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to refund.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief reason for the refund (customer-provided).",
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deny_refund",
            "description": (
                "Record a formal refund denial. Only call this when "
                "check_refund_eligibility returned verdict='denied'. "
                "Always include the specific policy rule being cited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID being denied.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Clear explanation of why the refund is denied.",
                    },
                    "policy_rule": {
                        "type": "string",
                        "description": "The specific policy section being cited (e.g. 'Policy §1 — Return Windows').",
                    },
                },
                "required": ["order_id", "reason", "policy_rule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Escalate a refund request for manual review by a senior agent. "
                "Use this when check_refund_eligibility returns verdict='escalate' "
                "(e.g. high-value orders over $500)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to escalate.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for escalation.",
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
]
