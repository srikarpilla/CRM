/**
 * chat.js — Customer chat interface
 *
 * Handles:
 *  - Message send/receive via SSE streaming
 *  - Typing indicator while agent is working
 *  - Voice recording → Groq Whisper STT → agent
 *  - Browser Web Speech API for TTS (reading agent responses aloud)
 *  - Auto-resize textarea
 *  - Outcome detection (refund approved/denied/escalated) for visual chips
 */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let sessionId = localStorage.getItem('refundai_session_id') || null;
let isAgentTyping = false;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let ttsEnabled = true;

// BroadcastChannel — sends reasoning events to admin panel (separate tab)
const bc = new BroadcastChannel('refundai_events');

// Outcome tracking for visual summary chips
const outcomes = { approved: 0, denied: 0, escalated: 0 };

// ── DOM refs ───────────────────────────────────────────────────────────────
const messagesEl     = document.getElementById('messages');
const welcomeState   = document.getElementById('welcome-state');
const messageInput   = document.getElementById('message-input');
const sendBtn        = document.getElementById('send-btn');
const micBtn         = document.getElementById('mic-btn');
const newChatBtn     = document.getElementById('new-chat-btn');
const orderIdInput   = document.getElementById('order-id-input');
const customerInfo   = document.getElementById('customer-info');
const sessionIndicator = document.getElementById('session-indicator');
const voiceToast     = document.getElementById('voice-toast');
const voiceToastText = document.getElementById('voice-toast-text');

// ── Init ───────────────────────────────────────────────────────────────────
(async function init() {
  if (!sessionId) {
    sessionId = await createNewSession();
  }
  updateSessionIndicator();

  // Show existing messages if any (page refresh)
  const stored = loadMessages();
  if (stored.length > 0) {
    hideWelcome();
    stored.forEach(m => renderMessage(m.role, m.content, m.outcome, false));
    scrollToBottom();
  }

  messageInput.addEventListener('input', handleInputChange);
  messageInput.addEventListener('keydown', handleKeydown);
  sendBtn.addEventListener('click', sendMessage);
  micBtn.addEventListener('click', toggleRecording);
  newChatBtn.addEventListener('click', startNewChat);
  orderIdInput.addEventListener('input', handleOrderIdInput);

  // Quick prompts
  document.querySelectorAll('.quick-prompt').forEach(btn => {
    btn.addEventListener('click', () => {
      messageInput.value = btn.dataset.prompt;
      handleInputChange();
      messageInput.focus();
    });
  });
})();

// ── Session management ─────────────────────────────────────────────────────

async function createNewSession() {
  try {
    const res = await fetch('/api/sessions/new', { method: 'POST' });
    const data = await res.json();
    const sid = data.session_id;
    localStorage.setItem('refundai_session_id', sid);
    return sid;
  } catch {
    // Fallback: generate locally
    const sid = crypto.randomUUID();
    localStorage.setItem('refundai_session_id', sid);
    return sid;
  }
}

function updateSessionIndicator() {
  if (sessionId) {
    sessionIndicator.textContent = `Session: ${sessionId.slice(0, 8)}…`;
  }
}

async function startNewChat() {
  sessionId = await createNewSession();
  updateSessionIndicator();
  localStorage.removeItem('refundai_messages');

  // Clear UI
  messagesEl.innerHTML = '';
  messagesEl.appendChild(welcomeState);
  welcomeState.style.display = '';
  customerInfo.innerHTML = '';
  orderIdInput.value = '';
  messageInput.value = '';
  handleInputChange();

  outcomes.approved = 0;
  outcomes.denied = 0;
  outcomes.escalated = 0;
}

// ── Message send ───────────────────────────────────────────────────────────

async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text || isAgentTyping) return;

  hideWelcome();
  renderMessage('user', text);
  persistMessage('user', text);

  messageInput.value = '';
  handleInputChange();

  await runAgent(text);
}

async function runAgent(userMessage) {
  if (isAgentTyping) return;
  isAgentTyping = true;
  sendBtn.disabled = true;

  const typingMsg = showTypingIndicator();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMessage,
        session_id: sessionId,
      }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResponse = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // Keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;

        let event;
        try { event = JSON.parse(raw); } catch { continue; }

        // Broadcast every event to the admin panel
        bc.postMessage({ ...event, session_id: sessionId });

        if (event.type === 'complete') {
          finalResponse = event.response || '';
        }
        // We don't render intermediate events in the chat — only the final answer
      }
    }

    removeElement(typingMsg);

    if (finalResponse) {
      const outcome = detectOutcome(finalResponse);
      renderMessage('agent', finalResponse, outcome);
      persistMessage('agent', finalResponse, outcome);

      // TTS — read the response aloud if enabled
      if (ttsEnabled) {
        speakText(finalResponse);
      }

      // Update outcome counters
      if (outcome) {
        outcomes[outcome]++;
        showOutcomeToast(outcome);
      }
    }
  } catch (err) {
    removeElement(typingMsg);
    const msg = 'Sorry, I encountered an error. Please try again.';
    renderMessage('agent', msg);
    console.error('Agent error:', err);
  } finally {
    isAgentTyping = false;
    sendBtn.disabled = messageInput.value.trim().length === 0;
  }
}

