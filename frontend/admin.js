/**
 * admin.js — Real-time admin dashboard
 *
 * Handles:
 *  - Fetching & displaying all agent sessions
 *  - Polling for new reasoning events per session
 *  - Rendering color-coded tool call cards
 *  - CRM customer list with search
 *  - Policy modal
 *  - Stats counters
 */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let activeSessionId = null;
let pollInterval = null;
let sessionEventCounts = {}; // sessionId → number of events rendered
let allEvents = []; // All events for active session
let stats = { sessions: 0, toolCalls: 0, approved: 0, denied: 0 };

// ── DOM refs ───────────────────────────────────────────────────────────────
const sessionsList     = document.getElementById('sessions-list');
const noSessionsMsg    = document.getElementById('no-sessions-msg');
const reasoningLog     = document.getElementById('reasoning-log');
const logEmptyState    = document.getElementById('log-empty-state');
const thinkingBar      = document.getElementById('thinking-bar');
const activeSessionLbl = document.getElementById('active-session-label');
const clearLogBtn      = document.getElementById('clear-log-btn');
const refreshBtn       = document.getElementById('refresh-sessions-btn');
const crmList          = document.getElementById('crm-list');
const crmSearchInput   = document.getElementById('crm-search-input');
const policyBtn        = document.getElementById('policy-btn');
const policyModal      = document.getElementById('policy-modal');
const closePolicyBtn   = document.getElementById('close-policy-btn');
const policyText       = document.getElementById('policy-text');
const sessionsDot      = document.getElementById('sessions-live-dot');

const statEls = {
  sessions:  document.getElementById('stat-sessions'),
  toolCalls: document.getElementById('stat-tool-calls'),
  customers: document.getElementById('stat-customers'),
  approved:  document.getElementById('stat-approved'),
  denied:    document.getElementById('stat-denied'),
};

// Tool metadata: icon, display name, colour class
const TOOL_META = {
  lookup_customer: {
    icon: '🔍',
    label: 'lookup_customer',
    desc: 'CRM Lookup',
  },
  get_order_details: {
    icon: '📦',
    label: 'get_order_details',
    desc: 'Order Details',
  },
  check_refund_eligibility: {
    icon: '⚖️',
    label: 'check_refund_eligibility',
    desc: 'Policy Check',
  },
  process_refund: {
    icon: '✅',
    label: 'process_refund',
    desc: 'Process Refund',
  },
  deny_refund: {
    icon: '❌',
    label: 'deny_refund',
    desc: 'Deny Refund',
  },
  escalate_to_human: {
    icon: '🔺',
    label: 'escalate_to_human',
    desc: 'Escalate',
  },
};

// ── Init ───────────────────────────────────────────────────────────────────
(async function init() {
  await loadSessions();
  await loadCRM();

  // Auto-refresh sessions every 5 seconds
  setInterval(loadSessions, 5000);

  refreshBtn.addEventListener('click', loadSessions);
  clearLogBtn.addEventListener('click', clearLog);
  crmSearchInput.addEventListener('input', filterCRM);
  policyBtn.addEventListener('click', openPolicy);
  closePolicyBtn.addEventListener('click', closePolicy);
  policyModal.addEventListener('click', e => {
    if (e.target === policyModal) closePolicy();
  });

  // Keyboard shortcut: Escape to close modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePolicy();
  });
})();

// ── Sessions ───────────────────────────────────────────────────────────────

async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    const sessions = data.sessions || [];

    stats.sessions = sessions.length;
    stats.toolCalls = sessions.reduce((s, sess) => s + (sess.tool_call_count || 0), 0);
    updateStats();

    renderSessions(sessions);

    // Flash the live indicator
    sessionsDot.style.opacity = sessions.length > 0 ? '1' : '0';
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

function renderSessions(sessions) {
  // Keep track of what's already rendered
  const existingIds = new Set(
    Array.from(sessionsList.querySelectorAll('.session-item')).map(el => el.dataset.sessionId)
  );

  if (sessions.length === 0) {
    sessionsList.innerHTML = '';
    sessionsList.appendChild(noSessionsMsg);
    return;
  }

  noSessionsMsg.remove();

  // Add new sessions
  sessions.forEach(sess => {
    if (existingIds.has(sess.session_id)) {
      // Update existing
      const el = sessionsList.querySelector(`[data-session-id="${sess.session_id}"]`);
      if (el) {
        el.querySelector('.session-meta').innerHTML = buildSessionMeta(sess);
      }
      return;
    }

    const item = document.createElement('div');
    item.className = 'session-item animate-in';
    item.setAttribute('role', 'listitem');
    item.dataset.sessionId = sess.session_id;
    item.innerHTML = `
      <div class="session-id-text">${sess.session_id}</div>
      <div class="session-meta">${buildSessionMeta(sess)}</div>
    `;
    item.addEventListener('click', () => selectSession(sess.session_id));
    sessionsList.prepend(item);
  });

  // Highlight active
  if (activeSessionId) {
    highlightSession(activeSessionId);
  }
}

