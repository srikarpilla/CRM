# Loom Video Walkthrough Script & Architecture Guide

This document contains a complete architectural overview of **RefundAI** and a detailed, minute-by-minute script for your 7–10 minute Loom video submission.

---

## 1. Project Code Architecture

Here is the structural breakdown of the repository and the communication flows:

```
d:\CRM\
├── backend/
│   ├── main.py        # FastAPI server, endpoints, SSE streams, audio uploading
│   ├── agent.py       # Multi-turn Cohere ClientV2 agent loop with tool-choice failsafe
│   ├── tools.py       # 6 tool schemas (Cohere format) and executor functions
│   ├── crm_data.py    # Mock CRM DB with 15 specialized test customer profiles
│   ├── policy.py      # Standardized company refund policy (single source of truth)
│   └── voice.py       # Audio transcription integration via Groq Whisper Large v3 Turbo
└── frontend/
    ├── index.html     # Customer support chat UI (styled with glassmorphism CSS)
    ├── admin.html     # Admin reasoning trace & dashboard UI
    ├── style.css      # Core premium design system, variables, layouts, and animations
    ├── chat.js        # SSE consumer, microphone/audio recorder, browser Web Speech TTS
    └── admin.js       # Real-time event aggregator (via BroadcastChannel) & CRM list
```

### Key Technical Patterns
1. **Raw Function Calling (No Abstraction Frameworks)**: The agent loop in `backend/agent.py` uses direct Cohere ClientV2 function calling in a while loop. This makes reasoning traces completely transparent, lightweight, and easy to debug.
2. **Server-Sent Events (SSE) Streaming**: As the agent reasons, it puts `ReasoningEvent` objects (`thinking`, `tool_call`, `tool_result`, `final`, `error`) into an asyncio queue. `backend/main.py` streams these events to the browser in real time.
3. **Cross-Tab Synchronization (BroadcastChannel)**: The customer chat UI (`index.html`) listens to the SSE stream and broadcasts events locally via the browser's `BroadcastChannel` API. The Admin Dashboard (`admin.html`) listens to this channel, instantly displaying reasoning logs in real time even when opened in a separate window.
4. **Deterministic Failsafe Lifecycle**: A Python-level failsafe catches situations where the LLM tries to complete a message conversationally without executing the appropriate refund action. It dynamically runs the necessary tool, writes the result to history, and forces the next turn to produce the final user response.
5. **Speech Integration**: Fully working Speech-to-Text (STT) powered by Groq Whisper, and Text-to-Speech (TTS) powered by the browser's native Web Speech API.

---

## 2. Loom Video Script (7–10 Minutes)

### Outline & Timing Plan
*   **0:00 - 1:00**: Intro & Application Overview
*   **1:00 - 3:00**: Live Customer Chat Demo (Happy Path & Policy Hold-The-Line)
*   **3:00 - 4:00**: Voice Interaction Demo (STT/TTS)
*   **4:00 - 5:30**: Admin Dashboard & Real-Time Reasoning logs
*   **5:30 - 8:30**: Code Tour (Architecture, Loops, Tools, and Failsafes)
*   **8:30 - 9:00**: Outro & Submission Summary

---

### Step-by-Step Script

#### [0:00 - 1:00] Part 1: Introduction
*   **Visual**: Face on camera or showing the Customer Chat UI (`http://localhost:8000/`) and Admin Panel side-by-side.
*   **What to speak**:
    > "Hi everyone, welcome to the walkthrough of RefundAI. This is an AI-powered customer support agent built to process or deny e-commerce refunds by evaluating a strict company policy in real time. The stack is built on FastAPI on the backend, a raw Cohere Command R+ agent loop for tool calling, and a modern, glassmorphic vanilla HTML/CSS/JS frontend. Let's start with a live demo."

#### [1:00 - 2:15] Part 2: Live Demo — Happy Path
*   **Visual**: Switch to Customer Chat UI. Click the quick prompt button: *"I want to refund ORD-9821"* or write *"Hello, I would like to request a refund for order ORD-9821. My email is marcus.webb@email.com"*. Press Send.
*   **Visual**: Show the chat typing indicator. Move your other tab (Admin Panel) next to it to show the logs printing: `lookup_customer`, then `get_order_details`, then `check_refund_eligibility`, then `process_refund`, and finally the response.
*   **What to speak**:
    > "Here, we have a standard happy-path customer, Marcus Webb. When he asks for a refund, the agent follows a strict sequential lifecycle: first, it identifies the customer, retrieves his order details, evaluates his compliance against our refund rules, and processes the refund. You can see the refund reference REF-XXXX is generated, and the database status changes to refunded. In the admin trace panel on the right, you can see all of these tool calls and results streaming in real time."