// ── Outcome detection ──────────────────────────────────────────────────────

function detectOutcome(text) {
  const lower = text.toLowerCase();
  // Look for strong signals
  if (lower.includes('refund has been') && (lower.includes('processed') || lower.includes('initiated') || lower.includes('approved'))) {
    return 'approved';
  }
  if (lower.includes('successfully initiated') || lower.includes('refund of $') || lower.includes('funds will arrive')) {
    return 'approved';
  }
  if (lower.includes('escalated') || lower.includes('senior agent') || lower.includes('manual review') || lower.includes('ticket:')) {
    return 'escalated';
  }
  if (
    lower.includes('unable to process') ||
    lower.includes('not eligible') ||
    lower.includes('cannot process') ||
    lower.includes('denied') ||
    lower.includes('return window has') ||
    lower.includes('non-refundable') ||
    lower.includes('policy') && lower.includes('deny')
  ) {
    return 'denied';
  }
  return null;
}

// ── Render helpers ─────────────────────────────────────────────────────────

function renderMessage(role, content, outcome = null, animate = true) {
  const msg = document.createElement('div');
  msg.className = `message ${role}${animate ? ' animate-in' : ''}`;

  const avatar = document.createElement('div');
  avatar.className = `msg-avatar ${role}`;
  avatar.textContent = role === 'agent' ? '🤖' : '👤';
  avatar.setAttribute('aria-hidden', 'true');

  const body = document.createElement('div');
  body.className = 'msg-body';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.innerHTML = formatMessage(content);

  const time = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = formatTime(new Date());

  body.appendChild(bubble);

  // Outcome chip
  if (outcome) {
    const chip = document.createElement('div');
    chip.className = `outcome-chip ${outcome}`;
    const icons = { approved: '✅', denied: '❌', escalated: '🔺' };
    const labels = {
      approved: 'Refund Approved',
      denied: 'Refund Denied',
      escalated: 'Escalated to Human',
    };
    chip.innerHTML = `<span>${icons[outcome]}</span><span>${labels[outcome]}</span>`;
    body.appendChild(chip);
  }

  body.appendChild(time);
  msg.appendChild(avatar);
  msg.appendChild(body);

  // Remove welcome state on first real message
  if (role === 'user') hideWelcome();

  messagesEl.appendChild(msg);
  scrollToBottom();
  return msg;
}

function formatMessage(text) {
  // Escape HTML, then convert markdown-like formatting
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  return escaped
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code style="font-family:var(--font-mono);background:rgba(255,255,255,0.08);padding:1px 5px;border-radius:3px;font-size:0.875em;">$1</code>')
    // Line breaks
    .replace(/\n/g, '<br>');
}

function formatTime(date) {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function showTypingIndicator() {
  const msg = document.createElement('div');
  msg.className = 'message agent typing-message animate-in';
  msg.id = 'typing-indicator';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar agent';
  avatar.textContent = '🤖';
  avatar.setAttribute('aria-hidden', 'true');

  const body = document.createElement('div');
  body.className = 'msg-body';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.setAttribute('aria-label', 'Agent is typing');

  const dots = document.createElement('div');
  dots.className = 'typing-dots';
  dots.setAttribute('aria-hidden', 'true');
  dots.innerHTML = '<span></span><span></span><span></span>';
  bubble.appendChild(dots);
  body.appendChild(bubble);
  msg.appendChild(avatar);
  msg.appendChild(body);

  messagesEl.appendChild(msg);
  scrollToBottom();
  return msg;
}

function hideWelcome() {
  if (welcomeState && welcomeState.parentNode === messagesEl) {
    messagesEl.removeChild(welcomeState);
  }
}

function showOutcomeToast(outcome) {
  // Brief flash on the agent avatar / nothing intrusive needed — chip does the job
}

function removeElement(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });
}

// ── Input handling ─────────────────────────────────────────────────────────