function buildSessionMeta(sess) {
  const msgs = sess.message_count || 0;
  const tools = sess.tool_call_count || 0;
  const time = new Date(sess.created_at + 'Z').toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  return `
    <span class="session-meta-chip">${msgs} msg</span>
    <span class="session-meta-chip">${tools} tools</span>
    <span style="margin-left:auto;">${time}</span>
  `;
}

function selectSession(sessionId) {
  activeSessionId = sessionId;
  activeSessionLbl.textContent = sessionId.slice(0, 8) + '…';
  highlightSession(sessionId);

  // Clear and reload log
  clearLog(false);
  allEvents = [];
  sessionEventCounts[sessionId] = 0;

  startPolling(sessionId);
}

function highlightSession(sessionId) {
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.sessionId === sessionId);
  });
}

// ── Event polling ──────────────────────────────────────────────────────────
// We poll because SSE from admin is an alternative architecture;
// here we re-fetch the session list and detect new tool-call events
// by comparing message counts. For real-time, the chat page already
// has SSE — the admin shows aggregated history.

function startPolling(sessionId) {
  if (pollInterval) clearInterval(pollInterval);

  // Immediately fetch events
  fetchSessionEvents(sessionId);

  // Then poll every 2 seconds while this session is active
  pollInterval = setInterval(() => {
    if (activeSessionId === sessionId) {
      fetchSessionEvents(sessionId);
    } else {
      clearInterval(pollInterval);
    }
  }, 2000);
}

async function fetchSessionEvents(sessionId) {
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    const session = (data.sessions || []).find(s => s.session_id === sessionId);

    if (!session) return;

    // Check if tool_call_count changed — if so, show "agent working" indicator
    const prevToolCount = sessionEventCounts[sessionId] || 0;
    const currToolCount = session.tool_call_count || 0;

    if (currToolCount > prevToolCount) {
      sessionEventCounts[sessionId] = currToolCount;
      // We can't get individual events from the REST endpoint without the SSE stream,
      // so we simulate event cards based on the delta.
      // In practice the chat page drives the SSE; admin shows the aggregate view.
      showThinkingBar();
      stats.toolCalls = currToolCount;
      updateStats();
    }

    // Update session list
    renderSessions(data.sessions || []);
  } catch { /* silent */ }
}

// ── Reasoning log rendering ────────────────────────────────────────────────
// Events are pushed here from chat.js via a shared BroadcastChannel
// so the admin panel sees live events even when opened in a separate tab.

const bc = new BroadcastChannel('refundai_events');

bc.addEventListener('message', ({ data: event }) => {
  if (!event || !event.type) return;
  if (event.session_id && activeSessionId && event.session_id !== activeSessionId) return;

  hideLogEmpty();
  renderEventCard(event);
  hideThinkingBar();

  // Update stats from events
  if (event.type === 'tool_call') {
    stats.toolCalls++;
    if (event.tool_name === 'process_refund') stats.approved++;
    if (event.tool_name === 'deny_refund') stats.denied++;
    updateStats();
  }
});

function renderEventCard(event) {
  const card = document.createElement('div');

  // Build class names
  let typeClass = `event-${event.type}`;
  if (event.type === 'tool_call' || event.type === 'tool_result') {
    typeClass += ` ${event.tool_name || ''}`;
  }
  card.className = `event-card ${typeClass} animate-in`;

  const meta = event.tool_name ? TOOL_META[event.tool_name] : null;
  const icon = meta ? meta.icon : eventTypeIcon(event.type);
  const label = meta ? meta.desc : eventTypeLabel(event.type);

  card.innerHTML = `
    <div class="event-card-header">
      <div class="event-icon">${icon}</div>
      <div class="event-name">${label}</div>
      <div class="event-iter">iter ${event.iteration || 0} · ${formatTs(event.timestamp)}</div>
    </div>
    <div class="event-payload">${formatPayload(event)}</div>
  `;

  reasoningLog.appendChild(card);
  reasoningLog.scrollTop = reasoningLog.scrollHeight;
}

