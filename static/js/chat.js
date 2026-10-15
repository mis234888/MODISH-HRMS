/* One-to-one chat. Loaded before app.js; bootstrap starts only from bootApp. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const canonical = value => {
    const id = typeof value === 'string' || typeof value === 'number' ? String(value) : '';
    return id && id.length <= 512 && id.trim() === id && !/[\x00-\x1f\x7f\ud800-\udfff]/u.test(id) && id !== '.' && id !== '..' ? id : null;
  };
  const numeric = value => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : 0;
  const text = (value, limit = 4000) => String(value ?? '').slice(0, limit);
  const node = (tag, className, value) => {
    const out = document.createElement(tag);
    if (className) out.className = className;
    if (value !== undefined) out.textContent = value;
    return out;
  };
  const s = {
    started: false, ready: false, epoch: 0, me: null, expectedAccount: null, csrf: '', contacts: new Map(),
    conversations: new Map(), threads: new Map(), snapshot: new Map(), cursor: 0,
    peer: null, selection: 0, timer: null, polling: false, moreEvents: false,
    bootstrap: null, conversationRequest: null, controllers: new Set(), blocked: false,
    registration: null, workerPromise: null, enabled: false, preview: false,
    notificationBusy: false, push: {}, channel: null, notices: new Set(), pendingNotices: new Map(), readTimer: null,
  };
  function visible() { return document.visibilityState === 'visible' && document.hasFocus(); }
  function active() { return el('module-chat').classList.contains('active'); }
  function messageBounds() {
    const viewport = el('chatMessages');
    if (!viewport.getClientRects().length) return null;
    const rect = viewport.getBoundingClientRect();
    const main = el('module-chat').closest('main').getBoundingClientRect();
    const bounds = { top: Math.max(0, rect.top, main.top), bottom: Math.min(window.innerHeight, rect.bottom, main.bottom), left: Math.max(0, rect.left, main.left), right: Math.min(window.innerWidth, rect.right, main.right) };
    return bounds.bottom > bounds.top && bounds.right > bounds.left ? bounds : null;
  }
  function reading(peer = s.peer) {
    return s.ready && peer === s.peer && active() && visible() && !!messageBounds();
  }
  function status(message = '') {
    el('chatStatusText').textContent = message;
    el('chatStatus').hidden = !message;
  }
  function threadStatus(message = '') {
    el('chatThreadStatus').textContent = message;
    el('chatThreadStatus').hidden = !message;
  }
  function fail(error) {
    if (error.name === 'AbortError' || error.stale) return;
    if (error.status === 403) {
      s.blocked = true;
      clearTimeout(s.timer);
      status('Chat access or your security token changed. Retry connection to refresh access; contact HR if this continues.');
    } else if (error.status === 503) {
      status('Chat is temporarily unavailable. Retry connection, or ask your administrator to check chat configuration.');
    } else status(error.message || 'Could not connect to chat. Check your connection and retry.');
    updateComposer();
  }
  async function workerClear(account) {
    try {
      const registration = s.registration || (window.isSecureContext && navigator.serviceWorker ? await navigator.serviceWorker.getRegistration('/') : null);
      if (registration?.active) await workerCall('CHAT_SESSION_CLEAR', { account_id: account || null }, registration.active);
    } catch (_) { /* Private page state is cleared even if no worker is reachable. */ }
  }
  function purge(clearWorker = true) {
    const account = s.me?.id;
    s.epoch++;
    s.ready = false;
    s.blocked = false;
    clearTimeout(s.timer);
    clearTimeout(s.readTimer);
    for (const controller of s.controllers) controller.abort();
    s.controllers.clear();
    s.me = null; s.expectedAccount = null; s.csrf = ''; s.peer = null; s.selection++;
    s.contacts.clear(); s.conversations.clear(); s.threads.clear(); s.snapshot.clear(); s.notices.clear(); s.pendingNotices.clear();
    s.cursor = 0; s.push = {}; s.enabled = false; s.preview = false;
    s.bootstrap = null; s.conversationRequest = null; s.moreEvents = false; s.workerPromise = null; s.notificationBusy = false;
    el('chatContacts').replaceChildren(node('p', 'chat-empty', 'Sign in again to use chat.'));
    el('chatMessageList').replaceChildren(); el('chatPopups').replaceChildren();
    el('chatDraft').value = ''; el('chatSearch').value = '';
    el('chatPeerName').textContent = 'Choose a colleague'; el('chatPeerDetails').textContent = '';
    el('chatEmpty').hidden = false; el('chatEmpty').textContent = 'Your conversations will appear here.';
    el('chatOlder').hidden = true; el('chatJump').hidden = true;
    el('chatUnreadTotal').textContent = ''; el('chatBadge').hidden = true;
    el('chatBadge').textContent = '0'; el('chatSearch').disabled = true;
    el('chatPreview').checked = false; el('chatLayout').classList.remove('chat-peer-open');
    threadStatus(); status(); updateComposer(); notificationControls();
    return clearWorker ? workerClear(account) : Promise.resolve();
  }
  async function request(path, options = {}) {
    const epoch = s.epoch;
    const controller = new AbortController();
    s.controllers.add(controller);
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
    try {
      const method = options.method || 'GET';
      const response = await fetch('/api/chat/' + path, {
        method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
        headers: { Accept: 'application/json', ...(method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Chat-CSRF': s.csrf }) },
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      });
      if (epoch !== s.epoch) throw Object.assign(new Error('Session changed'), { stale: true });
      if (response.status === 401) {
        s.channel?.postMessage({ type: 'clear', account_id: s.me?.id });
        await purge();
        window.location.href = '/login';
        throw Object.assign(new Error('Please sign in again.'), { stale: true });
      }
      let payload;
      try { payload = await response.json(); } catch (_) { payload = {}; }
      if (epoch !== s.epoch) throw Object.assign(new Error('Session changed'), { stale: true });
      if (!response.ok || payload.success === false) {
        const message = typeof payload.error === 'string' ? payload.error : typeof payload.message === 'string' ? payload.message : `Chat request failed (${response.status}).`;
        const error = Object.assign(new Error(text(message, 250)), { status: response.status });
        if (response.status === 403 || response.status === 503) fail(error);
        throw error;
      }
      return payload;
    } catch (error) {
      if (timedOut && epoch === s.epoch) throw new Error('Chat request timed out. Please retry.');
      throw error;
    } finally { clearTimeout(timeout); s.controllers.delete(controller); }
  }
  function thread(peer) {
    if (!s.threads.has(peer)) s.threads.set(peer, {
      messages: new Map(), loaded: false, hasMore: false, olderBusy: false, latest: null,
      sending: false, draft: '', attempts: new Map(), sendError: '', readAck: 0, readBusy: false,
    });
    return s.threads.get(peer);
  }
  function validMessage(raw, peer) {
    if (!raw || !numeric(raw.id)) return null;
    const sender = canonical(raw.sender_id), recipient = canonical(raw.recipient_id);
    if (!sender || !recipient || !s.me) return null;
    const other = sender === s.me.id ? recipient : recipient === s.me.id ? sender : null;
    if (!other || other === s.me.id || (peer && other !== peer)) return null;
    return { id: numeric(raw.id), sender_id: sender, recipient_id: recipient, body: text(raw.body), created_at: text(raw.created_at, 80), read_at: raw.read_at ? text(raw.read_at, 80) : null };
  }
  function merge(peer, messages) {
    const t = thread(peer);
    for (const raw of messages || []) {
      const message = validMessage(raw, peer);
      if (!message) continue;
      const old = t.messages.get(message.id);
      // A stale latest-page response must not undo a read receipt from another request.
      t.messages.set(message.id, { ...message, read_at: message.read_at || old?.read_at || null });
    }
  }
  function applyConversations(payload) {
    const next = new Map();
    for (const raw of payload.conversations || []) {
      const peer = canonical(raw.peer_id);
      if (!peer || peer === s.me.id) continue;
      const last = validMessage(raw.last_message, peer);
      next.set(peer, { peer_id: peer, last_message: last, unread_count: Math.max(0, Number(raw.unread_count) || 0) });
      if (!s.contacts.has(peer)) s.contacts.set(peer, { id: peer, name: 'Colleague', employee_code: '', department: '' });
      if (last && s.threads.has(peer)) merge(peer, [last]);
    }
    s.conversations = next;
    const total = Math.max(0, Number(payload.unread_count) || 0);
    el('chatBadge').textContent = total > 99 ? '99+' : String(total);
    el('chatBadge').hidden = total === 0;
    el('chatBadge').setAttribute('aria-label', `${total} unread chat messages`);
    el('chatUnreadTotal').textContent = total ? `(${total} unread)` : '';
    renderContacts();
  }
  function renderContacts() {
    const query = el('chatSearch').value.trim().toLocaleLowerCase();
    const peers = [...s.contacts.values()].filter(p => `${p.name} ${p.employee_code}`.toLocaleLowerCase().includes(query));
    peers.sort((a, b) => {
      const ac = s.conversations.get(a.id), bc = s.conversations.get(b.id);
      return (bc?.last_message?.id || 0) - (ac?.last_message?.id || 0) || a.name.localeCompare(b.name);
    });
    const fragment = document.createDocumentFragment();
    for (const person of peers) {
      const conversation = s.conversations.get(person.id);
      const button = node('button', 'chat-contact'); button.type = 'button';
      button.setAttribute('aria-current', String(person.id === s.peer));
      const initials = person.name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join('').toUpperCase();
      button.append(node('span', 'chat-contact-avatar', initials || '?'));
      const details = node('span', 'chat-contact-text');
      details.append(node('span', 'chat-contact-name', person.name));
      details.append(node('span', 'chat-contact-detail', [person.employee_code, person.department].filter(Boolean).join(' · ')));
      if (conversation?.last_message) details.append(node('span', 'chat-contact-preview', conversation.last_message.body.replace(/\s+/g, ' ').slice(0, 80)));
      button.append(details);
      if (conversation?.unread_count) button.append(node('span', 'chat-badge', String(conversation.unread_count)));
      button.addEventListener('click', () => openPeer(person.id));
      fragment.append(button);
    }
    if (!peers.length) fragment.append(node('p', 'chat-empty', query ? 'No people match your search.' : 'No chat contacts available yet.'));
    const top = el('chatContacts').scrollTop;
    el('chatContacts').replaceChildren(fragment); el('chatContacts').scrollTop = top;
  }
  function updateComposer() {
    const t = s.peer ? thread(s.peer) : null;
    const ready = s.ready && !!t && !s.blocked;
    el('chatDraft').disabled = !ready;
    const length = el('chatDraft').value.length;
    el('chatDraftCount').textContent = `${length} / 4000`;
    el('chatSend').disabled = !ready || t.sending || !el('chatDraft').value.trim() || length > 4000;
    el('chatSend').textContent = t?.sending ? 'Sending…' : 'Send';
    el('chatSendStatus').textContent = t?.sendError || '';
  }
  function stamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  function renderMessages(mode = 'refresh') {
    if (!s.peer || !s.ready) return;
    const t = thread(s.peer), viewport = el('chatMessages'), list = el('chatMessageList');
    const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 65;
    const oldTop = viewport.scrollTop;
    const bounds = viewport.getBoundingClientRect();
    const anchor = [...list.children].find(row => row.getBoundingClientRect().bottom > bounds.top);
    const anchorId = anchor?.dataset.messageId, offset = anchor ? anchor.getBoundingClientRect().top - bounds.top : 0;
    const messages = [...t.messages.values()].sort((a, b) => a.id - b.id);
    const existing = new Map([...list.children].map(row => [numeric(row.dataset.messageId), row]));
    let newIncoming = false;
    for (let index = 0; index < messages.length; index++) {
      const m = messages[index];
      let row = existing.get(m.id);
      if (!row) {
        row = node('div', `chat-message${m.sender_id === s.me.id ? ' chat-mine' : ''}`);
        row.dataset.messageId = String(m.id); row.setAttribute('role', 'listitem');
        row.append(node('div', 'chat-message-body', m.body), node('div', 'chat-message-meta'));
        if (m.recipient_id === s.me.id) newIncoming = true;
      }
      const meta = `${stamp(m.created_at)}${m.sender_id === s.me.id ? (m.read_at ? ' · ✓✓ Read' : ' · ✓ Sent') : ''}`;
      if (row.lastChild.textContent !== meta) row.lastChild.textContent = meta;
      if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
    }
    el('chatOlder').hidden = !t.loaded || !t.hasMore;
    el('chatOlder').disabled = t.olderBusy;
    el('chatOlder').textContent = t.olderBusy ? 'Loading…' : 'Load older messages';
    el('chatEmpty').hidden = messages.length > 0;
    el('chatEmpty').textContent = t.loaded ? 'No messages yet. Say hello!' : 'Loading messages…';
    if (mode === 'initial' || mode === 'sent' || (mode !== 'older' && atBottom)) {
      viewport.scrollTop = viewport.scrollHeight; el('chatJump').hidden = true;
    } else {
      const currentAnchor = anchorId ? [...list.children].find(row => row.dataset.messageId === anchorId) : null;
      viewport.scrollTop = currentAnchor ? oldTop + currentAnchor.getBoundingClientRect().top - bounds.top - offset : oldTop;
      if (newIncoming && mode !== 'older') el('chatJump').hidden = false;
    }
    scheduleRead();
  }
  function messagePath(peer) { return 'messages/' + encodeURIComponent(peer); }
  async function latest(peer, selection = s.selection) {
    const t = thread(peer), epoch = s.epoch;
    if (t.latest) return t.latest;
    const initial = !t.loaded;
    const promise = (async () => {
      const result = await request(messagePath(peer));
      if (epoch !== s.epoch) return;
      merge(peer, result.messages);
      if (initial) t.hasMore = !!result.has_more;
      t.loaded = true;
      if (peer === s.peer && selection === s.selection) {
        threadStatus(); renderMessages(initial ? 'initial' : 'refresh');
      }
    })();
    t.latest = promise;
    try { await promise; } finally { if (t.latest === promise) t.latest = null; }
  }
  async function older() {
    const peer = s.peer, selection = s.selection, epoch = s.epoch;
    if (!peer || !s.ready) return;
    const t = thread(peer), before = Math.min(...t.messages.keys());
    if (t.olderBusy || !t.hasMore || !numeric(before)) return;
    t.olderBusy = true; renderMessages();
    try {
      const result = await request(messagePath(peer) + '?before=' + before);
      if (epoch !== s.epoch) return;
      merge(peer, result.messages); t.hasMore = !!result.has_more;
      if (peer === s.peer && selection === s.selection) { threadStatus(); renderMessages('older'); }
    } catch (error) {
      if (epoch === s.epoch && peer === s.peer && selection === s.selection) { threadStatus('Could not load older messages. Use Load older messages to retry.'); fail(error); }
    } finally {
      t.olderBusy = false;
      if (epoch === s.epoch && peer === s.peer && selection === s.selection) renderMessages('older');
    }
  }
  async function openPeer(value, history = 'push') {
    const peer = canonical(value);
    if (!s.ready || !peer || !s.contacts.has(peer)) {
      if (s.ready) status('This chat contact is not available for your account. Choose a colleague from the list.');
      return;
    }
    if (s.peer) thread(s.peer).draft = el('chatDraft').value;
    const changed = peer !== s.peer;
    s.peer = peer; const selection = ++s.selection, epoch = s.epoch;
    const person = s.contacts.get(peer), t = thread(peer);
    el('chatPeerName').textContent = person.name;
    el('chatPeerDetails').textContent = [person.employee_code, person.department].filter(Boolean).join(' · ');
    el('chatDraft').value = t.draft;
    el('chatLayout').classList.add('chat-peer-open');
    if (changed) { el('chatMessageList').replaceChildren(); el('chatJump').hidden = true; }
    threadStatus(); renderContacts(); updateComposer(); renderMessages(changed ? 'initial' : 'refresh');
    if (!active()) switchModule('chat');
    if (history) {
      const url = new URL(window.location.href);
      if (url.searchParams.get('chat') !== peer) {
        url.searchParams.set('chat', peer);
        window.history[history === 'replace' ? 'replaceState' : 'pushState']({}, '', url);
      }
    }
    syncFocus();
    try {
      await latest(peer, selection);
      // An already-running refresh may belong to an earlier selection of the same peer.
      if (epoch === s.epoch && peer === s.peer && selection === s.selection) renderMessages(changed ? 'initial' : 'refresh');
    } catch (error) {
      if (epoch === s.epoch && peer === s.peer && selection === s.selection) { threadStatus('Could not refresh this conversation. Use Refresh to retry.'); fail(error); }
    }
  }
  function uuid() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    const bytes = new Uint8Array(16); window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  async function send() {
    const peer = s.peer, epoch = s.epoch;
    if (!s.ready || s.blocked || !peer) return;
    const t = thread(peer), body = el('chatDraft').value;
    if (t.sending || !body.trim() || body.length > 4000) return;
    t.draft = body; t.sending = true; t.sendError = ''; updateComposer();
    try {
      if (!t.attempts.has(body)) t.attempts.set(body, uuid());
      const result = await request(messagePath(peer), { method: 'POST', body: { body, client_id: t.attempts.get(body) } });
      if (epoch !== s.epoch) return;
      const message = validMessage(result.message, peer);
      if (!message) throw new Error('Could not confirm the message. Retry to check delivery safely.');
      merge(peer, [message]); t.attempts.delete(body);
      if (t.draft === body) t.draft = '';
      if (s.peer === peer) {
        if (el('chatDraft').value === body) el('chatDraft').value = '';
        renderMessages('sent');
      }
      refreshConversations().catch(fail);
    } catch (error) {
      if (epoch === s.epoch) { t.sendError = 'Message not confirmed. Your draft is saved here; Send retries safely.'; fail(error); }
    } finally { t.sending = false; if (epoch === s.epoch && s.peer === peer) updateComposer(); }
  }
  function scheduleRead() {
    clearTimeout(s.readTimer);
    s.readTimer = setTimeout(markRead, 180);
  }
  async function markRead() {
    const peer = s.peer, selection = s.selection, epoch = s.epoch;
    if (!peer || !reading(peer) || s.blocked) return;
    const t = thread(peer);
    if (t.readBusy) return;
    const bounds = messageBounds();
    if (!bounds) return;
    let through = 0;
    for (const row of el('chatMessageList').children) {
      const message = t.messages.get(numeric(row.dataset.messageId));
      if (!message || message.recipient_id !== s.me.id || message.read_at) continue;
      const rect = row.getBoundingClientRect();
      if (rect.bottom > bounds.top && rect.top < bounds.bottom) through = Math.max(through, message.id);
    }
    if (!through || through <= t.readAck || !reading(peer) || selection !== s.selection) return;
    t.readBusy = true;
    try {
      await request(messagePath(peer) + '/read', { method: 'POST', body: { through_id: through } });
      if (epoch !== s.epoch) return;
      t.readAck = Math.max(t.readAck, through);
      for (const message of t.messages.values()) if (message.recipient_id === s.me.id && message.id <= through) message.read_at ||= new Date().toISOString();
      workerCall('CHAT_READ', { account_id: s.me.id, peer_id: peer, through_id: through }).catch(() => {});
      refreshConversations().catch(fail);
    } catch (error) { if (epoch === s.epoch) fail(error); }
    finally {
      t.readBusy = false;
      if (epoch === s.epoch && selection === s.selection && t.readAck >= through) scheduleRead();
    }
  }
  async function refreshConversations() {
    if (s.conversationRequest) return s.conversationRequest;
    const epoch = s.epoch;
    const promise = request('conversations').then(payload => { if (epoch === s.epoch && s.ready) applyConversations(payload); });
    s.conversationRequest = promise;
    try { await promise; } finally { if (s.conversationRequest === promise) s.conversationRequest = null; }
  }
  function schedulePoll(delay) {
    clearTimeout(s.timer);
    if (s.ready && !s.blocked) s.timer = setTimeout(poll, delay ?? (document.visibilityState === 'visible' ? 5000 : 15000));
  }
  async function poll() {
    if (!s.ready || s.polling || s.blocked) return;
    s.polling = true; const epoch = s.epoch;
    let succeeded = false;
    try {
      for (let batch = 0; batch < 5; batch++) {
        const result = await request('events?after=' + s.cursor);
        if (epoch !== s.epoch) return;
        const previous = s.cursor;
        for (const raw of result.events || []) {
          const message = validMessage(raw);
          if (!message || message.recipient_id !== s.me.id) continue;
          s.cursor = Math.max(s.cursor, message.id);
          const peer = message.sender_id;
          if (s.threads.has(peer)) merge(peer, [message]);
          if (message.id > previous && message.id > (s.snapshot.get(peer) || 0) && !message.read_at) s.pendingNotices.set(peer, message);
        }
        s.cursor = Math.max(s.cursor, numeric(result.cursor));
        s.moreEvents = !!result.has_more;
        if (!s.moreEvents) break;
        if (s.cursor <= previous) throw new Error('Chat sync could not advance. Retry connection.');
      }
      await refreshConversations();
      if (epoch !== s.epoch) return;
      if (s.peer && active() && visible()) await latest(s.peer);
      if (epoch !== s.epoch) return;
      for (const [peer, message] of s.pendingNotices) {
        if (s.peer === peer && reading(peer)) renderMessages();
        else await notifyIncoming(peer, message, epoch);
        if (epoch !== s.epoch) return;
        s.pendingNotices.delete(peer);
      }
      succeeded = true;
      if (!s.blocked) status();
    } catch (error) { if (epoch === s.epoch) fail(error); }
    finally {
      s.polling = false;
      if (epoch === s.epoch) schedulePoll(succeeded && s.moreEvents ? 0 : undefined);
      else if (s.ready) schedulePoll(0);
    }
  }
  async function bootstrap() {
    if (s.bootstrap) return s.bootstrap;
    const epoch = s.epoch;
    const promise = (async () => {
      status('Connecting to chat…');
      const payload = await request('bootstrap');
      const account = canonical(payload.me?.id);
      if (!account || !payload.csrf_token) throw new Error('Chat identity is unavailable. Retry connection or contact HR.');
      if (s.expectedAccount && account !== s.expectedAccount) {
        await purge(false);
        status('Your account changed while chat was connecting. Reload the dashboard to use chat.');
        return;
      }
      if (s.me && s.me.id !== account) {
        await purge();
        return bootstrap();
      }
      if (epoch !== s.epoch) return;
      const first = !s.ready;
      s.me = { id: account, name: text(payload.me.name, 200) }; s.csrf = String(payload.csrf_token);
      s.contacts = new Map();
      for (const raw of payload.contacts || []) {
        const id = canonical(raw.id);
        if (id && id !== account) s.contacts.set(id, { id, name: text(raw.name || 'Colleague', 200), department: text(raw.department, 200), employee_code: text(raw.employee_code, 100) });
      }
      s.push = payload.push || {}; s.blocked = false; s.ready = true;
      applyConversations(payload);
      if (first) {
        s.cursor = 0; s.snapshot.clear();
        for (const [peer, c] of s.conversations) {
          s.snapshot.set(peer, c.last_message?.id || 0);
          if (c.last_message?.recipient_id === account) s.cursor = Math.max(s.cursor, c.last_message.id);
        }
      }
      readPreference(); el('chatSearch').disabled = false; el('chatPreview').checked = s.preview;
      s.channel?.postMessage({ type: 'account', account_id: account });
      status(); updateComposer(); notificationControls();
      const workerEpoch = s.epoch;
      setupWorker(workerEpoch).catch(() => { if (workerEpoch === s.epoch) notificationControls('Service worker unavailable. Check that /chat-sw.js is served from this origin with scope /.'); });
      const deepPeer = new URL(window.location.href).searchParams.get('chat');
      if (deepPeer) await openPeer(deepPeer, 'replace');
      else if (s.peer) await openPeer(s.peer, false);
      schedulePoll(0);
    })();
    s.bootstrap = promise;
    try { await promise; } catch (error) { if (epoch === s.epoch) fail(error); }
    finally { if (s.bootstrap === promise) s.bootstrap = null; }
  }
  function load() {
    // switchModule can run before bootApp has resolved /api/session.
    if (!s.started) return;
    if (!s.ready) { bootstrap(); return; }
    renderContacts(); updateComposer(); syncFocus(); scheduleRead();
    if (s.peer) latest(s.peer).catch(fail);
    if (!s.polling) schedulePoll(0);
  }
  function init() {
    if (s.started || !el('module-chat')) return;
    s.started = true;
    bindEvents();
    bootstrap();
  }

  /* Notification helpers are deliberately account-scoped. No message text is persisted. */
  function preferenceKey() { return 'ekkaa.chat.preview.' + encodeURIComponent(s.me.id); }
  function readPreference() {
    s.preview = false;
    try { s.preview = localStorage.getItem(preferenceKey()) === 'true'; } catch (_) { /* Preferences may be disabled. */ }
  }
  function writePreference() {
    try { localStorage.setItem(preferenceKey(), String(s.preview)); } catch (_) { /* Session-only preference. */ }
  }
  function workerCall(type, data = {}, worker = s.registration?.active) {
    if (!worker) return Promise.reject(new Error('Chat service worker is not ready.'));
    return new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      const timer = setTimeout(() => { channel.port1.close(); reject(new Error('Chat service worker did not respond. Please retry.')); }, 6000);
      channel.port1.onmessage = event => {
        clearTimeout(timer); channel.port1.close();
        if (event.data?.error) reject(new Error(text(event.data.error, 250)));
        else resolve(event.data || {});
      };
      worker.postMessage({ type, ...data }, [channel.port2]);
    });
  }
  function notificationControls(message) {
    const support = window.isSecureContext && 'serviceWorker' in navigator && 'Notification' in window;
    const available = s.ready && support && !s.notificationBusy;
    el('chatEnableNotifications').disabled = !available;
    el('chatDisableNotifications').disabled = !available;
    el('chatPreview').disabled = !s.ready || s.notificationBusy;
    el('chatSavePreviews').disabled = !s.ready || s.notificationBusy;
    let description = 'Notifications are off. Enable notifications to request browser permission for this account on this device.';
    if (!s.ready) description = 'Connect to chat to manage notifications.';
    else if (!window.isSecureContext) description = 'OS and Web Push notifications require HTTPS or localhost. In-app alerts still work.';
    else if (!support) description = 'This browser does not support service-worker OS notifications. In-app alerts still work.';
    else if (Notification.permission === 'denied') description = 'Notification permission is blocked. Allow notifications in your browser site settings, then enable again.';
    else if (s.enabled && Notification.permission === 'granted') {
      description = s.push.enabled && 'PushManager' in window && s.push.public_key
        ? 'Notifications enabled for this account on this device. Web Push can deliver with the tab closed; browser/device delivery is not guaranteed.'
        : 'Notifications enabled while a dashboard tab is open. Closed-tab delivery is unavailable: Web Push configuration or browser push support is missing.';
    } else if (!s.push.enabled) description += ' Web Push is not configured; closed-tab delivery is unavailable.';
    else if (!('PushManager' in window) || !s.push.public_key) description += ' Closed-tab delivery is unavailable: browser push support or the server public key is missing.';
    if (message) description = message;
    el('chatNotificationStatus').textContent = description;
  }
  async function setupWorker(epoch) {
    if (!window.isSecureContext || !('serviceWorker' in navigator)) { notificationControls(); return null; }
    if (s.workerPromise) return s.workerPromise;
    const account = s.me?.id;
    if (!account) return null;
    const promise = (async () => {
      const registration = await navigator.serviceWorker.register('/chat-sw.js', { scope: '/', updateViaCache: 'none' });
      let worker = registration.active;
      if (!worker) {
        worker = registration.installing || registration.waiting;
        if (!worker) throw new Error('Chat service worker could not start.');
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => { worker.removeEventListener('statechange', changed); reject(new Error('Chat service worker activation timed out.')); }, 12000);
          const changed = () => {
            if (worker.state === 'activated' || worker.state === 'redundant') {
              clearTimeout(timer); worker.removeEventListener('statechange', changed);
              if (worker.state === 'activated') resolve(); else reject(new Error('Chat service worker could not activate.'));
            }
          };
          worker.addEventListener('statechange', changed); changed();
        });
      }
      if (epoch !== s.epoch || s.me?.id !== account) return null;
      s.registration = registration;
      const binding = await workerCall('CHAT_SESSION_SYNC', { account_id: account, preview: s.preview }, registration.active || worker);
      if (epoch !== s.epoch || s.me?.id !== account) return null;
      s.enabled = binding.account_id === account && binding.enabled === true;
      syncFocus(); notificationControls();
      return registration;
    })();
    s.workerPromise = promise;
    try { return await promise; } finally { if (s.workerPromise === promise) s.workerPromise = null; }
  }
  function syncFocus() {
    if (!s.me || !s.registration?.active) return;
    s.registration.active.postMessage({ type: 'CHAT_CLIENT_STATE', account_id: s.me.id, peer_id: active() ? s.peer : null, visible: document.visibilityState === 'visible', focused: document.hasFocus() });
  }
  function publicKey(value) {
    const base64 = String(value).replace(/-/g, '+').replace(/_/g, '/');
    const decoded = atob(base64 + '='.repeat((4 - base64.length % 4) % 4));
    return Uint8Array.from(decoded, c => c.charCodeAt(0));
  }
  function sessionStill(epoch, account) {
    if (epoch !== s.epoch || !s.ready || s.me?.id !== account) throw Object.assign(new Error('Session changed'), { stale: true });
  }
  async function enableNotifications() {
    if (!s.ready || s.notificationBusy) return;
    if (!window.isSecureContext || !('Notification' in window) || !('serviceWorker' in navigator)) { notificationControls(); return; }
    const epoch = s.epoch, account = s.me.id;
    s.notificationBusy = true; notificationControls('Requesting browser permission…');
    try {
      // Call permission directly in the click gesture, before any asynchronous registration work.
      const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
      sessionStill(epoch, account);
      if (permission !== 'granted') { notificationControls(permission === 'denied' ? 'Permission denied. Allow notifications in browser site settings to enable them.' : 'Permission was not granted. Click Enable notifications when you are ready.'); return; }
      const registration = await setupWorker(epoch);
      sessionStill(epoch, account);
      if (!registration) throw new Error('The chat service worker is unavailable. Retry after checking /chat-sw.js.');
      if (s.push.enabled && (!s.push.public_key || !registration.pushManager)) {
        notificationControls('Browser permission granted, but Web Push cannot be enabled: browser push support or the server public key is missing. Ask your administrator to check configuration. In-app alerts still work.');
        return;
      }
      let pushBound = false;
      if (s.push.enabled && s.push.public_key && registration.pushManager) {
        let subscription = await registration.pushManager.getSubscription();
        sessionStill(epoch, account);
        if (!subscription) subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: publicKey(s.push.public_key) });
        sessionStill(epoch, account);
        // Binding an existing browser subscription is permitted ONLY from this explicit enable.
        await request('push-subscriptions', { method: 'POST', body: { subscription: subscription.toJSON(), preview: s.preview } });
        sessionStill(epoch, account); pushBound = true;
      }
      const result = await workerCall('CHAT_ENABLE', { account_id: account, preview: s.preview });
      sessionStill(epoch, account);
      if (!result.enabled || result.account_id !== account) throw new Error('The notification account changed. Reload chat and enable again.');
      s.enabled = true;
      notificationControls(pushBound ? undefined : 'OS notifications enabled while a dashboard tab is open. Closed-tab delivery needs configured Web Push and browser support.');
    } catch (error) {
      if (epoch === s.epoch && !error.stale) { fail(error); notificationControls(error.message || 'Could not enable notifications. Please retry.'); }
    } finally { if (epoch === s.epoch) { s.notificationBusy = false; notificationControls(el('chatNotificationStatus').textContent); } }
  }
  async function disableNotifications() {
    if (!s.ready || s.notificationBusy) return;
    const epoch = s.epoch, account = s.me.id;
    s.notificationBusy = true; notificationControls('Disabling notifications for this account…');
    try {
      const registration = s.registration || await setupWorker(epoch);
      sessionStill(epoch, account);
      const subscription = registration?.pushManager ? await registration.pushManager.getSubscription() : null;
      sessionStill(epoch, account);
      if (subscription) await request('push-subscriptions', { method: 'DELETE', body: { endpoint: subscription.endpoint } });
      sessionStill(epoch, account);
      const result = await workerCall('CHAT_DISABLE', { account_id: account, unsubscribe: true });
      sessionStill(epoch, account);
      if (!result.cleared) throw new Error('The notification account changed. Reload before disabling this device.');
      s.enabled = false;
      if (!result.unsubscribed) throw new Error('Account notifications are off, but the browser subscription could not be removed. Retry Disable notifications.');
      notificationControls('Notifications disabled for this account on this device. In-app alerts remain available.');
    } catch (error) {
      if (epoch === s.epoch && !error.stale) { fail(error); notificationControls(error.message || 'Could not disable notifications. Please retry.'); }
    } finally { if (epoch === s.epoch) { s.notificationBusy = false; notificationControls(el('chatNotificationStatus').textContent); } }
  }
  async function savePreviews() {
    if (!s.ready || s.notificationBusy) return;
    const epoch = s.epoch, account = s.me.id;
    s.notificationBusy = true; notificationControls('Updating preview settings…');
    try {
      if (s.enabled && s.push.enabled && s.registration?.pushManager) {
        const subscription = await s.registration.pushManager.getSubscription();
        sessionStill(epoch, account);
        if (!subscription) throw new Error('This device has no push subscription. Use Enable notifications to set it up.');
        await request('push-subscriptions', { method: 'POST', body: { subscription: subscription.toJSON(), preview: s.preview } });
        sessionStill(epoch, account);
      }
      if (s.registration?.active) await workerCall('CHAT_PREVIEW', { account_id: account, preview: s.preview });
      sessionStill(epoch, account);
      notificationControls(s.preview ? 'Message previews are on for this account. This device’s subscription settings are updated.' : 'Message previews are off for this account. Notifications use discreet text.');
    } catch (error) {
      if (epoch === s.epoch && !error.stale) { fail(error); notificationControls('Preview update failed. Click Update previews to retry.'); }
    } finally { if (epoch === s.epoch) { s.notificationBusy = false; notificationControls(el('chatNotificationStatus').textContent); } }
  }
  function popup(peer, message) {
    const wrap = el('chatPopups'), card = node('div', 'chat-popup');
    const open = node('button', 'chat-popup-open'); open.type = 'button';
    open.append(node('strong', '', s.contacts.get(peer)?.name || 'Colleague'));
    open.append(node('span', '', s.preview ? message.body.replace(/\s+/g, ' ').slice(0, 110) : 'New private message. Open chat to read it.'));
    open.addEventListener('click', () => { card.remove(); openPeer(peer); });
    const close = node('button', 'chat-popup-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Dismiss chat alert');
    close.addEventListener('click', () => card.remove()); card.append(open, close);
    while (wrap.children.length >= 3) wrap.firstChild.remove();
    wrap.append(card); setTimeout(() => card.remove(), 12000);
  }
  async function notifyIncoming(peer, message, epoch) {
    const key = `${s.me.id}:${message.id}`;
    if (s.notices.has(key)) return;
    s.notices.add(key);
    if (s.notices.size > 1000) s.notices.delete(s.notices.values().next().value);
    if (visible()) {
      let claimed = true;
      if (s.registration?.active) {
        try { claimed = (await workerCall('CHAT_CLAIM', { account_id: s.me.id, message_id: message.id })).claimed === true; } catch (_) { /* Local alert still works without a worker. */ }
      }
      if (claimed && epoch === s.epoch && s.ready && visible() && !reading(peer)) popup(peer, message);
    } else if (s.enabled && 'Notification' in window && Notification.permission === 'granted' && !s.push.enabled && s.registration?.active) {
      await workerCall('CHAT_NOTIFY', { account_id: s.me.id, peer_id: peer, message_id: message.id, title: s.contacts.get(peer)?.name || 'Ekkaa chat', body: message.body }).catch(() => {});
    }
  }
  function bindEvents() {
    el('chatSearch').addEventListener('input', renderContacts);
    el('chatCompose').addEventListener('submit', event => { event.preventDefault(); send(); });
    el('chatDraft').addEventListener('input', () => { if (s.peer) thread(s.peer).draft = el('chatDraft').value; updateComposer(); });
    el('chatDraft').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.isComposing && (!event.shiftKey || event.ctrlKey || event.metaKey)) { event.preventDefault(); send(); }
    });
    el('chatOlder').addEventListener('click', older);
    el('chatRefresh').addEventListener('click', () => {
      if (!s.ready || s.blocked) bootstrap();
      else { if (s.peer) latest(s.peer).catch(fail); schedulePoll(0); }
    });
    el('chatRetry').addEventListener('click', () => bootstrap());
    el('chatBack').addEventListener('click', () => { el('chatLayout').classList.remove('chat-peer-open'); syncFocus(); });
    el('chatJump').addEventListener('click', () => { el('chatMessages').scrollTop = el('chatMessages').scrollHeight; el('chatJump').hidden = true; scheduleRead(); });
    el('chatMessages').addEventListener('scroll', () => {
      if (el('chatMessages').scrollHeight - el('chatMessages').scrollTop - el('chatMessages').clientHeight < 65) el('chatJump').hidden = true;
      scheduleRead();
    }, { passive: true });
    el('chatEnableNotifications').addEventListener('click', enableNotifications);
    el('chatDisableNotifications').addEventListener('click', disableNotifications);
    el('chatSavePreviews').addEventListener('click', savePreviews);
    el('chatPreview').addEventListener('change', () => {
      if (!s.me) return;
      s.preview = el('chatPreview').checked; writePreference();
      workerCall('CHAT_PREVIEW', { account_id: s.me.id, preview: s.preview }).catch(() => {});
      // Remove an already-rendered opt-in preview immediately when opting out.
      if (!s.preview) el('chatPopups').replaceChildren();
      notificationControls('Preview preference saved for this account. Click Update previews to update this device’s Web Push subscription.');
    });
    const focusChanged = () => { syncFocus(); scheduleRead(); if (!s.polling) schedulePoll(document.visibilityState === 'visible' ? 0 : 15000); };
    document.addEventListener('visibilitychange', focusChanged);
    window.addEventListener('focus', focusChanged); window.addEventListener('blur', focusChanged);
    window.addEventListener('pageshow', event => { if (event.persisted) { purge(); bootstrap(); } });
    window.addEventListener('pagehide', () => {
      if (s.me) s.registration?.active?.postMessage({ type: 'CHAT_CLIENT_STATE', account_id: s.me.id, peer_id: null, visible: false, focused: false });
    });
    new MutationObserver(() => {
      syncFocus(); scheduleRead();
      if (!active()) {
        const url = new URL(window.location.href);
        if (url.searchParams.has('chat')) { url.searchParams.delete('chat'); window.history.replaceState({}, '', url); }
      }
    }).observe(el('module-chat'), { attributes: true, attributeFilter: ['class'] });
    document.addEventListener('click', event => {
      const link = event.target.closest('a');
      if (link?.dataset.module === 'chat') event.preventDefault();
      if (!link?.href) return;
      const url = new URL(link.href, window.location.origin);
      if (url.origin !== window.location.origin || url.pathname !== '/logout' || event.defaultPrevented) return;
      event.preventDefault();
      s.channel?.postMessage({ type: 'clear', account_id: s.me?.id });
      purge().finally(() => { window.location.href = url.href; });
    }, true);
    window.addEventListener('popstate', () => {
      const peer = new URL(window.location.href).searchParams.get('chat');
      if (peer && s.ready) openPeer(peer, false);
    });
    window.addEventListener('storage', event => {
      if (s.me && event.key === preferenceKey()) {
        readPreference(); el('chatPreview').checked = s.preview;
        if (!s.preview) el('chatPopups').replaceChildren();
      }
    });
    if ('BroadcastChannel' in window) {
      s.channel = new BroadcastChannel('ekkaa-chat-session');
      s.channel.onmessage = event => {
        const message = event.data;
        if (!message) return;
        if (message.type === 'account' && canonical(message.account_id) && !s.me) {
          // Do not let a delayed response from the previous cookie session render after a switch.
          s.expectedAccount = message.account_id;
          return;
        }
        if ((message.type === 'account' && s.me && message.account_id !== s.me.id) || (message.type === 'clear' && (!message.account_id || message.account_id === s.me?.id))) {
          purge(); status('Your account session changed in another tab. Reload the dashboard to use chat.');
        }
      };
    }
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.addEventListener('message', event => {
        const message = event.data;
        if (message?.type === 'CHAT_FOCUS_QUERY') {
          event.ports?.[0]?.postMessage({ account_id: s.ready ? s.me?.id : null, peer_id: active() && reading() ? s.peer : null, visible: document.visibilityState === 'visible', focused: document.hasFocus() });
        } else if (message?.type === 'CHAT_OPEN' && s.ready && message.account_id === s.me.id) openPeer(message.peer_id);
        else if (message?.type === 'CHAT_BINDING_CHANGED' && s.ready) {
          if (message.account_id !== s.me.id) {
            purge(false); status('Your notification account changed in another tab. Reload the dashboard to use chat.');
          } else { s.enabled = message.enabled === true; notificationControls(); }
        }
      });
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (s.ready) setupWorker(s.epoch).catch(() => {}); });
    }
  }
  window.EkkaaChat = { init, load };
})();
