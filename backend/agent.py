"""
Agent loop — the core reasoning engine.

Uses Cohere's Command R+ tool-use API in a multi-turn loop:

  user message
    → LLM decides which tool(s) to call
      → tools execute, results appended to message history
        → LLM reasons about results, decides next tool or final answer
          → loop exits when LLM produces a plain text response (no tool calls)

Each tool call emits a ReasoningEvent to an asyncio.Queue so the FastAPI
SSE endpoint can stream it to the admin panel in real time.

The loop has a hard cap of MAX_ITERATIONS to prevent runaway agents.
"""

import json
import asyncio
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime

import cohere

from backend.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
COHERE_MODEL = "command-r-plus-08-2024"

# ── Reasoning event (sent to admin panel via SSE) ─────────────────────────────

@dataclass
class ReasoningEvent:
    type: str           # "tool_call" | "tool_result" | "thinking" | "final" | "error"
    tool_name: str | None
    payload: dict
    iteration: int
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional customer support agent for an e-commerce platform.
Your job is to handle refund requests by following the company's refund policy precisely.

RULES YOU MUST FOLLOW:
1. Always use lookup_customer first to identify the customer before doing anything else.
2. Always use get_order_details to confirm the specific order details. Never answer a refund request or make any decision using only lookup_customer.
3. Always use check_refund_eligibility for the order being requested, even if lookup_customer shows the order status is already 'refunded', 'in_transit', or has flags. You must run this tool.
4. If eligibility verdict is "approved" → call process_refund.
5. If eligibility verdict is "denied" → call deny_refund, citing the exact policy rule.
6. If eligibility verdict is "escalate" → call escalate_to_human.
7. Never process a refund, deny a refund, or tell a customer a refund is processed/denied/already done without first running the eligibility check and then calling the corresponding action tool.
8. When denying, be empathetic but firm. Quote the specific policy section.
9. Never make up information — only use data returned by your tools.
10. If you cannot identify the customer or order, ask for clarification.

Your tone is professional, empathetic, and clear. Do not be robotic.
When a refund is denied, acknowledge the customer's frustration but be clear about the policy."""


# ── Agent session ─────────────────────────────────────────────────────────────