function formatPayload(event) {
  const p = event.payload || {};
  if (event.type === 'thinking') return p.message || '';
  if (event.type === 'final') return `✓ ${(p.response || '').slice(0, 120)}${(p.response || '').length > 120 ? '…' : ''}`;
  if (event.type === 'error') return `⚠ ${p.error || 'Unknown error'}`;
  if (event.type === 'tool_call') {
    return JSON.stringify(p.arguments || {}, null, 2);
  }
  if (event.type === 'tool_result') {
    // Show key fields only
    const keys = Object.keys(p).slice(0, 6);
    const filtered = {};
    keys.forEach(k => { filtered[k] = p[k]; });
    const str = JSON.stringify(filtered, null, 2);
    return str.length > 400 ? str.slice(0, 400) + '\n…' : str;
  }
  return JSON.stringify(p, null, 2);
}

function eventTypeIcon(type) {
  const icons = {
    thinking: '🧠',
    final: '✅',
    error: '⚠️',
    tool_result: '↩',
    ping: '·',
    heartbeat: '·',
  };
  return icons[type] || '·';
}

function eventTypeLabel(type) {
  const labels = {
    thinking: 'Agent Thinking',
    final: 'Final Response',
    error: 'Error',
    tool_result: 'Tool Result',
    ping: 'Ping',
    heartbeat: 'Heartbeat',
  };
  return labels[type] || type;
}

function formatTs(ts) {
  if (!ts) return '';
  try {
    return new Date(ts + 'Z').toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

function clearLog(showEmpty = true) {
  reasoningLog.innerHTML = '';
  if (showEmpty) {
    reasoningLog.appendChild(logEmptyState);
    activeSessionId = null;
    activeSessionLbl.textContent = '';
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  }
  if (pollInterval) clearInterval(pollInterval);
}

function hideLogEmpty() {
  if (logEmptyState.parentNode === reasoningLog) {
    reasoningLog.removeChild(logEmptyState);
  }
}

function showThinkingBar() { thinkingBar.classList.remove('hidden'); }
function hideThinkingBar() { thinkingBar.classList.add('hidden'); }

// ── CRM panel ──────────────────────────────────────────────────────────────

let allCustomers = [];

async function loadCRM() {
  try {
    const res = await fetch('/api/customers');
    const data = await res.json();
    allCustomers = data.customers || [];
    statEls.customers.textContent = allCustomers.length;
    renderCRM(allCustomers);
  } catch (err) {
    console.error('Failed to load CRM:', err);
  }
}

function renderCRM(customers) {
  crmList.innerHTML = '';
  customers.forEach(c => {
    const initials = c.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
    const hasFlags = c.account_flags?.length > 0;

    const row = document.createElement('div');
    row.className = 'crm-row';
    row.setAttribute('role', 'listitem');
    row.setAttribute('title', `${c.name} · ${c.email}`);
    row.innerHTML = `
      <div class="crm-avatar ${c.tier}">${initials}</div>
      <div class="crm-info">
        <div class="crm-name">
          ${escHtml(c.name)}
          ${hasFlags ? '<span class="flag-dot" title="Account flag" aria-label="Account has flags"></span>' : ''}
        </div>
        <div class="crm-email">${escHtml(c.email)}</div>
      </div>
      <div class="crm-badges">
        <span class="badge badge-${c.tier}">${c.tier}</span>
      </div>
    `;

    // Click → pre-fill chat window in new tab
    row.addEventListener('click', () => {
      window.open(`/?customer=${encodeURIComponent(c.email)}`, '_blank');
    });

    crmList.appendChild(row);
  });
}

function filterCRM() {
  const q = crmSearchInput.value.toLowerCase().trim();
  if (!q) {
    renderCRM(allCustomers);
    return;
  }
  const filtered = allCustomers.filter(c =>
    c.name.toLowerCase().includes(q) ||
    c.email.toLowerCase().includes(q) ||
    c.customer_id.toLowerCase().includes(q) ||
    c.tier.toLowerCase().includes(q)
  );
  renderCRM(filtered);
}

// ── Policy modal ───────────────────────────────────────────────────────────

async function openPolicy() {
  policyModal.classList.add('open');
  if (policyText.textContent === 'Loading…') {
    try {
      const res = await fetch('/api/policy');
      const data = await res.json();
      policyText.textContent = data.policy || 'Policy not available.';
    } catch {
      policyText.textContent = 'Failed to load policy.';
    }
  }
}

function closePolicy() {
  policyModal.classList.remove('open');
}

// ── Stats ──────────────────────────────────────────────────────────────────

function updateStats() {
  statEls.sessions.textContent = stats.sessions;
  statEls.toolCalls.textContent = stats.toolCalls;
  statEls.approved.textContent = stats.approved;
  statEls.denied.textContent = stats.denied;
}

// ── Utilities ──────────────────────────────────────────────────────────────

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
