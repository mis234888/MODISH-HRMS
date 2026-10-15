/* Root-scoped chat notifications only. No fetch handler and no content caching. */
'use strict';
const BINDING_CACHE = 'ekkaa-chat-account-v1';
const BINDING_URL = new URL('/__ekkaa-chat-account-binding__', self.location.origin).href;
const TAG_PREFIX = 'ekkaa-chat:';
const claims = new Map();
let queue = Promise.resolve();
function serial(task) {
  const result = queue.then(task);
  queue = result.catch(() => {});
  return result;
}
function canonical(value) {
  const id = typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  return id && id.length <= 512 && id.trim() === id && !/[\x00-\x1f\x7f\ud800-\udfff]/u.test(id) && id !== '.' && id !== '..' ? id : null;
}
function numeric(value) { return Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : 0; }
function dashboard(value) {
  try {
    const url = new URL(value);
    return url.origin === self.location.origin && url.pathname === '/dashboard';
  } catch (_) { return false; }
}
function chatURL(peer) {
  return canonical(peer) ? new URL('/dashboard?chat=' + encodeURIComponent(peer), self.location.origin).href : null;
}
function validatedURL(value) {
  try {
    const url = new URL(value);
    const peer = canonical(url.searchParams.get('chat'));
    return peer && url.href === chatURL(peer) ? { url: url.href, peer } : null;
  } catch (_) { return null; }
}
async function binding() {
  const cache = await caches.open(BINDING_CACHE);
  const response = await cache.match(BINDING_URL);
  if (!response) return { account_id: null, enabled: false, preview: false };
  try {
    const raw = await response.json();
    return { account_id: canonical(raw.account_id), enabled: raw.enabled === true, preview: raw.preview === true };
  } catch (_) { return { account_id: null, enabled: false, preview: false }; }
}
async function saveBinding(config) {
  // This is the entire persistent state: account binding and booleans, never messages or keys.
  const cache = await caches.open(BINDING_CACHE);
  await cache.put(BINDING_URL, new Response(JSON.stringify({ account_id: canonical(config.account_id), enabled: config.enabled === true, preview: config.preview === true }), { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }));
}
async function closeNotifications(account, peer, through) {
  const notifications = await self.registration.getNotifications();
  for (const notification of notifications) {
    if (!notification.tag.startsWith(TAG_PREFIX)) continue;
    if (account && notification.data?.recipient_id !== account) continue;
    if (peer && validatedURL(notification.data?.url)?.peer !== peer) continue;
    const id = numeric(notification.tag.slice(notification.tag.lastIndexOf(':') + 1));
    if (through && (!id || id > through)) continue;
    notification.close();
  }
}
async function broadcastBinding(config) {
  for (const client of await self.clients.matchAll({ type: 'window', includeUncontrolled: true })) {
    if (dashboard(client.url)) client.postMessage({ type: 'CHAT_BINDING_CHANGED', account_id: config.account_id, enabled: config.enabled });
  }
}
function queryClient(client) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timeout = setTimeout(() => { channel.port1.close(); resolve(null); }, 700);
    channel.port1.onmessage = event => { clearTimeout(timeout); channel.port1.close(); resolve(event.data || null); };
    // No message contents are sent to clients, including login/unrelated accounts.
    try { client.postMessage({ type: 'CHAT_FOCUS_QUERY' }, [channel.port2]); }
    catch (_) { clearTimeout(timeout); channel.port1.close(); resolve(null); }
  });
}
async function clientStates() {
  const clients = (await self.clients.matchAll({ type: 'window', includeUncontrolled: true })).filter(client => dashboard(client.url));
  const replies = await Promise.all(clients.map(queryClient));
  return clients.map((client, index) => ({ client, state: replies[index] }));
}
async function matchingClients(account) {
  return (await clientStates()).filter(entry => canonical(entry.state?.account_id) === account);
}
async function show(config, payload) {
  const recipient = canonical(payload.recipient_id), peer = canonical(payload.peer_id), id = numeric(payload.message_id);
  if (!config.enabled || !config.account_id || recipient !== config.account_id || !peer || peer === recipient || !id) return;
  const url = chatURL(peer);
  if (!url) return;
  const states = await clientStates();
  // Bootstrap can finish before its SESSION_SYNC reaches this worker. A responding dashboard
  // with unknown/different identity must never see a previous account's notification preview.
  if (states.some(entry => entry.state && canonical(entry.state.account_id) !== recipient)) return;
  const clients = states.filter(entry => canonical(entry.state?.account_id) === recipient);
  // A foreground dashboard handles in-app alerts; this also suppresses a focused open peer.
  if (clients.some(entry => entry.state.visible === true && entry.state.focused === true)) return;
  const tag = TAG_PREFIX + encodeURIComponent(recipient) + ':' + id;
  if ((await self.registration.getNotifications({ tag })).length) return;
  const key = `os:${recipient}:${id}`;
  if (claims.has(key)) return;
  const title = config.preview ? String(payload.title || 'Ekkaa chat').slice(0, 120) : 'New Ekkaa chat message';
  const body = config.preview ? String(payload.body || 'Open chat to read your message.').slice(0, 180) : 'Open Ekkaa to read your private message.';
  await self.registration.showNotification(title, { body, tag, data: { url, recipient_id: recipient } });
  claims.set(key, Date.now());
}
function trimClaims() {
  for (const [key, time] of claims) if (Date.now() - time > 10 * 60 * 1000) claims.delete(key);
  while (claims.size > 2000) claims.delete(claims.keys().next().value);
}
self.addEventListener('install', event => { event.waitUntil(self.skipWaiting()); });
self.addEventListener('activate', event => { event.waitUntil(self.clients.claim()); });
self.addEventListener('message', event => {
  const source = event.source, message = event.data;
  if (!source || !dashboard(source.url) || !message || typeof message.type !== 'string') return;
  event.waitUntil(serial(async () => {
    const account = canonical(message.account_id);
    let config = await binding();
    let result = {};
    trimClaims();
    if (message.type === 'CHAT_SESSION_SYNC') {
      if (!account) throw new Error('Chat account is required.');
      if (config.account_id !== account) {
        await closeNotifications(); claims.clear();
        config = { account_id: account, enabled: false, preview: message.preview === true };
      } else {
        if (config.preview && message.preview !== true) await closeNotifications(account);
        config.preview = message.preview === true;
      }
      await saveBinding(config); await broadcastBinding(config); result = config;
    } else if (message.type === 'CHAT_SESSION_CLEAR') {
      // A stale account tab must not clear a newer account's binding.
      if (!account || config.account_id === account) {
        await closeNotifications(); claims.clear();
        config = { account_id: null, enabled: false, preview: false };
        await saveBinding(config); await broadcastBinding(config);
      }
      result = { cleared: !account || config.account_id !== account };
    } else {
      if (!account || account !== config.account_id) throw new Error('Chat notification account changed. Reload the dashboard.');
      if (message.type === 'CHAT_ENABLE') {
        config.enabled = true; config.preview = message.preview === true;
        await saveBinding(config); await broadcastBinding(config); result = config;
      } else if (message.type === 'CHAT_DISABLE') {
        config.enabled = false; config.preview = false;
        await saveBinding(config); await closeNotifications(account); claims.clear();
        // Serialized with account changes/enables so an old page cannot unsubscribe a new binding.
        let unsubscribed = true;
        if (message.unsubscribe && self.registration.pushManager) {
          const subscription = await self.registration.pushManager.getSubscription();
          if (subscription) unsubscribed = await subscription.unsubscribe();
        }
        await broadcastBinding(config); result = { cleared: true, unsubscribed };
      } else if (message.type === 'CHAT_PREVIEW') {
        config.preview = message.preview === true;
        await saveBinding(config);
        if (!config.preview) await closeNotifications(account);
        result = config;
      } else if (message.type === 'CHAT_BINDING') result = config;
      else if (message.type === 'CHAT_CLAIM') {
        const id = numeric(message.message_id);
        const key = `app:${account}:${id}`;
        result = { claimed: !!id && !claims.has(key) };
        if (result.claimed) claims.set(key, Date.now());
      } else if (message.type === 'CHAT_NOTIFY') {
        await show(config, { ...message, recipient_id: account });
      } else if (message.type === 'CHAT_READ') {
        const peer = canonical(message.peer_id), through = numeric(message.through_id);
        if (peer && through) await closeNotifications(account, peer, through);
      }
      // CHAT_CLIENT_STATE contains no content. Foreground state is queried live before delivery.
    }
    event.ports?.[0]?.postMessage(result);
  }).catch(() => { event.ports?.[0]?.postMessage({ error: 'Chat notification settings could not be applied. Reload chat and retry.' }); }));
});
self.addEventListener('push', event => {
  event.waitUntil(serial(async () => {
    let payload;
    try { payload = event.data?.json(); } catch (_) { return; }
    if (!payload || typeof payload !== 'object') return;
    trimClaims();
    await show(await binding(), payload);
  }).catch(() => {}));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(serial(async () => {
    const config = await binding(), data = event.notification.data;
    const target = validatedURL(data?.url);
    if (!target || !config.enabled || !config.account_id || data.recipient_id !== config.account_id) return;
    const clients = await matchingClients(config.account_id);
    const existing = clients.find(entry => entry.state.focused) || clients[0];
    if (existing) {
      existing.client.postMessage({ type: 'CHAT_OPEN', account_id: config.account_id, peer_id: target.peer });
      await existing.client.focus();
    } else await self.clients.openWindow(target.url);
  }).catch(() => {}));
});
