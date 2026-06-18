/* Vacation Planner — frontend */

const $ = id => document.getElementById(id);

let currentThreadId = null;
let currentPlan = null;

// ── Auth ──────────────────────────────────────────────────────────────────────

async function checkAuth() {
  const res = await fetch('/api/auth/status');
  const { authenticated } = await res.json();
  $('auth-label').textContent = authenticated ? '✓ Google Calendar connected' : 'Google Calendar not connected';
  $('auth-btn').classList.toggle('hidden', authenticated);
  $('plan-btn').disabled = !authenticated;
  $('auth-warning').classList.toggle('hidden', authenticated);
}

// ── Plan submission ───────────────────────────────────────────────────────────

$('plan-btn').addEventListener('click', async () => {
  const prompt = $('prompt-input').value.trim();
  if (!prompt) return;
  const authRes = await fetch('/api/auth/status');
  const { authenticated } = await authRes.json();
  if (!authenticated) {
    showToast('Please connect your Google Calendar first!', true);
    return;
  }
  startPlanStream(prompt);
});

function startPlanStream(prompt) {
  resetUI();
  $('progress-section').classList.remove('hidden');
  $('plan-btn').disabled = true;

  fetchSSE('/api/plan', { prompt }, handlePlanEvent, () => {
    $('plan-btn').disabled = false;
  });
}

// ── Approve / Revise ──────────────────────────────────────────────────────────

$('approve-btn').addEventListener('click', () => {
  sendDecision('approve');
});

$('revise-btn').addEventListener('click', () => {
  $('revise-section').classList.remove('hidden');
});

$('submit-revision-btn').addEventListener('click', () => {
  const feedback = $('feedback-input').value.trim();
  if (!feedback) return;
  sendDecision('revise', feedback);
});

function sendDecision(decision, feedback = null) {
  $('itinerary-section').classList.add('hidden');
  $('progress-section').classList.remove('hidden');
  clearProgress();

  const body = { thread_id: currentThreadId, decision, feedback };

  fetchSSE('/api/approve', body, handlePlanEvent, () => {
    $('plan-btn').disabled = false;
  });
}

// ── SSE helper ────────────────────────────────────────────────────────────────

function fetchSSE(url, body, onEvent, onDone) {
  // Use fetch + ReadableStream for POST SSE
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async res => {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE lines
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete last line

      let eventName = 'message';
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          const data = line.slice(5).trim();
          onEvent(eventName, data);
          eventName = 'message';
        }
      }
    }
    onDone();
  }).catch(err => {
    showToast('Connection error: ' + err.message, true);
    onDone();
  });
}

// ── Event handlers ────────────────────────────────────────────────────────────

function handlePlanEvent(eventName, data) {
  if (eventName === 'thread') {
    currentThreadId = data;
  } else if (eventName === 'progress') {
    const { tool } = JSON.parse(data);
    addProgressTick(tool);
  } else if (eventName === 'plan') {
    currentPlan = JSON.parse(data);
    renderItinerary(currentPlan);
  } else if (eventName === 'done') {
    const { event_count } = JSON.parse(data);
    showToast(`Added ${event_count} events to Google Calendar!`);
    $('action-bar').classList.add('hidden');
  } else if (eventName === 'error') {
    const { message } = JSON.parse(data);
    showToast('Error: ' + message, true);
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function resetUI() {
  currentThreadId = null;
  currentPlan = null;
  clearProgress();
  $('itinerary-section').classList.add('hidden');
  $('revise-section').classList.add('hidden');
  $('action-bar').classList.remove('hidden');
  $('feedback-input').value = '';
}

function clearProgress() {
  $('progress-list').innerHTML = '';
  seenTools.clear();
}

const seenTools = new Set();

function addProgressTick(toolName) {
  // Mark previous item as done
  const list = $('progress-list');
  const last = list.querySelector('li:not(.done)');
  if (last) last.classList.add('done');

  if (seenTools.has(toolName)) return;
  seenTools.add(toolName);

  const li = document.createElement('li');
  li.textContent = toolName;
  list.appendChild(li);
}

const TYPE_ICON = {
  hotel: '🏨',
  restaurant: '🍽',
  attraction: '🗺',
  transport: '✈',
};

function renderItinerary(plan) {
  $('itinerary-section').classList.remove('hidden');
  $('itinerary-title').textContent =
    `${plan.trip_title} · ${plan.start_date} → ${plan.end_date}`;

  const body = $('itinerary-body');
  body.innerHTML = '';

  for (const day of (plan.days || [])) {
    const card = document.createElement('div');
    card.className = 'day-card';

    const header = document.createElement('div');
    header.className = 'day-header';
    header.textContent = `Day ${day.day} — ${day.date}  |  ${day.theme || ''}`;
    card.appendChild(header);

    for (const act of (day.activities || [])) {
      const row = document.createElement('div');
      row.className = 'activity-row';

      const time = document.createElement('span');
      time.className = 'act-time';
      time.textContent = act.time || '';

      const icon = document.createElement('span');
      icon.className = 'act-icon';
      icon.textContent = TYPE_ICON[act.type] || '📍';

      const body2 = document.createElement('div');
      body2.className = 'act-body';

      const name = document.createElement('span');
      name.className = 'act-name';
      name.textContent = act.name;

      body2.appendChild(name);

      const meta = [];
      if (act.rating) meta.push(`★${act.rating}`);
      if (act.address) meta.push(act.address);
      if (act.notes) meta.push(act.notes);
      if (meta.length) {
        const metaEl = document.createElement('span');
        metaEl.className = 'act-meta';
        metaEl.textContent = meta.join(' · ');
        body2.appendChild(metaEl);
      }

      if (act.travel_from_prev) {
        const t = act.travel_from_prev;
        const travel = document.createElement('span');
        travel.className = 'act-travel';
        travel.textContent = `↓ ${t.duration_min} min ${t.mode} (${t.distance_km} km)`;
        body2.appendChild(travel);
      }

      row.appendChild(time);
      row.appendChild(icon);
      row.appendChild(body2);
      card.appendChild(row);
    }

    body.appendChild(card);
  }
}

function showToast(msg, isError = false) {
  const toast = $('toast');
  toast.textContent = msg;
  toast.classList.toggle('error', isError);
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 4000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

checkAuth();

// Show auth success message if redirected back from OAuth
if (new URLSearchParams(location.search).get('auth') === 'success') {
  showToast('Google Calendar connected!');
  history.replaceState({}, '', '/');
}