#### [2:15 - 3:00] Part 3: Live Demo — Edge Case / Policy Violation ("Holding the line")
*   **Visual**: Switch back to Chat. Click **New Chat** or just type a new message: *"Hi, please refund order ORD-4450. My email is diana.forsythe@email.com"*.
*   **Visual**: Watch the admin panel trace the calls. It should run `lookup_customer`, `get_order_details`, `check_refund_eligibility`, and then `deny_refund`. The response shows a polite denial with reference `DEN-XXXX`.
*   **What to speak**:
    > "Now let's look at an edge case where the agent must 'hold the line'. Diana Forsythe is requesting a refund for order ORD-4450. The agent runs the eligibility check and finds that the order was delivered 38 days ago. Since Diana is a Bronze tier customer, she is subject to a strict 30-day return window. The eligibility engine returns a denied verdict, and the agent executes a `deny_refund` tool call, quoting Policy Section 1 to Diana empathetically but firmly."

#### [3:00 - 4:00] Part 4: Voice Pipeline Demonstration
*   **Visual**: Customer Chat UI. Click the **Microphone** icon. Speak clearly into it: *"Hello, I want to cancel and refund my subscription order ORD-4433. My email is nina.petrova@mail.ru"*. Click the mic again to stop.
*   **Visual**: Wait for transcription. The transcript *"Heard: ..."* toast appears, the text is typed in user chat automatically, and the bot begins typing and talks back using synthesized browser speech.
*   **What to speak**:
    > "I've also integrated a voice pipeline. When I click the mic button, the frontend records audio, uploads it to our FastAPI backend, and transcribes it using Groq's Whisper Large v3 Turbo. The transcribed text is then piped directly into the agent loop. Once the agent loop completes, the browser's native Web Speech API reads the final refund confirmation aloud to the customer."

#### [4:00 - 5:30] Part 5: Admin Panel & Reasoning Logs
*   **Visual**: Maximize the Admin Dashboard (`http://localhost:8000/admin`).
*   **Visual**: Show the Session list, Stats counters (Active Sessions, Tool Calls, Approved, Denied), CRM Database list (15 profiles), and search search bar (search for "Priya" or "Gold").
*   **What to speak**:
    > "Let's take a closer look at the Admin Dashboard. On the left side, we have an active session browser showing the list of chats. In the center, we show the real-time Reasoning Trace, containing color-coded cards for each tool call and tool result. On the right, we display the CRM Database representing all 15 customer profiles. Clicking any customer profile automatically pre-fills a chat session. The dashboard syncs instantly across windows using a local BroadcastChannel, allowing support managers to audit agent logic live."

#### [5:30 - 7:15] Part 6: Code Tour — Back-end Loop & Failsafe
*   **Visual**: Open VS Code or showing `backend/agent.py`. Highlight the `AgentSession.run` method.
*   **What to speak**:
    > "Moving on to the code tour, here is `backend/agent.py`. Unlike complex wrappers like LangGraph or CrewAI, we are using a lightweight, raw function-calling loop. We load Cohere's ClientV2, construct the messages history starting with our system instructions, and run a standard while loop.
    >
    > One key production pattern we implemented is this Python-level failsafe. LLMs are sometimes prone to explaining the result textually without issuing the final action tool call. If the model exits the loop without calling the action tool after `check_refund_eligibility` has run, our backend intercepts it, programmatically invokes the correct tool (`process_refund`, `deny_refund`, or `escalate_to_human`), and appends the result. This ensures the ledger database is updated correctly."

#### [7:15 - 8:30] Part 7: Tools & Policy Engine
*   **Visual**: Switch to `backend/tools.py` and `backend/policy.py`.
*   **What to speak**:
    > "In `backend/tools.py`, we define the schemas for our 6 tools: customer lookup, order details, eligibility check, process refund, deny refund, and escalation. The policy engine itself resides in `backend/policy.py`, which is the single source of truth defining tier-based return windows (Bronze 30, Silver 35, Gold 45 days), the $500 manual review threshold, and rules for subscriptions or digital goods. For example, during testing, we found a profile ORD-3302 (Priya Nair) requesting a refund on a software license. The engine successfully caught this as a digital good and invoked a denial."

#### [8:30 - 9:00] Part 8: Outro
*   **Visual**: Return to the admin dashboard or face cam.
*   **What to speak**:
    > "That concludes the walkthrough of RefundAI. The app delivers transparent, robust, and fast policy enforcement. The public repository link, full automated test scripts, and README configuration are included in the submission links. Thank you for watching!"
