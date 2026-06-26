# RefundAI — AI Customer Support Agent

A production-quality AI customer support agent that processes or denies e-commerce refunds using a live LLM agent loop with real-time reasoning transparency and voice capabilities.

---

## 1. The Challenge (Problem Statement)
E-commerce support teams handle large volumes of refund requests daily. These requests are governed by complex, multi-tiered company policies. Standard support bots are either too rigid to handle conversational nuances, or they are too unrestricted, leading to policy violations, hallucinations, and a lack of transaction validation. 

**RefundAI** solves this by enforcing a deterministic, multi-step validation loop:
1. Identifying the customer.
2. Checking the specific order.
3. Reviewing policy compliance via a strict rules engine.
4. Executing the correct transaction tool (`process_refund`, `deny_refund`, or `escalate_to_human`).

Team managers can audit and monitor the agent's step-by-step reasoning in real time via a glassmorphic admin dashboard.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Browser                              │
│  ┌─────────────────┐      ┌──────────────────────────────┐  │
│  │   Chat UI        │      │   Admin Dashboard            │  │
│  │  (index.html)    │ SSE  │   (admin.html)               │  │
│  │                  │──────│                              │  │
│  │  • Send message  │ BC   │  • Tool call cards           │  │
│  │  • 🎤 Voice input│──────│  • Session browser           │  │
│  │  • TTS playback  │      │  • CRM viewer                │  │
│  └─────────────────┘      └──────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
                      │ HTTP / SSE
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                            │
│                                                               │
│  ┌─────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │  Agent   │  │   Tool Engine    │  │  Voice Pipeline  │   │
│  │  Loop    │  │                  │  │                  │   │
│  │          │→ │ lookup_customer   │  │ Groq Whisper STT │   │
│  │ Cohere   │  │ get_order_details │  │ Web Speech TTS   │   │
│  │ Command  │  │ check_eligibility │  └──────────────────┘   │
│  │  R+      │  │ process_refund    │                          │
│  │          │  │ deny_refund       │  ┌──────────────────┐   │
│  │ Tool use │  │ escalate_human    │  │  Mock CRM (JSON) │   │
│  └─────────┘  └──────────────────┘  │  15 customers    │   │
│                                       │  Refund policy   │   │
│                                       └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
          │                    │
    Cohere API           Groq API
    (LLM + tools)        (Whisper STT)