function handleInputChange() {
  const val = messageInput.value;
  sendBtn.disabled = val.trim().length === 0 || isAgentTyping;

  // Auto-resize
  messageInput.style.height = 'auto';
  messageInput.style.height = Math.min(messageInput.scrollHeight, 140) + 'px';
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function handleOrderIdInput() {
  const val = orderIdInput.value.toUpperCase().trim();
  orderIdInput.value = val;
  // Auto-fill message hint if order ID looks complete
  if (/^ORD-\w{4}$/.test(val)) {
    orderIdInput.style.borderColor = 'var(--color-success)';
    orderIdInput.style.boxShadow = '0 0 0 3px rgba(16,185,129,0.15)';
  } else {
    orderIdInput.style.borderColor = '';
    orderIdInput.style.boxShadow = '';
  }
}

// ── TTS — Web Speech API ───────────────────────────────────────────────────

function speakText(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel(); // Cancel any ongoing speech

  // Strip markdown-like syntax for cleaner TTS
  const clean = text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`[^`]+`/g, '')
    .replace(/\n/g, ' ')
    .substring(0, 500); // Cap at 500 chars for TTS

  const utter = new SpeechSynthesisUtterance(clean);
  utter.rate = 1.05;
  utter.pitch = 1.0;
  utter.volume = 0.9;

  // Prefer a natural-sounding voice
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(v =>
    v.name.includes('Google') || v.name.includes('Natural') || v.name.includes('Samantha')
  );
  if (preferred) utter.voice = preferred;

  window.speechSynthesis.speak(utter);
}

// Voices load async in some browsers
window.speechSynthesis?.addEventListener('voiceschanged', () => {});

// ── Voice recording — Groq Whisper STT ────────────────────────────────────

async function toggleRecording() {
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    alert('Your browser does not support microphone access.');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    mediaRecorder = new MediaRecorder(stream, { mimeType });
    audioChunks = [];

    mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      await processVoiceInput();
    };

    mediaRecorder.start(100); // 100ms chunks
    isRecording = true;
    micBtn.classList.add('recording');
    micBtn.title = 'Stop recording';
    showVoiceToast('Recording… tap mic to stop');
  } catch (err) {
    console.error('Microphone error:', err);
    alert('Could not access microphone. Please check permissions.');
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.classList.remove('recording');
    micBtn.title = 'Record voice message';
    showVoiceToast('Processing audio…');
  }
}

async function processVoiceInput() {
  if (audioChunks.length === 0) {
    hideVoiceToast();
    return;
  }

  const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
  audioChunks = [];

  if (audioBlob.size < 1000) {
    hideVoiceToast();
    showVoiceToastError('Recording too short. Please try again.');
    return;
  }

  showVoiceToast('Transcribing…');

  const formData = new FormData();
  formData.append('audio', audioBlob, 'voice.webm');
  formData.append('session_id', sessionId || '');

  hideWelcome();
  const typingMsg = showTypingIndicator();
  isAgentTyping = true;
  sendBtn.disabled = true;

  try {
    const response = await fetch('/api/voice', {
      method: 'POST',
      body: formData,
    });

    // 503 means Groq key not set — show helpful message
    if (response.status === 503) {
      removeElement(typingMsg);
      document.getElementById('typing-indicator')?.remove();
      hideVoiceToast();
      isAgentTyping = false;
      sendBtn.disabled = false;
      showVoiceToastError('Voice requires a Groq API key. Set GROQ_API_KEY in .env');
      return;
    }

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let transcript = '';
    let finalResponse = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;

        let event;
        try { event = JSON.parse(raw); } catch { continue; }

        if (event.type === 'transcript') {
          transcript = event.text;
          removeElement(typingMsg);
          renderMessage('user', `🎤 ${transcript}`);
          persistMessage('user', `🎤 ${transcript}`);
          showVoiceToast(`Heard: "${transcript.slice(0, 40)}…"`);
          const typingMsg2 = showTypingIndicator();
          // Re-reference for cleanup
          typingMsg.id = '__old';
          typingMsg2.id = 'typing-indicator';
        }
        if (event.type === 'complete') {
          finalResponse = event.response || '';
          sessionId = event.session_id || sessionId;
        }
      }
    }

    // Clean up any remaining typing indicator
    document.getElementById('typing-indicator')?.remove();

    hideVoiceToast();

    if (finalResponse) {
      const outcome = detectOutcome(finalResponse);
      renderMessage('agent', finalResponse, outcome);
      persistMessage('agent', finalResponse, outcome);
      if (ttsEnabled) speakText(finalResponse);
    }
  } catch (err) {
    removeElement(typingMsg);
    document.getElementById('typing-indicator')?.remove();
    renderMessage('agent', 'Sorry, I had trouble processing your voice message. Please try again or type your request.');
    console.error('Voice error:', err);
    hideVoiceToast();
  } finally {
    isAgentTyping = false;
    sendBtn.disabled = messageInput.value.trim().length === 0;
  }
}

// ── Voice toast helpers ────────────────────────────────────────────────────

function showVoiceToast(text) {
  voiceToastText.textContent = text;
  voiceToast.classList.remove('hidden');
}

function showVoiceToastError(text) {
  voiceToast.style.background = 'rgba(239,68,68,0.15)';
  showVoiceToast(text);
  setTimeout(hideVoiceToast, 3000);
}

function hideVoiceToast() {
  voiceToast.classList.add('hidden');
}

// ── Persistence ────────────────────────────────────────────────────────────

function persistMessage(role, content, outcome = null) {
  try {
    const stored = loadMessages();
    stored.push({ role, content, outcome, ts: Date.now() });
    // Cap at 50 messages to avoid localStorage bloat
    const capped = stored.slice(-50);
    localStorage.setItem('refundai_messages', JSON.stringify(capped));
  } catch { /* localStorage full */ }
}

function loadMessages() {
  try {
    return JSON.parse(localStorage.getItem('refundai_messages') || '[]');
  } catch {
    return [];
  }
}