class AgentSession:
    """
    Maintains conversation history for a single support session.
    Supports multi-turn conversations (customer can ask follow-up questions).
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[dict] = []
        self.event_queue: asyncio.Queue[ReasoningEvent | None] = asyncio.Queue()
        self.created_at = datetime.utcnow().isoformat()
        self.iteration_count = 0
        self.tool_call_count = 0

    async def run(self, user_message: str) -> str:
        """
        Run the agent loop for a single user message.
        Returns the final text response.
        Emits ReasoningEvents to self.event_queue throughout.
        """
        co = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])

        # Append user message to history
        self.messages.append({"role": "user", "content": user_message})

        await self._emit(ReasoningEvent(
            type="thinking",
            tool_name=None,
            payload={"message": f"Processing: \"{user_message[:80]}...\"" if len(user_message) > 80 else f"Processing: \"{user_message}\""},
            iteration=0,
            timestamp=_now(),
        ))

        final_response = ""
        iteration = 0

        while iteration < MAX_ITERATIONS:
            iteration += 1
            self.iteration_count += 1

            # ── Call Cohere with current message history ─────────────────────
            try:
                chat_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.messages
                response = co.chat(
                    model=COHERE_MODEL,
                    messages=chat_messages,
                    tools=TOOL_DEFINITIONS,
                    temperature=0.0,
                )
            except Exception as e:
                logger.error(f"Cohere API error: {e}")
                await self._emit(ReasoningEvent(
                    type="error",
                    tool_name=None,
                    payload={"error": str(e)},
                    iteration=iteration,
                    timestamp=_now(),
                ))
                return "I'm sorry, I'm having trouble processing your request right now. Please try again."

            # ── Check if the model wants to call tools ───────────────────────
            tool_calls = response.message.tool_calls if response.message else None

            if not tool_calls:
                # ── Failsafe: Force execute action tool if eligibility check was run but no action was called ──
                eligibility_result = None
                has_action_tool_call = False
                order_id = None

                for msg in self.messages:
                    if msg.get("role") == "tool":
                        tool_call_id = msg.get("tool_call_id")
                        tool_name = None
                        for prev_msg in self.messages:
                            if prev_msg.get("role") == "assistant" and "tool_calls" in prev_msg:
                                for tc in prev_msg["tool_calls"]:
                                    if tc.get("id") == tool_call_id:
                                        tool_name = tc.get("function", {}).get("name")
                                        break
                        if tool_name == "check_refund_eligibility":
                            try:
                                eligibility_result = json.loads(msg.get("content", "{}"))
                            except Exception:
                                pass
                        elif tool_name in ("process_refund", "deny_refund", "escalate_to_human"):
                            has_action_tool_call = True

                # Find order_id
                for msg in self.messages:
                    if msg.get("role") == "assistant" and "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            fn = tc.get("function", {})
                            if fn.get("name") == "check_refund_eligibility":
                                try:
                                    args = json.loads(fn.get("arguments", "{}")) if isinstance(fn.get("arguments"), str) else fn.get("arguments", {})
                                    if "order_id" in args:
                                        order_id = args["order_id"]
                                except Exception:
                                    pass

                force_tool_name = None
                force_tool_args = {}

                if eligibility_result and not has_action_tool_call:
                    verdict = eligibility_result.get("verdict")
                    if verdict == "approved" and order_id:
                        force_tool_name = "process_refund"
                        force_tool_args = {"order_id": order_id, "reason": "Customer requested a refund"}
                    elif verdict == "denied" and order_id:
                        force_tool_name = "deny_refund"
                        force_tool_args = {
                            "order_id": order_id,
                            "reason": eligibility_result.get("reason", "Refund eligibility check failed"),
                            "policy_rule": eligibility_result.get("policy_rule", "Company Refund Policy")
                        }
                    elif verdict == "escalate" and order_id:
                        force_tool_name = "escalate_to_human"
                        force_tool_args = {
                            "order_id": order_id,
                            "reason": eligibility_result.get("reason", "Escalated for senior review")
                        }

                if force_tool_name:
                    import uuid
                    fake_tc_id = f"force_{force_tool_name}_{uuid.uuid4().hex[:6]}"
                    self.messages.append({
                        "role": "assistant",
                        "tool_calls": [{
                            "id": fake_tc_id,
                            "type": "function",
                            "function": {
                                "name": force_tool_name,
                                "arguments": json.dumps(force_tool_args)
                            }
                        }],
                        "content": ""
                    })

                    await self._emit(ReasoningEvent(
                        type="tool_call",
                        tool_name=force_tool_name,
                        payload={"arguments": force_tool_args},
                        iteration=iteration,
                        timestamp=_now(),
                    ))

                    result = execute_tool(force_tool_name, force_tool_args)

                    await self._emit(ReasoningEvent(
                        type="tool_result",
                        tool_name=force_tool_name,
                        payload=result,
                        iteration=iteration,
                        timestamp=_now(),
                    ))

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": fake_tc_id,
                        "content": json.dumps(result)
                    })

                    self.tool_call_count += 1
                    continue

                # No forcing needed → this is the final answer
                content = response.message.content
                if isinstance(content, list):
                    final_response = " ".join(
                        block.text for block in content if hasattr(block, "text")
                    )
                else:
                    final_response = str(content) if content else ""

                self.messages.append({
                    "role": "assistant",
                    "content": final_response,
                })

                await self._emit(ReasoningEvent(
                    type="final",
                    tool_name=None,
                    payload={"response": final_response[:200] + "..." if len(final_response) > 200 else final_response},
                    iteration=iteration,
                    timestamp=_now(),
                ))
                break

            # ── Execute each tool call ───────────────────────────────────────
            # First, append the assistant's tool-call message
            self.messages.append({
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
                "content": "",
            })

            tool_results = []
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                except json.JSONDecodeError:
                    args = {}

                self.tool_call_count += 1

                # Emit: tool call announced
                await self._emit(ReasoningEvent(
                    type="tool_call",
                    tool_name=tool_name,
                    payload={"arguments": args},
                    iteration=iteration,
                    timestamp=_now(),
                ))

                # Execute the tool
                result = execute_tool(tool_name, args)

                # Emit: tool result received
                await self._emit(ReasoningEvent(
                    type="tool_result",
                    tool_name=tool_name,
                    payload=result,
                    iteration=iteration,
                    timestamp=_now(),
                ))

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

            # Append all tool results to history
            self.messages.extend(tool_results)

        else:
            # Hit max iterations without a final answer
            logger.warning(f"Session {self.session_id} hit MAX_ITERATIONS={MAX_ITERATIONS}")
            final_response = (
                "I've processed your request but need additional time to resolve it. "
                "A support agent will follow up with you shortly."
            )
            await self._emit(ReasoningEvent(
                type="error",
                tool_name=None,
                payload={"error": "Max iterations reached", "iterations": MAX_ITERATIONS},
                iteration=iteration,
                timestamp=_now(),
            ))

        return final_response

    async def _emit(self, event: ReasoningEvent) -> None:
        await self.event_queue.put(event)


# ── Session registry ──────────────────────────────────────────────────────────

_sessions: dict[str, AgentSession] = {}


def get_or_create_session(session_id: str) -> AgentSession:
    if session_id not in _sessions:
        _sessions[session_id] = AgentSession(session_id)
    return _sessions[session_id]


def get_all_sessions() -> list[dict]:
    return [
        {
            "session_id": sid,
            "created_at": s.created_at,
            "message_count": len(s.messages),
            "iteration_count": s.iteration_count,
            "tool_call_count": s.tool_call_count,
        }
        for sid, s in _sessions.items()
    ]


def clear_session(session_id: str) -> bool:
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()