```

### Key Technical Patterns
1. **Raw Multi-Turn Function Calling**: Built using direct `cohere.ClientV2` tool execution loops without high-level framework wrappers. This guarantees lightweight, traceable execution.
2. **Server-Sent Events (SSE)**: The FastAPI server streams real-time logs (`thinking`, `tool_call`, `tool_result`, `final`) to the browser using an asyncio event queue.
3. **Cross-Tab Synchronization**: The browser's native `BroadcastChannel` API allows the Customer Chat UI to sync reasoning events to the Admin Dashboard instantly in real time.
4. **Deterministic Loop Failsafe**: A Python-level check intercepts the loop if the model outputs conversational text after the eligibility check instead of calling an action tool. It programmatically executes the correct tool (`process_refund`, `deny_refund`, or `escalate_to_human`), updates the ledger database, and lets the LLM summarize the outcome.
5. **Voice Pipeline**: Supports Speech-to-Text (Groq Whisper Large v3 Turbo) and Text-to-Speech (native Web Speech API).

---

## 3. Features & Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Cohere Command R+ (`command-r-plus-08-2024`) |
| **Backend** | FastAPI + uvicorn |
| **STT** | Groq Whisper Large v3 Turbo |
| **TTS** | Browser Web Speech API |
| **Frontend** | Vanilla HTML / CSS / JS |
| **Database** | In-memory JSON (mock CRM ledger) |

- **6 Agent Tools**: `lookup_customer`, `get_order_details`, `check_refund_eligibility`, `process_refund`, `deny_refund`, `escalate_to_human`.
- **15 Mock CRM Profiles**: Profiles testing edge cases (suspected fraud, expired windows, gold tier return windows, digital products, active subscriptions, and undelivered orders).
- **Admin Dashboard**: Real-time stats (tool calls, approvals, denials), interactive CRM search, session selector, and live reasoning log trace.

---

## 4. Quick Start

### 1. Set up Python Environment
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in API keys:
```
COHERE_API_KEY=your-cohere-key-here
GROQ_API_KEY=your-groq-key-here
```
*   **Cohere**: https://dashboard.cohere.com/api-keys
*   **Groq**: https://console.groq.com

### 3. Run the Server
```bash
python -m uvicorn backend.main:app --reload --port 8000
```
- **Customer Chat**: http://localhost:8000
- **Admin Dashboard**: http://localhost:8000/admin

---

## 5. Refund Policy Rules (Summary)

| Rule | Detail |
|------|--------|
| **Bronze Tier Return Window** | 30 days |
| **Silver Tier Return Window** | 35 days |
| **Gold Tier Return Window** | 45 days |
| **Auto-Approve Ceiling** | ≤ $500.00 |
| **Manual Review Escalation** | > $500.00 |
| **Max Refunds per 12-Months** | 2 |
| **Digital Goods** | Non-refundable once access granted |
| **Subscription Cancellation** | 7-day cancel window |
| **Damaged Items** | Always eligible (overrides window) |
| **Account Flags (Fraud/Suspension)** | Blocked completely |
| **Undelivered Packages** | Require cancellation, not refund |

---

## 6. Test Scenarios

| Test Scenario | Customer Email | Order ID | Expected Outcome |
|---|---|---|---|
| **Standard refund** | `marcus.webb@email.com` | `ORD-9821` | ✅ Approved (within 30-day window) |
| **Expired window** | `diana.forsythe@email.com` | `ORD-4450` | ❌ Denied (38 days, Bronze 30-day limit) |
| **Fraud flag** | `ethan.blackwood@tempmail.xyz` | `ORD-7731` | ❌ Denied (account flagged) |
| **Digital goods** | `priya.nair@gmail.com` | `ORD-3302` | ❌ Denied (non-refundable digital good) |
| **Damaged item** | `leo.fitz@outlook.com` | `ORD-6610` | ✅ Approved (damage override) |
| **Gold tier edge** | `sophia.hartmann@company.de` | `ORD-1144` | ✅ Approved (40 days, Gold 45-day window) |
| **Double refund** | `cmendez@protonmail.com` | `ORD-2250` | ❌ Denied (already refunded) |
| **Over limit** | `amara.osei@yahoo.com` | `ORD-8890` | ❌ Denied (2 refunds in 12 months) |
| **High-value** | `j.whitmore@enterprise.com` | `ORD-5577` | 🔺 Escalated ($1,249 > $500 limit) |
| **Subscription ok** | `nina.petrova@mail.ru` | `ORD-4433` | ✅ Approved (4 days, within 7-day window) |
| **Subscription bad** | `tyler.nguyen@gmail.com` | `ORD-3355` | ❌ Denied (14 days, past 7-day window) |

---

## 7. Loom Video Walkthrough Script (7–10 Minutes)

Use this outline as a checklist when recording your demo video:

*   **0:00 - 1:00 (Introduction)**: Show your screen at the chat interface (`http://localhost:8000/`) and explain the project stack (FastAPI, Cohere Command R+, vanilla JS frontend, Web Speech TTS, Groq Whisper STT).
*   **1:00 - 2:15 (Happy Path Demo)**: Request a refund for Marcus Webb (`marcus.webb@email.com` / `ORD-9821`). Display the admin console side-by-side to show the real-time reasoning events: `lookup_customer` $\rightarrow$ `get_order_details` $\rightarrow$ `check_refund_eligibility` $\rightarrow$ `process_refund`.
*   **2:15 - 3:00 (Policy Hold-The-Line)**: Try a return window violation for Diana Forsythe (`diana.forsythe@email.com` / `ORD-4450`). Show the eligibility check failing (38 days delivery age > 30-day Bronze window) and the `deny_refund` tool executing.
*   **3:00 - 4:00 (Voice Demonstration)**: Click the mic icon, record a request for Nina Petrova (`ORD-4433`), showing Whisper STT transcribing the file and native TTS reading the refund confirmation aloud.
*   **4:00 - 5:30 (Admin Audit)**: Maximize `http://localhost:8000/admin`. Showcase the session browser, stats counters (approvals vs. denials), interactive customer list search, and BroadcastChannel real-time sync.
*   **5:30 - 8:30 (Code Walkthrough)**: Walk through `backend/agent.py` to showcase the loop logic and the custom Python-level tool calling failsafe. Review the tools in `backend/tools.py` and the policies in `backend/policy.py`.
*   **8:30 - 9:00 (Outro)**: Summarize key benefits (reproducible, reliable policy enforcement, auditability) and conclude.
