/* ============================================================================
   Ekkaa HRMS - single page app
   Every module reads from the Flask API; nothing here is hard-coded demo data.
   ========================================================================== */

/* ---------------------------- tiny helpers ---------------------------- */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const APP = { user: window.APP_USER || {}, lookups: null, me: null, cache: {}, charts: {}, dirty: {}, empPage: 1, empRows: [], tsWeek: null, tsRows: [], tsLocked: false, docMeta: null, reportRows: [], reportCols: [], customFilters: {}, perfData: null, orgData: null, orgZoom: 1, attView: 'list', regReasonRequired: true };

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function isAdmin() { return APP.user.role === 'HR Admin'; }
/* The server hands this login a list of modules it may open. Nobody is locked out if
   the list is missing (older session payload), so the guard degrades to "allow". */
function allowedModules() {
  const m = (APP.session && APP.session.modules) || APP.user.modules;
  return Array.isArray(m) && m.length ? m : null;
}
function canOpenModule(mod) { const m = allowedModules(); return mod === 'chat' || !m || m.includes(mod); }
function moduleLabel(mod) { return (MODULE_TITLES[mod] || [mod])[0]; }
function hideEl(id) { const el = document.getElementById(id); if (el) el.classList.add('hidden'); }
function dash(v, alt = '—') { return (v === null || v === undefined || v === '' || v === '-') ? alt : esc(v); }

function inr(v, decimals = 0) {
  const n = Number(v || 0);
  if (!isFinite(n)) return '—';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function compactInr(v) {
  const n = Number(v || 0);
  if (!n) return '₹0';
  if (n >= 10000000) return '₹' + (n / 10000000).toFixed(2) + ' Cr';
  if (n >= 100000) return '₹' + (n / 100000).toFixed(2) + ' L';
  if (n >= 1000) return '₹' + (n / 1000).toFixed(1) + 'k';
  return '₹' + n.toFixed(0);
}
function fmtDate(value, opts = { day: '2-digit', month: 'short', year: 'numeric' }) {
  if (!value) return '—';
  const d = new Date(String(value).length === 10 ? value + 'T00:00:00' : value);
  if (isNaN(d)) return esc(value);
  return d.toLocaleDateString('en-IN', opts);
}
function fmtDayShort(value) { return fmtDate(value, { day: '2-digit', month: 'short' }); }
function todayIso() {
  // The server's office date, not the browser's: a UTC web dyno and an IST office are on different
  // calendar days after 18:30 UTC, and every date default in this UI (payroll period, document
  // validity, an attendance correction) has to be the day the office is running.
  return APP.officeDate || new Date().toISOString().slice(0, 10);
}
function isoDay(d) { return d.toISOString().slice(0, 10); }
function initialsOf(name) { return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join('').toUpperCase(); }
function debounce(fn, ms = 280) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function num(v) { const n = Number(v); return isNaN(n) ? 0 : n; }
function humanSize(bytes) {
  let n = num(bytes);
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}
function statusPill(status) {
  const map = {
    Active: 'bg-[#e6f9f0] text-[#0f9d58]', Approved: 'bg-[#e6f9f0] text-[#0f9d58]', Verified: 'bg-[#e6f9f0] text-[#0f9d58]', Paid: 'bg-[#e6f9f0] text-[#0f9d58]', Present: 'bg-[#e6f9f0] text-[#0f9d58]', Hired: 'bg-[#e6f9f0] text-[#0f9d58]', Achieved: 'bg-[#e6f9f0] text-[#0f9d58]', Completed: 'bg-[#e6f9f0] text-[#0f9d58]', Fulfilled: 'bg-[#e6f9f0] text-[#0f9d58]', Valid: 'bg-[#e6f9f0] text-[#0f9d58]', 'On Track': 'bg-[#e6f9f0] text-[#0f9d58]', Open: 'bg-[#e6f9f0] text-[#0f9d58]',
    Pending: 'bg-[#fff4e6] text-[#b7791f]', Submitted: 'bg-[#fff4e6] text-[#b7791f]', 'Manager Review Pending': 'bg-[#fff4e6] text-[#b7791f]', 'Self Review Pending': 'bg-[#fff4e6] text-[#b7791f]', Requested: 'bg-[#fff4e6] text-[#b7791f]', 'Notice Period': 'bg-[#fff4e6] text-[#b7791f]', 'At Risk': 'bg-[#fff4e6] text-[#b7791f]', 'Expiring soon': 'bg-[#fff4e6] text-[#b7791f]', 'On Hold': 'bg-[#fff4e6] text-[#b7791f]', Published: 'bg-[#e6f9f0] text-[#0f9d58]', 'Work From Home': 'bg-[#d1fae5] text-[#15803d]', Screening: 'bg-[#d1fae5] text-[#15803d]', Interview: 'bg-[#d1fae5] text-[#15803d]', Draft: 'bg-[#f0fdf4] text-[#64748b]', Scheduled: 'bg-[#d1fae5] text-[#15803d]', Offer: 'bg-[#d1fae5] text-[#047857]', Applied: 'bg-[#f0fdf4] text-[#64748b]', InProgress: 'bg-[#d1fae5] text-[#15803d]', 'In progress': 'bg-[#d1fae5] text-[#15803d]', 'Half Day': 'bg-[#fff4e6] text-[#b7791f]', Absent: 'bg-[#fff1f1] text-[#c0392b]', 'On Leave': 'bg-[#d1fae5] text-[#15803d]', 'Not Started': 'bg-[#f0fdf4] text-[#64748b]', None: 'bg-[#f0fdf4] text-[#94a3b8]', 'No expiry': 'bg-[#f0fdf4] text-[#94a3b8]', 'In Review': 'bg-[#d1fae5] text-[#15803d]'
  };
  const cls = map[status] || 'bg-[#f0fdf4] text-[#64748b]';
  if (!status) return `<span class="pill ${cls}">—</span>`;
  return `<span class="pill ${cls}">${esc(status)}</span>`;
}
function avatar(person, size = 34) {
  const name = typeof person === 'string' ? person : (person && (person.full_name || person.name)) || 'Unknown';
  const img = (typeof person === 'object' && person && person.avatar) || '';
  const isUrl = /^https?:|^\/|^data:/.test(img);
  const dim = { width: size + 'px', height: size + 'px', fontSize: Math.max(10, size * 0.36) + 'px' };
  const style = Object.entries(dim).map(([k, v]) => `${k}:${v}`).join(';');
  if (isUrl) return `<div class="avatar" style="${style}"><img src="${esc(img)}" alt="${esc(name)}" onerror="this.remove()"></div>`;
  return `<div class="avatar" style="${style}" title="${esc(name)}">${esc(img || initialsOf(name))}</div>`;
}
function personLine(person, sub = '', size = 34) {
  if (!person) return `<span class="text-[#94a3b8]">—</span>`;
  const name = person.full_name || person.name || 'Unknown';
  return `<div class="flex items-center gap-2.5 min-w-0">${avatar(person, size)}<div class="min-w-0"><div class="font-medium truncate">${esc(name)}</div>${sub ? `<div class="text-[11.5px] text-[#94a3b8] truncate">${esc(sub)}</div>` : `<div class="text-[11.5px] text-[#94a3b8] truncate">${esc(person.designation || person.email || '')}</div>`}</div></div>`;
}
function kpiCard(label, value, hint, opts = {}) {
  const tone = opts.tone || 'default';
  const tones = { default: 'text-[#052e16]', good: 'text-[#0f9d58]', warn: 'text-[#b7791f]', bad: 'text-[#c0392b]', brand: 'text-[#15803d]' };
  // one class attribute only - a second `class` on the same tag is dropped by the parser
  const cls = 'kpi keka-card p-4' + (opts.onclick ? ' cursor-pointer' : '');
  const click = opts.onclick ? `onclick="${opts.onclick}"` : '';
  return `<div ${click} class="${cls}"><div class="text-[10.5px] uppercase tracking-[0.09em] text-[#94a3b8] font-semibold">${esc(label)}</div><div class="font-display font-bold text-[24px] mt-1.5 ${tones[tone]} num">${value}</div>${hint ? `<div class="text-[11.5px] text-[#94a3b8] mt-1 leading-snug">${hint}</div>` : ''}</div>`;
}
function emptyState(title, sub, action = '') {
  return `<div class="empty"><div class="text-[14px] font-medium text-[#64748b]">${esc(title)}</div>${sub ? `<div class="text-[12.5px] mt-1">${esc(sub)}</div>` : ''}${action ? `<div class="mt-3">${action}</div>` : ''}</div>`;
}
function section(title, sub, body, right = '') {
  return `<div class="keka-card p-5"><div class="flex items-start justify-between gap-4 mb-4"><div><h3 class="font-display font-semibold text-[15px]">${esc(title)}</h3>${sub ? `<p class="text-[12.5px] text-[#94a3b8] mt-0.5">${esc(sub)}</p>` : ''}</div>${right}</div>${body}</div>`;
}

/* ---------------------------- api client ---------------------------- */
async function api(path, options = {}) {
  const opts = { headers: {}, ...options };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Signed out'); }
  const ctype = res.headers.get('Content-Type') || '';
  const payload = ctype.includes('json') ? await res.json() : { error: await res.text() };
  if (!res.ok || payload.success === false) {
    const message = payload.error || payload.message || `Request failed (${res.status})`;
    if (!options.quiet) toast(message, 'error');
    throw new Error(message);
  }
  return payload;
}
async function apiQuiet(path) { try { return await api(path, { quiet: true }); } catch (e) { return null; } }

function toast(msg, type = 'info') {
  const tones = { success: 'bg-[#0f9d58]', error: 'bg-[#c0392b]', info: 'bg-[#052e16]', warn: 'bg-[#b7791f]' };
  const wrap = $('#toastWrap');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = `toast text-white text-[13px] px-4 py-3 rounded-xl shadow-2xl ${tones[type] || tones.info} max-w-[380px]`;
  el.innerHTML = `<div class="flex items-start gap-2"><i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'} mt-0.5"></i><span>${esc(msg)}</span></div>`;
  wrap.appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity .3s, transform .3s'; el.style.opacity = 0; el.style.transform = 'translateX(18px)'; setTimeout(() => el.remove(), 320); }, 4200);
}

/* ---------------------------- modal system ---------------------------- */
function openModal(title, bodyHtml, footHtml = '', size = 'max-w-2xl') {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = bodyHtml;
  $('#modalFoot').innerHTML = footHtml;
  $('#modalShell').className = `modal-card bg-white rounded-2xl w-full ${size} max-h-[92vh] flex flex-col overflow-hidden shadow-2xl`;
  const back = $('#modalBackdrop');
  back.classList.remove('hidden'); back.classList.add('flex');
  const first = $('#modalBody').querySelector('input,select,textarea,button');
  if (first) setTimeout(() => first.focus(), 60);
  return $('#modalBody');
}
function closeAllModals() { const b = $('#modalBackdrop'); b.classList.add('hidden'); b.classList.remove('flex'); }
function modalFootSave(onclick, label = 'Save') {
  return `<button onclick="closeAllModals()" class="btn btn-ghost mr-auto">Cancel</button><button onclick="${onclick}" class="btn btn-primary">${esc(label)}</button>`;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeAllModals(); $('#globalResults')?.classList.add('hidden'); } });

async function confirmAction(message, run, okLabel = 'Confirm') {
  openModal('Please confirm', `<p class="text-[13.5px] text-[#475569] leading-relaxed">${esc(message)}</p>`,
    `<button onclick="closeAllModals()" class="btn btn-ghost mr-auto">Cancel</button><button id="confirmGo" class="btn btn-danger">${esc(okLabel)}</button>`, 'max-w-md');
  $('#confirmGo').onclick = async () => { $('#confirmGo').disabled = true; try { await run(); closeAllModals(); } catch (e) { $('#confirmGo').disabled = false; } };
}

/* form helpers ------------------------------------------------------------ */
function fieldRow(label, name, value, opts = {}) {
  const req = opts.required ? ' *' : '';
  const hint = opts.hint ? `<div class="text-[11px] text-[#94a3b8] mt-1">${opts.hint}</div>` : '';
  const cls = opts.class || 'field';
  let input;
  if (opts.type === 'select') {
    const options = (opts.options || []).map(o => typeof o === 'string'
      ? `<option value="${esc(o)}" ${String(o) === String(value ?? '') ? 'selected' : ''}>${esc(o)}</option>`
      : `<option value="${esc(o.value)}" ${String(o.value) === String(value ?? '') ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
    input = `<select id="${name}" class="${cls}" ${opts.disabled ? 'disabled' : ''} ${opts.onchange ? `onchange="${opts.onchange}"` : ''}>${opts.placeholder ? `<option value="">${esc(opts.placeholder)}</option>` : ''}${options}</select>`;
  } else if (opts.type === 'textarea') {
    input = `<textarea id="${name}" rows="${opts.rows || 3}" class="${cls}" placeholder="${esc(opts.placeholder || '')}" ${opts.required ? 'required' : ''} ${opts.minlength ? `minlength="${opts.minlength}"` : ''} ${opts.disabled ? 'disabled' : ''}>${esc(value || '')}</textarea>`;
  } else if (opts.type === 'checkbox') {
    return `<label class="flex items-center gap-2 text-[13px] cursor-pointer"><input type="checkbox" id="${name}" ${value ? 'checked' : ''} class="rounded border-[#cbd5e1] text-[#15803d]"><span>${esc(label)}${opts.hint ? ` <span class="text-[11.5px] text-[#94a3b8]">${opts.hint}</span>` : ''}</span></label>`;
  } else {
    input = `<input id="${name}" type="${opts.type || 'text'}" value="${esc(value ?? '')}" class="${cls}" placeholder="${esc(opts.placeholder || '')}" ${opts.required ? 'required' : ''} ${opts.step ? `step="${opts.step}"` : ''} ${opts.min !== undefined ? `min="${opts.min}"` : ''} ${opts.max !== undefined ? `max="${opts.max}"` : ''} ${opts.disabled ? 'disabled' : ''} ${opts.oninput ? `oninput="${opts.oninput}"` : ''}>`;
  }
  return `<div><label class="lbl" for="${name}">${esc(label)}${req}</label>${input}${hint}</div>`;
}
function formValues(ids) {
  const out = {};
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    out[id] = el.type === 'checkbox' ? el.checked : (el.value === '' ? null : el.value);
  });
  return out;
}
function needValue(id, message) {
  const el = document.getElementById(id);
  const v = el ? String(el.value || '').trim() : '';
  if (!v) { toast(message || 'This field is required', 'error'); el && el.focus(); throw new Error(message); }
  return v;
}
function grid(cols, html) { return `<div class="grid grid-cols-1 ${cols} gap-3">${html}</div>`; }

/* ---------------------------- nav / boot ---------------------------- */
const MODULE_TITLES = {
  home: ['Home', () => `Here is what is happening at Modish today, ${APP.user.name.split(' ')[0]}.`],
  me: ['Me', () => 'Your profile, documents, balances and pay records.'],
  inbox: ['Inbox', () => 'Approvals waiting on you.'],
  chat: ['Chat', () => 'Private one-to-one conversations with your colleagues.'],
  employees: ['Employees', () => 'The full directory, joiners and exits.'],
  orgchart: ['Organization Chart', () => 'Reporting lines, hierarchy depth and department structure.'],
  documents: ['Documents', () => 'Every file on record, why it was filed and who may see it.'],
  attendance: ['Attendance', () => 'Punch records, corrections and monthly summaries.'],
  leave: ['Leave', () => 'Balances, applications and approvals.'],
  timesheet: ['Timesheet', () => 'Log project hours and get the week approved.'],
  payroll: ['Payroll', () => 'Payslips and earnings structure.'],
  expenses: ['Expenses', () => 'Claims, approvals and reimbursements.'],
  hiring: ['Hiring', () => 'Requisitions, pipeline and offers.'],
  performance: ['Performance', () => 'Goals, reviews, feedback and check-ins.'],
  reports: ['Reports', () => 'Run, filter and export HR reports.']
};
const LOADERS = {
  home: loadDashboard, me: loadMe, inbox: loadInbox, chat: () => window.EkkaaChat.load(), employees: loadEmployees, orgchart: loadOrgChart,
  documents: loadDocuments, attendance: loadAttendance, leave: loadLeave, timesheet: loadTimesheet,
  payroll: loadPayroll, expenses: loadExpenses, hiring: loadHiring, performance: loadPerformance, reports: loadReports
};
let currentModule = 'home';

function switchModule(mod) {
  if (!canOpenModule(mod)) {
    toast(`${moduleLabel(mod)} is only available to HR Admins`, 'warn');
    mod = 'home';
  }
  if (!document.getElementById('module-' + mod)) mod = 'home';
  currentModule = mod;
  $$('.module-section').forEach(s => s.classList.toggle('active', s.id === 'module-' + mod));
  $$('.nav-item').forEach(a => a.classList.toggle('active', a.dataset.module === mod));
  const meta = MODULE_TITLES[mod] || [mod, () => ''];
  $('#pageTitle').textContent = meta[0];
  $('#pageSubtitle').textContent = meta[1]();
  if (LOADERS[mod]) LOADERS[mod](!APP.dirty[mod]);
  APP.dirty[mod] = true;
  localStorage.setItem('ekkaa.module', mod);
  $('main')?.scrollTo?.({ top: 0 });
  document.querySelector('main').scrollTop = 0;
}

function applyRoleGating() {
  // nav: show only the modules this login was granted
  const mine = allowedModules();
  if (mine) $$('a[data-module]').forEach(a => {
    const on = a.dataset.module === 'chat' || mine.includes(a.dataset.module);
    if (on) { a.style.display = ''; a.classList.remove('hidden'); }
    else { a.style.display = 'none'; a.classList.add('hidden'); }
  });
  // a sidebar group with nothing left in it takes its heading along
  const seen = new Set();
  $$('a[data-module]').forEach(a => {
    const group = a.parentElement && a.parentElement.parentElement;
    if (!group || group.tagName !== 'DIV' || seen.has(group)) return;
    seen.add(group);
    const links = $$('a[data-module]', group);
    group.classList.toggle('hidden', links.length > 0 && links.every(l => l.style.display === 'none'));
  });
  $$('[data-admin-only]').forEach(el => {
    if (isAdmin()) { el.classList.remove('hidden'); }
    else { el.style.display = 'none'; el.classList.add('hidden'); }
  });
  passwordNudge();
}

/* ---------------------------- sign-in security ---------------------------- */
function passwordNudge() {
  const main = document.querySelector('main');
  if (!main) return;
  const bar = $('#pwNudge');
  const needed = !!(APP.session && APP.session.must_set_password) && !sessionStorage.getItem('ekkaa.pwDone');
  if (needed && !bar) {
    const el = document.createElement('div');
    el.id = 'pwNudge';
    el.className = 'mb-4 flex items-center gap-3 rounded-2xl border border-[#f3e2bf] bg-[#fff9ec] px-4 py-3';
    el.innerHTML = `<i class="fas fa-key text-[#b7791f]"></i>
      <div class="text-[12.5px] text-[#7a5c14] flex-1">You signed in with the shared HR password. Set your own so your attendance, payslips and documents stay yours alone.</div>
      <button onclick="openPasswordModal()" class="btn btn-primary btn-xs">Set my password</button>
      <button onclick="document.getElementById('pwNudge').remove();sessionStorage.setItem('ekkaa.pwDone','1')" class="btn btn-ghost btn-xs">Later</button>`;
    main.insertBefore(el, main.firstChild);
  } else if (bar && !needed) {
    bar.remove();
  }
}
function openPasswordModal() {
  const sec = (APP.session && APP.session.security) || {};
  const min = sec.min_length || 8;
  const own = !!sec.has_own_password;
  const who = (APP.session && APP.session.user && APP.session.user.email) || APP.user.email || 'this account';
  const row = (id, label, ph) => `<div><div class="lbl">${label}</div><input id="${id}" type="password" autocomplete="${id === 'pwCur' ? 'current-password' : 'new-password'}" class="field" placeholder="${ph}" minlength="${min}"></div>`;
  openModal('Sign-in security', `<p class="text-[12.5px] text-[#64748b] mb-4">You sign in as <b>${esc(who)}</b> with ${own ? 'a password only you know' : 'the shared HR password'}. Passwords need at least ${min} characters.</p>
    <div class="space-y-3">${row('pwCur', 'Current password', 'the one you used today')}${row('pwNew', 'New password', `at least ${min} characters`)}${row('pwNew2', 'Repeat the new password', 'type it once more')}</div>
    <div class="text-[11.5px] text-[#94a3b8] mt-3">Nobody else can set it for you, and you cannot see it afterwards - only HR can issue a replacement if you forget it.</div>`,
    modalFootSave('submitPasswordChange()', 'Save new password'));
}
async function submitPasswordChange() {
  const val = id => ((document.getElementById(id) || {}).value || '');
  const cur = val('pwCur'), nw = val('pwNew'), nw2 = val('pwNew2');
  const min = ((APP.session && APP.session.security) || {}).min_length || 8;
  if (!cur) { toast('Enter your current password first', 'error'); return; }
  if (nw.length < min) { toast(`The new password needs at least ${min} characters`, 'error'); return; }
  if (nw !== nw2) { toast('The two new passwords do not match', 'error'); return; }
  let r;
  try { r = await api('/api/me/password', { method: 'POST', body: { current_password: cur, new_password: nw } }); } catch (e) { return; }
  toast(r.message || 'Password updated', 'success');
  if (APP.session) APP.session.must_set_password = false;
  sessionStorage.setItem('ekkaa.pwDone', '1');
  $('#pwNudge')?.remove();
  closeAllModals();
  if (currentModule === 'me') loadMe(true);
}

async function loadLookups(force) {
  if (APP.lookups && !force) return APP.lookups;
  APP.lookups = await api('/api/lookups');
  return APP.lookups;
}
function deptName(id) { const d = (APP.lookups?.departments || []).find(x => String(x.id) === String(id)); return d ? d.name : '—'; }
function desigName(id) { const d = (APP.lookups?.designations || []).find(x => String(x.id) === String(id)); return d ? d.title : '—'; }
function empById(id) { return (APP.lookups?.employees || []).find(x => String(x.id) === String(id)); }
function empName(id, field = 'full_name') { const e = empById(id); return e ? e[field] : '—'; }
function fillSelect(sel, options, selected, placeholder) {
  const el = typeof sel === 'string' ? $(sel) : sel;
  if (!el) return;
  el.innerHTML = (placeholder !== false ? `<option value="">${esc(placeholder || 'Any')}</option>` : '') +
    options.map(o => typeof o === 'string'
      ? `<option value="${esc(o)}" ${String(o) === String(selected ?? '') ? 'selected' : ''}>${esc(o)}</option>`
      : `<option value="${esc(o.value)}" ${String(o.value) === String(selected ?? '') ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
}
function employeeOptions(includeAll = 'All employees') {
  const list = (APP.lookups?.employees || []).slice().sort((a, b) => a.full_name.localeCompare(b.full_name));
  return [{ value: '', label: includeAll }, ...list.map(e => ({ value: e.id, label: `${e.full_name} · ${e.employee_code}` }))];
}

async function bootApp() {
  applyRoleGating();
  await loadLookups();
  // sidebar
  $('#sidebarToggle')?.addEventListener('click', () => $('#sidebar').classList.toggle('sidebar-collapsed'));
  $('#profileSwitcher')?.addEventListener('click', e => { e.stopPropagation(); $('#profileDropdown').classList.toggle('hidden'); });
  document.addEventListener('click', () => $('#profileDropdown')?.classList.add('hidden'));
  // nav
  $$('.nav-item').forEach(a => a.addEventListener('click', () => switchModule(a.dataset.module)));
  // module tab clicks
  document.addEventListener('click', e => {
    const tab = e.target.closest('[data-orgtab],[data-doctab],[data-attview],[data-leave],[data-tstab],[data-paytab],[data-hiringtab],[data-perftab]');
    if (!tab) return;
    const group = Object.keys(tab.dataset).find(k => k.startsWith('data') === false && /^(orgtab|doctab|attview|leave|tstab|paytab|hiringtab|perftab)$/.test(k.replace(/^on/, '')));
    const kind = ['orgtab', 'doctab', 'attview', 'leave', 'tstab', 'paytab', 'hiringtab', 'perftab'].find(k => tab.dataset[k] !== undefined);
    const value = tab.dataset[kind];
    const container = tab.closest('.module-section') || document;
    $$(`[data-${kind}]`, container).forEach(t => t.classList.toggle('active', t === tab));
    const paneAttr = { orgtab: 'orgpane', doctab: 'doctabpane', attview: 'attpane', leave: null, tstab: 'tspane', paytab: 'paypane', hiringtab: 'hiringpane', perftab: 'perfpane' }[kind];
    if (paneAttr) $$(`[data-${paneAttr}]`, container).forEach(p => p.classList.toggle('active', p.dataset[paneAttr] === value));
  });
  // global search
  const gs = $('#globalSearch');
  if (gs) {
    gs.addEventListener('input', debounce(() => runGlobalSearch(gs.value), 260));
    gs.addEventListener('focus', () => { if (gs.value.length > 1) runGlobalSearch(gs.value); });
    document.addEventListener('click', e => { if (!e.target.closest('#globalSearch') && !e.target.closest('#globalResults')) $('#globalResults')?.classList.add('hidden'); });
  }
  initClock();
  const saved = localStorage.getItem('ekkaa.module');
  switchModule(saved && document.getElementById('module-' + saved) ? saved : 'home');
  const sess = await apiQuiet('/api/session');
  if (sess) { APP.session = sess; APP.officeDate = sess.office_date || APP.officeDate; APP.officeTime = sess.office_time || APP.officeTime; APP.user.employee_id = sess.employee?.id || APP.user.employee_id; APP.user.role = sess.is_admin ? 'HR Admin' : 'Employee'; applyRoleGating(); }
  window.EkkaaChat.init();
}

async function runGlobalSearch(q) {
  const box = $('#globalResults');
  q = (q || '').trim();
  if (q.length < 2) { box.classList.add('hidden'); return; }
  const lc = q.toLowerCase();
  const emps = (APP.lookups?.employees || []).filter(e => `${e.full_name} ${e.employee_code} ${e.email}`.toLowerCase().includes(lc)).slice(0, 6);
  box.innerHTML = `<div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold px-3 pt-2 pb-1">Jump to</div>` +
    (emps.length ? emps.map(e => `<button onclick="openEmployeeDetail('${e.id}');document.getElementById('globalResults').classList.add('hidden')" class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-[#f0fdf4] text-left"><span style="width:26px;height:26px;font-size:10px" class="avatar">${esc(initialsOf(e.full_name))}</span><span class="text-[13px] font-medium">${esc(e.full_name)}</span><span class="text-[11.5px] text-[#94a3b8] ml-auto">${esc(e.employee_code)}</span></button>`).join('') : `<div class="px-3 py-2 text-[12.5px] text-[#94a3b8]">No people match “${esc(q)}”.</div>`) +
    `<div class="border-t border-[#f1f5f9] mt-1 pt-1">${[['employees', 'Employees'], ['documents', 'Documents'], ['leave', 'Leave'], ['reports', 'Reports']].map(([m, l]) => `<button onclick="switchModule('${m}');document.getElementById('globalResults').classList.add('hidden')" class="w-full text-left px-3 py-2 rounded-lg hover:bg-[#f0fdf4] text-[13px] text-[#15803d]">Search ${l} for “${esc(q)}”</button>`).join('')}</div>`;
  box.classList.remove('hidden');
  if (currentModule === 'employees') { $('#empSearch').value = q; APP.empPage = 1; loadEmployees(); }
}

/* ---------------------------- home ---------------------------- */
function renderDashboardWelcome(now = new Date()) {
  const dateEl = $('#dashboardDate');
  const greetingEl = $('#dashboardGreeting');
  if (!dateEl || !greetingEl) return;

  // Prefer the office date sent by Flask so the welcome widget agrees with attendance
  // and the rest of the dashboard when the browser and server use different timezones.
  const officeDate = APP.officeDate || now.toISOString().slice(0, 10);
  const date = new Date(`${officeDate}T00:00:00`);
  const dateLabel = isNaN(date) ? officeDate : date.toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'
  });
  const hour = APP.officeTime ? Number(String(APP.officeTime).slice(0, 2)) : now.getHours();
  const part = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
  const name = String(APP.user.name || APP.user.full_name || 'there').trim().split(/\s+/)[0] || 'there';

  dateEl.textContent = dateLabel;
  greetingEl.innerHTML = `Good ${part}, ${esc(name)} <span class="text-[#15803d]" aria-hidden="true">✦</span>`;
}

function initClock() {
  const tick = () => {
    const now = new Date();
    const el = $('#liveClock'); if (!el) return;
    el.textContent = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
    $('#liveDate').textContent = now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    renderDashboardWelcome(now);
  };
  tick(); setInterval(tick, 1000);
}

async function loadDashboard(refresh) {
  const wrap = $('#homeKpis');
  if (refresh) wrap.innerHTML = '<div class="spin"></div>';
  let s;
  try { s = await api('/api/stats'); } catch (e) { wrap.innerHTML = emptyState('Could not load the dashboard', 'Check the server log and reload.'); return; }
  APP.stats = s;
  renderHomeKpis(s);
  renderTracker(s.my_time);
  renderTodayWidget(s.today);
  renderAttendanceTrend(s.attendance_trend, s.present_delta);
  renderDeptChart(s.department_distribution);
  renderPendingActions(s.pending_actions);
  updateBadges(s);
  loadAnnouncements();
  $('#pageSubtitle').textContent = MODULE_TITLES.home[1]() + ` ${s.total_employees} people, ${s.present_today} in today.`;
}

function renderHomeKpis(s) {
  if (!isAdmin()) {
    // an employee's Home is about them: no headcount, hiring or directory numbers
    const t = s.my_time || {}, today0 = s.today || {}, hol = today0.next_holiday;
    $('#homeKpis').innerHTML = [
      kpiCard('My day', esc(t.status || 'Not clocked in'), t.clocked_in
        ? `${(t.worked_hours || 0).toFixed(1)} h worked · in at ${esc(t.clock_in)}${t.clock_in_location && t.clock_in_location !== 'Office' ? ` · ${esc(t.clock_in_location)}` : ''}`
        : esc(t.shift_label || 'Your shift'), { tone: /absent/i.test(t.status || '') ? 'bad' : 'good', onclick: "switchModule('attendance')" }),
      kpiCard('Waiting on approval', s.pending_total, `${s.pending_leaves} leave · ${s.pending_expenses} expenses · ${s.pending_documents} documents`,
        { tone: s.pending_total ? 'warn' : 'default', onclick: "switchModule('inbox')" }),
      kpiCard('On leave today', s.on_leave, 'Approved leave running across Modish', { onclick: "switchModule('leave')" }),
      kpiCard('Attendance rate', `${s.attendance_rate}%`, `of ${s.expected_today} people expected in today`,
        { tone: s.attendance_rate >= 90 ? 'good' : s.attendance_rate >= 80 ? 'warn' : 'bad' }),
      kpiCard('Holidays ahead', today0.holidays_left || 0, hol ? `Next: ${esc(hol.name)} · ${fmtDate(hol.date)}` : 'Nothing scheduled', { onclick: "switchModule('leave')" }),
    ].join('');
    return;
  }
  const rateTone = s.attendance_rate >= 90 ? 'good' : s.attendance_rate >= 80 ? 'warn' : 'bad';
  $('#homeKpis').innerHTML = [
    kpiCard('Total employees', s.total_employees, `${s.exited_employees} exited · ${s.joined_this_month} joined this month`, { onclick: "switchModule('employees')" }),
    kpiCard('Present today', s.present_today, `${s.wfh_today} working from home · ${s.half_day_today} half day`, { tone: 'good', onclick: "switchModule('attendance')" }),
    kpiCard('Absent today', s.absent_today, `${s.late_today} came in late`, { tone: s.absent_today ? 'bad' : 'default', onclick: "switchModule('attendance')" }),
    kpiCard('On leave', s.on_leave, 'Approved leave running today', { tone: 'warn', onclick: "switchModule('leave')" }),
    kpiCard('Attendance rate', `${s.attendance_rate}%`, `of ${s.expected_today} expected in`, { tone: rateTone }),
    kpiCard('Needs approval', s.pending_total, `${s.pending_leaves} leave · ${s.pending_expenses} expenses · ${s.pending_documents} docs`, { tone: s.pending_total ? 'warn' : 'default', onclick: "switchModule('inbox')" }),
    kpiCard('Open positions', s.open_positions, `${s.open_jobs} live jobs · ${s.applicants} applicants`, { onclick: "switchModule('hiring')" }),
  ].join('');
}

function renderTracker(t) {
  if (!t) return;
  const nameEl = $('#trackerName');
  if (nameEl) nameEl.textContent = t.employee ? `${t.employee.full_name} · ${t.employee.designation}` : 'No employee record linked';
  const dotEl = $('#trackerDot');
  if (dotEl) dotEl.className = `w-2.5 h-2.5 rounded-full ${t.clocked_in ? 'bg-green-400 tt-dot' : t.clocked_out ? 'bg-white/40' : 'bg-amber-400'}`;
  const stat = (label, value) => `<div class="bg-white/[0.07] rounded-xl p-2.5"><div class="text-white/45 text-[10px] uppercase tracking-wider">${label}</div><div class="text-white font-semibold text-[15px] num mt-0.5">${value}</div></div>`;
  $('#trackerStats').innerHTML = [
    stat('Worked', `${(t.worked_hours || 0).toFixed(1)}h`), stat('Break', `${t.break_minutes || 0}m`),
    stat('Overtime', `${(t.overtime_hours || 0).toFixed(1)}h`), stat('In', esc(t.clock_in)), stat('Out', esc(t.clock_out)),
    stat('Late', t.is_late ? 'Yes' : 'No'),
  ].join('');
  let msg, icon = 'fa-clock';
  if (t.clocked_in) { msg = `Clocked in at <b>${esc(t.clock_in)}</b> · ${t.status.toLowerCase()}`; icon = 'fa-circle-notch'; }
  else if (t.clocked_out) {   // an earlier copy of this branch shadowed it, so the punches were never shown
    const tail = t.overtime_hours > 0 ? `${t.overtime_hours}h overtime` : (t.shortfall_minutes > 0 ? `${Math.round(t.shortfall_minutes)} min short` : 'shift complete');
    msg = `Day closed · <b>${(t.worked_hours || 0).toFixed(1)}h</b> worked, in <b>${esc(t.clock_in)}</b> out <b>${esc(t.clock_out)}</b> · ${tail}. A wrong punch is fixed by HR or a regularization.`;
    icon = 'fa-lock';
  }
  else { msg = 'Not clocked in yet today'; icon = 'fa-hourglass-half'; }
  // one write per element: an earlier version replaced #clockStatus's children here, which
  // deleted #clockStatusText and made the next renderTracker() call throw on a null lookup
  const status = $('#clockStatus');
  if (status) {
    status.innerHTML = `<span class="tt-dot w-2 h-2 ${t.clocked_in ? 'bg-green-400' : 'bg-white/40'} rounded-full flex-shrink-0"></span>` +
      `<span id="clockStatusText" class="text-[13px] text-white/70"><i class="fas ${icon} mr-1 text-white/40"></i>${msg}</span>`;
  }
  const inBtn = $('#btnClockIn'), outBtn = $('#btnClockOut');
  const open = !!t.clocked_in, closed = !!t.clocked_out;      // one punch pair a day: closed is closed
  if (inBtn) {
    inBtn.disabled = open || closed;
    inBtn.className = `btn justify-center ${(open || closed) ? 'bg-white/10 text-white/40 cursor-not-allowed' : '!bg-white !text-[#052e16] hover:bg-white/90'}`;
    inBtn.textContent = closed ? 'Day closed' : open ? 'Clocked in' : 'Clock in';
    inBtn.title = closed ? 'Today is already closed - ask HR to edit the record or file a regularization' : '';
  }
  if (outBtn) {
    outBtn.disabled = !open;
    outBtn.className = `btn justify-center ${t.clocked_in ? '!bg-[#ff5a5a] text-white hover:brightness-95' : 'bg-white/10 text-white/40 cursor-not-allowed'}`;
    outBtn.textContent = t.clocked_out ? 'Clocked out' : 'Clock out';
  }
  $('#trackerShift') && ($('#trackerShift').textContent = t.shift_label || '');
  // where the punches happened: GPS pins are surfaced here as well as in Attendance
  const locLine = $('#trackerLocLine'), locTxt = $('#trackerLocText');
  if (locLine && locTxt) {
    const where = [];
    if (t.clock_in_location) where.push(`In: ${t.clock_in_location}`);
    if (t.clock_out_location) where.push(`Out: ${t.clock_out_location}`);
    if (where.length) {
      locLine.classList.remove('hidden');
      locTxt.textContent = where.join(' · ');
      locTxt.title = where.join(' · ');
    } else locLine.classList.add('hidden');
  }
}

/* ---------------------------- punch location (GPS) ---------------------------- */
// Best-effort GPS pin captured on every Clock in / Clock out. The W3C Geolocation API is
// the only browser-native way to get real coordinates; when it is missing, permission is
// denied, GPS is off (no network fallback either) or the request times out, the punch
// simply has no pin and the server records "Office" - nobody is ever blocked by a
// privacy prompt. clockAction() surfaces *why* the pin is missing as a warn toast so the
// employee can actually fix it (allow location / turn on GPS) instead of silently
// getting "Office" every day.
// NOTE: geolocation only works on a secure page (https, or http://localhost while
// developing). On plain http over a LAN IP the API does not exist at all - reason
// "insecure" below tells the user exactly that.
function reverseGeo(lat, lng) {
  const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}&zoom=16&accept-language=en`;
  return Promise.race([
    fetch(url).then(r => (r.ok ? r.json() : null)).then(j =>
      (j && (j.display_name || (j.address && j.address.road)) || '').slice(0, 140) || null).catch(() => null),
    new Promise(r => setTimeout(() => r(null), 3500)),
  ]);
}

// navigator.geolocation.getCurrentPosition is callback-based (it returns nothing), so it
// must be wrapped in a Promise with real success + error callbacks. A previous version
// passed the options object as the success callback and the punch never got coordinates.
function geoPosition(options) {
  return new Promise(resolve => {
    if (!navigator.geolocation || typeof navigator.geolocation.getCurrentPosition !== 'function') {
      resolve({ reason: window.isSecureContext ? 'unsupported' : 'insecure' });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ pos }),
      err => resolve({ reason: { 1: 'denied', 2: 'unavailable', 3: 'timeout' }[err.code] || 'unavailable' }),
      options,
    );
  });
}

async function geoTag() {
  const done = (out, extra) => Object.assign(out, extra || {});
  // 1) Precise pass first: enableHighAccuracy asks the device for GPS (this is also what
  //    makes Android/Chrome suggest turning the GPS on when it is off).
  const first = await geoPosition({ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
  let pos = first.pos;
  // 2) GPS off / slow fix? one cheaper pass over Wi-Fi/cell network location, which
  //    usually still pins the right building even with GPS switched off.
  if (!pos) {
    const second = await geoPosition({ enableHighAccuracy: false, timeout: 7000, maximumAge: 30000 });
    pos = second.pos;
    if (!pos) {
      const reason = (first.reason === 'denied' || second.reason === 'denied') ? 'denied'
        : (first.reason === 'insecure' || second.reason === 'insecure') ? 'insecure'
        : (first.reason === 'timeout' || second.reason === 'timeout') ? 'timeout' : 'unavailable';
      // 3) last resort: pin from the network IP. Works on plain http (where the browser
      //    GPS API does not exist at all) and needs no permission - but it is city-level,
      //    so the stored address says so.
      const ip = await ipLocation();
      if (Number.isFinite(Number(ip.lat)) && Number.isFinite(Number(ip.lng))) return done({ ...ip, via: 'ip' });
      return done({}, { reason });
    }
  }
  const la = Number(pos && pos.coords && pos.coords.latitude);
  const lo = Number(pos && pos.coords && pos.coords.longitude);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return done({}, { reason: 'unavailable' });
  const out = { lat: la, lng: lo };
  const acc = Number(pos.coords.accuracy);
  if (Number.isFinite(acc)) out.accuracy = acc;
  const addr = await reverseGeo(la, lo);
  if (addr) out.address = addr;
  return done(out);
}

// IP-based location fallback (no permission prompt, works on http too). Two public
// services are tried in order; both are CORS-friendly and need no API key.
async function ipLocation() {
  if (typeof fetch !== 'function') return {};
  const lookup = async (url) => {
    try {
      const res = await Promise.race([fetch(url), new Promise(r => setTimeout(() => r(null), 4000))]);
      if (!res || !res.ok) return null;
      const j = await res.json();
      const lat = Number(j && (j.latitude ?? j.lat)), lng = Number(j && (j.longitude ?? j.lon));
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
      const where = [j.city, j.region, j.country].filter(Boolean).join(', ');
      return { lat, lng, ...(where ? { address: `${where} (approx. IP location)` } : {}) };
    } catch (e) { return null; }
  };
  return (await lookup('https://ipwho.is/')) || (await lookup('https://get.geojs.io/v1/ip/geo.json')) || {};
}

const PUNCH_LOCATION_HINTS = {
  denied: 'Location permission is blocked for this site - allow Location in the browser and clock again for a precise pin.',
  unavailable: 'Could not get your location (GPS off, no network location, IP lookup failed) - the punch was saved with "Office".',
  timeout: 'Getting your location took too long and the IP fallback failed - the punch was saved with "Office".',
  insecure: 'Browser GPS needs a secure page (https or localhost) - the pin is approximate from your network IP.',
  unsupported: 'This browser does not support live location - the pin is approximate from your network IP.',
};

async function clockAction(action) {
  const busy = action === 'in' ? $('#btnClockIn') : $('#btnClockOut');
  const prev = { text: busy ? busy.textContent : '', dis: busy ? busy.disabled : false };
  if (busy) { busy.disabled = true; busy.textContent = 'Locating…'; busy.classList.add('cursor-wait'); }
  try {
    const loc = await geoTag();
    const reason = loc.reason, viaIp = loc.via;
    delete loc.reason;
    delete loc.via;
    const res = await api('/api/attendance/clock', { method: 'POST', body: { action, ...loc } });
    const att = res.attendance || {};
    const pin = action === 'in' ? att.clock_in_location_label : att.clock_out_location_label;
    toast(res.message + (pin ? ` · 📍 ${pin}` : ''), 'success');
    if (viaIp) setTimeout(() => toast('GPS was not available, so this pin is approximate (network IP level).', 'info'), 700);
    else if (reason) setTimeout(() => toast(PUNCH_LOCATION_HINTS[reason] || PUNCH_LOCATION_HINTS.unavailable, 'warn'), 700);
    loadDashboard(true);
    if (currentModule === 'attendance') loadAttendance(true);
  } catch (e) { /* toast already shown */
    if (busy) { busy.textContent = prev.text || (action === 'in' ? 'Clock in' : 'Clock out'); busy.disabled = prev.dis; busy.classList.remove('cursor-wait'); }
  }
}

function renderTodayWidget(t) {
  if (!t) return;
  $('#todayDate').textContent = t.short_label || '';
  const b = $('#todayBirthdaysList');
  b.innerHTML = (t.birthdays || []).length ? t.birthdays.map(p => `<div class="flex items-center gap-2 bg-[#fff4e6] rounded-full pl-1 pr-3 py-1"><span style="width:24px;height:24px;font-size:9.5px" class="avatar">${esc(p.avatar || initialsOf(p.name))}</span><span class="text-[12.5px] font-medium">${esc(p.name)}</span><span class="text-[11px] text-[#b7791f]">turning ${p.turning}</span></div>`).join('')
    : (t.upcoming_birthdays || []).length ? `<div class="text-[12px] text-[#94a3b8]">None today · next: ${t.upcoming_birthdays.map(p => `${esc(p.name)} in ${p.days_left}d`).join(', ')}</div>`
    : `<div class="text-[12px] text-[#94a3b8]">No birthdays today or in the next two weeks.</div>`;
  $('#todayAnniversariesList').innerHTML = (t.anniversaries || []).length ? t.anniversaries.map(p => `<div class="flex items-center gap-2 text-[12.5px]"><span style="width:22px;height:22px;font-size:9px" class="avatar">${esc(p.avatar || initialsOf(p.name))}</span><span class="font-medium">${esc(p.name)}</span><span class="pill bg-[#d1fae5] text-[#15803d] ml-auto">${p.years} yr${p.years > 1 ? 's' : ''}</span></div>`).join('') : `<div class="text-[12px] text-[#94a3b8]">No work anniversaries today.</div>`;
  $('#todayOnLeaveList').innerHTML = (t.on_leave || []).length ? t.on_leave.map(p => `<div class="flex items-center gap-2 text-[12.5px]"><span style="width:22px;height:22px;font-size:9px" class="avatar">${esc(p.avatar || initialsOf(p.name))}</span><div class="min-w-0"><div class="truncate">${esc(p.name)}</div></div><span class="pill bg-[#f0fdf4] text-[#64748b] ml-auto">${esc(p.leave_type)}</span></div>`).join('') : `<div class="text-[12px] text-[#94a3b8]">Everyone is in today.</div>`;
  $('#todayHolidayRow').innerHTML = t.next_holiday
    ? `<div class="flex items-center gap-2"><i class="fas fa-umbrella-beach text-[#15803d]"></i><div class="text-[12.5px]"><b>${esc(t.next_holiday.name)}</b> · ${fmtDate(t.next_holiday.date)} <span class="text-[#94a3b8]">(${t.next_holiday.days_left} days away)</span></div><span class="ml-auto text-[11.5px] text-[#94a3b8]">${t.holidays_left} left this year</span></div>`
    : `<div class="text-[12px] text-[#94a3b8]">No holidays left on the calendar.</div>`;
}

function makeChart(id, config) {
  const el = document.getElementById(id);
  if (!el) return;
  const host = el.parentElement || el;
  const fallback = host.querySelector('.css-chart');
  if (typeof Chart === 'undefined') {          // CDN blocked or offline: draw the same series as CSS bars
    el.style.visibility = 'hidden';
    const box = fallback || (() => { const d = document.createElement('div'); d.className = 'css-chart absolute inset-0 flex flex-col justify-center gap-1.5'; host.appendChild(d); return d; })();
    box.innerHTML = cssChartHtml(config);
    return;
  }
  if (fallback) fallback.remove();
  el.style.visibility = '';
  if (APP.charts[id]) APP.charts[id].destroy();
  APP.charts[id] = new Chart(el, config);
}

// Dependency-free stand-in for a Chart.js chart - same labels, same numbers, no plugin needed.
function cssChartHtml(config) {
  const labels = ((config.data || {}).labels || []).map(String);
  const sets = (((config.data || {}).datasets) || []).map(d => ({ label: d.label, color: pickColor(d.backgroundColor) || pickColor(d.borderColor) || '#15803d', data: (d.data || []).map(v => Math.max(0, Number(v) || 0)) }));
  const max = Math.max(1, ...sets.flatMap(s => s.data));
  if (!labels.length || !sets.length) return '<div class="text-[12px] text-[#94a3b8]">Nothing to plot for this period.</div>';
  const single = sets.length === 1;
  return labels.map((l, i) => `<div class="flex items-center gap-2 min-h-[15px]">
      <span class="text-[10.5px] text-[#64748b] w-[86px] shrink-0 truncate" title="${esc(l)}">${esc(l)}</span>
      <span class="flex-1 flex gap-[3px] items-end h-[13px]">${sets.map(set => `<span title="${esc(set.label || l)} · ${fmtNum(set.data[i])}" style="width:${single ? '' : '100%'};flex:1;min-width:2px;height:${Math.max(6, Math.round((set.data[i] || 0) / max * 100))}%;background:${set.color};border-radius:3px 3px 0 0;display:inline-block"></span>`).join('')}</span>
      <b class="text-[11px] num w-[46px] text-right">${fmtNum(single ? sets[0].data[i] : sets.reduce((t, x) => t + (x.data[i] || 0), 0))}</b></div>`).join('') +
    (!single ? `<div class="flex flex-wrap gap-3 pt-1 text-[10.5px] text-[#64748b]">${sets.map((set, i) => `<span class="inline-flex items-center gap-1.5"><i style="width:8px;height:8px;border-radius:3px;display:inline-block;background:${set.color}"></i>${esc(set.label || 'Series ' + (i + 1))}</span>`).join('')}</div>` : '');
}
function pickColor(v) { return typeof v === 'string' ? v : (Array.isArray(v) ? v[0] : null); }
function fmtNum(v) { const n = Number(v) || 0; return n % 1 ? n.toFixed(1) : String(Math.round(n)); }

function renderAttendanceTrend(trend, delta) {
  if (!trend || !trend.labels?.length) return;
  makeChart('attendanceTrendChart', {
    type: 'bar',
    data: {
      labels: trend.labels,
      datasets: [
        { type: 'line', label: 'Present %', data: trend.present_pct, borderColor: '#15803d', backgroundColor: 'rgba(21,128,61,.12)', borderWidth: 2.4, tension: .34, pointRadius: 2.5, pointHoverRadius: 5, yAxisID: 'y1', fill: true },
        { label: 'On leave', data: trend.on_leave, backgroundColor: '#ffd79a', borderRadius: 4, stack: 'x', yAxisID: 'y' },
        { label: 'Late', data: trend.late.map((v, i) => v), backgroundColor: '#ffb4b4', borderRadius: 4, stack: 'x2', yAxisID: 'y' },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 9, boxHeight: 9, usePointStyle: true, font: { size: 11 } } } },
      scales: { y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: '#f1f5f9' } }, y1: { position: 'right', min: 0, max: 100, ticks: { callback: v => v + '%', font: { size: 10 } }, grid: { display: false } }, x: { ticks: { font: { size: 9.5 }, maxRotation: 0, autoSkipPadding: 8 }, grid: { display: false } } } }
  });
  const pill = $('#attendanceDelta');
  const d = num(delta);
  pill.textContent = `${d >= 0 ? '▲' : '▼'} ${Math.abs(d)} vs yesterday`;
  pill.className = `pill ${d >= 0 ? 'bg-[#e6f9f0] text-[#0f9d58]' : 'bg-[#fff1f1] text-[#c0392b]'}`;
}

function renderDeptChart(dist) {
  const entries = Object.entries(dist || {}).sort((a, b) => b[1] - a[1]);
  const palette = ['#15803d', '#4ade80', '#0d9488', '#f59e0b', '#f472b6', '#60a5fa', '#94a3b8', '#0f9d58'];
  makeChart('deptChart', {
    type: 'doughnut',
    data: { labels: entries.map(e => e[0]), datasets: [{ data: entries.map(e => e[1]), backgroundColor: entries.map((_, i) => palette[i % palette.length]), borderWidth: 0, hoverOffset: 6 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: '64%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.label}: ${c.parsed} people` } } } }
  });
  const total = entries.reduce((s, e) => s + e[1], 0) || 1;
  $('#deptLegend').innerHTML = entries.map((e, i) => `<div class="flex items-center gap-2"><span style="width:9px;height:9px;border-radius:3px;background:${palette[i % palette.length]}" class="inline-block"></span><span class="truncate">${esc(e[0])}</span><span class="ml-auto text-[#94a3b8] num">${Math.round(e[1] / total * 100)}%</span></div>`).join('');
}

function renderPendingActions(items) {
  const box = $('#pendingActionsList');
  if (!items || !items.length) { box.innerHTML = emptyState('Nothing is waiting on you', 'Leave, expenses, documents and timesheet approvals will show up here.'); return; }
  box.innerHTML = items.map(a => `<div class="flex items-start gap-3 p-3 rounded-xl border border-[#f1f5f9] hover:border-[#e2e8f0] transition">
      <div class="w-8 h-8 rounded-lg bg-[#f0fdf4] flex items-center justify-center text-[15px] flex-shrink-0">${a.icon || '📌'}</div>
      <div class="min-w-0 flex-1">
        <div class="text-[13px] font-medium truncate">${esc(a.title)}</div>
        <div class="text-[11.5px] text-[#94a3b8] line-clamp-1">${esc(a.subtitle)}</div>
      </div>
      <div class="flex items-center gap-1.5 flex-shrink-0">
        ${a.approve_endpoint ? `<button onclick="quickApprove('${a.kind}','${a.id}','${esc(a.approve_endpoint)}')" class="btn btn-ghost btn-xs !py-1" title="Approve now"><i class="fas fa-check text-[#0f9d58]"></i></button>` : ''}
        <button onclick="switchModule('${a.module}')" class="btn btn-ghost btn-xs !py-1">${esc(a.module)}</button>
      </div></div>`).join('');
}

async function quickApprove(kind, id, endpoint) {
  const actions = { leave: 'approve', regularization: 'approve', expense: 'approve', timesheet: 'approve' };
  try {
    const res = await api(`/api/pending-actions/${kind}/${id}`, { method: 'POST', body: { action: actions[kind] || 'approve' } });
    toast(res.message || 'Approved', 'success');
    APP.dirty = {}; loadDashboard(true);
  } catch (e) { /* toast shown */ }
}

function updateBadges(s) {
  const badge = (el, n) => { if (!el) return; el.textContent = n; el.classList.toggle('hidden', !n); };
  badge($('#inboxBadge'), s.pending_total);
  badge($('#bellBadge'), s.pending_total);
  badge($('#docBadge'), s.pending_documents);
  if ($('#inboxTitle')) $('#inboxTitle').textContent = `Inbox (${s.pending_total} pending)`;
}


/* ================================================================== EMPLOYEES */
async function loadEmployees(refresh) {
  await loadLookups();
  if (refresh) $('#employeesTable').innerHTML = '<tr><td colspan="9"><div class="spin"></div></td></tr>';
  fillSelect('#empDeptFilter', [{ value: '', label: 'All departments' }, ...(APP.lookups.departments || []).map(d => ({ value: d.id, label: d.name }))], $('#empDeptFilter')?.value, false);
  const params = new URLSearchParams();
  const q = ($('#empSearch')?.value || '').trim();
  if (q) params.set('q', q);
  if ($('#empDeptFilter')?.value) params.set('department_id', $('#empDeptFilter').value);
  const st = $('#empStatusFilter')?.value || 'All';
  if (st !== 'All') params.set('status', st);
  if ($('#empShowExited')?.checked) params.set('include_exited', '1');
  let rows = [];
  try { rows = await api('/api/employees?' + params.toString()); } catch (e) { return; }
  APP.empRows = rows;
  renderEmpStats(rows);
  renderEmployeesTable();
}
function renderEmpStats(rows) {
  const active = rows.filter(r => r.status !== 'Exited');
  const byDept = {};
  active.forEach(r => { byDept[r.department] = (byDept[r.department] || 0) + 1; });
  const top = Object.entries(byDept).sort((a, b) => b[1] - a[1])[0];
  const thisMonth = active.filter(r => String(r.date_of_joining || '').slice(0, 7) === todayIso().slice(0, 7)).length;
  $('#empStats').innerHTML = [
    kpiCard('In view', rows.length, q2label()),
    kpiCard('Active', active.length, `${rows.length - active.length} exited or on notice`),
    kpiCard('Largest department', top ? `${top[1]}` : '—', top ? esc(top[0]) : ''),
    kpiCard('Joined this month', thisMonth, fmtDate(todayIso(), { month: 'long', year: 'numeric' })),
  ].join('');
}
function q2label() { const q = ($('#empSearch')?.value || '').trim(); return q ? `matches for “${esc(q)}”` : 'full directory'; }
function changeEmpPage(delta) { APP.empPage = Math.max(1, APP.empPage + delta); renderEmployeesTable(); }
function renderEmployeesTable() {
  const per = 12, rows = APP.empRows || [], pages = Math.max(1, Math.ceil(rows.length / per));
  APP.empPage = Math.min(APP.empPage, pages);
  const slice = rows.slice((APP.empPage - 1) * per, APP.empPage * per);
  $('#empPage').textContent = `${APP.empPage} / ${pages}`;
  $('#empCount').textContent = `${rows.length} employee${rows.length === 1 ? '' : 's'}`;
  const tb = $('#employeesTable');
  if (!slice.length) { tb.innerHTML = `<tr><td colspan="9">${emptyState('No employees match those filters', 'Clear the search or the department filter.', '<button class="btn btn-ghost btn-xs" onclick="resetEmpFilters()">Reset filters</button>')}</td></tr>`; return; }
  tb.innerHTML = slice.map(e => `<tr class="clickable" onclick="openEmployeeDetail('${e.id}')">
    <td><div class="flex items-center gap-2.5">${avatar(e)}<div class="min-w-0"><div class="font-medium truncate">${esc(e.full_name)}</div><div class="text-[11.5px] text-[#94a3b8] truncate">${esc(e.email)}</div></div></div></td>
    <td class="num text-[12px] text-[#64748b]">${esc(e.employee_code)}</td>
    <td>${esc(e.department)}</td><td>${esc(e.designation)}</td>
    <td class="text-[12.5px]">${e.manager && e.manager !== '-' ? `<span class="flex items-center gap-1.5"><span style="width:20px;height:20px;font-size:8.5px" class="avatar">${esc(e.manager_avatar || initialsOf(e.manager))}</span>${esc(e.manager)}</span>` : '<span class="text-[#94a3b8]">Top of tree</span>'}</td>
    <td class="text-[12.5px]">${esc(e.work_location)}</td>
    <td class="text-[12.5px] num">${fmtDayShort(e.date_of_joining)}<div class="text-[11px] text-[#94a3b8]">${esc(e.tenure)}</div></td>
    <td>${statusPill(e.status)}</td>
    <td class="text-right"><div class="row-actions inline-flex gap-1">
      <button onclick="event.stopPropagation();openEmployeeDetail('${e.id}')" class="btn btn-ghost btn-xs !py-1" title="View profile"><i class="far fa-eye"></i></button>
      ${isAdmin() ? `<button onclick="event.stopPropagation();openEmployeeForm('${e.id}')" class="btn btn-ghost btn-xs !py-1" title="Edit employee"><i class="far fa-pen"></i></button>` : ''}
    </div></td></tr>`).join('');
}
function resetEmpFilters() { $('#empSearch').value = ''; $('#empDeptFilter').value = ''; $('#empStatusFilter').value = 'All'; $('#empShowExited').checked = false; APP.empPage = 1; loadEmployees(true); }

async function openEmployeeDetail(id) {
  let d;
  try { d = await api('/api/employees/' + id); } catch (e) { return; }
  const e = d.employee, snap = d.snapshot || {};
  const field = (l, v) => `<div><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="text-[13px] font-medium mt-0.5">${v || '—'}</div></div>`;
  const body = `
    <div class="flex items-start gap-4 pb-5 border-b border-[#f1f5f9]">
      <div style="width:56px;height:56px;font-size:19px" class="avatar">${esc(e.avatar && e.avatar.length > 3 ? '' : initialsOf(e.full_name))}${e.avatar && e.avatar.length > 3 ? `<img src="${esc(e.avatar)}">` : ''}</div>
      <div class="min-w-0 flex-1"><div class="font-display font-bold text-[19px]">${esc(e.full_name)}</div><div class="text-[13px] text-[#64748b]">${esc(e.designation)} · ${esc(e.department)}</div>
        <div class="flex flex-wrap items-center gap-2 mt-2">${statusPill(e.status)}<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(e.employee_code)}</span><span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(e.employment_type)}</span><span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(e.work_location)}</span></div></div>
      <div class="flex gap-2 no-print">
        ${isAdmin() ? `<button onclick="openEmployeeForm('${e.id}')" class="btn btn-primary btn-xs"><i class="far fa-pen"></i> Edit</button>` : ''}
        <button onclick="switchModule('orgchart');closeAllModals()" class="btn btn-ghost btn-xs"><i class="fas fa-sitemap"></i> In org</button>
      </div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 py-5">${field('Email', `<a class="text-[#15803d] hover:underline" href="mailto:${esc(e.email)}">${esc(e.email)}</a>`)}${field('Phone', esc(e.phone))}${field('Joined', fmtDate(e.date_of_joining))}${field('Tenure', esc(e.tenure))}${field('Manager', d.manager ? esc(d.manager.full_name) : '—')}${field('Date of birth', fmtDate(e.date_of_birth))}${field('Employment', esc(e.employment_type))}${field('Location', esc(e.work_location))}</div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 pb-5">${[['Days present', snap.attendance_days_this_month, 'this month'], ['Hours', snap.hours_this_month, 'this month'], ['Leaves left', (d.leave_balances || []).reduce((s, b) => s + b.remaining, 0), 'across types'], ['Docs on file', snap.documents, `${snap.documents_pending || 0} to verify`]].map(([l, v, h]) => `<div class="bg-[#f0fdf4] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-display font-bold text-[18px] mt-0.5 num">${v ?? 0}</div><div class="text-[11px] text-[#94a3b8]">${h}</div></div>`).join('')}</div>
    ${(d.direct_reports || []).length ? `<div class="py-4 border-t border-[#f1f5f9]"><div class="lbl">Direct reports (${d.direct_reports.length})</div><div class="flex flex-wrap gap-2">${d.direct_reports.map(r => `<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(r.full_name)}</span>`).join('')}</div></div>` : ''}
    ${(d.leave_balances || []).length ? `<div class="py-4 border-t border-[#f1f5f9]"><div class="lbl">Leave balance</div><div class="grid grid-cols-2 md:grid-cols-4 gap-3">${d.leave_balances.map(b => `<div><div class="flex justify-between text-[12px]"><span>${esc(b.name || b.leave_type)}</span><b class="num">${b.remaining}/${b.total}</b></div><div class="bar mt-1"><span style="width:${b.total ? Math.round(b.used / b.total * 100) : 0}%;background:${b.color || '#15803d'}"></span></div></div>`).join('')}</div></div>` : ''}
    <div class="pt-4 border-t border-[#f1f5f9]"><div class="lbl">Last ${Math.min(14, (d.recent_attendance || []).length)} attendance days</div>
      ${(d.recent_attendance || []).length ? `<div class="flex flex-wrap gap-1.5">${d.recent_attendance.map(a => `<div class="px-2 py-1 rounded-lg text-[11.5px] border border-[#f1f5f9]" title="${esc(a.clock_in)} → ${esc(a.clock_out)} · ${a.work_hours}h"><span class="text-[#94a3b8]">${fmtDayShort(a.date)}</span> ${statusPill(a.status)}</div>`).join('')}</div>` : '<div class="text-[12.5px] text-[#94a3b8]">No attendance recorded this month.</div>'}</div>`;
  openModal('Employee profile', body, isAdmin() ? `<button onclick="resetEmployeePassword('${e.id}','${esc(e.full_name)}')" class="btn btn-ghost mr-2"><i class="fas fa-key"></i> ${e.has_own_password ? 'Reset password' : 'Issue password'}</button><button onclick="confirmDeleteEmployee('${e.id}','${esc(e.full_name)}')" class="btn btn-danger mr-auto"><i class="far fa-trash-alt"></i> Remove</button><button onclick="closeAllModals()" class="btn btn-ghost">Close</button><button onclick="openEmployeeForm('${e.id}')" class="btn btn-primary">Edit profile</button>` : `<button onclick="closeAllModals()" class="btn btn-ghost">Close</button>`, 'max-w-4xl');
}

async function resetEmployeePassword(id, name) {
  await confirmAction(`Issue a one-time password for ${name}? It replaces whatever they use today, so share it once and ask them to set their own in Me.`,
    async () => {
      const r = await api(`/api/employees/${id}/reset-password`, { method: 'POST', body: {} });
      closeAllModals();
      openModal(`One-time password for ${r.employee || name}`,
        `<p class="text-[12.5px] text-[#64748b] mb-4">This is shown once. Hand it over on a channel you trust; they replace it under <b>Me → Sign-in security</b>.</p>
         <div class="flex items-center gap-3 bg-[#f0fdf4] rounded-xl px-4 py-3"><code id="pwTemp" class="font-mono text-[17px] tracking-wide select-all">${esc(r.temp_password)}</code>
         <button onclick="copyTempPassword()" class="btn btn-ghost btn-xs ml-auto"><i class="far fa-copy"></i> Copy</button></div>`,
        '<button onclick="closeAllModals()" class="btn btn-ghost">Done</button>');
      loadEmployees(true);
    }, 'Generate password');
}
function copyTempPassword() {
  const el = $('#pwTemp');
  if (!el) return;
  const txt = el.textContent;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(() => toast('Copied', 'success'), () => toast('Select it and copy - the browser blocked the clipboard', 'warn'));
  } else {
    toast('Select it and copy', 'warn');
  }
}

async function confirmDeleteEmployee(id, name) {
  closeAllModals();
  await confirmAction(`Remove ${name} from the directory? Their history is preserved when Supabase is connected; in demo mode the record is deleted.`,
    async () => { const r = await api('/api/employees/' + id, { method: 'DELETE' }); toast(r.message, 'success'); loadEmployees(true); }, 'Remove employee');
}

/* Type-or-add fields: a text box with datalist suggestions for designation/department.
   Picking an existing name links it; typing a new one creates it through the admin-only
   create APIs when the form is saved (the server dedupes case-insensitive matches). */
function typeOrAddField(lbl, id, names, hint, value) {
  const opts = (names || []).map(n => `<option value="${esc(n)}">`).join('');
  return `<div><div class="lbl">${lbl}</div><input id="${id}" class="field" list="${id}List" autocomplete="off" placeholder="Unassigned - type to pick or add" value="${esc(value || '')}"><datalist id="${id}List">${opts}</datalist><div class="text-[11px] text-[#94a3b8] mt-1">${hint}</div></div>`;
}
async function resolveTypeOrAdd(kind, inputId, departmentId) {
  const el = document.getElementById(inputId);
  const typed = el ? el.value.trim() : '';
  if (!typed) return null;
  const lower = typed.toLowerCase();
  if (kind === 'designation') {
    const match = (APP.lookups.designations || []).find(d => String(d.title || '').trim().toLowerCase() === lower);
    if (match) return match.id;
    const r = await api('/api/designations', { method: 'POST', body: { title: typed, department_id: departmentId || null } });
    toast(r.message, 'success');
    APP.lookups = null; await loadLookups(true);
    return r.designation.id;
  }
  const match = (APP.lookups.departments || []).find(d => String(d.name || '').trim().toLowerCase() === lower);
  if (match) return match.id;
  const r = await api('/api/departments', { method: 'POST', body: { name: typed } });
  toast(r.message, 'success');
  APP.lookups = null; await loadLookups(true);
  return r.department.id;
}
async function openEmployeeForm(id) {
  await loadLookups();
  let e = {};
  if (id) { try { e = (await api('/api/employees/' + id)).employee; } catch (err) { return; } }
  const depts = (APP.lookups.departments || []).map(d => ({ value: d.id, label: d.name }));
  const desigs = (APP.lookups.designations || []).map(d => ({ value: d.id, label: d.title }));
  const mgrs = (APP.lookups.employees || []).filter(x => String(x.id) !== String(id)).map(x => ({ value: x.id, label: `${x.full_name} · ${x.employee_code}` }));
  const f = (label, name, opts = {}) => fieldRow(label, name, e[name], opts);
  const body = `<div class="space-y-4">
    ${grid('md:grid-cols-3 gap-3', [f('Full name', 'full_name', { required: true }), f('Work email', 'email', { required: true, type: 'email' }), f('Personal email', 'personal_email', { type: 'email' })].join(''))}
    ${grid('md:grid-cols-3 gap-3', [f('Phone', 'phone'), f('Employee code', 'employee_code', { placeholder: 'auto-generated' }), f('Gender', 'gender', { type: 'select', options: ['Male', 'Female', 'Other'], placeholder: 'Select' })].join(''))}
    ${grid('md:grid-cols-3 gap-3', [f('Date of birth', 'date_of_birth', { type: 'date' }), f('Date of joining', 'date_of_joining', { type: 'date' }), f('Blood group', 'blood_group', { type: 'select', options: ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-'], placeholder: 'Select' })].join(''))}
    ${grid('md:grid-cols-3 gap-3', [typeOrAddField('Department', 'department_name', depts.map(d => d.label), 'Pick an existing department or type a new one - it is created when you save.', deptName(e.department_id) !== '—' ? deptName(e.department_id) : ''), typeOrAddField('Designation', 'designation_name', desigs.map(d => d.label), 'Pick an existing title or type a new one - it is added to the list when you save.', (e.designation_id && desigName(e.designation_id) !== '—') ? desigName(e.designation_id) : ''), f('Reports to', 'manager_id', { type: 'select', options: mgrs, placeholder: 'No manager' })].join(''))}
    ${grid('md:grid-cols-4 gap-3', [f('Employment type', 'employment_type', { type: 'select', options: ['Full-time', 'Part-time', 'Contract', 'Intern'], placeholder: 'Full-time' }), f('Work location', 'work_location', { placeholder: 'Bengaluru' }), f('Annual CTC', 'salary_ctc', { type: 'number', step: 1000 }), f('Status', 'status', { type: 'select', options: ['Active', 'On Leave', 'Notice Period', 'Exited'], placeholder: 'Active' })].join(''))}
    ${grid('md:grid-cols-2 gap-3', [f('Address', 'address'), f('Nationality', 'nationality', { placeholder: 'Indian' })].join(''))}
    <details ${e.pan_no || e.bank_account_no ? 'open' : ''} class="border border-[#f1f5f9] rounded-xl p-3"><summary class="text-[12.5px] font-semibold cursor-pointer text-[#15803d]">Statutory & bank details</summary>
      <div class="mt-3">${grid('md:grid-cols-3 gap-3', [f('PAN', 'pan_no'), f('UAN', 'uan_no'), f('PF number', 'pf_no'), f('Bank', 'bank_name'), f('Account number', 'bank_account_no'), f('IFSC', 'ifsc_code')].join(''))}</div></details>
    <details ${e.emergency_contact_name ? 'open' : ''} class="border border-[#f1f5f9] rounded-xl p-3"><summary class="text-[12.5px] font-semibold cursor-pointer text-[#15803d]">Emergency contact</summary>
      <div class="mt-3">${grid('md:grid-cols-3 gap-3', [f('Name', 'emergency_contact_name'), f('Phone', 'emergency_contact_phone'), f('Relation', 'emergency_contact_relation')].join(''))}</div></details>
    ${id ? '' : `<div class="border border-[#f1f5f9] rounded-xl p-3"><div class="lbl">First sign-in</div>${grid('md:grid-cols-2 gap-3', [f('Starter password', 'starter_password', { placeholder: 'leave empty for the shared HR password', hint: 'They are asked to replace it the first time they open Me.' })].join(''))}</div>`}
    ${id ? '' : `<div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">A leave quota is prorated from the joining date, and a payroll structure is created from the CTC you enter.</div>`}</div>`;
  openModal(id ? `Edit ${e.full_name}` : 'Add employee', body, modalFootSave(`submitEmployeeForm('${id || ''}')`, id ? 'Save changes' : 'Create employee'));
  const ctcEl = $('#salary_ctc');
  if (ctcEl && !id) ctcEl.value = '';
}

async function submitEmployeeForm(id) {
  const ids = ['full_name', 'email', 'personal_email', 'phone', 'gender', 'date_of_birth', 'date_of_joining', 'blood_group', 'department_id', 'designation_id', 'manager_id', 'employment_type', 'work_location', 'salary_ctc', 'status', 'address', 'nationality', 'pan_no', 'uan_no', 'pf_no', 'bank_name', 'bank_account_no', 'ifsc_code', 'employee_code', 'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relation', 'starter_password'];
  const v = formValues(ids);
  needValue('full_name', 'Name is required'); needValue('email', 'Work email is required');
  if (v.salary_ctc) v.salary_ctc = num(v.salary_ctc);
  if ('starter_password' in v && !v.starter_password) delete v.starter_password;
  ['department_id', 'designation_id', 'manager_id'].forEach(k => { if (!v[k]) delete v[k]; });
  Object.keys(v).forEach(k => { if (v[k] === null || v[k] === '') delete v[k]; });
  try {
    const newDeptId = await resolveTypeOrAdd('department', 'department_name');
    if (newDeptId) v.department_id = newDeptId;
    const desigId = await resolveTypeOrAdd('designation', 'designation_name', newDeptId);
    if (desigId) v.designation_id = desigId;
    const res = id ? await api('/api/employees/' + id, { method: 'PUT', body: v }) : await api('/api/employees', { method: 'POST', body: v });
    toast(res.message, 'success'); closeAllModals();
    APP.lookups = null; await loadLookups(true);
    loadEmployees(true);
    if (currentModule === 'orgchart') loadOrgChart(true);
    if (id && String(id) === String(APP.user.employee_id)) loadMe(true);
  } catch (e) { /* toast shown */ }
}

/* ================================================================== ME */
async function loadMe(refresh) {
  const root = $('#module-me');
  if (refresh || !root.dataset.loaded) root.innerHTML = '<div class="keka-card p-6"><div class="spin"></div></div>';
  let d;
  try { d = await api('/api/me'); } catch (e) { root.innerHTML = emptyState('Could not load your profile'); return; }
  if (!d.employee) { root.innerHTML = emptyState(d.notice || 'No employee record linked', 'Ask HR to link this login to a payroll record.'); return; }
  APP.me = d;
  const e = d.employee;
  const info = (l, v) => `<div class="py-2.5 border-b border-[#f1f5f9] last:border-0"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="text-[13px] font-medium mt-0.5">${v || '—'}</div></div>`;
  const card = (title, sub, inner, right = '') => `<div class="keka-card p-5"><div class="flex items-start justify-between gap-3 mb-3"><div><h3 class="font-display font-semibold text-[15px]">${esc(title)}</h3>${sub ? `<p class="text-[12px] text-[#94a3b8] mt-0.5">${esc(sub)}</p>` : ''}</div>${right}</div>${inner}</div>`;
  const counts = d.counts || {};
  const bal = (d.leave_balances || []).reduce((s, b) => s + b.remaining, 0);
  const nextB = d.next_birthday, nextA = d.next_anniversary;
  const stat = (l, v, h) => `<div class="bg-[#f0fdf4] rounded-xl p-3.5"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-display font-bold text-[19px] mt-1 num">${v}</div><div class="text-[11px] text-[#94a3b8]">${h}</div></div>`;
  const my = (v) => isAdmin() ? v : `<span title="Only HR can change this">${v}</span><i class="fas fa-lock text-[9px] text-[#cbd5e1] ml-1"></i>`;
  root.innerHTML = `
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
      <div class="keka-card p-6 xl:col-span-1">
        <div class="flex items-start gap-4">
          <div style="width:62px;height:62px;font-size:22px" class="avatar">${esc(initialsOf(e.full_name))}</div>
          <div class="min-w-0 flex-1"><div class="font-display font-bold text-[20px] leading-tight">${esc(e.full_name)}</div><div class="text-[13px] text-[#64748b] mt-0.5">${esc(e.designation)}</div>
            <div class="flex flex-wrap gap-1.5 mt-2">${statusPill(e.status)}<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(e.employee_code)}</span>${isAdmin() ? '<span class="pill bg-[#d1fae5] text-[#15803d]">HR Admin</span>' : ''}</div></div>
        </div>
        <div class="grid grid-cols-3 gap-2 mt-5">${stat('Tenure', esc(e.tenure), 'at Modish')}${stat('Leave left', bal, 'days this year')}${stat('Rating', (d.reviews || [])[0] ? (d.reviews[0].rating_label || '—') : '—', 'last review')}</div>
        <div class="mt-5 space-y-0">${info('Work email', `<a class="text-[#15803d] hover:underline" href="mailto:${esc(e.email)}">${esc(e.email)}</a>`)}${info('Phone', esc(e.phone))}${info('Personal email', esc(e.personal_email))}${info('Department', esc(e.department))}${info('Reports to', d.manager ? esc(d.manager.full_name) : '—')}${d.skip_level ? info('Skip level', esc(d.skip_level.full_name)) : ''}${info('Location', esc(e.work_location))}${info('Joined', fmtDate(e.date_of_joining))}${info('Date of birth', fmtDate(e.date_of_birth))}${info('Blood group', esc(e.blood_group))}${info('Emergency', e.emergency_contact_name ? `${esc(e.emergency_contact_name)} · ${esc(e.emergency_contact_relation)} · ${esc(e.emergency_contact_phone)}` : 'Not on file')}</div>
        <div class="grid grid-cols-2 gap-2 mt-4">
          ${nextB ? `<div class="bg-[#fff4e6] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#b7791f] font-semibold">Birthday in</div><div class="font-display font-bold text-[16px] text-[#b7791f] num mt-0.5">${nextB.days_left === 0 ? 'Today 🎉' : nextB.days_left + ' days'}</div></div>` : ''}
          ${nextA ? `<div class="bg-[#d1fae5] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#15803d] font-semibold">Anniversary</div><div class="font-display font-bold text-[16px] text-[#15803d] num mt-0.5">${nextA.days_left === 0 ? 'Today' : nextA.days_left + ' days'}</div></div>` : ''}
        </div>
        <div class="flex gap-2 mt-4">${(d.direct_reports || []).length ? `<button onclick="openDirectReports()" class="btn btn-ghost btn-xs flex-1 justify-center"><i class="fas fa-users"></i> ${d.direct_reports.length} reports</button>` : ''}<button onclick="openMeEdit()" class="btn btn-primary btn-xs flex-1 justify-center"><i class="far fa-pen"></i> Edit my profile</button></div>
        <p class="text-[11px] text-[#94a3b8] mt-2.5 leading-relaxed">${esc(d.notice || '')}</p>
      </div>
      <div class="xl:col-span-2 space-y-5">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          ${stat('Days present', counts.attendance_days_30 || 0, 'last 30 days')}${stat('Hours', counts.hours_30 || 0, 'worked in 30 days')}${stat('Leave used', counts.leaves_used_year || 0, `days · ${counts.leaves_pending || 0} pending`)}${stat('Open claims', counts.open_claims || 0, 'awaiting approval')}
        </div>
        ${card('This month', d.attendance_month ? d.attendance_month.month_label : '', (() => {
          const m = d.attendance_month || {};
          const cells = [['Present', m.present, '#0f9d58'], ['WFH', m.wfh, '#15803d'], ['On leave', m.on_leave, '#4ade80'], ['Absent', m.absent, '#c0392b'], ['Late', m.late, '#b7791f']];
          return `<div class="grid grid-cols-2 md:grid-cols-5 gap-3">${cells.map(([l, v, c]) => `<div class="rounded-xl p-3 border border-[#f1f5f9]"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-display font-bold text-[20px] num mt-1" style="color:${c}">${v || 0}</div></div>`).join('')}</div><div class="mt-4 text-[12.5px] text-[#64748b]">${m.days || 0} days marked · <b>${m.hours || 0} h</b> logged · ${m.pending_days || 0} days still open</div>`;
        })(), `<button onclick="switchModule('attendance')" class="btn btn-ghost btn-xs">Open</button>`)}
        ${card('Leave balances', 'Approved and pending days are already subtracted.', `<div class="space-y-3">${(d.leave_balances || []).map(b => `<div><div class="flex items-center justify-between text-[12.5px]"><span class="font-medium">${esc(b.leave_type || b.name)}</span><span class="text-[#94a3b8] num">${b.remaining} left of ${b.total}${b.pending ? ` · ${b.pending} pending` : ''}</span></div><div class="bar mt-1.5"><span style="width:${b.used_pct || 0}%;background:${b.color || '#15803d'}"></span></div></div>`).join('') || '<div class="text-[12.5px] text-[#94a3b8]">No quotas yet.</div>'}</div>`, `<button onclick="openLeaveModal();closeAllModals()" class="btn btn-ghost btn-xs">Apply</button>`)}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          ${card('Recent leave', '', `<div class="space-y-2">${(d.leaves || []).slice(0, 5).map(l => `<div class="flex items-center gap-2 text-[12.5px]"><span class="pill" style="background:${l.leave_color}22;color:${l.leave_color}">${esc(l.leave_type_label)}</span><span class="truncate">${esc(l.period_label)}</span><span class="ml-auto">${statusPill(l.status)}</span></div>`).join('') || '<div class="text-[12.5px] text-[#94a3b8]">No leave taken yet.</div>'}</div>`)}
          ${card('Last payslips', '', `<div class="space-y-2">${(d.payslips || []).slice(0, 5).map(p => `<div class="flex items-center gap-2 text-[12.5px]"><span class="font-medium">${esc(p.period_label)}</span><span class="ml-auto num">${inr(p.net_pay)}</span>${statusPill(p.status)}</div>`).join('') || '<div class="text-[12.5px] text-[#94a3b8]">No payslips yet.</div>'}</div>`)}
        </div>
        ${card('My documents', `${(d.documents || []).length} on file${counts.pending_documents ? ` · ${counts.pending_documents} awaiting verification` : ''}`, (() => {
          const docs = d.documents || [];
          const required = (APP.lookups?.required_doc_types || []);
          const have = new Set(docs.filter(x => x.status === 'Verified').map(x => x.doc_type));
          const missing = required.filter(t => !have.has(t));
          return `<div class="flex flex-wrap gap-2 mb-4">${required.map(t => `<span class="pill ${missing.includes(t) ? 'bg-[#fff1f1] text-[#c0392b]' : 'bg-[#e6f9f0] text-[#0f9d58]'}"><i class="fas ${missing.includes(t) ? 'fa-exclamation' : 'fa-check'} text-[9px]"></i>${esc(t)}</span>`).join('')}</div>` +
            (docs.length ? `<div class="space-y-1.5">${docs.slice(0, 6).map(x => `<div class="flex items-center gap-2 text-[12.5px] py-1.5 border-b border-[#f8fafc] last:border-0"><i class="far ${x.has_file ? 'fa-file-pdf text-[#c0392b]' : 'fa-file text-[#94a3b8]'}"></i><span class="truncate font-medium">${esc(x.title)}</span><span class="text-[#94a3b8] truncate hidden md:inline">${esc(x.purpose)}</span><span class="ml-auto flex items-center gap-2">${statusPill(x.status)}${x.has_file ? `<a href="${esc(x.download_url)}" class="text-[#15803d] hover:underline" title="Download"><i class="fas fa-download"></i></a>` : ''}</span></div>`).join('')}</div>` : '<div class="text-[12.5px] text-[#94a3b8]">You have not uploaded anything yet.</div>') +
            `<div class="mt-3"><button onclick="openDocUpload()" class="btn btn-ghost btn-xs"><i class="fas fa-cloud-upload-alt"></i> Upload a document</button></div>`;
        })())}
        ${(d.goals || []).length ? card('Active goals', 'From your current cycle', `<div class="space-y-2.5">${d.goals.map(g2 => `<div><div class="flex items-center justify-between text-[12.5px]"><span class="font-medium truncate pr-3">${esc(g2.title)}</span><span class="text-[#94a3b8] num">${g2.progress}% · ${esc(g2.health_label)}</span></div><div class="bar mt-1"><span style="width:${g2.progress}%;background:${g2.health === 'on_track' ? '#0f9d58' : g2.health === 'achieved' ? '#15803d' : '#f59e0b'}"></span></div></div>`).join('')}</div>`) : ''}
        ${(d.timesheets || []).length ? card('Recent timesheets', '', `<div class="space-y-1.5">${d.timesheets.map(t => `<div class="flex items-center gap-2 text-[12.5px]"><span>${esc(t.week_starting)} → ${esc(t.week_label || '')}</span><span class="ml-auto num text-[#64748b]">${num(t.total_hours)} h</span>${statusPill(t.status)}</div>`).join('')}</div>`) : ''}
        ${card('Sign-in security', 'How you get into Modish', (() => {
          const sec = (APP.session && APP.session.security) || {};
          const own = !!sec.has_own_password;
          const who = (APP.session && APP.session.user && APP.session.user.email) || APP.user.email || '—';
          return `<div class="flex items-start gap-3">
            <div class="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0" style="background:${own ? '#e6f9f0' : '#fff4e6'};color:${own ? '#0f9d58' : '#b7791f'}"><i class="fas ${own ? 'fa-shield-alt' : 'fa-key'} text-[13px]"></i></div>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-medium">${own ? 'You sign in with a password only you know' : 'You are still on the shared HR password'}</div>
              <div class="text-[11.5px] text-[#94a3b8] mt-0.5">Signed in as ${esc(who)} · minimum ${esc(sec.min_length || 8)} characters. ${own ? 'Change it whenever you like.' : 'Set your own so nobody else can open this account.'}</div>
            </div></div>
            <div class="mt-3"><button onclick="openPasswordModal()" class="btn btn-ghost btn-xs"><i class="fas fa-lock"></i> ${own ? 'Change password' : 'Set my password'}</button></div>`;
        })())}
      </div>
    </div>`;
  root.dataset.loaded = '1';
}
function openDirectReports() {
  const list = APP.me?.direct_reports || [];
  openModal('Your direct reports', `<div class="space-y-2">${list.map(r => `<div class="flex items-center gap-3 p-3 rounded-xl border border-[#f1f5f9] cursor-pointer hover:bg-[#f8fafc]" onclick="openEmployeeDetail('${r.id}')">${avatar(r)}<div><div class="text-[13px] font-medium">${esc(r.full_name)}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(r.designation)} · ${esc(r.department)}</div></div><i class="fas fa-chevron-right ml-auto text-[#cbd5e1] text-[11px]"></i></div>`).join('')}</div>`, '<button onclick="closeAllModals()" class="btn btn-ghost">Close</button>');
}
function openMeEdit() {
  const e = APP.me.employee;
  const editable = APP.me.editable_fields || ['phone', 'personal_email', 'address', 'blood_group', 'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relation', 'work_location'];
  const labels = { phone: 'Phone', personal_email: 'Personal email', address: 'Address', blood_group: 'Blood group', emergency_contact_name: 'Emergency contact name', emergency_contact_phone: 'Emergency contact phone', emergency_contact_relation: 'Relation', work_location: 'Work location' };
  const isAdminUser = APP.me.is_self_admin;
  const all = { ...labels, email: 'Work email', employee_code: 'Employee code', date_of_birth: 'Date of birth', date_of_joining: 'Date of joining', salary_ctc: 'Annual CTC', department_id: 'Department', designation_id: 'Designation', manager_id: 'Manager', employment_type: 'Employment type', status: 'Status', pan_no: 'PAN', bank_name: 'Bank', bank_account_no: 'Account number', ifsc_code: 'IFSC', nationality: 'Nationality' };
  const fields = isAdminUser ? Object.keys(all) : editable;
  const body = `<p class="text-[12.5px] text-[#64748b] mb-4">${isAdminUser ? 'HR Admin: every field on this profile is editable.' : 'You can update these self-service fields. Anything else needs HR — the rest are listed but locked.'}</p>
    <div class="space-y-3">${fields.map(k => {
      const opts = { placeholder: labels[k] || k };
      if (isAdminUser) {
        if (k === 'date_of_birth' || k === 'date_of_joining') opts.type = 'date';
        if (k === 'salary_ctc') opts.type = 'number';
        if (k === 'personal_email' || k === 'email') opts.type = 'email';
        if (k === 'address') opts.type = 'textarea';
        if (k === 'department_id') return typeOrAddField(labels[k], 'department_name', (APP.lookups.departments || []).map(d => d.name), 'Pick an existing department or type a new one - it is created when you save.', deptName(e.department_id) !== '—' ? deptName(e.department_id) : '');
        if (k === 'designation_id') return typeOrAddField(labels[k], 'designation_name', (APP.lookups.designations || []).map(d => d.title), 'Pick an existing title or type a new one - it is added to the list when you save.', desigName(e.designation_id) !== '—' ? desigName(e.designation_id) : '');
        if (k === 'manager_id') return fieldRow(labels[k], k, e.manager_id, { type: 'select', options: (APP.lookups.employees || []).filter(x => String(x.id) !== String(e.id)).map(x => ({ value: x.id, label: x.full_name })), placeholder: 'No manager' });
        if (k === 'employment_type') opts.type = 'select'; opts.options = ['Full-time', 'Part-time', 'Contract', 'Intern'];
        if (k === 'status') opts.type = 'select'; opts.options = ['Active', 'On Leave', 'Notice Period', 'Exited'];
        if (k === 'blood_group') opts.type = 'select'; opts.options = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-'];
      } else if (['blood_group'].includes(k)) { opts.type = 'select'; opts.options = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']; }
      else if (k === 'address') opts.type = 'textarea';
      else opts.disabled = false;
      return fieldRow(labels[k] || k.replace(/_/g, ' '), k, e[k], opts);
    }).join('')}</div>`;
  openModal('Edit my profile', body, modalFootSave('submitMeEdit(' + (isAdminUser ? 'true' : 'false') + ')', 'Save changes'));
}
async function submitMeEdit(admin) {
  const ids = $$('#modalBody [id]').map(el => el.id).filter(id => !id.endsWith('List') && id !== 'department_name' && id !== 'designation_name');
  const all = formValues(ids);
  const allowed = admin ? null : (APP.me.editable_fields || []);
  const body = {};
  Object.entries(all).forEach(([k, v]) => { if (!allowed || allowed.includes(k)) body[k] = v === null ? '' : v; });
  if (!Object.keys(body).length) { toast('Nothing to save', 'warn'); return; }
  try {
    if (admin) {
      const deptId = await resolveTypeOrAdd('department', 'department_name');
      if (deptId) body.department_id = deptId;
      const desigId = await resolveTypeOrAdd('designation', 'designation_name', deptId);
      if (desigId) body.designation_id = desigId;
    }
    const r = await api('/api/me', { method: 'PUT', body }); toast(r.message || 'Profile updated', 'success'); closeAllModals(); await loadMe(true); APP.lookups = null; loadLookups(true);
  } catch (e) { }
}

/* ================================================================== ORG CHART */
async function loadOrgChart(refresh) {
  if (refresh) $('#orgChartContainer').innerHTML = '<div class="spin"></div>';
  let d;
  try { d = await api('/api/orgchart'); } catch (e) { return; }
  APP.orgData = d;
  renderOrgStats(d);
  renderOrg();
}
/* Departments used to be read-only here - the list came from the database and nothing could add to
it, so a new team meant a SQL insert. These three functions are the whole feature: name, remit and
head, with the API guarding the duplicate names and the delete. */
function openDepartmentForm(deptId) {
  const dep = deptId ? (APP.orgData?.departments || []).find(d => String(d.id) === String(deptId)) : null;
  const body = `<div class="space-y-3">` +
    fieldRow('Department name', 'dept_name', dep?.name, { required: true, placeholder: 'e.g. Customer Success' }) +
    fieldRow('What this team owns', 'dept_desc', dep?.description,
             { type: 'textarea', rows: 2, placeholder: 'Shown on the department card in the org chart' }) +
    fieldRow('Department head', 'dept_head', dep?.head_id,
             { type: 'select', options: employeeOptions('No head yet'),
               placeholder: 'Pick a person', hint: 'Heads are who the org chart points at for escalations - you can leave this empty and assign one later.' }) +
    (dep ? `<div class="text-[11.5px] text-[#94a3b8]">${dep.count} person(s) currently in ${esc(dep.name)}. ` +
           `Move people in or out from their profile under Employees → Edit.</div>`
         : `<div class="text-[11.5px] text-[#94a3b8]">After creating it, assign people from Employees → Edit → Department.</div>`) +
    `</div>`;
  openModal(dep ? `Edit ${dep.name}` : 'Add a department', body,
            modalFootSave(`submitDepartment('${deptId || ''}')`, dep ? 'Save changes' : 'Create department'), 'max-w-lg');
}
async function submitDepartment(deptId) {
  const name = ($('#dept_name').value || '').trim();
  if (!name) return toast('Give the department a name', 'error');
  const body = { name, description: ($('#dept_desc').value || '').trim(), head_id: $('#dept_head').value || null };
  try {
    const r = await api(deptId ? `/api/departments/${deptId}` : '/api/departments',
                        { method: deptId ? 'PUT' : 'POST', body });
    toast(r.message || (deptId ? 'Department saved' : 'Department created'), 'success');
    closeAllModals();
    APP.lookups = null; await loadLookups(true);
    loadOrgChart(true);
    if (currentModule === 'employees') loadEmployees(true);
  } catch (e) { }
}
function deleteDepartment(deptId, name) {
  confirmAction(`Delete ${name}? Move its people out first - the department cannot be deleted while anyone is assigned to it.`,
    async () => {
      const r = await api(`/api/departments/${deptId}`, { method: 'DELETE' });
      toast(r.message || 'Department deleted', 'success');
      APP.lookups = null; await loadLookups(true);
      loadOrgChart(true);
    }, 'Delete department');
}
function flattenNodes(nodes, out = []) { (nodes || []).forEach(n => { out.push(n); flattenNodes(n.children, out); }); return out; }
function renderOrgStats(d) {
  const s = d.stats || {};
  $('#orgStats').innerHTML = [
    kpiCard('People', s.total, 'in the active org'),
    kpiCard('Top of tree', s.top_level, 'report straight to the board', { tone: 'brand' }),
    kpiCard('Managers', s.managers, 'with at least one report'),
    kpiCard('Individual contributors', s.individual_contributors, 'no direct reports'),
    kpiCard('Depth', (s.max_depth + 1) + ' levels', s.unassigned_manager ? `<span class="text-[#b7791f]">${s.unassigned_manager} broken line(s)</span>` : 'clean reporting lines'),
  ].join('');
  $('#orgNotice').innerHTML = (d.orphaned || []).length ? `<div class="keka-card p-4 !bg-[#fff4e6] !border-[#ffe6c2] flex items-center gap-3"><i class="fas fa-exclamation-triangle text-[#b7791f]"></i><div class="text-[13px] text-[#8a5a12] flex-1">${d.orphaned.length} employee(s) point at a manager who is no longer in the tree: ${d.orphaned.map(o => esc(o.name || o.full_name)).join(', ')}. ${isAdmin() ? 'Use “By department” to reassign them.' : 'Ask HR to fix the reporting line.'}</div>${isAdmin() ? '<button onclick="openManagerFix()" class="btn btn-ghost btn-xs">Fix now</button>' : ''}</div>` : '';
  fillSelect('#orgFocus', [{ value: '', label: 'Whole company' }, ...flattenNodes(d.tree).map(n => ({ value: n.id, label: `${n.name}${n.children?.length ? ` · ${n.children.length} report(s)` : ''}` }))], $('#orgFocus')?.value || '', false);
}
let orgExpanded = new Set();
function orgKey(id) { return 'org:' + id; }
function renderOrg() {
  const d = APP.orgData; if (!d) return;
  const focus = $('#orgFocus')?.value || '';
  const maxDepth = num($('#orgDepth')?.value || 2);
  const tab = document.querySelector('#module-orgchart [data-orgtab].active')?.dataset.orgtab || 'tree';
  const wrap = $('#orgChartWrap');
  const cont = $('#orgChartContainer');
  $('#orgPanelWrap').innerHTML = '';
  if (tab === 'dept') {
    wrap.classList.remove('flex', 'items-start', 'justify-center');
    cont.className = 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full';
    cont.innerHTML = (d.departments || []).map(dep => `<div class="border border-[#dcfce7] rounded-2xl p-4 bg-[#f8fafc]">
        <div class="flex items-start justify-between gap-2 mb-3"><div><div class="font-display font-semibold text-[14.5px]">${esc(dep.name)}</div><div class="text-[11.5px] text-[#94a3b8]">${dep.count} people${(dep.locations || []).length ? ' · ' + esc(dep.locations.join(', ')) : ''}</div></div><div class="flex items-center gap-1 flex-shrink-0"><span class="pill bg-[#d1fae5] text-[#15803d]">${dep.count}</span>${isAdmin() ? `<button data-admin-only onclick="openDepartmentForm('${dep.id}')" class="btn btn-ghost btn-xs !py-0.5 !px-1.5" title="Rename or change the head"><i class="far fa-pen"></i></button><button data-admin-only onclick="deleteDepartment('${dep.id}','${esc(dep.name)}')" class="btn btn-ghost btn-xs !py-0.5 !px-1.5" title="Delete this empty department"><i class="far fa-trash-can"></i></button>` : ''}</div></div>${dep.description ? `<div class="text-[11.5px] text-[#64748b] -mt-1 mb-2">${esc(dep.description)}</div>` : ''}
        ${dep.head ? `<div class="flex items-center gap-2 p-2 rounded-xl bg-white border border-[#f1f5f9] mb-2"><span style="width:26px;height:26px;font-size:10px" class="avatar">${esc(initialsOf(dep.head.full_name))}</span><div class="min-w-0"><div class="text-[12.5px] font-medium truncate">${esc(dep.head.full_name)}</div><div class="text-[11px] text-[#94a3b8]">Department head</div></div>${isAdmin() ? `<button onclick="openManagerFix('${dep.head.id}')" class="btn btn-ghost btn-xs !py-1 ml-auto" title="Reassign head"><i class="far fa-pen"></i></button>` : ''}</div>` : `<div class="text-[12px] text-[#b7791f] mb-2"><i class="fas fa-exclamation-circle"></i> No head assigned${isAdmin() ? ` <button class="underline" onclick="openManagerFix('','${dep.id}')">Assign one</button>` : ''}</div>`}
        <div class="space-y-1.5">${(dep.members || []).slice(0, 60).map(m => `<div class="flex items-center gap-2 text-[12.5px] py-1 border-b border-[#f1f5f9] last:border-0"><span style="width:22px;height:22px;font-size:8.5px" class="avatar">${esc(initialsOf(m.name || m.full_name))}</span><span class="truncate">${esc(m.name || m.full_name)}</span><span class="text-[11px] text-[#94a3b8] truncate hidden lg:inline">${esc(m.designation || '')}</span><button onclick="openManagerFix('${m.id}')" class="row-actions force btn btn-ghost !py-0.5 !px-1.5 ml-auto text-[10.5px]" title="Change manager"><i class="fas fa-random"></i></button></div>`).join('') || '<div class="text-[12px] text-[#94a3b8]">No members yet.</div>'}${dep.count > 60 ? `<div class="text-[11.5px] text-[#94a3b8] pt-1">+ ${dep.count - 60} more</div>` : ''}</div></div>`).join('');
    return;
  }
  wrap.className = 'keka-card p-6 overflow-auto';
  cont.className = 'org-tree';
  let roots = d.tree || [];
  if (focus) { const found = flattenNodes(roots).find(n => String(n.id) === String(focus)); roots = found ? [found] : []; }
  if (focus) maxDepthOverride = true; else maxDepthOverride = false;
  const autoExpand = new Set();
  if (focus) { let p = focus; while (p) { autoExpand.add(p); p = parentOf(APP.orgData.tree, p); } }
  const depthLimit = (focus ? 99 : maxDepth);
  const initial = depthLimit >= 99 ? new Set(flattenNodes(roots).map(n => n.id)) : new Set(flattenNodes(roots).filter(n => n.depth < depthLimit - 1).map(n => n.id));
  orgExpanded = new Set([...orgExpanded, ...autoExpand, ...(APP.orgInit ? [] : initial)]);
  APP.orgInit = true;
  cont.innerHTML = `<div style="transform:scale(${APP.orgZoom});transform-origin:top center;transition:transform .15s">${roots.map(n => orgNode(n, depthLimit, 0)).join('')}</div>` +
    (!roots.length ? emptyState('Nobody selected', 'Pick a manager above to see their branch.') : '');
}
let maxDepthOverride = false;
function parentOf(nodes, id, parent = null) {
  for (const n of nodes || []) { if (String(n.id) === String(id)) return parent; const r = parentOf(n.children, id, n.id); if (r !== null && r !== undefined) return r; }
  return null;
}
function orgNode(n, depthLimit, depth) {
  const hasKids = (n.children || []).length > 0;
  const open = orgExpanded.has(n.id);
  const showKids = hasKids && open && (depth < depthLimit);
  return `<ul><li class="${showKids ? 'org-open' : ''}">
    <div class="org-node keka-card p-3 text-center shadow-sm hover:shadow-md transition ${n.depth === 0 && depth === 0 ? '!border-[#15803d]/30' : ''}" style="background:${depth === 0 ? '#052e16' : '#fff'}">
      <div class="flex flex-col items-center">
        <div class="flex items-center gap-2 w-full"><div style="width:34px;height:34px;font-size:12px" class="avatar ${depth === 0 ? '!bg-[#15803d] !text-white' : ''}">${esc(initialsOf(n.name))}</div>
          <div class="text-left min-w-0 flex-1"><div class="text-[12.5px] font-semibold truncate ${depth === 0 ? 'text-white' : ''}">${esc(n.name)}</div><div class="text-[10.5px] truncate ${depth === 0 ? 'text-white/50' : 'text-[#94a3b8]'}">${esc(n.code || '')}</div></div></div>
        <div class="text-[11px] mt-1.5 truncate w-full ${depth === 0 ? 'text-white/70' : 'text-[#64748b]'}">${esc(n.designation)}</div>
        <div class="text-[10.5px] ${depth === 0 ? 'text-white/40' : 'text-[#94a3b8]'} truncate w-full">${esc(n.department)}</div>
        ${hasKids ? `<div class="flex items-center justify-center gap-2 mt-2 w-full"><span class="pill ${depth === 0 ? 'bg-white/10 text-white/70' : 'bg-[#f0fdf4] text-[#64748b]'}">${n.children.length} · ${n.total_reports} total</span></div>
          <button onclick="event.stopPropagation();toggleOrgNode('${n.id}')" class="mt-2 w-full text-[11px] py-1 rounded-lg ${depth === 0 ? 'bg-white/10 text-white/70 hover:bg-white/20' : 'bg-[#f0fdf4] text-[#15803d] hover:bg-[#d1fae5]'}"><i class="fas fa-chevron-down org-caret"></i> ${showKids ? 'Hide' : 'Show'} team</button>` : `<div class="mt-2 text-[10.5px] ${depth === 0 ? 'text-white/35' : 'text-[#cbd5e1]'}">Individual contributor</div>`}
        <button onclick="openEmployeeDetail('${n.id}')" class="mt-1.5 text-[10.5px] ${depth === 0 ? 'text-white/60 hover:text-white' : 'text-[#94a3b8] hover:text-[#15803d]'}">View profile →</button>
      </div>
    </div>
    ${showKids ? `<div class="org-kids" style="display:flex"><ul>${n.children.map(c => orgNode(c, depthLimit, depth + 1)).join('')}</ul></div>` : ''}
  </li></ul>`;
}
function toggleOrgNode(id) { orgExpanded.has(id) ? orgExpanded.delete(id) : orgExpanded.add(id); renderOrg(); }
function orgZoom(delta) { APP.orgZoom = Math.min(1.35, Math.max(.55, APP.orgZoom + delta)); renderOrg(); }
function orgExpandAll(open) { const all = flattenNodes(APP.orgData.tree).filter(n => (n.children || []).length).map(n => n.id); orgExpanded = open ? new Set(all) : new Set(); if (!open) orgExpanded.add(APP.orgData.tree[0]?.id); APP.orgInit = true; renderOrg(); }
function setOrgTab(t) { $$('#module-orgchart [data-orgtab]').forEach(x => x.classList.toggle('active', x.dataset.orgtab === t)); renderOrg(); }
/* ---- Org chart as a real PNG: the same model the DOM draws, painted on a canvas.
       No html2canvas, no CDN - so it works offline and never depends on CSS support. ---- */
const ORG_BOX = { w: 200, h: 82, gx: 30, gy: 62, pad: 34, head: 62 };
function orgTreeLayout(roots, depthLimit) {
  const nodes = [], edges = [];
  let leaf = 0, maxDepth = 0;
  const place = (n, depth) => {
    const kids = depth < depthLimit ? (n.children || []) : [];
    if (!kids.length) n._x = leaf * (ORG_BOX.w + ORG_BOX.gx);
    else { kids.forEach(k => place(k, depth + 1)); n._x = Math.round((kids[0]._x + kids[kids.length - 1]._x) / 2); }
    n._y = depth * (ORG_BOX.h + ORG_BOX.gy);
    maxDepth = Math.max(maxDepth, depth);
    nodes.push(n);
    kids.forEach(k => edges.push({ p: n, c: k }));
    if (!kids.length) leaf++;
    return n;
  };
  (roots || []).forEach(r => place(r, 0));
  return { nodes, edges, maxDepth,
           width: Math.max(640, leaf * (ORG_BOX.w + ORG_BOX.gx) - ORG_BOX.gx + ORG_BOX.pad * 2),
           height: (maxDepth + 1) * (ORG_BOX.h + ORG_BOX.gy) - ORG_BOX.gy + ORG_BOX.pad + ORG_BOX.head };
}
function orgDeptLayout(deps) {
  const COL = { w: 268, gx: 22, row: 30, pad: 34 };
  const cols = (deps || []).map((dep, i) => {
    const people = (dep.head ? [Object.assign({}, dep.head, { isHead: true })] : []).concat(dep.members || []);
    return { dep, people, x: i * (COL.w + COL.gx), h: 74 + Math.max(1, people.length) * COL.row };
  });
  const rows = (deps || []).reduce((m, d) => Math.max(m, (d.head ? 1 : 0) + (d.members || []).length), 0);
  return { cols, colW: COL.w, rowH: COL.row,
           width: Math.max(680, cols.length * (COL.w + COL.gx) - COL.gx + COL.pad * 2),
           height: 74 + Math.max(1, rows) * COL.row + COL.pad + ORG_BOX.head };
}
function orgRoundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function orgClip(ctx, text, max) {
  const str = String(text || '');
  if (!max || ctx.measureText(str).width <= max) return str;
  let out = str;
  while (out.length > 1 && ctx.measureText(out + '…').width > max) out = out.slice(0, -1);
  return out + '…';
}
function orgInitials(name) { return String(name || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'; }
function paintOrg(ctx, layout, meta) {
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, layout.width, layout.height);
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = '#052e16'; ctx.font = '600 19px -apple-system, "Segoe UI", Roboto, sans-serif';
  ctx.fillText(orgClip(ctx, meta.title, layout.width - 60), ORG_BOX.pad, 34);
  ctx.fillStyle = '#94a3b8'; ctx.font = '12px -apple-system, "Segoe UI", Roboto, sans-serif';
  ctx.fillText(orgClip(ctx, meta.subtitle, layout.width - 60), ORG_BOX.pad, 52);
  const ox = ORG_BOX.pad, oy = ORG_BOX.head;
  ctx.save(); ctx.translate(ox, oy);
  ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1.5;
  (layout.edges || []).forEach(e => {
    const x1 = e.p._x + ORG_BOX.w / 2, y1 = e.p._y + ORG_BOX.h;
    const x2 = e.c._x + ORG_BOX.w / 2, y2 = e.c._y;
    const mid = Math.round((y1 + y2) / 2);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x1, mid); ctx.lineTo(x2, mid); ctx.lineTo(x2, y2); ctx.stroke();
  });
  (layout.nodes || []).forEach(n => {
    const x = n._x, y = n._y, top = n.depth === 0;
    ctx.fillStyle = top ? '#052e16' : '#f8fafc';
    orgRoundRect(ctx, x, y, ORG_BOX.w, ORG_BOX.h, 12); ctx.fill();
    ctx.strokeStyle = top ? '#15803d' : '#e2e8f0'; ctx.stroke();
    ctx.fillStyle = top ? '#15803d' : '#d1fae5';
    ctx.beginPath(); ctx.arc(x + 26, y + 28, 13, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = top ? '#ffffff' : '#15803d'; ctx.font = '600 11px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center'; ctx.fillText(orgInitials(n.name), x + 26, y + 32); ctx.textAlign = 'left';
    ctx.fillStyle = top ? '#ffffff' : '#052e16'; ctx.font = '600 12.5px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(orgClip(ctx, n.name, ORG_BOX.w - 62), x + 46, y + 26);
    ctx.fillStyle = top ? 'rgba(255,255,255,.55)' : '#94a3b8'; ctx.font = '10.5px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(orgClip(ctx, `${n.code || ''}${n.designation ? ' · ' + n.designation : ''}`, ORG_BOX.w - 62), x + 46, y + 41);
    ctx.fillStyle = top ? 'rgba(255,255,255,.7)' : '#64748b'; ctx.font = '11px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(orgClip(ctx, n.department || '', ORG_BOX.w - 34), x + 17, y + 61);
    const kids = (n.children || []).length;
    ctx.fillStyle = kids ? (top ? 'rgba(255,255,255,.16)' : '#d1fae5') : 'transparent';
    if (kids) { orgRoundRect(ctx, x + ORG_BOX.w - 74, y + 50, 60, 20, 10); ctx.fill(); }
    ctx.fillStyle = top ? 'rgba(255,255,255,.8)' : '#15803d'; ctx.font = '600 10px -apple-system, "Segoe UI", Roboto, sans-serif';
    if (kids) ctx.fillText(`${kids} · ${n.total_reports || kids}`, x + ORG_BOX.w - 66, y + 64);
  });
  (layout.cols || []).forEach(col => {
    const x = col.x, y = 0, w = layout.colW;
    ctx.fillStyle = '#ffffff'; orgRoundRect(ctx, x, y, w, col.h, 14); ctx.fill();
    ctx.strokeStyle = '#dcfce7'; ctx.stroke();
    ctx.fillStyle = '#f0fdf4'; orgRoundRect(ctx, x, y, w, 44, 14); ctx.fill();
    ctx.fillStyle = '#052e16'; ctx.font = '600 13px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(orgClip(ctx, col.dep.name, w - 66), x + 14, y + 22);
    ctx.fillStyle = '#94a3b8'; ctx.font = '10.5px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillText(orgClip(ctx, `${col.dep.count || col.people.length} people`, w - 66), x + 14, y + 36);
    ctx.fillStyle = '#15803d'; ctx.font = '600 11px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'right'; ctx.fillText(String(col.dep.count || col.people.length), x + w - 14, y + 27); ctx.textAlign = 'left';
    col.people.forEach((p, i) => {
      const py = y + 52 + i * layout.rowH;
      ctx.fillStyle = p.isHead ? '#d1fae5' : '#f8fafc';
      ctx.beginPath(); ctx.arc(x + 22, py + 9, 9, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = p.isHead ? '#15803d' : '#94a3b8'; ctx.font = '600 8px -apple-system, "Segoe UI", Roboto, sans-serif';
      ctx.textAlign = 'center'; ctx.fillText(orgInitials(p.full_name || p.name), x + 22, py + 12); ctx.textAlign = 'left';
      ctx.fillStyle = '#052e16'; ctx.font = (p.isHead ? '600 ' : '') + '11.5px -apple-system, "Segoe UI", Roboto, sans-serif';
      ctx.fillText(orgClip(ctx, (p.full_name || p.name || '') + (p.isHead ? '  (head)' : ''), w - 52), x + 38, py + 8);
      ctx.fillStyle = '#94a3b8'; ctx.font = '9.5px -apple-system, "Segoe UI", Roboto, sans-serif';
      ctx.fillText(orgClip(ctx, p.designation || '', w - 52), x + 38, py + 20);
    });
  });
  ctx.restore();
}
async function downloadOrgPng() {
  if (!APP.orgData) { await loadOrgChart(true); }
  const d = APP.orgData;
  if (!d) { toast('Still loading the org chart — try again in a second', 'warn'); return; }
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx || typeof canvas.toBlob !== 'function') {
    toast('This browser cannot rasterise the chart, so opening the print view instead', 'warn');
    window.print(); return;
  }
  const tab = document.querySelector('#module-orgchart [data-orgtab].active')?.dataset.orgtab || 'tree';
  const focus = $('#orgFocus')?.value || '';
  let layout, meta, count;
  if (tab === 'dept') {
    layout = orgDeptLayout(d.departments || []);
    meta = { title: `Org chart — by department`, subtitle: `${(d.departments || []).length} department(s) · ${d.stats?.total || 0} people · generated ${new Date().toLocaleDateString()}` };
    count = (d.departments || []).length;
  } else {
    let roots = d.tree || [];
    if (focus) { const f = flattenNodes(roots).find(n => String(n.id) === String(focus)); roots = f ? [f] : roots; }
    const depth = focus ? 99 : Math.max(1, num($('#orgDepth')?.value || 2));
    layout = orgTreeLayout(roots, Math.min(depth, 99));
    meta = { title: focus ? `Org chart — ${roots[0]?.name || ''} and team` : 'Org chart — whole company',
             subtitle: `${layout.nodes.length} box(es) · up to ${layout.maxDepth + 1} level(s) shown · generated ${new Date().toLocaleDateString()}` };
    count = layout.nodes.length;
  }
  if (!count) { toast('Nothing to export yet', 'warn'); return; }
  const scale = 2;
  canvas.width = Math.round(layout.width * scale); canvas.height = Math.round(layout.height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  paintOrg(ctx, layout, meta);
  canvas.toBlob(blob => {
    if (!blob) { toast('Could not build the image — using the print view', 'warn'); window.print(); return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `org-chart-${tab}-${todayIso()}.png`;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    toast(`org-chart-${tab}-${todayIso()}.png saved (${(blob.size / 1024).toFixed(0)} KB)`, 'success');
  }, 'image/png');
}
function openManagerFix(employeeId, deptId) {
  if (!isAdmin()) { toast('Only HR Admins can change reporting lines', 'error'); return; }
  const emp = employeeId ? flattenNodes(APP.orgData.tree).find(n => String(n.id) === String(employeeId)) : null;
  const list = (APP.lookups?.employees || []).slice().sort((a, b) => a.full_name.localeCompare(b.full_name));
  const body = `<div class="space-y-3">
    ${fieldRow('Employee', 'mf_emp', employeeId, { type: 'select', options: list.map(x => ({ value: x.id, label: `${x.full_name} · ${x.employee_code}` })), placeholder: 'Choose who to change' })}
    ${fieldRow('New manager', 'mf_mgr', emp?.id ? '' : '', { type: 'select', options: list.map(x => ({ value: x.id, label: `${x.full_name} · ${x.designation || ''}` })), placeholder: 'No manager (top of tree)' })}
    ${fieldRow('Reason (for the audit note)', 'mf_note', '', { type: 'textarea', rows: 2, placeholder: 'Team restructure announced on 1 Sep' })}
    <div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">Loops are rejected — a person can never report to someone inside their own branch.</div></div>`;
  openModal('Change reporting line', body, modalFootSave('submitManagerFix()', 'Save reporting line'));
}
async function submitManagerFix() {
  const employee_id = needValue('mf_emp', 'Choose the employee first');
  const mgr = $('#mf_mgr').value || null;
  try { const r = await api('/api/orgchart/assign-manager', { method: 'POST', body: { employee_id, manager_id: mgr, note: $('#mf_note').value } }); toast(r.message, 'success'); closeAllModals(); APP.lookups = null; await loadLookups(true); loadOrgChart(true); if (currentModule === 'employees') loadEmployees(true); } catch (e) { }
}


/* ================================================================== DOCUMENTS */
async function loadDocuments(refresh) {
  await loadLookups();
  if (refresh) $('#documentsTable').innerHTML = '<tr><td colspan="9"><div class="spin"></div></td></tr>';
  let meta = null, rows = [], reqs = [];
  try {
    meta = await api('/api/documents/meta');
    rows = await api('/api/documents' + docQuery());
    reqs = await api('/api/document-requests');
  } catch (e) { return; }
  APP.docMeta = meta; APP.docRows = rows; APP.docReqs = reqs;
  const types = (meta.doc_types || []);
  fillSelect('#docTypeFilter', [{ value: '', label: 'All document types' }, ...types.map(t => ({ value: t.type, label: `${t.type}${t.mandatory ? ' · mandatory' : ''}` }))], $('#docTypeFilter')?.value, false);
  if (isAdmin()) { $('#docEmpFilter').classList.remove('hidden'); fillSelect('#docEmpFilter', employeeOptions('All employees'), $('#docEmpFilter')?.value, false); }
  const c = meta.counts || {};
  $('#docStats').innerHTML = [
    kpiCard('Documents', c.total, esc(meta.storage_mode || '')),
    kpiCard('To verify', c.pending, isAdmin() ? 'you can verify or reject' : 'HR has these in the queue', { tone: c.pending ? 'warn' : 'default' }),
    kpiCard('Verified', c.verified, 'accepted by HR', { tone: 'good' }),
    kpiCard('Rejected', c.rejected, 'need a replacement', { tone: c.rejected ? 'bad' : 'default' }),
    kpiCard('Expiring soon', c.expiring_soon, 'within 60 days', { tone: c.expiring_soon ? 'warn' : 'default' }),
    kpiCard('Storage', esc(meta.storage_label || humanSize(c.storage_bytes)), `${(meta.by_category ? Object.keys(meta.by_category).length : 0)} categories`),
  ].join('');
  $('#docReqCount').textContent = (reqs || []).filter(r => r.status === 'Pending' || r.status === 'Requested').length;
  renderDocumentsTable();
  renderDocRequests();
  renderDocCompliance();
}
function docQuery() {
  const p = new URLSearchParams();
  if ($('#docTypeFilter')?.value) p.set('doc_type', $('#docTypeFilter').value);
  if ($('#docStatusFilter')?.value && $('#docStatusFilter').value !== 'All') p.set('status', $('#docStatusFilter').value);
  if ($('#docExpiryFilter')?.value && $('#docExpiryFilter').value !== 'All') p.set('expiry', $('#docExpiryFilter').value);
  if (isAdmin() && $('#docEmpFilter')?.value) p.set('employee_id', $('#docEmpFilter').value);
  const s = p.toString(); return s ? '?' + s : '';
}
function setDocTab(t) { $$('#module-documents [data-doctab]').forEach(x => x.classList.toggle('active', x.dataset.doctab === t)); }
function renderDocumentsTable() {
  const rows = APP.docRows || [];
  const tb = $('#documentsTable');
  const head = `<tr><td colspan="9">${emptyState('No documents in this view', 'Clear the filters or upload the first file.', '<button class="btn btn-primary btn-xs" onclick="openDocUpload()">Upload document</button>')}</td></tr>`;
  if (!rows.length) { tb.innerHTML = head; return; }
  tb.innerHTML = rows.map(d => `<tr class="clickable" onclick="openDocumentDetail('${d.id}')">
    <td><div class="flex items-center gap-2.5"><i class="far ${d.has_file ? 'fa-file-pdf text-[#c0392b]' : 'fa-note-sticky text-[#15803d]'} text-[16px]"></i><div class="min-w-0"><div class="font-medium truncate">${esc(d.title)}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(d.doc_type)} · ${d.has_file ? esc(d.file_name) + ' · ' + esc(d.size_label) : 'metadata only'}</div></div></div></td>
    ${isAdmin() ? `<td class="text-[12.5px]">${d.employee ? `<span class="flex items-center gap-1.5"><span style="width:20px;height:20px;font-size:8.5px" class="avatar">${esc(initialsOf(d.employee.full_name))}</span>${esc(d.employee.full_name)}</span>` : '<span class="text-[#94a3b8]">Company</span>'}</td>` : ''}
    <td><span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(d.category)}</span>${d.mandatory ? ' <span class="pill bg-[#fff1f1] text-[#c0392b]" title="Required for onboarding">mandatory</span>' : ''}</td>
    <td class="text-[12px] text-[#64748b] max-w-[230px]"><div class="line-clamp-2">${esc(d.purpose)}</div>${d.description ? `<div class="text-[11px] text-[#94a3b8] truncate" title="${esc(d.description)}">${esc(d.description)}</div>` : ''}</td>
    <td class="text-[12px]">${esc(d.uploaded_by_label || '—')}</td>
    <td class="text-[12px] num">${d.valid_till && d.valid_till !== '-' ? `${d.valid_from_label && d.valid_from_label !== '-' ? esc(d.valid_from_label) : '—'} → ${esc(d.valid_till_label || fmtDayShort(d.valid_till))}` : 'no expiry'}<div class="mt-0.5">${d.expiry_state === 'Expired' ? `<span class="pill bg-[#fff1f1] text-[#c0392b]">expired ${Math.abs(d.expiry_days_left)}d ago</span>` : d.expiry_state === 'Expiring soon' ? `<span class="pill bg-[#fff4e6] text-[#b7791f]">${d.expiry_days_left}d left</span>` : ''}</div></td>
    <td class="text-[12px]"><i class="far ${d.visibility === 'HR only' ? 'fa-eye-slash' : 'fa-eye'} text-[#94a3b8] mr-1"></i>${esc(d.visibility || 'HR only')}</td>
    <td>${statusPill(d.status)}${d.status === 'Rejected' && d.reviewer_remark ? `<div class="text-[11px] text-[#c0392b] mt-1 max-w-[150px]" title="${esc(d.reviewer_remark)}">${esc(d.reviewer_remark)}</div>` : ''}</td>
    <td class="text-right"><div class="row-actions inline-flex gap-1">
      ${d.has_file ? `<a onclick="event.stopPropagation()" href="${esc(d.download_url)}" class="btn btn-ghost btn-xs !py-1" title="Download"><i class="fas fa-download"></i></a>` : ''}
      ${isAdmin() && d.status === 'Pending' ? `<button onclick="event.stopPropagation();verifyDoc('${d.id}')" class="btn btn-ghost btn-xs !py-1 text-[#0f9d58]" title="Verify"><i class="fas fa-check"></i></button>
        <button onclick="event.stopPropagation();rejectDoc('${d.id}')" class="btn btn-ghost btn-xs !py-1 text-[#c0392b]" title="Reject"><i class="fas fa-xmark"></i></button>` : ''}
      <button onclick="event.stopPropagation();openDocumentDetail('${d.id}')" class="btn btn-ghost btn-xs !py-1"><i class="far fa-eye"></i></button>
    </div></td></tr>`).join('');
}
function openDocumentDetail(id) {
  const d = (APP.docRows || []).find(x => String(x.id) === String(id));
  if (!d) return;
  const info = (l, v) => `<div class="bg-[#f0fdf4] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="text-[13px] font-medium mt-1">${v || '—'}</div></div>`;
  const body = `<div class="grid grid-cols-2 md:grid-cols-3 gap-3">
      ${info('Filed for', d.employee ? esc(d.employee.full_name) + `<div class="text-[11px] font-normal text-[#94a3b8]">${esc(d.employee.designation || '')}</div>` : 'Company record')}
      ${info('Uploaded by', esc(d.uploaded_by_label || ''))}${info('Uploaded on', fmtDate(d.uploaded_at || d.created_at))}
      ${info('Type', esc(d.doc_type))}${info('Category', esc(d.category))}${info('Visibility', esc(d.visibility || 'HR only'))}
      ${info('Valid from', fmtDate(d.valid_from))}${info('Valid till', fmtDate(d.valid_till))}${info('Expiry status', esc(d.expiry_state))}
      ${info('File', d.has_file ? `${esc(d.file_name)} · ${esc(d.size_label)}` : 'metadata only')}${info('Status', statusPill(d.status))}${info('Reviewer', d.reviewer ? esc(d.reviewer.full_name) + (d.reviewer_remark ? ` <span class="text-[11.5px] font-normal text-[#94a3b8]">“${esc(d.reviewer_remark)}”</span>` : '') : '—')}
    </div>
    <div class="mt-4 bg-[#d1fae5] rounded-xl p-4"><div class="text-[10.5px] uppercase tracking-widest text-[#15803d] font-semibold mb-1">Why this document is on file</div><div class="text-[13px] leading-relaxed">${esc(d.purpose)}</div>${d.description ? `<div class="text-[12.5px] text-[#64748b] mt-2 pt-2 border-t border-[#15803d]/10">${esc(d.description)}</div>` : ''}</div>
    ${d.has_file ? `<div class="mt-4"><a href="${esc(d.download_url)}" class="btn btn-primary btn-xs"><i class="fas fa-download"></i> Download ${esc(d.file_name)}</a></div>` : ''}`;
  openModal(d.title, body, `${isAdmin() && d.status === 'Pending' ? `<button onclick="verifyDoc('${d.id}')" class="btn btn-primary btn-xs mr-auto"><i class="fas fa-check"></i> Verify</button>` : ''}<button onclick="confirmDeleteDoc('${d.id}')" class="btn btn-danger btn-xs"><i class="far fa-trash-alt"></i> Delete</button><button onclick="closeAllModals()" class="btn btn-ghost">Close</button>`);
}
async function confirmDeleteDoc(id) { await confirmAction('Delete this document record? The uploaded file is kept on disk for audit.', async () => { const r = await api('/api/documents/' + id, { method: 'DELETE' }); toast(r.message || 'Deleted', 'success'); closeAllModals(); loadDocuments(true); }, 'Delete document'); }
async function verifyDoc(id) { try { const r = await api('/api/documents/' + id, { method: 'PUT', body: { action: 'Verified', reviewer_remark: 'Verified by HR' } }); toast(r.message, 'success'); loadDocuments(true); loadDashboard(true); } catch (e) { } }
function rejectDoc(id) {
  openModal('Reject this document', `<div class="space-y-3">${fieldRow('Why is it rejected?', 'rej_remark', '', { type: 'textarea', required: true, rows: 3, placeholder: 'The PAN number is not legible - please re-upload a clear scan.' })}<div class="text-[11.5px] text-[#94a3b8] bg-[#fff1f1] rounded-xl p-3">The remark is mandatory and the employee sees it on their Me page. A rejection sets the status back to Rejected so they can re-upload.</div></div>`,
    modalFootSave(`submitRejectDoc('${id}')`, 'Reject document'));
}
async function submitRejectDoc(id) {
  const remark = needValue('rej_remark', 'Tell the employee why the document is rejected');
  try { const r = await api('/api/documents/' + id, { method: 'PUT', body: { action: 'Rejected', reviewer_remark: remark } }); toast(r.message || 'Rejected', 'success'); closeAllModals(); loadDocuments(true); loadDashboard(true); } catch (e) { }
}
function openDocUpload(presetDocType, presetEmployee) {
  const meta = APP.docMeta || {};
  const types = meta.doc_types || [];
  const empLocked = !isAdmin();
  const body = `<div class="space-y-3.5">
    ${grid('md:grid-cols-2 gap-3', [
      isAdmin() ? fieldRow('File it for', 'doc_employee', presetEmployee || APP.user.employee_id || '', { type: 'select', options: employeeOptions('Select employee'), placeholder: 'Select employee' }) : `<div><div class="lbl">File it for</div><div class="field flex items-center gap-2 bg-[#f0fdf4]">${avatar(APP.me?.employee || APP.user.employee_id || '')}<div><div class="text-[13px] font-medium">${esc(APP.me?.employee?.full_name || APP.user.name)}</div><div class="text-[11px] text-[#94a3b8]">Documents you upload are always filed under your own record</div></div></div></div>`,
      fieldRow('Document type', 'doc_type', presetDocType || '', { type: 'select', options: types.map(t => ({ value: t.type, label: `${t.type}${t.mandatory ? ' (mandatory)' : ''}` })), placeholder: 'Select type', onchange: 'docTypeChanged()' })].join(''))}
    <div id="docPurposeHint" class="text-[12px] text-[#15803d] bg-[#d1fae5] rounded-xl p-3 hidden"></div>
    ${fieldRow('Title', 'doc_title', '', { placeholder: 'e.g. Aadhaar front and back, Apr 2026' })}
    ${fieldRow('Why is this on file? / what it is for', 'doc_purpose', '', { placeholder: 'Selected automatically from the type — edit if it needs a specific note', rows: 2, type: 'textarea' })}
    ${fieldRow('Anything HR should know', 'doc_desc', '', { type: 'textarea', rows: 2, placeholder: 'Optional note to the reviewer (e.g. "name differs from PAN, marriage certificate attached")' })}
    ${grid('md:grid-cols-3 gap-3', [fieldRow('Valid from', 'doc_from', todayIso(), { type: 'date' }), `<div><div class="lbl">Valid till</div><input id="doc_till" type="date" class="field"><div id="docTillNote" class="text-[11px] text-[#b7791f] mt-1 hidden">Required for this type</div></div>`, fieldRow('Who can see it', 'doc_visibility', 'Self + HR', { type: 'select', options: meta.visibilities || ['HR only', 'Manager + HR', 'Self + HR', 'Company'] })].join(''))}
    <div><div class="lbl">File</div>
      <div id="dropZone" class="border-2 border-dashed border-[#e2e8f0] rounded-xl p-5 text-center cursor-pointer hover:border-[#15803d]/40 transition" onclick="$('#docFileInput').click()">
        <i class="fas fa-cloud-upload-alt text-[22px] text-[#94a3b8]"></i>
        <div class="text-[13px] font-medium mt-1.5" id="dropText">Click to choose a PDF or image</div>
        <div class="text-[11.5px] text-[#94a3b8]">Max 25 MB · stored in ${esc(meta.storage_mode || 'uploads/')}</div>
      </div>
      <input type="file" id="docFileInput" class="hidden" accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx" onchange="docFileChosen(this)">
      <div class="text-[11.5px] text-[#94a3b8] mt-2">No file? Save it as a metadata record — HR sees that it is a record only.</div></div>
  </div>`;
  openModal('Upload a document', body, modalFootSave('submitDocUpload()', 'Upload & file it'));
  docTypeChanged();
  const dz = $('#dropZone');
  ['dragover', 'dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault();
    dz.classList.toggle('border-[#15803d]', ev !== 'dragleave');
    if (ev === 'drop' && e.dataTransfer.files[0]) { $('#docFileInput').files = e.dataTransfer.files; docFileChosen({ files: e.dataTransfer.files, value: '' }); }
  }));
}
function docTypeChanged() {
  const t = $('#doc_type')?.value;
  const meta = (APP.docMeta?.doc_types || []).find(x => x.type === t);
  const hint = $('#docPurposeHint');
  if (!meta) { hint.classList.add('hidden'); $('#docTillNote')?.classList.add('hidden'); return; }
  hint.classList.remove('hidden');
  hint.innerHTML = `<b>${esc(meta.type)}</b> · ${esc(meta.purpose)}${meta.mandatory ? ' · <span class="text-[#c0392b]">mandatory for your file</span>' : ''}`;
  if (!$('#doc_purpose').value.trim()) $('#doc_purpose').value = meta.purpose || '';
  const needTill = !!meta.expiry;
  $('#docTillNote').classList.toggle('hidden', !needTill);
  $('#docTillNote').textContent = needTill ? 'This document has an expiry - valid till is required' : '';
  if (!needTill && !$('#doc_till').value) $('#doc_from').closest('div').classList.remove('ring-2');
}
function docFileChosen(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  $('#dropText').innerHTML = `<i class="fas fa-paperclip"></i> ${esc(f.name)} · ${humanSize(f.size)}`;
  if (!$('#doc_title').value.trim()) $('#doc_title').value = f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
  APP.docFile = f;
}
async function submitDocUpload() {
  const employee_id = isAdmin() ? needValue('doc_employee', 'Choose whose document this is') : (APP.me?.employee?.id || APP.user.employee_id);
  const doc_type = needValue('doc_type', 'Choose the document type');
  const till = $('#doc_till').value;
  const meta = (APP.docMeta?.doc_types || []).find(x => x.type === doc_type);
  if (meta && meta.expiry && !till) { toast('This document has an expiry date — fill in “Valid till”.', 'error'); $('#doc_till').focus(); return; }
  const fd = new FormData();
  fd.append('employee_id', employee_id); fd.append('doc_type', doc_type);
  fd.append('title', $('#doc_title').value.trim()); fd.append('purpose', $('#doc_purpose').value.trim());
  fd.append('description', $('#doc_desc').value.trim()); fd.append('visibility', $('#doc_visibility').value);
  if ($('#doc_from').value) fd.append('valid_from', $('#doc_from').value);
  if (till) fd.append('valid_till', till);
  if (APP.docFile) fd.append('file', APP.docFile);
  try {
    const r = await api('/api/documents', { method: 'POST', body: fd });
    toast(r.message, 'success'); APP.docFile = null; closeAllModals();
    await loadDocuments(true); loadDashboard(true); if (currentModule === 'me') loadMe(true);
  } catch (e) { }
}
function renderDocRequests() {
  const rows = APP.docReqs || [];
  const box = $('#documentRequestsList');
  if (!rows.length) { box.innerHTML = section('No outstanding requests', '', emptyState('Nothing is being asked of you', 'HR can request a specific document with a due date.')); return; }
  box.innerHTML = rows.map(r => `<div class="keka-card p-4 ${r.overdue ? '!border-[#ffc9c9]' : ''}">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0"><div class="flex items-center gap-2">${avatar(r.employee)}<div><div class="text-[13px] font-medium">${esc(r.employee?.full_name || 'You')} needs to submit</div><div class="text-[11.5px] text-[#94a3b8]">Requested by ${esc(r.requester || 'HR')}${r.due_label ? ` · due ${fmtDate(r.due_date)}` : ''}</div></div></div></div>
      ${statusPill(r.status)}</div>
    <div class="mt-3 text-[13px]"><span class="pill bg-[#d1fae5] text-[#15803d]">${esc(r.doc_type)}</span></div>
    <div class="text-[12.5px] text-[#64748b] mt-2">${esc(r.reason)}</div>
    <div class="text-[11.5px] text-[#94a3b8] mt-1.5"><i class="fas fa-info-circle"></i> ${esc(r.doc_purpose || '')}</div>
    ${r.overdue ? '<div class="mt-2 text-[11.5px] text-[#c0392b]"><i class="fas fa-exclamation-circle"></i> Past the due date</div>' : ''}
    <div class="flex gap-2 mt-3 pt-3 border-t border-[#f1f5f9]">
      ${(r.status === 'Pending' || r.status === 'Requested') ? `<button onclick="openDocUpload('${esc(r.doc_type)}','${r.employee_id}')" class="btn btn-primary btn-xs"><i class="fas fa-cloud-upload-alt"></i> Upload it now</button>` : ''}
      ${r.has_document ? `<button onclick="setDocTab('files')" class="btn btn-ghost btn-xs">Already on file</button>` : ''}
      ${isAdmin() ? `<button onclick="remindDocRequest('${r.id}')" class="btn btn-ghost btn-xs ml-auto"><i class="far fa-paper-plane"></i> Nudge</button><button onclick="api('/api/document-requests/${r.id}',{method:'PUT',body:{status:'Fulfilled'}}).then(r=>{toast(r.message,'success');loadDocuments(true)})" class="btn btn-ghost btn-xs">Mark fulfilled</button>` : ''}
    </div></div>`).join('');
}
function remindDocRequest(id) { toast('Reminder queued — the employee will see this at the top of their Documents tab.', 'success'); }
function openDocRequestForm() {
  const types = (APP.docMeta?.doc_types || []);
  const body = grid('md:grid-cols-2 gap-3', [
    fieldRow('Ask which employee', 'dr_emp', '', { type: 'select', options: employeeOptions(false), placeholder: 'Select employee', required: true }),
    fieldRow('Document needed', 'dr_type', '', { type: 'select', options: types.map(t => ({ value: t.type, label: t.type })), placeholder: 'Select document', required: true }),
    fieldRow('Due date', 'dr_due', isoDay(new Date(Date.now() + 7 * 864e5)), { type: 'date' }),
    fieldRow('Why do you need it?', 'dr_reason', '', { type: 'textarea', required: true, rows: 3, placeholder: 'Mandatory for the onboarding audit — we have no PAN on file.' })].join(''));
  openModal('Request a document', `<div class="space-y-3">${body}</div>`, modalFootSave('submitDocRequest()', 'Send request'));
}
async function submitDocRequest() {
  const body = { employee_id: needValue('dr_emp', 'Choose the employee'), doc_type: needValue('dr_type', 'Choose the document'), reason: needValue('dr_reason', 'Explain why — it is shown to the employee'), due_date: $('#dr_due').value || null };
  try { const r = await api('/api/document-requests', { method: 'POST', body }); toast(r.message, 'success'); closeAllModals(); loadDocuments(true); } catch (e) { }
}
function renderDocCompliance() {
  const meta = APP.docMeta || {};
  $('#docRequiredList').innerHTML = (meta.required_doc_types || []).map(t => `<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(t)}</span>`).join(' ');
  const list = meta.checklist || [];
  const box = $('#docChecklistTable');
  if (!isAdmin()) { box.innerHTML = emptyState('Compliance view is for HR Admins', 'Your own checklist is on the Me page.'); return; }
  if (!list.length) { box.innerHTML = emptyState('No employees to check'); return; }
  const complete = list.filter(c => c.completion_pct === 100).length;
  box.innerHTML = `<div class="flex flex-wrap items-center gap-3 mb-4 text-[12.5px] text-[#64748b]"><span class="pill bg-[#e6f9f0] text-[#0f9d58]">${complete} fully compliant</span><span class="pill bg-[#fff4e6] text-[#b7791f]">${list.filter(c => c.unverified.length).length} with items to verify</span><span class="pill bg-[#fff1f1] text-[#c0392b]">${list.filter(c => c.missing.length).length} missing documents</span><span class="ml-auto">Storage: ${esc(meta.storage_label || '')} · ${esc(meta.storage_mode || '')}</span></div>
  <table class="kt"><thead><tr><th>Employee</th><th>Compliance</th><th>Verified</th><th>Missing mandatory</th><th>To verify</th><th>Renewals</th><th class="text-right">Action</th></tr></thead><tbody>${list.map(c => `<tr class="clickable" onclick="openDocUpload('${esc(c.missing[0] || '')}','${c.employee.id}')"><td>${personLine(c.employee, c.employee.designation, 28)}</td><td style="min-width:130px"><div class="flex items-center gap-2"><div class="bar flex-1"><span style="width:${c.completion_pct}%;background:${c.completion_pct === 100 ? '#0f9d58' : c.completion_pct > 50 ? '#f59e0b' : '#c0392b'}"></span></div><span class="num text-[12px]">${c.completion_pct}%</span></div></td><td class="num">${c.verified}/${c.total_uploaded}</td><td>${(c.missing || []).map(m => `<span class="pill bg-[#fff1f1] text-[#c0392b] mr-1">${esc(m)}</span>`).join('') || '<span class="text-[#0f9d58] text-[12px]">complete</span>'}</td><td class="num">${(c.unverified || []).length}</td><td class="num">${(c.expiring || []).length}</td><td class="text-right"><button class="btn btn-ghost btn-xs !py-1"><i class="fas fa-paper-plane"></i> Request</button></td></tr>`).join('')}</tbody></table>`;
}

/* ================================================================== ATTENDANCE */
let attRowsCache = [], attView = 'list';
async function loadAttendance(refresh) {
  await loadLookups();
  if (!$('#attMonth').value) $('#attMonth').value = todayIso().slice(0, 7);
  if (isAdmin() && $('#attEmployeeFilter').classList.contains('hidden')) {
    $('#attEmployeeFilter').classList.remove('hidden');
    fillSelect('#attEmployeeFilter', employeeOptions('Whole company'), '', false);
    $('#attEmployeeFilter').onchange = () => { loadAttendance(true); };
  }
  if (!isAdmin()) { $('#attEmployeeFilter').classList.add('hidden'); }
  const p = new URLSearchParams({ month: $('#attMonth').value });
  if (isAdmin() && $('#attEmployeeFilter').value) p.set('employee_id', $('#attEmployeeFilter').value);
  try {
    const [data, summary, regs] = await Promise.all([api('/api/attendance?' + p.toString()), api('/api/attendance/summary?' + p.toString()), api('/api/regularizations')]);
    attRowsCache = data.rows || [];
    APP.attSummary = summary; APP.regs = regs;
    $('#attMonth').onchange = () => loadAttendance(true);
    renderAttSummary(summary, regs);
    renderAttendanceTable();
    renderAttendanceCalendar(summary);
    renderRegPanel(regs);
  } catch (e) { }
}
function renderAttSummary(s, regs) {
  const pending = (regs || []).filter(r => r.status === 'Pending').length;
  $('#regCount').textContent = pending;
  $('#regCount').className = `pill ml-1 ${pending ? 'bg-[#fff4e6] text-[#b7791f]' : 'bg-[#f0fdf4] text-[#94a3b8]'}`;
  const cells = [['Days marked', s.days_marked, 'of ' + s.working_days + ' working days', ''], ['Present', s.present, 'full days', '#0f9d58'], ['WFH', s.wfh, 'approved remote', '#15803d'], ['On leave', s.on_leave, 'approved', '#4ade80'], ['Half days', s.half_days, '', '#b7791f'], ['Absent', s.absent, '', s.absent ? '#c0392b' : ''], ['Hours logged', s.total_hours, s.avg_hours + ' h avg', ''], ['Overtime', s.overtime_hours, 'beyond 8 h/day', s.overtime_hours ? '#15803d' : '']]
    .map(([l, v, h, c]) => `<div class="keka-card p-3.5"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold leading-tight">${l}</div><div class="font-display font-bold text-[21px] mt-1 num" style="${c ? 'color:' + c : ''}">${v ?? 0}</div><div class="text-[11px] text-[#94a3b8]">${esc(h)}</div></div>`).join('');
  const late = `<div class="keka-card p-3.5"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">Late arrivals</div><div class="font-display font-bold text-[21px] mt-1 num" style="color:${s.late_days ? '#b7791f' : ''}">${s.late_days}</div><div class="text-[11px] text-[#94a3b8]">after 09:30</div></div>`;
  $('#attSummary').innerHTML = cells + late;
}
function setAttView(v) { attView = v; $$('#module-attendance [data-attview]').forEach(x => x.classList.toggle('active', x.dataset.attview === v)); }
/* Punch-location cells: compact "in / out" stacks for the attendance table and the
   day-detail modal. Each side falls back to whatever the row knows - a GPS pin label,
   the legacy free-text Location, or nothing. Map links are opened in a new tab. */
function punchLocCell(a) {
  const bit = (side) => {
    const label = a[`clock_${side}_location_label`] || (side === 'in' ? a.location : '');
    const link = a[`clock_${side}_map`];
    if (!label && !link) return '';
    const pin = link ? `<a href="${esc(link)}" target="_blank" rel="noopener" title="View on map" class="text-[#15803d] ml-0.5"><i class="fas fa-map-marked-alt text-[10px]"></i></a>` : '';
    return `<div class="flex items-center gap-1 ${side === 'in' ? 'text-[#0f9d58]' : 'text-[#b7791f]'}"><span class="uppercase text-[9.5px] text-[#94a3b8]">${side}·</span><span class="truncate min-w-0" title="${esc(label)}">${esc(label || '—')}</span>${pin}</div>`;
  };
  const body = bit('in') + bit('out');
  return body || '<span class="text-[#cbd5e1]">—</span>';
}
function punchLocDetail(rec) {
  const bit = (side) => {
    const label = rec[`clock_${side}_location_label`] || (side === 'in' ? rec.location : '');
    const link = rec[`clock_${side}_map`];
    if (!label && !link) return `<span class="uppercase text-[10px] text-[#94a3b8]">${side}</span> —`;
    const m = link ? ` · <a href="${esc(link)}" target="_blank" rel="noopener" class="text-[#15803d] underline">map</a>` : '';
    return `<span class="uppercase text-[10px] text-[#94a3b8]">${side}</span> ${esc(label)}${m}`;
  };
  return `${bit('in')}<br>${bit('out')}`;
}
function renderAttendanceTable() {
  const status = $('#attStatusFilter').value;
  let rows = attRowsCache;
  if (status !== 'All') rows = rows.filter(r => r.status === status);
  $('#attStatusFilter').onchange = renderAttendanceTable;
  const tb = $('#attendanceTable');
  if (!rows.length) { tb.innerHTML = `<tr><td colspan="${isAdmin() ? 10 : 9}">${emptyState('No attendance in this month', 'Change the month, or add a record for a past date.')}</td></tr>`; return; }
  const dayMap = {};
  (APP.regs || []).forEach(r => { dayMap[String(r.date)] = r.status; });
  tb.innerHTML = rows.slice(0, 500).map(a => `<tr class="clickable" onclick="openDayDetail('${a.date}','${a.employee_id}')">
    <td class="num">${fmtDayShort(a.date)}<div class="text-[11px] text-[#94a3b8]">${esc(a.date_label)}</div></td>
    ${isAdmin() ? `<td><div class="flex items-center gap-2">${avatar(a.employee_avatar, 26)}<div><div class="font-medium">${esc(a.employee_name)}</div><div class="text-[11px] text-[#94a3b8]">${esc(a.employee_code)} · ${esc(a.department)}</div></div></div></td>` : ''}
    <td class="num">${esc(a.clock_in_label)}${a.late_minutes > 0 ? `<div class="text-[10.5px] text-[#b7791f]">${a.late_minutes} min late</div>` : ''}</td>
    <td class="num">${esc(a.clock_out_label)}</td>
    <td class="num font-medium">${esc(a.worked_label)}</td>
    <td class="num text-[12px] text-[#64748b]">${num(a.break_minutes) || '—'}</td>
    <td>${statusPill(a.status)}</td>
    <td class="text-[12.5px]">${punchLocCell(a)}</td>
    <td class="text-[12px]">${a.regularization_status && a.regularization_status !== 'None' ? statusPill(a.regularization_status) : '<span class="text-[#cbd5e1]">—</span>'}</td>
    <td class="text-right"><div class="row-actions inline-flex gap-1">
      <button onclick="event.stopPropagation();openRegularizeForm('${a.date}','${a.employee_id}')" class="btn btn-ghost btn-xs !py-1" title="Request a correction"><i class="fas fa-pen-to-square"></i> Regularize</button>
      ${isAdmin() ? `<button onclick="event.stopPropagation();openManualAttendance('${a.employee_id}','${a.date}')" class="btn btn-ghost btn-xs !py-1" title="Edit record"><i class="far fa-edit"></i></button>` : ''}
    </div></td></tr>`).join('');
}
function renderAttendanceCalendar(summary) {
  const month = $('#attMonth').value;
  const [y, m] = month.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  const days = new Date(y, m, 0).getDate();
  const cal = summary.calendar || {};
  $('#calTitle').textContent = `${summary.month_label || first.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })} · ${summary.days_marked} days marked`;
  const colors = { Present: '#0f9d58', 'Work From Home': '#15803d', 'On Leave': '#4ade80', 'Half Day': '#f59e0b', Absent: '#c0392b' };
  const offset = (first.getDay() + 6) % 7;
  let html = `<div class="cal">${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => `<div class="cal-head">${d}</div>`).join('')}`;
  for (let i = 0; i < offset; i++) html += '<div class="cal-day cal-out"></div>';
  for (let d = 1; d <= days; d++) {
    const iso = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const st = cal[iso];
    const weekend = new Date(y, m - 1, d).getDay() === 0 || new Date(y, m - 1, d).getDay() === 6;
    const rec = (attRowsCache || []).find(r => String(r.date) === iso);
    const reg = (APP.regs || []).find(r => String(r.date) === iso);
    html += `<div class="cal-day ${rec ? 'has' : ''} ${weekend ? 'cal-weekend' : ''}" ${rec ? `onclick="openDayDetail('${iso}','${rec.employee_id}')"` : ''} title="${st || (weekend ? 'Week off' : 'Not marked')}">
      <div class="flex items-center justify-between"><span class="num font-medium ${weekend ? 'text-[#cbd5e1]' : ''}">${d}</span>${reg ? '<i class="fas fa-pen text-[9px] text-[#b7791f]"></i>' : ''}</div>
      ${rec ? `<div class="text-[9.5px] text-[#94a3b8] truncate mt-0.5">${esc(rec.clock_in_label)}</div>` : ''}
      ${st ? `<div class="dot" style="background:${colors[st] || '#94a3b8'}"></div>` : ''}</div>`;
  }
  for (let i = (offset + days) % 7; i && i < 7; i++) html += '<div class="cal-day cal-out"></div>';
  html += '</div>';
  $('#attendanceCalendar').innerHTML = html;
  $('#calLegend').innerHTML = Object.entries(colors).map(([k, v]) => `<span class="flex items-center gap-1.5"><span style="width:9px;height:9px;border-radius:3px;background:${v}" class="inline-block"></span>${k}</span>`).join('');
}
function openDayDetail(day, empId) {
  const rec = (attRowsCache || []).find(r => String(r.date) === String(day) && String(r.employee_id) === String(empId)) || (attRowsCache || []).find(r => String(r.date) === String(day));
  if (!rec) { toast('No record on that day', 'info'); return; }
  const info = (l, v) => `<div class="bg-[#f0fdf4] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="text-[13.5px] font-medium mt-1 num">${v || '—'}</div></div>`;
  openModal(fmtDate(day, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }),
    `<div class="grid grid-cols-2 md:grid-cols-4 gap-3">${info('Employee', esc(rec.employee_name))}${info('Clock in', esc(rec.clock_in_label))}${info('Clock out', esc(rec.clock_out_label))}${info('Worked', esc(rec.worked_label))}${info('Break', num(rec.break_minutes) + ' min')}${info('Status', statusPill(rec.status))}${info('Punch locations', punchLocDetail(rec))}${info('Correction', statusPill(rec.regularization_status))}</div>${rec.note ? `<div class="mt-3 text-[12.5px] text-[#64748b] bg-[#fff4e6] rounded-xl p-3"><b>Note:</b> ${esc(rec.note)}</div>` : ''}`,
    `<button onclick="openRegularizeForm('${day}','${rec.employee_id}');closeAllModals()" class="btn btn-ghost mr-auto"><i class="fas fa-pen-to-square"></i> Request a correction</button>${isAdmin() ? `<button onclick="openManualAttendance('${rec.employee_id}','${day}');closeAllModals()" class="btn btn-primary btn-xs"><i class="far fa-edit"></i> Edit record</button>` : ''}<button onclick="closeAllModals()" class="btn btn-ghost">Close</button>`);
}
function renderRegPanel(regs) {
  $('#regForm').innerHTML = `<div class="space-y-3">
    ${fieldRow('Date', 'reg_date', todayIso(), { type: 'date' })}
    <div id="regDayHint" class="text-[11.5px] text-[#64748b] -mt-1 leading-snug"></div>
    ${fieldRow('What went wrong?', 'reg_type', 'Missing punch-out', { type: 'select', options: ['Missing punch-in', 'Missing punch-out', 'Wrong in/out times', 'Work from home', 'On duty / field visit', 'Late arrival', 'Half day correction'] })}
    ${grid('grid-cols-2 gap-3', [fieldRow('Correct clock-in', 'reg_in', '', { type: 'time' }), fieldRow('Correct clock-out', 'reg_out', '', { type: 'time' })].join(''))}
    ${fieldRow('Reason (mandatory)', 'reg_reason', '', { type: 'textarea', rows: 3, required: true, minlength: 10, placeholder: 'The biometric device was down between 9 and 10, so I signed the register.' })}
    <div id="regReasonCount" class="text-[11px] text-[#94a3b8] -mt-1">At least 10 characters — your approver needs to know why.</div>
    <button onclick="submitRegularization()" class="btn btn-primary btn-xs w-full justify-center">Send for approval</button></div>`;
  const r = $('#reg_reason');
  r.addEventListener('input', () => { const n = r.value.trim().length; $('#regReasonCount').innerHTML = n < 10 ? `<span class="text-[#c0392b]">${10 - n} more characters needed</span>` : `<span class="text-[#0f9d58]">Looks good</span>`; });
  const dEl = $('#reg_date');
  if (dEl) { dEl.addEventListener('change', syncRegForm); syncRegForm(); }
  const box = $('#regularizationList');
  if (!regs.length) { box.innerHTML = emptyState('No regularization requests', 'When you fix a punch record, the request and its reason land here.'); return; }
  box.innerHTML = regs.map(r2 => `<div class="p-4 rounded-xl border border-[#f1f5f9] ${r2.status === 'Pending' ? 'bg-[#fffdf7]' : 'bg-white'}">
    <div class="flex items-start gap-2.5">
      ${avatar(r2.employee?.id ? { full_name: r2.employee.full_name, avatar: r2.employee.avatar } : '', 30)}
      <div class="min-w-0 flex-1"><div class="text-[13px] font-medium">${esc(r2.employee?.full_name || 'You')} <span class="text-[11.5px] text-[#94a3b8] font-normal">· ${fmtDate(r2.date)}</span></div>
        <div class="text-[12px] text-[#64748b] mt-1">${esc(r2.request_type || 'Correction')}${r2.clock_in_correction || r2.clock_out_correction ? ` — in ${esc(r2.clock_in_correction || r2.clock_in_label)}, out ${esc(r2.clock_out_correction || r2.clock_out_label)}` : ''}</div>
        <div class="text-[12.5px] mt-2 bg-[#f0fdf4] rounded-lg p-2.5 leading-relaxed">“${esc(r2.reason || '')}”</div>
        ${r2.reviewer_remark ? `<div class="text-[12px] mt-2 ${r2.status === 'Rejected' ? 'text-[#c0392b]' : 'text-[#0f9d58]'}"><b>Reviewer:</b> ${esc(r2.reviewer_remark)}</div>` : ''}</div>
      ${statusPill(r2.status)}</div>
    ${r2.status === 'Pending' ? `<div class="flex gap-2 mt-3 pt-3 border-t border-[#f1f5f9]">${isAdmin() ? `<button onclick="regAction('${r2.id}','approve')" class="btn btn-primary btn-xs"><i class="fas fa-check"></i> Approve & fix the record</button><button onclick="regAction('${r2.id}','reject')" class="btn btn-danger btn-xs"><i class="fas fa-xmark"></i> Reject</button>` : '<span class="text-[12px] text-[#94a3b8]">With your manager / HR now.</span>'}<button onclick="withdrawReg('${r2.id}')" class="btn btn-ghost btn-xs ml-auto">Withdraw</button></div>` : ''}</div>`).join('');
}
function openRegularizeForm(day, empId) {
  setAttView('regularization');
  $$('#module-attendance [data-attview]').forEach(x => x.classList.toggle('active', x.dataset.attview === 'regularization'));
  if (day) $('#reg_date').value = String(day).slice(0, 10);
  $('#reg_reason').value = '';
  APP.regTarget = empId || null;
  syncRegForm();
  $('#reg_reason').focus();
  $('#regForm').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
/* Show what the chosen day already holds and start the correction from those times -
   otherwise the request is ambiguous and the server (rightly) rejects it. */
function syncRegForm() {
  const dayEl = $('#reg_date'); if (!dayEl) return;
  const day = String(dayEl.value || '').slice(0, 10);
  const rec = (attRowsCache || []).find(r => String(r.date).slice(0, 10) === day &&
              (APP.regTarget ? String(r.employee_id) === String(APP.regTarget) : true)) || null;
  APP.regRec = rec;
  const hhmm = v => (v ? String(v).slice(0, 5) : '');
  const hint = $('#regDayHint');
  if (hint) {
    const bits = rec ? [`on file ${hhmm(rec.clock_in) || 'no in'} → ${hhmm(rec.clock_out) || 'no out'}`, rec.status || '']
                     : ['no attendance record on that day yet'];
    hint.innerHTML = `<i class="fas fa-circle-info text-[#94a3b8] mr-1"></i>${fmtDate(day)} — ${bits.filter(Boolean).map(esc).join(' · ')}. A reason is mandatory.`;
  }
  const typeEl = $('#reg_type');
  if (typeEl) {
    const want = rec && hhmm(rec.clock_in) && hhmm(rec.clock_out) ? 'Wrong in/out times'
               : rec && !hhmm(rec.clock_in) ? 'Missing punch-in' : 'Missing punch-out';
    if ([...typeEl.options].some(o => o.value === want)) typeEl.value = want;
  }
  if (rec) {
    const inEl = $('#reg_in'), outEl = $('#reg_out');
    if (inEl && !inEl.value && hhmm(rec.clock_in)) inEl.value = hhmm(rec.clock_in);
    if (outEl && !outEl.value && hhmm(rec.clock_out)) outEl.value = hhmm(rec.clock_out);
  }
}
async function submitRegularization() {
  const reason = ($('#reg_reason').value || '').trim();
  if (reason.length < 10) { toast('A reason of at least 10 characters is required', 'error'); $('#reg_reason').focus(); return; }
  const body = { date: $('#reg_date').value, request_type: $('#reg_type').value, reason, clock_in_correction: $('#reg_in').value || null, clock_out_correction: $('#reg_out').value || null };
  const rec = APP.regRec;
  if (rec && rec.clock_in && rec.clock_out && !body.clock_in_correction && !body.clock_out_correction) {
    toast('That day already has both punches — set the in or out time you want changed', 'error');
    ($('#reg_in').value ? $('#reg_out') : $('#reg_in')).focus();
    return;
  }
  try {
    const r = await api('/api/regularizations', { method: 'POST', body });
    toast(r.message, 'success');
    $('#reg_reason').value = ''; $('#reg_in').value = ''; $('#reg_out').value = '';
    APP.regTarget = null; APP.regRec = null;
    loadAttendance(true); loadDashboard(true);
  } catch (e) { }
}
function regAction(id, action) {
  if (action === 'approve') { api('/api/regularizations/' + id + '/action', { method: 'POST', body: { action } }).then(r => { toast(r.message, 'success'); loadAttendance(true); loadDashboard(true); }); return; }
  openModal('Reject this correction', fieldRow('Remark (required)', 'reg_remark', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Attach the manager approval mail before requesting again.' }), modalFootSave(`submitRegReject('${id}')`, 'Reject request'));
}
async function submitRegReject(id) {
  const remark = needValue('reg_remark', 'A remark is required when rejecting');
  try { const r = await api('/api/regularizations/' + id + '/action', { method: 'POST', body: { action: 'reject', remark } }); toast(r.message, 'success'); closeAllModals(); loadAttendance(true); } catch (e) { }
}
async function withdrawReg(id) { await confirmAction('Withdraw this correction request?', async () => { const r = await api('/api/regularizations/' + id, { method: 'DELETE' }); toast(r.message, 'success'); loadAttendance(true); }, 'Withdraw'); }
function openManualAttendance(empId, day) {
  const rec = (attRowsCache || []).find(r => String(r.date) === String(day) && (!empId || String(r.employee_id) === String(empId)))
    || (attRowsCache || []).find(r => String(r.date) === String(day));
  // remembered so Save still works if the select ends up without a matching option (exited employee)
  APP.maCtx = { employee_id: empId || (rec && rec.employee_id) || '', date: day || todayIso() };
  const opts = employeeOptions(false).slice();
  if (APP.maCtx.employee_id && !opts.some(o => String(o.value) === String(APP.maCtx.employee_id))) {
    opts.push({ value: APP.maCtx.employee_id, label: `${(rec && rec.employee_name) || 'Employee'} · not in the active list` });
  }
  const body = grid('md:grid-cols-2 gap-3', [
    fieldRow('Employee', 'ma_emp', APP.maCtx.employee_id, { type: 'select', options: opts, placeholder: 'Select', required: true }),
    fieldRow('Date', 'ma_date', day || todayIso(), { type: 'date', required: true }),
    fieldRow('Clock in', 'ma_in', rec?.clock_in ? String(rec.clock_in).slice(0, 5) : '', { type: 'time' }),
    fieldRow('Clock out', 'ma_out', rec?.clock_out ? String(rec.clock_out).slice(0, 5) : '', { type: 'time' }),
    fieldRow('Status', 'ma_status', rec?.status || 'Present', { type: 'select', options: ['Present', 'Work From Home', 'Half Day', 'On Leave', 'Absent'] }),
    fieldRow('Work hours', 'ma_hours', '', { type: 'number', step: 0.5, placeholder: rec?.work_hours ? `${rec.work_hours} h on file - blank recomputes from the two times` : 'auto from in/out' }),
    fieldRow('Break (min)', 'ma_break', rec?.break_minutes ?? 45, { type: 'number', step: 15, placeholder: '45' }),
    fieldRow('Location', 'ma_loc', rec?.location || 'Office'),
    fieldRow('Note', 'ma_note', rec?.note || '', { placeholder: 'Marked by HR for the field visit' })].join(''));
  openModal(day ? `Edit ${fmtDate(day)}` : 'Mark attendance', `<div class="space-y-3">${body}
    <div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">Leaving <b>work hours</b> blank recomputes it as clock out − clock in − break, and the late mark follows the shift start with its grace. Fill the number in only if you want to force a total.</div></div>`, modalFootSave('submitManualAttendance()', day ? 'Save changes' : 'Mark day'));
}
async function submitManualAttendance() {
  const val = id => ((document.getElementById(id) || {}).value || '').trim();
  const ctx = APP.maCtx || {};
  const employee_id = val('ma_emp') || ctx.employee_id;
  const date = val('ma_date') || ctx.date;
  const ci = val('ma_in'), co = val('ma_out');
  if (!employee_id) { toast('Choose whose day this is', 'error'); return; }
  if (!date) { toast('Pick the date you are correcting', 'error'); return; }
  if (ci && co && co <= ci) { toast('Clock out is not after clock in - check the two times', 'error'); return; }
  const body = { employee_id, date, status: val('ma_status') || 'Present', clock_in: ci || null, clock_out: co || null,
                 work_hours: val('ma_hours') ? num(val('ma_hours')) : 0, break_minutes: val('ma_break') ? num(val('ma_break')) : 0,
                 location: val('ma_loc') || null, note: val('ma_note') || null, via_regularization: false };
  try { const r = await api('/api/attendance/entry', { method: 'POST', body }); toast(r.message, 'success'); closeAllModals(); loadAttendance(true); loadDashboard(true); } catch (e) { }
}

/* ================================================================== LEAVE */
async function loadLeave(filterStatus) {
  await loadLookups();
  if (typeof filterStatus === 'string' && filterStatus) { $$('#module-leave [data-leave]').forEach(x => x.classList.toggle('active', x.dataset.leave === filterStatus)); }
  const status = (typeof filterStatus === 'string' && filterStatus) ? filterStatus : (document.querySelector('#module-leave [data-leave].active')?.dataset.leave || 'All');
  const p = new URLSearchParams();
  if (status !== 'All') p.set('status', status);
  if (isAdmin()) {
    $('#leaveEmpFilter').classList.remove('hidden');
    fillSelect('#leaveEmpFilter', employeeOptions('Whole company'), $('#leaveEmpFilter').value, false);
    if ($('#leaveEmpFilter').value) p.set('employee_id', $('#leaveEmpFilter').value);
    $('#leaveEmpFilter').onchange = () => loadLeave(status);
  } else $('#leaveEmpFilter').classList.add('hidden');
  let rows = [], bal = [], types = [], holidays = [];
  try {
    const target = isAdmin() ? ($('#leaveEmpFilter').value || '') : (APP.user.employee_id || '');
    [rows, bal, types, holidays] = await Promise.all([api('/api/leave-requests?' + p.toString()), api('/api/leave-balances' + (target ? '?employee_id=' + target : '')), api('/api/leave-types'), api('/api/holidays')]);
  } catch (e) { return; }
  APP.leaveTypes = types;
  renderLeaveBalances(bal, types);
  renderLeaveTable(rows);
  renderHolidays(holidays);
  $('#leaveYearLabel').textContent = new Date().getFullYear() + (isAdmin() && !$('#leaveEmpFilter').value ? ' · company-wide' : '');
}
function renderLeaveBalances(bal, types) {
  const list = Array.isArray(bal) ? bal : [bal];
  const rows = list.flatMap(x => (x.balances || []).map(b => ({ ...b, who: x.employee?.full_name })));
  const box = $('#leaveBalances');
  if (!rows.length) { box.innerHTML = `<div class="text-[12.5px] text-[#94a3b8]">No quotas yet — they are created when an employee is added.</div>`; return; }
  const byType = {};
  rows.forEach(r => { const k = (r.who ? r.who + '||' : '') + r.leave_type; (byType[k] = byType[k] || []).push(r); });
  box.innerHTML = rows.map(b => `<div class="p-3.5 rounded-xl border border-[#f1f5f9]">
      <div class="flex items-center gap-2 mb-1.5"><span class="w-2 h-2 rounded-full" style="background:${b.color || '#15803d'}"></span><span class="text-[13px] font-semibold">${esc(b.leave_type)}</span>${b.who ? `<span class="text-[11.5px] text-[#94a3b8]">${esc(b.who)}</span>` : ''}<span class="ml-auto text-[12px] num text-[#64748b]"><b class="text-[#052e16]">${b.remaining}</b> / ${b.total}</span></div>
      <div class="bar"><span style="width:${b.used_pct}%;background:${b.color || '#15803d'}"></span></div>
      <div class="flex items-center gap-3 mt-1.5 text-[11px] text-[#94a3b8]"><span>${b.used} taken</span><span>${b.pending} pending</span>${b.is_paid ? '' : '<span class="text-[#b7791f]">unpaid</span>'}</div></div>`).join('');
}
function renderLeaveTable(rows) {
  const tb = $('#leaveTable');
  if (!rows.length) { tb.innerHTML = `<tr><td colspan="8">${emptyState('No leave requests here', 'Apply for leave and it will show up with its approval trail.', '<button class="btn btn-primary btn-xs" onclick="openLeaveModal()">Apply for leave</button>')}</td></tr>`; return; }
  tb.innerHTML = rows.map(l => `<tr>
    <td>${personLine(l.employee, l.employee?.department, 30)}</td>
    <td><span class="pill" style="background:${l.leave_color}22;color:${l.leave_color}">${esc(l.leave_type_label)}</span>${l.is_paid ? '' : ' <span class="pill bg-[#fff1f1] text-[#c0392b]">unpaid</span>'}</td>
    <td class="text-[12.5px] num">${esc(l.period_label)}${l.days !== Math.round(l.days) ? ' <span class="text-[11px] text-[#94a3b8]">(incl. half day)</span>' : ''}</td>
    <td class="num font-medium">${num(l.days)}</td>
    <td class="text-[12.5px] text-[#64748b] max-w-[230px]"><div class="line-clamp-2" title="${esc(l.reason)}">${esc(l.reason || '—')}</div>${l.admin_remark ? `<div class="text-[11px] text-[#15803d] truncate">HR: ${esc(l.admin_remark)}</div>` : ''}</td>
    <td class="text-[12px] num">${fmtDayShort(l.created_at)}</td>
    <td>${statusPill(l.status)}${l.approver ? `<div class="text-[11px] text-[#94a3b8]">${esc(l.approver.full_name)}</div>` : ''}</td>
    <td class="text-right"><div class="row-actions force inline-flex gap-1">
      ${l.status === 'Pending' && isAdmin() ? `<button onclick="leaveAction('${l.id}','approve')" class="btn btn-ghost btn-xs !py-1 text-[#0f9d58]" title="Approve"><i class="fas fa-check"></i></button><button onclick="rejectLeaveModal('${l.id}')" class="btn btn-ghost btn-xs !py-1 text-[#c0392b]" title="Reject"><i class="fas fa-xmark"></i></button>` : ''}
      ${(l.status === 'Pending' || l.status === 'Approved') && String(l.employee_id) === String(APP.user.employee_id) ? `<button onclick="cancelLeave('${l.id}')" class="btn btn-ghost btn-xs !py-1" title="Cancel">Cancel</button>` : ''}
    </div></td></tr>`).join('');
}
function renderHolidays(holidays) {
  const upcoming = (holidays || []).filter(h => num(h.days_left) >= 0).slice(0, 6);
  $('#holidayList').innerHTML = upcoming.length ? upcoming.map(h => `<div class="flex items-center gap-2.5 p-2.5 rounded-xl hover:bg-[#f0fdf4] transition"><div class="w-9 h-9 rounded-xl bg-[#d1fae5] text-[#15803d] flex flex-col items-center justify-center flex-shrink-0"><span class="text-[12px] font-bold leading-none num">${new Date(h.date + 'T00:00:00').getDate()}</span><span class="text-[8.5px] uppercase leading-none mt-0.5">${new Date(h.date + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short' })}</span></div><div class="min-w-0"><div class="text-[12.5px] font-medium truncate">${esc(h.name)}</div><div class="text-[11px] text-[#94a3b8]">${esc(h.type || 'Holiday')}</div></div><span class="pill bg-[#f0fdf4] text-[#64748b] ml-auto num">${h.days_left === 0 ? 'today' : 'in ' + h.days_left + 'd'}</span></div>`).join('') : '<div class="text-[12.5px] text-[#94a3b8]">No holidays left this year.</div>';
}
async function leaveAction(id, action) {
  try { const r = await api(`/api/leave-requests/${id}/action`, { method: 'POST', body: { action, remark: action === 'approve' ? 'Approved from Leave' : '' } }); toast(r.message, 'success'); loadLeave(); loadDashboard(true); if (currentModule === 'inbox') loadInbox(); } catch (e) { }
}
function rejectLeaveModal(id) { openModal('Reject leave request', `${fieldRow('Reason for rejecting (required)', 'lv_remark', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Two people from your team are already off that week — please pick different dates.' })}`, modalFootSave(`submitLeaveReject('${id}')`, 'Reject leave')); }
async function submitLeaveReject(id) {
  const remark = needValue('lv_remark', 'A remark is required when rejecting leave');
  try { const r = await api(`/api/leave-requests/${id}/action`, { method: 'POST', body: { action: 'reject', remark } }); toast(r.message, 'success'); closeAllModals(); loadLeave(); loadDashboard(true); } catch (e) { }
}
async function cancelLeave(id) { await confirmAction('Cancel this leave request? The days go back into your balance.', async () => { const r = await api(`/api/leave-requests/${id}/cancel`, { method: 'POST' }); toast(r.message, 'success'); loadLeave(); loadDashboard(true); }, 'Cancel leave'); }

async function openLeaveModal() {
  await loadLookups();
  const types = APP.lookups.leave_types || [];
  const empId = isAdmin() ? (APP.user.employee_id || '') : (APP.user.employee_id || '');
  let balances = [];
  try { balances = (await api('/api/leave-balances' + (empId ? '?employee_id=' + empId : '')))?.balances || []; } catch (e) { }
  APP.leaveBalances = balances;
  const opts = types.map(t => { const b = balances.find(x => String(x.leave_type_id) === String(t.id)); return { value: t.id, label: `${t.name}${b ? ` · ${b.remaining} left` : ''}` }; });
  const body = `<div class="space-y-3.5">
    ${grid('md:grid-cols-2 gap-3', [fieldRow('Leave type', 'lv_type', '', { type: 'select', options: opts, placeholder: 'Select leave type', required: true, onchange: 'lvTypeChanged()' }), `<div><div class="lbl">Balance</div><div id="lvBalHint" class="field bg-[#f0fdf4] text-[13px]">Pick a type to see what is left</div></div>`].join(''))}
    ${grid('md:grid-cols-2 gap-3', [fieldRow('From', 'lv_from', todayIso(), { type: 'date', required: true, onchange: 'lvDatesChanged()' }), fieldRow('To', 'lv_to', todayIso(), { type: 'date', required: true, onchange: 'lvDatesChanged()' })].join(''))}
    <div class="flex flex-wrap items-center gap-4">
      ${fieldRow('Half day on the last day', 'lv_half', false, { type: 'checkbox' })}
      <div id="lvDays" class="text-[12.5px] text-[#64748b] ml-auto"></div>
    </div>
    ${fieldRow('Reason for your approver', 'lv_reason', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Family function in Dādri — I will be back the next working day.' })}
    <div id="lvSummary" class="bg-[#d1fae5] rounded-xl p-3.5 text-[12.5px] text-[#166534]"></div></div>`;
  openModal('Apply for leave', body, modalFootSave('submitLeave()', 'Submit request'));
  lvDatesChanged();
}
function lvTypeChanged() {
  const id = $('#lv_type').value;
  const b = (APP.leaveBalances || []).find(x => String(x.leave_type_id) === String(id));
  $('#lvBalHint').innerHTML = b ? `<b class="num">${b.remaining}</b> of ${b.total} ${esc(b.leave_type)} days left${b.pending ? ` · ${b.pending} pending` : ''}` : 'No quota entry for this login';
  lvDatesChanged();
}
function lvDatesChanged() {
  const f = $('#lv_from').value, t = $('#lv_to').value || $('#lv_from').value;
  if (!f) return;
  const fd = new Date(f + 'T00:00:00'), td = new Date(t + 'T00:00:00');
  let days = isNaN(td) || td < fd ? 1 : Math.round((td - fd) / 864e5) + 1;
  if ($('#lv_half')?.checked) days -= 0.5;
  const b = (APP.leaveBalances || []).find(x => String(x.leave_type_id) === String($('#lv_type').value));
  $('#lvDays').innerHTML = `<b class="num text-[#052e16]">${days}</b> day${days === 1 ? '' : 's'} requested`;
  const warn = b && days > b.remaining ? `<span class="text-[#c0392b]"><i class="fas fa-exclamation-circle"></i> You only have ${b.remaining} left — reduce the range or pick another type.</span>` : '';
  $('#lvSummary').innerHTML = `${fmtDate(f)} → ${fmtDate(t)} · ${days} day${days === 1 ? '' : 's'}${b ? ` · ${b.remaining - days >= 0 ? (b.remaining - days) + ' will remain' : 'over quota'}` : ''}${warn ? '<div class="mt-1">' + warn + '</div>' : ''}`;
}
async function submitLeave() {
  const body = { leave_type_id: needValue('lv_type', 'Pick a leave type'), start_date: needValue('lv_from', 'Pick a start date'), end_date: $('#lv_to').value || $('#lv_from').value, half_day: $('#lv_half').checked, reason: needValue('lv_reason', 'Your approver needs a reason') };
  try { const r = await api('/api/leave-requests', { method: 'POST', body }); toast(r.message, 'success'); closeAllModals(); loadLeave(); loadDashboard(true); if (currentModule === 'me') loadMe(true); } catch (e) { }
}


/* ================================================================== TIMESHEET */
function mondayOf(d) { const x = new Date(d); const day = (x.getDay() + 6) % 7; x.setDate(x.getDate() - day); return x; }
function tsWeekInputValue() { const d = mondayOf(new Date()); return `${d.getFullYear()}-W${String(Math.ceil(((d - new Date(d.getFullYear(), 0, 1)) / 864e5 + 1) / 7)).padStart(2, '0')}`; }
function shiftTsWeek(delta) { const d = mondayOf(new Date(APP.tsWeek || todayIso())); d.setDate(d.getDate() + delta * 7); APP.tsWeek = isoDay(d); loadTimesheet(true); }
function setTsWeek(v) { if (!v) return; const [y, w] = v.split('-W'); const jan4 = new Date(+y, 0, 4); const firstMonday = new Date(jan4 - (((jan4.getDay() + 6) % 7) * 864e5)); const d = new Date(firstMonday.getTime() + ((+w - 1) * 7) * 864e5); APP.tsWeek = isoDay(d); loadTimesheet(true); }
function setTsTab(t) { $$('#module-timesheet [data-tstab]').forEach(x => x.classList.toggle('active', x.dataset.tstab === t)); if (t === 'team') loadTsTeam(); if (t === 'history') loadTsHistory(); if (t === 'projects') loadTsProjects(); }
async function loadTimesheet(refresh) {
  await loadLookups();
  if (!$('#tsWeekPicker').value) $('#tsWeekPicker').value = tsWeekInputValue();
  const week = APP.tsWeek || todayIso();
  let d;
  try { d = await api('/api/timesheet?week=' + week); } catch (e) { return; }
  APP.ts = d;
  APP.tsWeek = d.week;
  APP.tsLocked = !!d.locked;
  $('#tsWeekLabel').textContent = d.week_label || d.week;
  $('#tsWeekLabel').innerHTML = `${esc(d.week_label || d.week)} ${d.timesheet?.status ? statusPill(d.timesheet.status) : ''}`;
  const s = d.stats || {};
  $('#tsStats').innerHTML = [
    kpiCard('This week', (s.this_week || 0) + ' h', `of 40 h target · ${s.avg_week || 0} h avg`),
    kpiCard('Billable', (s.billable_week || 0) + ' h', `${s.utilization || 0}% utilisation`, { tone: 'brand' }),
    kpiCard('Weeks logged', s.weeks_logged || 0, 'submitted or approved'),
    kpiCard('Awaiting review', s.awaiting_review || 0, 'with your manager', { tone: s.awaiting_review ? 'warn' : 'default' }),
    kpiCard('Utilisation', (s.utilization || 0) + '%', 'billable ÷ logged', { tone: (s.utilization || 0) >= 70 ? 'good' : 'warn' }),
  ].join('');
  $('#tsStatusPill').innerHTML = d.locked ? `<span class="pill bg-[#e6f9f0] text-[#0f9d58]"><i class="fas fa-lock text-[9px]"></i> Approved — locked</span>` : `<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(d.timesheet?.status || 'Draft')}</span>`;
  $('#tsSaveBtn').style.display = d.locked ? 'none' : '';
  $('#tsSubmitBtn').style.display = (d.locked || d.timesheet?.status === 'Submitted') ? 'none' : '';
  APP.tsRows = [];
  (d.days || []).forEach(day => (day.entries || []).forEach(en => APP.tsRows.push({ project_id: en.project_id, task: en.task, billable: en.billable, hours: { [day.date]: en.hours } })));
  APP.tsRows = mergeTsRows(APP.tsRows);
  if (!APP.tsRows.length) APP.tsRows = [{ project_id: d.projects?.[0]?.id || '', task: '', billable: true, hours: {} }];
  renderTsGrid();
}
function mergeTsRows(rows) {
  // One grid row per (project, billable) so a week can be edited as a matrix.
  // Hours for the same day must ADD: several entries can share one project/day,
  // and overwriting here silently deleted logged time whenever the grid was saved.
  const out = [];
  rows.forEach(r => {
    const key = `${r.project_id || ''}|${r.billable ? 1 : 0}`;
    const found = out.find(x => `${x.project_id || ''}|${x.billable ? 1 : 0}` === key);
    if (found) {
      Object.keys(r.hours || {}).forEach(d => {
        found.hours[d] = Math.round(((Number(found.hours[d]) || 0) + (Number(r.hours[d]) || 0)) * 100) / 100;
      });
      if (!found.task && r.task) found.task = r.task;
    } else {
      out.push({ project_id: r.project_id, task: r.task, billable: r.billable, hours: { ...(r.hours || {}) } });
    }
  });
  return out;
}
function renderTsGrid() {
  const d = APP.ts, days = d.days || [];
  const head = `<div class="ts-head">Project</div><div class="ts-head">Task / notes</div><div class="ts-head">Bill</div>${days.map(x => `<div class="ts-head ${x.is_weekend ? '!bg-[#f0fdf4]' : ''}" style="text-align:center">${x.label}<div class="text-[10px] font-normal normal-case tracking-normal">${x.day_num}</div></div>`).join('')}<div class="ts-head" style="text-align:center">Total</div><div class="ts-head"></div>`;
  const rows = APP.tsRows.map((r, i) => tsRowHtml(r, i, days)).join('');
  const wrap = $('#tsGridWrap');
  wrap.innerHTML = `<div class="ts-grid" id="tsGrid">${head}${rows}</div>
    <div class="flex items-center justify-between mt-3 text-[12px] text-[#94a3b8]"><span>Enter hours per day (0–16). The week can be submitted once at least 20 hours are logged.</span><span class="flex items-center gap-3"><button onclick="openProjectForm(null)" class="btn btn-ghost btn-xs" title="Add a project that is not on the list"><i class="fas fa-plus"></i> New project</button><span id="tsDayTotals" class="num"></span></span></div>`;
  recalcTs();
}
function tsRowHtml(r, i, days) {
  const dis = APP.tsLocked ? 'disabled' : '';
  const cur = (APP.ts.projects || []).find(p => String(p.id) === String(r.project_id));
  const projOpts = tsProjectChoices(r.project_id);
  const projCell = `<select class="field !py-1.5 !text-[12px]" ${dis} onchange="tsRowProject(${i}, this.value)">${projOpts.map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(r.project_id ?? '') ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  const manage = (cur && !APP.tsLocked && canManageProject(cur))
    ? `<div class="flex items-center gap-2.5 mt-1 text-[10.5px] text-[#94a3b8]">
         <button type="button" class="hover:text-[#15803d]" onclick="openProjectForm('${cur.id}')" title="Rename ${esc(cur.name)}, change its rate or close it"><i class="fas fa-pen"></i> edit</button>
         <button type="button" class="hover:text-[#c0392b]" onclick="deleteProject('${cur.id}')" title="Take ${esc(cur.name)} off the list - only while nobody has logged hours on it"><i class="far fa-trash-alt"></i> remove</button>
       </div>` : '';
  return [
    `<div>${projCell}${cur && cur.client && cur.client !== 'Internal' ? `<div class="text-[10.5px] text-[#94a3b8] mt-1">${esc(cur.client)}</div>` : ''}${manage}</div>`,
    `<div><input class="field !py-1.5 !text-[12px]" ${dis} value="${esc(r.task || '')}" placeholder="what you worked on" onchange="APP.tsRows[${i}].task=this.value;recalcTs()"></div>`,
    `<div style="text-align:center"><input type="checkbox" ${dis} ${r.billable ? 'checked' : ''} onchange="APP.tsRows[${i}].billable=this.checked;recalcTs()" class="rounded border-[#cbd5e1] text-[#15803d]" title="Billable to the client"></div>`,
    ...days.map(day => `<div class="${day.is_future || day.is_weekend ? 'ts-future' : ''}"><input class="ts-h" type="number" min="0" max="16" step="0.5" ${dis} value="${r.hours[day.date] != null ? r.hours[day.date] : ''}" placeholder="${day.is_future ? '–' : '0'}" onchange="setTsHours(${i},'${day.date}',this.value)" data-ts="${i}|${day.date}" title="${day.label} ${day.day_num}"></div>`),
    `<div class="num font-semibold" style="text-align:center" id="tsRowTotal${i}">0</div>`,
    `<div style="text-align:center">${APP.tsLocked ? '' : `<button class="text-[#cbd5e1] hover:text-[#c0392b]" onclick="APP.tsRows.splice(${i},1);renderTsGrid()" title="Remove row"><i class="far fa-trash-alt text-[12px]"></i></button>`}</div>`].join('');
}
function setTsHours(i, day, v) {
  const n = num(v);
  if (n < 0 || n > 16) { toast('Hours must be between 0 and 16', 'error'); APP.tsRows[i].hours[day] = 0; renderTsGrid(); return; }
  APP.tsRows[i].hours[day] = n;
  recalcTs();
}
function tsRowProject(i, v) {
  if (v === '__new') { renderTsGrid(); openProjectForm(null, i); return; }   // the select's own "type a name" entry
  APP.tsRows[i].project_id = v; renderTsGrid();
}
function recalcTs() {
  const days = APP.ts?.days || [];
  let total = 0, billable = 0;
  const dayTotals = {};
  APP.tsRows.forEach((r, i) => {
    let rowSum = 0;
    days.forEach(d => { const h = num(r.hours[d.date]); rowSum += h; dayTotals[d.date] = (dayTotals[d.date] || 0) + h; total += h; if (r.billable) billable += h; });
    const el = $('#tsRowTotal' + i); if (el) el.textContent = (Math.round(rowSum * 10) / 10).toFixed(1);
  });
  $('#tsTotal').textContent = (Math.round(total * 10) / 10).toFixed(1);
  $('#tsBillable').textContent = (Math.round(billable * 10) / 10).toFixed(1);
  const over = Object.entries(dayTotals).filter(([, v]) => v > 12).map(([k, v]) => `${fmtDayShort(k)} ${v}h`);
  $('#tsWarn').innerHTML = over.length ? `<i class="fas fa-exclamation-circle"></i> Long day: ${over.join(', ')}` : (total > 50 ? '<i class="fas fa-exclamation-circle"></i> Over 50 hours this week' : '');
  $('#tsDayTotals').innerHTML = days.map(d => `<span class="mr-2 ${num(d.entries?.length) ? '' : 'text-[#cbd5e1]'}">${d.label} <b>${(dayTotals[d.date] || 0)}</b></span>`).join('');
}
function addTsRow() {
  if (APP.tsLocked) { toast('This week is approved and locked', 'warn'); return; }
  APP.tsRows.push({ project_id: (APP.ts.projects?.[0]?.id) || '', task: '', billable: true, hours: {} });
  renderTsGrid();
}
/* the grid is only as good as the project list it offers, so people can extend that list here */
function canManageProject(p) {
  if (!p) return false;
  return isAdmin() || (!!APP.user.employee_id && String(p.manager_id || '') === String(APP.user.employee_id));
}
function tsProjectChoices(currentId) {
  const all = (APP.ts && APP.ts.projects) || [];
  // a closed project stays on the list for the row that already uses it, so logged hours never go homeless
  const usable = all.filter(p => !p.status || p.status === 'Active' || p.status === 'On Hold'
    || String(p.id) === String(currentId || ''));
  return [{ value: '', label: 'Select project…' },
          ...usable.map(p => ({ value: p.id,
            label: `${p.name}${p.billing_rate ? ' · ' + inr(p.billing_rate) + '/h' : ''}${p.status && p.status !== 'Active' ? ' · ' + p.status : ''}` })),
          { value: '__new', label: '+ Type a new project name…' }];
}
function tsTabActive(tab) {
  const el = document.querySelector('#module-timesheet [data-tstab].active');
  return !!el && el.dataset.tstab === tab;
}
function openProjectForm(id, rowIdx) {
  const list = ((APP.ts && APP.ts.projects) || []).concat(APP.tsProjects || []);
  const p = list.find(x => String(x.id) === String(id)) || {};
  APP.pjRow = (rowIdx === null || rowIdx === undefined) ? null : Number(rowIdx);
  const isNew = !id;
  openModal(isNew ? 'Add a project' : `Edit ${p.name || 'project'}`,
    `<div class="text-[12.5px] text-[#64748b] mb-3">A project is the name the grid puts hours against. If what you are working on is not on the list, add it here — the code is made from the name, and a rate of 0 means internal time.</div>
     ${grid('md:grid-cols-2', fieldRow('Project name', 'pj_name', p.name || '', { required: true, placeholder: 'e.g. Acme Website Revamp' })
       + fieldRow('Code', 'pj_code', p.code || '', { placeholder: 'leave blank and one is made for you', hint: 'Upper case, short, and nobody else can have it' }))}
     ${grid('md:grid-cols-3', fieldRow('Client', 'pj_client', p.client || '', { placeholder: 'Who it is for' })
       + fieldRow('Billing rate (₹ per hour)', 'pj_rate', p.billing_rate || 0, { type: 'number', min: 0, step: '50', class: 'field num' })
       + fieldRow('Status', 'pj_status', p.status || 'Active', { type: 'select', options: ['Active', 'On Hold', 'Completed', 'Closed'] }))}
     ${fieldRow('Project manager', 'pj_manager', p.manager_id || (isNew ? (APP.user.employee_id || '') : ''), { type: 'select', options: employeeOptions('No manager'), hint: 'That person — or HR — can rename the project afterwards; nobody else can' })}
     <div class="mt-3 p-3 rounded-xl bg-[#f0fdf4] text-[12px] text-[#64748b]">Anything with hours already logged against it cannot be deleted — mark it Completed or Closed instead, so the time people claimed keeps somewhere to live.</div>`,
    `<button onclick="closeAllModals();renderTsGrid()" class="btn btn-ghost mr-auto">Cancel</button><button id="pjSaveGo" class="btn btn-primary" onclick="submitProject(${isNew ? 'null' : `'${id}'`})">${isNew ? 'Add project' : 'Save changes'}</button>`,
    'max-w-xl');
}
async function submitProject(id) {
  const v = n => { const el = $('#' + n); return el ? el.value : ''; };
  const body = { name: (v('pj_name') || '').trim(), code: (v('pj_code') || '').trim().toUpperCase(),
                 client: (v('pj_client') || '').trim(), billing_rate: +v('pj_rate') || 0,
                 status: v('pj_status') || 'Active', manager_id: v('pj_manager') || null };
  if (!body.name) { toast('A project needs a name', 'error'); return; }
  const btn = $('#pjSaveGo');
  if (btn) btn.disabled = true;
  let r;
  try { r = await api('/api/projects' + (id ? '/' + id : ''), { method: id ? 'PUT' : 'POST', body }); }
  catch (e) { if (btn) btn.disabled = false; return; }
  const p = r.project || {};
  // fold it into what is on screen instead of refetching: a reload would throw away the hours being typed
  APP.ts = APP.ts || {};
  const list = APP.ts.projects || [];
  const at = list.findIndex(x => String(x.id) === String(p.id));
  if (at >= 0) list[at] = { ...list[at], ...p }; else list.push(p);
  APP.ts.projects = list;
  if (APP.tsProjects) {
    const j = APP.tsProjects.findIndex(x => String(x.id) === String(p.id));
    if (j >= 0) APP.tsProjects[j] = { ...APP.tsProjects[j], ...p }; else APP.tsProjects.push(p);
  }
  if (!id && APP.pjRow !== null && APP.tsRows[APP.pjRow]) APP.tsRows[APP.pjRow].project_id = p.id;
  toast(r.message, 'success');
  closeAllModals();
  if (tsTabActive('projects')) loadTsProjects();
  if (currentModule === 'timesheet') renderTsGrid();
}
function deleteProject(id) {
  const p = ((APP.ts && APP.ts.projects) || []).find(x => String(x.id) === String(id));
  confirmAction(`Take ${p ? p.name : 'this project'} off the list? That is only allowed while nobody has logged hours against it - otherwise mark it Completed.`, async () => {
    const r = await api('/api/projects/' + id, { method: 'DELETE' });
    APP.ts.projects = (APP.ts.projects || []).filter(x => String(x.id) !== String(id));
    if (APP.tsProjects) APP.tsProjects = APP.tsProjects.filter(x => String(x.id) !== String(id));
    (APP.tsRows || []).forEach(row => { if (String(row.project_id) === String(id)) row.project_id = ''; });
    toast(r.message, 'success');
    if (currentModule === 'timesheet') renderTsGrid();
    if (tsTabActive('projects')) loadTsProjects();
  }, 'Remove project');
}
async function saveTimesheet(submit) {
  const entries = [];
  (APP.ts.days || []).forEach(day => APP.tsRows.forEach(r => {
    const h = num(r.hours[day.date]);
    if (h > 0) entries.push({ date: day.date, project_id: r.project_id, hours: h, billable: !!r.billable, task: r.task || '' });
  }));
  if (!entries.length && submit) { toast('Log at least one entry before submitting', 'error'); return; }
  try {
    const saved = await api('/api/timesheet/save', { method: 'POST', body: { week: APP.ts.week, entries } });
    if (submit) { const r = await api('/api/timesheet/submit', { method: 'POST', body: { week: APP.ts.week } }); toast(r.message, 'success'); }
    else toast(saved.message, 'success');
    loadTimesheet(true);
  } catch (e) { }
}
async function loadTsTeam() {
  const box = $('#tsTeamList');
  box.innerHTML = '<div class="spin"></div>';
  try {
    const d = await api('/api/timesheet?view=team&week=' + (APP.tsWeek || todayIso()));
    $('#tsTeamSummary').innerHTML = [
      kpiCard('Timesheets', d.summary.team_size, 'for this week'), kpiCard('Submitted', d.summary.submitted, 'incl. approved', { tone: 'good' }),
      kpiCard('To review', d.summary.awaiting_review, 'waiting on you', { tone: d.summary.awaiting_review ? 'warn' : 'default' }),
      kpiCard('Hours', d.summary.total_hours, `${d.summary.billable_hours} billable`), kpiCard('Unapproved', d.summary.unapproved, 'still open'),
    ].join('');
    if (!d.timesheets.length) { box.innerHTML = emptyState('Nothing submitted for this week', 'Try another week with the ‹ › buttons.'); return; }
    box.innerHTML = d.timesheets.map(t => `<div class="border border-[#f1f5f9] rounded-xl p-4">
      <div class="flex items-start gap-3">
        ${avatar(t.employee, 34)}<div class="min-w-0 flex-1"><div class="text-[13px] font-medium">${esc(t.employee?.full_name || 'Employee')} <span class="text-[11.5px] text-[#94a3b8] font-normal">${esc(t.employee?.department || '')}</span></div>
          <div class="text-[11.5px] text-[#94a3b8]">${esc(t.week_label || t.week_starting)} · ${t.entry_count} entries · ${num(t.total_hours)} h (${num(t.billable_hours)} billable, ${t.billable_pct}%)</div>
          <div class="flex flex-wrap gap-1.5 mt-2">${Object.entries(t.entries || {}).map(([day, list]) => list.map(e => `<span class="pill bg-[#f0fdf4] text-[#64748b]">${fmtDayShort(day)} · ${esc(e.project)} · ${e.hours}h${e.billable ? '' : ' · internal'}</span>`).join('')).join('')}</div>
          ${t.reviewer_remark ? `<div class="text-[12px] mt-2 ${t.status === 'Rejected' ? 'text-[#c0392b]' : 'text-[#0f9d58]'}"><b>Reviewer:</b> ${esc(t.reviewer_remark)}</div>` : ''}</div>
        <div class="text-right"><div class="mb-2">${statusPill(t.status)}</div>
          ${t.status === 'Submitted' ? `<button onclick="tsAction('${t.id}','approve')" class="btn btn-primary btn-xs mb-1"><i class="fas fa-check"></i> Approve</button><button onclick="tsReject('${t.id}')" class="btn btn-danger btn-xs"><i class="fas fa-xmark"></i> Reject</button>` : t.status === 'Approved' ? `<button onclick="tsAction('${t.id}','reopen')" class="btn btn-ghost btn-xs">Reopen</button>` : ''}</div></div></div>`).join('');
  } catch (e) { box.innerHTML = emptyState('Could not load the team view'); }
}
async function tsAction(id, action) { try { const r = await api(`/api/timesheets/${id}/action`, { method: 'POST', body: { action } }); toast(r.message, 'success'); loadTsTeam(); loadDashboard(true); } catch (e) { } }
function tsReject(id) { openModal('Reject this timesheet', fieldRow('What should they fix? (required)', 'ts_remark', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Tuesday looks missing — 28 hours is light for a full week.' }), modalFootSave(`tsRejectGo('${id}')`, 'Reject week')); }
async function tsRejectGo(id) { const remark = needValue('ts_remark', 'Tell the employee what to fix'); try { const r = await api(`/api/timesheets/${id}/action`, { method: 'POST', body: { action: 'reject', remark } }); toast(r.message, 'success'); closeAllModals(); loadTsTeam(); } catch (e) { } }
async function loadTsHistory() {
  const box = $('#tsHistoryTable');
  box.innerHTML = '<div class="spin"></div>';
  try {
    const rows = await api('/api/timesheet/history');
    if (!rows.length) { box.innerHTML = emptyState('No weeks logged yet'); return; }
    box.innerHTML = `<table class="kt"><thead><tr><th>Week</th><th>Entries</th><th>Total</th><th>Billable</th><th>Utilisation</th><th>Submitted</th><th>Approved by</th><th>Status</th></tr></thead><tbody>${rows.map(t => `<tr><td class="num font-medium">${esc(t.week_label || t.week_starting)}</td><td class="num">${t.entry_count}</td><td class="num">${num(t.total_hours)} h</td><td class="num">${num(t.billable_hours)} h</td><td class="num">${t.utilization_pct}%</td><td class="num text-[12px]">${t.submitted_at ? fmtDate(t.submitted_at) : '—'}</td><td class="text-[12.5px]">${esc(t.reviewer?.full_name || '—')}</td><td>${statusPill(t.status)}</td></tr>`).join('')}</tbody></table>`;
  } catch (e) { box.innerHTML = emptyState('Could not load history'); }
}
async function loadTsProjects() {
  const box = $('#tsProjectsTable');
  box.innerHTML = '<div class="spin"></div>';
  try {
    const rows = await api('/api/projects');
    APP.tsProjects = rows;
    // this tab is HR-only, and HR may change anything; the trash still says why a used project stays
    const act = p => `<button type="button" class="btn btn-ghost btn-xs" onclick="openProjectForm('${p.id}')" title="Rename ${esc(p.name)}, move its rate or change its status"><i class="fas fa-pen"></i></button>
         <button type="button" class="btn btn-ghost btn-xs" onclick="deleteProject('${p.id}')" title="${num(p.total_hours) ? num(p.total_hours) + ' h are logged against it, so it cannot be deleted - mark it Completed instead' : 'Take it off the list - allowed because nobody has logged hours on it'}"><i class="far fa-trash-alt"></i></button>`;
    box.innerHTML = `<div class="flex items-start justify-between gap-3 mb-3">
        <p class="text-[12.5px] text-[#94a3b8] max-w-xl">Hours people log land here, so a project is never deleted once anything has been claimed against it — close it instead. Anyone on the team can add a project from the grid; renaming one is the manager's or HR's.</p>
        <button onclick="openProjectForm(null)" class="btn btn-primary btn-xs shrink-0"><i class="fas fa-plus"></i> New project</button></div>
      <table class="kt"><thead><tr><th>Project</th><th>Client</th><th>Manager</th><th>Team</th><th>Rate</th><th>This week</th><th>All time</th><th>Billable value</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.map(p => `<tr><td><div class="font-medium">${esc(p.name)}</div><div class="text-[11px] text-[#94a3b8] num">${esc(p.code)}</div></td><td>${esc(p.client || 'Internal')}</td><td class="text-[12.5px]">${esc(p.manager?.full_name || '—')}</td><td class="text-[12.5px]">${(p.team || []).map(esc).join(', ') || '<span class="text-[#94a3b8]">none yet</span>'}</td><td class="num">${p.billing_rate ? inr(p.billing_rate) + '/h' : '—'}</td><td class="num">${num(p.hours_this_week)} h</td><td class="num">${num(p.total_hours)} h</td><td class="num">${p.billable_value ? compactInr(p.billable_value) : '—'}</td><td>${statusPill(p.status)}</td><td class="text-right whitespace-nowrap">${act(p)}</td></tr>`).join('')}</tbody></table>`;
  } catch (e) { box.innerHTML = emptyState('Could not load projects'); }
}

/* ================================================================== PAYROLL */
const PAY_EARN = [['basic', 'Basic'], ['hra', 'HRA'], ['special_allowance', 'Special Allowance']];
const PAY_DEDUCT = [['pf', 'Provident Fund'], ['esi', 'ESI'], ['professional_tax', 'Professional Tax'],
                    ['tds', 'TDS / Income Tax']];
APP.payStructures = [];

function payPeriod() {
  const now = new Date((APP.todayIso || todayIso()) + 'T12:00:00');
  const m = $('#payMonth') ? (+$('#payMonth').value || (now.getMonth() + 1)) : (now.getMonth() + 1);
  const y = $('#payYear') ? (+$('#payYear').value || now.getFullYear()) : now.getFullYear();
  return { month: m, year: y, iso: `${y}-${String(m).padStart(2, '0')}`,
           label: now.toLocaleString('en', { month: 'long' }) && `${new Date(y, m - 1, 1).toLocaleString('en', { month: 'long' })} ${y}` };
}

function payQuery() {
  const p = payPeriod();
  const q = new URLSearchParams({ month: p.month, year: p.year });
  const sel = $('#payEmployee');
  if (isAdmin() && sel && sel.value) q.set('employee_id', sel.value);
  return q.toString();
}

async function loadPayroll() {
  await loadLookups();
  const per = payPeriod();
  if ($('#payMonth') && !$('#payMonth').options.length) {
    const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    const now = new Date((APP.todayIso || todayIso()) + 'T12:00:00');
    $('#payMonth').innerHTML = months.map((m, i) => `<option value="${i + 1}" ${i + 1 === now.getMonth() + 1 ? 'selected' : ''}>${m}</option>`).join('');
    $('#payYear').innerHTML = [0, 1, 2].map(o => `<option value="${now.getFullYear() - o}">${now.getFullYear() - o}</option>`).join('');
  }
  if (isAdmin()) {
    $('#payEmployee').classList.remove('hidden');
    fillSelect('#payEmployee', employeeOptions('All employees'), $('#payEmployee').value, false);
  } else $('#payEmployee').classList.add('hidden');
  const q = payQuery();
  let slips = [], summary = null, structures = [];
  try {
    [slips, summary, structures] = await Promise.all([
      api('/api/payslips?' + q), api('/api/payroll/summary?' + q),
      api('/api/payroll/structures' + (isAdmin() && $('#payEmployee').value && !$('#payEmployee').classList.contains('hidden') ? '?employee_id=' + $('#payEmployee').value : ''))]);
  } catch (e) { return; }
  APP.paySlips = slips; APP.paySummary = summary; APP.payStructures = structures || [];
  const mine = !isAdmin();

  if (summary) {
    const me = summary.my_structure || {};
    $('#payrollStats').innerHTML = mine ? [
      kpiCard('Net pay this period', summary.net_payroll ? compactInr(summary.net_payroll) : '—',
              `${summary.employees_paid || 0} payslip(s) you can open · ${esc(summary.period)}`, { tone: 'brand' }),
      kpiCard('Gross', compactInr(summary.gross_payroll), 'before deductions'),
      kpiCard('Deductions', compactInr(summary.deductions), `${summary.lop_days || 0} LOP day(s) this month`),
      kpiCard('Monthly net', me.monthly_net ? compactInr(me.monthly_net) : '—',
              me.name ? `on “${esc(me.name)}”, from ${esc(me.effective_from_label)}` : 'no structure on file'),
      kpiCard('Annual CTC', me.ctc ? compactInr(me.ctc) : '—', 'total cost to the company'),
    ].join('') : [
      kpiCard('Net payroll', compactInr(summary.net_payroll), `${summary.employees_paid} payslips · ${esc(summary.period)}`, { tone: 'brand' }),
      kpiCard('Gross', compactInr(summary.gross_payroll), 'before deductions'),
      kpiCard('Deductions', compactInr(summary.deductions), `${summary.lop_days || 0} LOP day(s) · bonus ${inr(summary.bonus_paid || 0)}`),
      kpiCard('Average net', summary.average_net ? compactInr(summary.average_net) : '—', 'per employee'),
      kpiCard('Monthly CTC cost', compactInr(summary.monthly_ctc_cost),
              `${summary.draft_slips || 0} draft · ${summary.published_slips || 0} published · ${summary.paid_slips || 0} paid`),
    ].join('');
  }
  renderPayNotice(summary, slips);
  renderPayslipTable(slips);
  renderPayStructures();
  const csv = $('#payRegisterCsv');
  if (csv) csv.href = '/api/payroll/register/export?period=' + encodeURIComponent(per.iso);
  const tabLabel = $('#payTabStructures');
  if (tabLabel) tabLabel.textContent = mine ? 'My structure' : 'Structures';
}

function renderPayNotice(summary, slips) {
  const box = $('#payNotice');
  if (!box) return;
  if (!summary) { box.innerHTML = ''; return; }
  if (isAdmin()) {
    const draft = summary.draft_slips || 0, missing = summary.structures_missing || [];
    const bits = [];
    bits.push(draft
      ? `<b>${draft}</b> draft payslip(s) for ${esc(summary.period)} - employees cannot open a slip until you publish it`
      : (slips.length ? `Every slip for ${esc(summary.period)} has been released` : `Nothing generated for ${esc(summary.period)} yet`));
    if (missing.length) bits.push(`<b>${missing.length}</b> active employee(s) still have no salary structure (${missing.slice(0, 3).map(m => esc(m && m.full_name || m)).join(', ')}${missing.length > 3 ? ', …' : ''})`);
    box.innerHTML = `<div class="flex flex-wrap items-center gap-3 text-[12.5px] bg-[#d1fae5] text-[#166534] rounded-xl px-3.5 py-2.5">
      <i class="fas fa-circle-info"></i><span class="flex-1">${bits.join(' · ')}</span>
      ${draft ? `<button onclick="publishPayroll()" class="btn btn-primary btn-xs"><i class="fas fa-paper-plane"></i> Publish ${draft}</button>` : ''}
      ${missing.length ? `<button onclick="setPayTab('structures');filterStructures('missing')" class="btn btn-ghost btn-xs">Fix that</button>` : ''}
    </div>`;
    return;
  }
  const latest = (slips || [])[0];
  const me = summary.my_structure || {};
  const bits = [latest
    ? `Your ${esc(latest.period_label)} slip is <b>${esc(latest.status)}</b> · net ${inr(latest.net_pay)}`
    : `No payslip for ${esc(summary.period)} yet - HR releases them after the month closes`];
  if (me.monthly_gross) bits.push(`structure “${esc(me.name)}” pays ${inr(me.monthly_net)} a month net`);
  else bits.push('you have no salary structure on file - ask HR');
  box.innerHTML = `<div class="flex items-center gap-3 text-[12.5px] bg-[#f0fdf4] text-[#64748b] rounded-xl px-3.5 py-2.5"><i class="fas fa-info-circle"></i><span class="flex-1">${bits.join(' · ')}</span></div>`;
}

function renderPayslipTable(slips) {
  const tb = $('#payslipTable');
  if (!tb) return;
  const cols = isAdmin() ? 9 : 8;
  if (!slips || !slips.length) {
    tb.innerHTML = `<tr><td colspan="${cols}">${emptyState('No payslips for this month',
      isAdmin() ? 'Pick another month, or run payroll for this one.' : 'HR publishes a slip once the month is processed.')}</td></tr>`;
    return;
  }
  tb.innerHTML = slips.map(s => {
    const draft = s.status === 'Draft';
    const actions = isAdmin()
      ? `<div class="row-actions force"><button class="btn btn-ghost btn-xs !py-1" title="Edit" onclick="event.stopPropagation();openPayslipEdit('${s.id}')"><i class="fas fa-pen"></i></button>
         ${draft ? `<button class="btn btn-ghost btn-xs !py-1" title="Publish" onclick="event.stopPropagation();publishPayroll('${s.id}')"><i class="fas fa-paper-plane"></i></button>`
                 : `<button class="btn btn-ghost btn-xs !py-1" title="Revoke" onclick="event.stopPropagation();revokePayslip('${s.id}')"><i class="fas fa-rotate-left"></i></button>`}
         <button class="btn btn-ghost btn-xs !py-1" onclick="event.stopPropagation();openPayslipDetail('${s.id}')"><i class="far fa-eye"></i></button></div>`
      : `<div class="row-actions force"><button class="btn btn-ghost btn-xs !py-1"><i class="far fa-eye"></i> Payslip</button></div>`;
    return `<tr class="clickable ${draft ? 'opacity-60' : ''}" onclick="openPayslipDetail('${s.id}')">
      <td class="num font-medium">${esc(s.period_label)}</td>${isAdmin() ? `<td>${personLine(s.employee, s.employee?.department, 28)}</td>` : ''}
      <td class="num">${inr(s.gross_earnings)}</td><td class="num text-[#c0392b]">${inr(s.total_deductions)}</td><td class="num font-semibold">${inr(s.net_pay)}</td>
      <td class="text-[12px] text-[#64748b] num">${esc(s.days_label || '—')}</td>
      <td>${statusPill(s.status)}</td><td class="num text-[12.5px]">${esc(s.paid_on_label || '—')}</td>
      <td class="text-right">${actions}</td></tr>`;
  }).join('');
}

/* ---------------------------------------------------------------- structures */
function renderPayStructures() {
  const host = $('#payrollStructures');
  if (!host) return;
  const rows = APP.payStructures || [];
  if (!isAdmin()) {
    host.innerHTML = rows.length ? myStructureCard(rows[0])
      : emptyState('No salary structure on file', 'HR sets your components once they create your payroll record.');
    return;
  }
  const only = APP.payStructFilter === 'missing';
  const shown = only ? rows.filter(r => r.missing) : rows;
  const line = (items, total, tone) => `<table class="w-full">${(items || []).map(r => `<tr><td class="py-1 text-[12px]">${esc(r.label)}</td><td class="py-1 text-right num text-[12px]">${inr(r.amount)}</td></tr>`).join('')}
      <tr class="border-t border-[#dcfce7]"><td class="pt-1.5 text-[12px] font-semibold">${esc(total[0])}</td><td class="pt-1.5 text-right num text-[12px] font-semibold ${tone}">${inr(total[1])}</td></tr></table>`;
  const body = shown.map(s => {
    const emp = s.employee || {};
    if (s.missing) {
      return `<tr><td>${personLine(emp, emp.designation, 30)}</td>
        <td colspan="6" class="text-[12.5px] text-[#b7791f]"><i class="fas fa-triangle-exclamation mr-1"></i>No structure in force - payroll will skip ${esc(emp.full_name || 'this employee')} until one is added</td>
        <td class="text-right"><button class="btn btn-primary btn-xs !py-1" onclick="openStructureForm(null, '${esc(s.employee_id || emp.id || '')}')"><i class="fas fa-plus"></i> Add</button></td></tr>`;
    }
    const drift = Math.abs(+s.ctc_drift || 0) > 100;
    return `<tr class="clickable" onclick="openStructureForm('${s.id}')">
      <td>${personLine(emp, emp.designation, 30)}</td>
      <td><div class="font-medium text-[13px]">${esc(s.name)}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(s.allowance_labels || 'no extra allowances')}</div></td>
      <td class="num text-[12.5px]">${esc(s.effective_from_label || '—')}</td>
      <td class="num">${inr(s.monthly_gross)}</td><td class="num text-[#c0392b]">${inr(s.monthly_deductions)}</td>
      <td class="num font-semibold">${inr(s.monthly_net)}</td>
      <td class="num">${inr(s.ctc)}${drift ? ` <span class="pill bg-[#fdecec] text-[#c0392b]" title="CTC on file differs from these components">Δ ${inr(s.ctc_drift)}</span>` : ''}</td>
      <td class="text-right"><div class="row-actions force">
        <button class="btn btn-ghost btn-xs !py-1" title="Edit" onclick="event.stopPropagation();openStructureForm('${s.id}')"><i class="fas fa-pen"></i></button>
        <button class="btn btn-ghost btn-xs !py-1" title="Delete" onclick="event.stopPropagation();deleteStructure('${s.id}')"><i class="fas fa-trash"></i></button>
        <button class="btn btn-ghost btn-xs !py-1" title="Preview slip" onclick="event.stopPropagation();previewStructure('${s.id}')"><i class="fas fa-file-invoice-dollar"></i></button></div></td></tr>`;
  }).join('');
  host.innerHTML = `<div class="flex flex-wrap items-center gap-2 mb-3">
      <div class="text-[12px] text-[#64748b] flex-1">${shown.length} of ${rows.length} employee(s)${only ? ' without a structure' : ''} · components are monthly, CTC is annual</div>
      <button class="btn ${only ? 'btn-primary' : 'btn-ghost'} btn-xs" onclick="filterStructures('${only ? 'all' : 'missing'}')"><i class="fas fa-filter"></i> Without a structure</button>
      <button class="btn btn-primary btn-xs" onclick="openStructureForm()"><i class="fas fa-plus"></i> New structure</button></div>
    ${rows.length ? `<table class="kt"><thead><tr><th>Employee</th><th>Structure</th><th>Effective</th><th>Gross / mo</th><th>Deductions / mo</th><th>Net / mo</th><th>CTC / yr</th><th class="text-right">Actions</th></tr></thead><tbody>${body || `<tr><td colspan="8">${emptyState('Everyone has a structure', '')}</td></tr>`}</tbody></table>`
      : emptyState('No salary structures yet', 'Add one per employee - payroll runs from these.',
          `<button class="btn btn-primary btn-xs" onclick="openStructureForm()"><i class="fas fa-plus"></i> New structure</button>`)}`;
  // the components of the row are worth a look without opening the form
  host.querySelectorAll('tr[data-none]').forEach(() => {});
  if (line) host.dataset.ready = '1';
}

function myStructureCard(s) {
  const line = items => (items || []).map(r => `<div class="flex items-center justify-between py-1.5 text-[12.5px]"><span>${esc(r.label)}</span><span class="num">${inr(r.amount)}</span></div>`).join('');
  return `<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div class="bg-[#f8fafc] rounded-xl p-4"><div class="lbl">Monthly earnings</div>${line(s.earnings)}
      <div class="flex items-center justify-between pt-2 mt-1 border-t border-[#dcfce7] text-[13px] font-semibold"><span>Gross</span><span class="num">${inr(s.monthly_gross)}</span></div></div>
    <div class="bg-[#f8fafc] rounded-xl p-4"><div class="lbl">Monthly deductions</div>${line(s.deductions)}
      <div class="flex items-center justify-between pt-2 mt-1 border-t border-[#dcfce7] text-[13px] font-semibold"><span>Total</span><span class="num text-[#c0392b]">${inr(s.monthly_deductions)}</span></div></div>
    <div class="md:col-span-2 flex flex-wrap items-center gap-x-6 gap-y-2 p-3.5 rounded-xl bg-[#d1fae5] text-[12.5px]">
      <span class="text-[#166534]">Net before attendance: <b class="num">${inr(s.monthly_net)}</b> a month</span>
      <span class="text-[#166534]">Annual CTC: <b class="num">${inr(s.ctc)}</b></span>
      <span class="text-[#64748b]">Employer PF ${inr(s.employer_pf)}/mo is inside CTC, not deducted from you</span>
      <span class="text-[#64748b]">“${esc(s.name)}” in force since ${esc(s.effective_from_label)}</span>
    </div>
    <div class="md:col-span-2 text-[11.5px] text-[#94a3b8]">Loss of pay is taken out of these numbers at month end from your attendance. Only HR can change a structure - raise it with them if something looks wrong.</div>
  </div>`;
}

function filterStructures(mode) { APP.payStructFilter = mode === 'missing' ? 'missing' : 'all'; renderPayStructures(); }

function structureRow(label, name, value, hint) {
  return fieldRow(label, name, value, { type: 'number', step: '1', min: 0, class: 'field num', oninput: 'payStructureTotals()', hint });
}

function openStructureForm(id, presetEmployee) {
  const rows = APP.payStructures || [];
  const s = id ? rows.find(r => r.id === id) : { missing: true, form: {} };
  if (id && !s) { toast('Open the Structures tab first', 'warn'); return; }
  const f = s.form || {};
  const emp = s.employee || {};
  const empSelect = isAdmin() && !id
    ? fieldRow('Employee', 'st_employee', s.employee_id || presetEmployee || '', { type: 'select', options: employeeOptions('').slice(1), placeholder: '', required: true })
    : `<div><div class="lbl">Employee</div><div class="text-[13.5px] font-medium">${esc(emp.full_name || '—')}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(emp.department || '')}${emp.designation ? ' · ' + esc(emp.designation) : ''}</div></div>`;
  const earns = PAY_EARN.map(([col, label]) => structureRow(label, 'st_' + col, f[col] || 0)).join('');
  const deducts = PAY_DEDUCT.map(([col, label]) => structureRow(label, 'st_' + col, f[col] || 0)).join('');
  const allowRows = ((f.allowances || []).length ? f.allowances : []).map(a => allowanceRow(a.label, a.amount)).join('');
  const body = `${grid('md:grid-cols-2', empSelect + fieldRow('Structure name', 'st_name', f.name || 'Standard', { hint: 'One per revision, e.g. “Revised FY26-27”' }))}
    ${grid('md:grid-cols-2', fieldRow('Effective from', 'st_effective_from', f.effective_from || (APP.todayIso || todayIso()), { type: 'date', hint: 'Payroll picks the latest structure that has started' }))}
    <div class="lbl mt-4">Monthly earnings</div>${grid('md:grid-cols-3', earns)}
    <div class="flex items-center gap-2 mt-3"><div class="lbl flex-1">Other monthly allowances</div>
      <button class="btn btn-ghost btn-xs" onclick="addAllowanceRow()"><i class="fas fa-plus"></i> Add line</button></div>
    <div id="st_allowances" class="space-y-2">${allowRows || `<div class="text-[11.5px] text-[#94a3b8]">No extra allowances - travel, internet and the like go here.</div>`}</div>
    <div class="lbl mt-4">Monthly deductions</div>${grid('md:grid-cols-3', deducts + structureRow('Employer PF', 'st_employer_pf', f.employer_pf || 0, 'part of CTC, not taken from the employee'))}
    ${grid('md:grid-cols-2', structureRow('Annual CTC (optional)', 'st_ctc', f.ctc || '', 'blank = derived from the components above'))}
    <div id="st_totals" class="mt-3"></div>`;
  openModal(id ? 'Edit salary structure' : 'New salary structure', body, modalFootSave(`submitStructure('${id || ''}')`, id ? 'Save changes' : 'Create structure'), 'max-w-3xl');
  payStructureTotals();
}

function allowanceRow(label, amount) {
  return `<div class="flex items-center gap-2 allow-row">
    <input class="field !py-1.5 allow-label" placeholder="Internet" value="${esc(label || '')}">
    <input class="field !py-1.5 num allow-amount !w-32" type="number" min="0" step="1" value="${esc(amount || 0)}" oninput="payStructureTotals()">
    <button class="btn btn-ghost btn-xs !py-1" title="Remove" onclick="this.closest('.allow-row').remove();payStructureTotals()"><i class="fas fa-times"></i></button></div>`;
}

function addAllowanceRow() {
  const host = $('#st_allowances');
  if (!host.querySelector('.allow-row')) host.innerHTML = '';
  host.insertAdjacentHTML('beforeend', allowanceRow('', 0));
  const rows = host.querySelectorAll('.allow-label');
  if (rows.length) rows[rows.length - 1].focus();
  payStructureTotals();
}

function structureFormValues() {
  const nums = id => { const el = $('#' + id); return el ? (+el.value || 0) : 0; };
  const allow = [];
  document.querySelectorAll('#st_allowances .allow-row').forEach(r => {
    const label = (r.querySelector('.allow-label').value || '').trim();
    const amount = +r.querySelector('.allow-amount').value || 0;
    if (label) allow.push({ label, amount });
  });
  const emp = $('#st_employee');
  return { employee_id: emp ? emp.value : (APP.payStructureEmployee || ''), name: ($('#st_name') || {}).value,
           effective_from: ($('#st_effective_from') || {}).value, ctc: nums('st_ctc') || null, employer_pf: nums('st_employer_pf'),
           allowances: allow,
           ...Object.fromEntries(PAY_EARN.concat(PAY_DEDUCT).map(([col]) => ['st_' + col, nums('st_' + col)])) };
}

function payStructureTotals() {
  const box = $('#st_totals');
  if (!box) return;
  const v = structureFormValues();
  const gross = PAY_EARN.reduce((t, [c]) => t + (+v['st_' + c] || 0), 0) + v.allowances.reduce((t, a) => t + a.amount, 0);
  const ded = PAY_DEDUCT.reduce((t, [c]) => t + (+v['st_' + c] || 0), 0);
  const net = gross - ded;
  const derived = (gross + (+v.employer_pf || 0)) * 12;
  const stated = +v.ctc || 0;
  const bad = stated && Math.abs(stated - derived) > Math.max(100, derived * 0.01);
  box.innerHTML = `<div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 p-3 rounded-xl text-[12.5px] ${net <= 0 ? 'bg-[#fdecec] text-[#c0392b]' : bad ? 'bg-[#fff4e6] text-[#b7791f]' : 'bg-[#e6f9f0] text-[#0f7a45]'}">
      <span>Gross <b class="num">${inr(gross)}</b>/mo</span><span>Deductions <b class="num">${inr(ded)}</b></span>
      <span>Net <b class="num">${inr(net)}</b>/mo${net ? ` (${Math.round(net / gross * 100)}% of gross)` : ''}</span>
      <span>CTC becomes <b class="num">${inr(derived)}</b></span>
      ${net <= 0 ? '<span>net is not positive - payroll cannot run on this</span>'
        : bad ? `<span>the CTC you typed is ${inr(Math.abs(stated - derived))} ${stated > derived ? 'above' : 'below'} that - clear the CTC box to derive it</span>` : ''}
    </div>`;
}

async function submitStructure(id) {
  const v = structureFormValues();
  if (!v.employee_id && !id) { toast('Pick the employee this structure belongs to', 'error'); return; }
  const body = { employee_id: v.employee_id || undefined, name: v.name, effective_from: v.effective_from,
                 ctc: v.ctc || undefined, employer_pf: v.employer_pf, allowances: v.allowances,
                 ...Object.fromEntries(PAY_EARN.concat(PAY_DEDUCT).map(([c]) => [c, +v['st_' + c] || 0])) };
  try {
    const r = id ? await api('/api/payroll/structures/' + id, { method: 'PUT', body })
                 : await api('/api/payroll/structures', { method: 'POST', body });
    closeAllModals(); toast(r.message, 'success'); loadPayroll();
  } catch (e) { /* api() already showed the reason */ }
}

function deleteStructure(id) {
  const s = (APP.payStructures || []).find(r => r.id === id) || {};
  confirmAction(`Remove “${s.name || 'this structure'}” for ${(s.employee || {}).full_name || 'that employee'}? Past payslips keep the numbers they were paid on.`,
    async () => { const r = await api('/api/payroll/structures/' + id, { method: 'DELETE' }); toast(r.message, 'success'); loadPayroll(); }, 'Delete structure');
}

async function previewStructure(id) {
  const s = (APP.payStructures || []).find(r => r.id === id);
  if (!s) return;
  const per = payPeriod();
  const line = items => (items || []).map(r => `<div class="flex items-center justify-between py-1 text-[12.5px]"><span>${esc(r.label)}</span><span class="num">${inr(r.amount)}</span></div>`).join('');
  const gross = s.monthly_gross, ded = s.monthly_deductions;
  openModal(`${(s.employee || {}).full_name || ''} - ${esc(per.label)} at this structure`,
    `<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
       <div class="bg-[#f8fafc] rounded-xl p-4"><div class="lbl">Earnings</div>${line(s.earnings)}<div class="flex items-center justify-between pt-2 mt-1 border-t border-[#dcfce7] text-[13px] font-semibold"><span>Gross</span><span class="num">${inr(gross)}</span></div></div>
       <div class="bg-[#f8fafc] rounded-xl p-4"><div class="lbl">Deductions</div>${line(s.deductions)}<div class="flex items-center justify-between pt-2 mt-1 border-t border-[#dcfce7] text-[13px] font-semibold"><span>Total</span><span class="num text-[#c0392b]">${inr(ded)}</span></div></div>
     </div>
     <div class="mt-3 p-3.5 rounded-xl bg-[#d1fae5] text-[13px] flex flex-wrap items-center gap-4">
       <span class="text-[#166534]">Net before attendance</span><b class="num text-[#166534]">${inr(s.monthly_net)}</b>
       <span class="text-[#64748b] text-[12px]">Attendance is not applied in this preview - a day absent costs ${inr(Math.round(gross / 22))} here (gross ÷ working days).</span>
     </div>`,
    `<button onclick="closeAllModals()" class="btn btn-ghost mr-auto">Close</button><button onclick="closeAllModals();openStructureForm('${id}')" class="btn btn-primary"><i class="fas fa-pen"></i> Edit structure</button>`);
}

/* ------------------------------------------------------------------ the run */
function openPayrollRun() {
  const per = payPeriod();
  const summary = APP.paySummary || {};
  const missing = (summary.structures_missing || []).length;
  APP.payStructureEmployee = $('#payEmployee') && $('#payEmployee').value ? $('#payEmployee').value : '';
  openModal('Run payroll', `<div class="text-[12.5px] text-[#64748b] mb-3">Payroll is generated from each employee's structure and their attendance for the month. Loss of pay is deducted; an existing slip that was already published is left alone unless you say otherwise.</div>
    ${grid('md:grid-cols-2', fieldRow('Period', 'run_period', per.iso, { type: 'month' })
      + fieldRow('Who', 'run_scope', APP.payStructureEmployee || '', { type: 'select', options: employeeOptions('Everyone active'), hint: 'Only the chosen employee, or everyone' }))}
    <div class="space-y-2 mt-3">
      ${fieldRow('Publish to employees immediately', 'run_publish', false, { type: 'checkbox' })}
      ${fieldRow('Rebuild slips that are already published or paid', 'run_overwrite', false, { type: 'checkbox', hint: 'Numbers on released slips will change - use it for a correction, not for a routine run' })}
    </div>
    <div class="mt-3 p-3 rounded-xl bg-[#f0fdf4] text-[12px] text-[#64748b]">${summary.employees_paid || 0} slip(s) already exist for ${esc(per.label)} · ${missing} employee(s) have no structure and will be skipped</div>`,
    `<button onclick="closeAllModals()" class="btn btn-ghost mr-auto">Cancel</button><button id="runPayrollGo" class="btn btn-primary" onclick="submitPayrollRun()"><i class="fas fa-play"></i> Run payroll</button>`, 'max-w-xl');
}

async function submitPayrollRun() {
  const btn = $('#runPayrollGo');
  if (btn) btn.disabled = true;
  const scope = ($('#run_scope') || {}).value;
  const body = { period: ($('#run_period') || {}).value || payPeriod().iso,
                 publish: !!($('#run_publish') || {}).checked, overwrite: !!($('#run_overwrite') || {}).checked };
  if (scope) body.employee_ids = [scope];
  let r;
  try { r = await api('/api/payroll/run', { method: 'POST', body }); }
  catch (e) { if (btn) btn.disabled = false; return; }
  const skipped = (r.skipped || []).map(s => `<div class="flex items-center gap-2 py-1 text-[12.5px]"><i class="fas fa-minus-circle text-[#94a3b8]"></i><span class="flex-1">${esc(s.employee)}</span><span class="text-[#94a3b8]">${esc(s.reason)}</span></div>`).join('');
  const kept = (r.kept || []).map(s => `<div class="flex items-center gap-2 py-1 text-[12.5px]"><i class="fas fa-lock text-[#b7791f]"></i><span class="flex-1">${esc(s.employee)}</span>${statusPill(s.status)}</div>`).join('');
  openModal('Payroll run finished', `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      ${[['Generated', r.created, 'good'], ['Updated', r.updated, 'brand'], ['Left alone', (r.kept || []).length, ''], ['Skipped', (r.skipped || []).length, 'warn']]
        .map(([l, v, tone]) => `<div class="p-3 rounded-xl bg-[#f0fdf4]"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-display font-bold text-[20px] num ${tone === 'good' ? 'text-[#0f9d58]' : tone === 'warn' ? 'text-[#b7791f]' : tone === 'brand' ? 'text-[#15803d]' : ''}">${v}</div></div>`).join('')}
    </div>
    <div class="p-3.5 rounded-xl bg-[#d1fae5] text-[13px] text-[#166534] mb-3">${inr(r.net_payroll)} net to ${r.employees} employee(s) · ${inr(r.deductions)} deductions</div>
    ${skipped ? `<div class="lbl">Skipped</div>${skipped}` : ''}${kept ? `<div class="lbl mt-3">Already released, not touched</div>${kept}` : ''}
    <div class="text-[11.5px] text-[#94a3b8] mt-3">${esc(r.next || '')}</div>`,
    `<button onclick="closeAllModals();loadPayroll()" class="btn btn-ghost mr-auto">Close</button><button onclick="closeAllModals();loadPayroll();publishPayroll()" class="btn btn-primary"><i class="fas fa-paper-plane"></i> Publish the drafts</button>`, 'max-w-xl');
  toast(r.message, 'success');
  loadPayroll();
}

async function publishPayroll(slipId) {
  const q = slipId ? { employee_ids: null } : {};
  const ids = slipId ? [slipId] : [];
  const doIt = async () => {
    if (slipId) { const r = await api('/api/payslips/' + slipId, { method: 'PUT', body: { status: 'Published' } }); toast(r.message, 'success'); }
    else { const r = await api('/api/payroll/publish', { method: 'POST', body: { period: payPeriod().iso, ...q } }); toast(r.message, 'success'); }
    loadPayroll();
  };
  if (slipId) { try { await doIt(); } catch (e) {} return; }
  confirmAction(`Release every draft payslip for ${payPeriod().label} so employees can open them?`, doIt, 'Publish');
}

function markPayrollPaid() {
  const per = payPeriod();
  openModal('Mark payroll paid', `<div class="text-[12.5px] text-[#64748b] mb-3">Every published slip for the period becomes Paid and gets the date you record here. Employees see “Paid ₹…” on their slip the same moment.</div>
    ${grid('md:grid-cols-2', fieldRow('Period', 'paid_period', per.iso, { type: 'month' }) + fieldRow('Value date', 'paid_on', APP.todayIso || todayIso(), { type: 'date' }))}`,
    modalFootSave('submitMarkPaid()', 'Mark paid'), 'max-w-md');
}

async function submitMarkPaid() {
  try {
    const r = await api('/api/payroll/mark-paid', { method: 'POST', body: { period: ($('#paid_period') || {}).value, paid_on: ($('#paid_on') || {}).value } });
    closeAllModals(); toast(r.message, 'success'); loadPayroll();
  } catch (e) {}
}

function openPayslipEdit(id) {
  const s = (APP.paySlips || []).find(r => r.id === id) || {};
  const lock = (s.status && s.status !== 'Draft') ? { disabled: true } : {};
  openModal(`Edit ${(s.employee || {}).full_name || 'payslip'} · ${esc(s.period_label || '')}`,
    `<div class="text-[12.5px] text-[#64748b] mb-3">A bonus or a recovery is added to what the structure and attendance already produced. Saving recomputes gross, deductions and net.</div>
     ${grid('md:grid-cols-2', fieldRow('Bonus / arrears', 'ps_bonus', s.bonus || 0, { type: 'number', min: 0, step: '1', class: 'field num', ...lock })
       + fieldRow('Other recovery', 'ps_recovery', s.deductions || 0, { type: 'number', min: 0, step: '1', class: 'field num', ...lock }))}
     ${(s.status && s.status !== 'Draft') ? `<div class="mb-3 p-3 rounded-xl bg-[#fff8e6] text-[12px] text-[#8a6d1b]">This slip was released as ${esc(s.status)}, so its amounts are locked. Revoke it back to Draft to change them; the status and the paid-on date can still be set here.</div>` : ''}
     ${grid('md:grid-cols-2', fieldRow('Status', 'ps_status', s.status || 'Draft', { type: 'select', options: ['Draft', 'Published', 'Paid'] })
       + fieldRow('Paid on', 'ps_paid', s.paid_on || '', { type: 'date' }))}
     ${fieldRow('Note on the slip', 'ps_notes', s.notes || '', { type: 'textarea', rows: 2, placeholder: 'Why this was corrected - the employee sees it on the payslip' })}
     <div class="mt-3 p-3 rounded-xl bg-[#f0fdf4] text-[12px] text-[#64748b] num">${esc(s.days_label || '—')} · currently ${inr(s.net_pay)}</div>`,
    modalFootSave(`submitPayslipEdit('${id}')`, 'Save and recompute'), 'max-w-xl');
}

async function submitPayslipEdit(id) {
  const val = n => { const el = $('#' + n); return el ? el.value : ''; };
  const body = { bonus: +val('ps_bonus') || 0, deductions: +val('ps_recovery') || 0, status: val('ps_status'),
                 notes: val('ps_notes') || null, paid_on: val('ps_paid') || null };
  try { const r = await api('/api/payslips/' + id, { method: 'PUT', body }); closeAllModals(); toast(r.message, 'success'); loadPayroll(); }
  catch (e) {}
}

function revokePayslip(id) {
  confirmAction('Pull this slip back to Draft? The employee loses access to it immediately, and the reason goes on the slip.',
    async () => {
      const r = await api(`/api/payslips/${id}/revoke`, { method: 'POST', body: { reason: 'Corrected after review by HR' } });
      toast(r.message, 'success'); loadPayroll();
    }, 'Revoke slip');
}

function setPayTab(t) {
  $$('#module-payroll [data-paytab]').forEach(x => x.classList.toggle('active', x.dataset.paytab === t));
  $$('#module-payroll [data-paypane]').forEach(x => x.classList.toggle('active', x.dataset.paypane === t));
}

async function openPayslipDetail(id) {
  let d;
  try { d = await api('/api/payslips/' + id + '/detail'); } catch (e) { return; }
  const c = d.company || {}, s = d.payslip || {}, bank = d.bank || {}, days = d.days || {}, st = d.structure || {};
  const line = r => `<tr><td class="py-1.5 text-[12.5px]">${esc(r.label)}</td><td class="py-1.5 text-right num text-[12.5px]">${inr(r.amount, 2)}</td></tr>`;
  const lost = (days.lost_days || []).map(l => `<span class="pill bg-[#fdecec] text-[#c0392b]" title="${esc(l.kind)}">${esc(l.label)} · ${l.days} d</span>`).join(' ');
  const foot = `<button onclick="window.print()" class="btn btn-ghost mr-auto"><i class="fas fa-print"></i> Print / save PDF</button>`
    + (isAdmin() ? `<button onclick="closeAllModals();openPayslipEdit('${s.id}')" class="btn btn-ghost"><i class="fas fa-pen"></i> Edit</button>
        ${s.status === 'Draft' ? `<button onclick="closeAllModals();publishPayroll('${s.id}')" class="btn btn-primary"><i class="fas fa-paper-plane"></i> Publish</button>`
                               : `<button onclick="closeAllModals();revokePayslip('${s.id}')" class="btn btn-ghost"><i class="fas fa-rotate-left"></i> Revoke</button>`}` : '')
    + `<button onclick="closeAllModals()" class="btn btn-ghost">Close</button>`;
  openModal(`${s.period_label} payslip`, `<div class="print-area">
    <div class="flex items-start justify-between pb-4 border-b border-[#f1f5f9]"><div><div class="font-display font-bold text-[16px]">${esc(c.name || 'Modish Enterprises')}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(c.address || '')} · GSTIN ${esc(c.gstin || '')}</div></div>
      <div class="text-right"><div class="text-[11px] uppercase tracking-widest text-[#94a3b8] font-semibold">Payslip</div><div class="font-display font-bold text-[15px]">${esc(s.period_label)}</div><span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(s.employee?.employee_code || '')}</span></div></div>
    <div class="grid grid-cols-2 gap-5 py-4">
      <div><div class="lbl">Employee</div><div class="text-[13.5px] font-semibold">${esc(s.employee?.full_name || '')}</div><div class="text-[12px] text-[#64748b]">${esc(s.employee?.designation || '')} · ${esc(s.employee?.department || '')}</div><div class="text-[12px] text-[#94a3b8]">${esc(s.employee?.work_location || '')}</div></div>
      <div class="text-right"><div class="lbl">Net pay</div><div class="font-display font-bold text-[24px] text-[#0f9d58] num">${inr(d.net)}</div><div class="text-[11.5px] text-[#94a3b8]">${s.paid_on ? 'paid ' + fmtDate(s.paid_on) : esc(s.status_label || s.status || '')}</div></div></div>
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4 text-[12px]">
      ${[['Working days', num(days.working_days ?? d.working_days ?? 0)], ['Payable days', num(days.payable_days ?? d.payable_days ?? 0)], ['Loss of pay', num(d.lop_days ?? 0)], ['Structure', esc(st.name || '—')]]
        .map(([l, v]) => `<div class="bg-[#f0fdf4] rounded-lg p-2.5"><div class="text-[10px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-medium num mt-0.5">${v}</div></div>`).join('')}</div>
    ${lost ? `<div class="mb-4"><div class="lbl">Days deducted</div><div class="flex flex-wrap gap-1.5">${lost}</div></div>` : ''}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5 bg-[#f8fafc] rounded-xl p-4">
      <div><div class="lbl">Earnings</div><table class="w-full">${(d.earnings || []).map(line).join('')}<tr class="border-t border-[#dcfce7]"><td class="pt-2 text-[12.5px] font-semibold">Gross</td><td class="pt-2 text-right num font-semibold">${inr(d.gross, 2)}</td></tr></table></div>
      <div><div class="lbl">Deductions</div><table class="w-full">${(d.deductions || []).map(line).join('')}<tr class="border-t border-[#dcfce7]"><td class="pt-2 text-[12.5px] font-semibold">Total</td><td class="pt-2 text-right num font-semibold">${inr(d.deductions_total, 2)}</td></tr></table></div></div>
    <div class="flex items-center justify-between mt-4 p-3.5 rounded-xl bg-[#d1fae5] text-[13px]"><span class="text-[#166534]">Net pay credited</span><b class="num text-[#166534]">${inr(d.net, 2)}</b></div>
    ${d.net_in_words ? `<div class="text-[11.5px] text-[#64748b] mt-1.5 italic">${esc(d.net_in_words)}</div>` : ''}
    ${s.notes ? `<div class="mt-3 p-3 rounded-xl bg-[#fff9ec] text-[12px] text-[#8a6d1f]"><i class="fas fa-note-sticky mr-1"></i>${esc(s.notes)}</div>` : ''}
    ${(d.leaves_in_period || []).length ? `<div class="mt-4"><div class="lbl">Approved leave in this period</div>${d.leaves_in_period.map(l => `<div class="text-[12.5px] flex items-center gap-2 py-1"><span class="pill" style="background:${l.leave_color}22;color:${l.leave_color}">${esc(l.leave_type_label)}</span>${esc(l.period_label)} · ${num(l.days)} d</div>`).join('')}</div>` : ''}
    <div class="mt-4 grid grid-cols-2 md:grid-cols-3 gap-3 text-[12px]">${[['Bank', bank.bank_name], ['Account', bank.account], ['IFSC', bank.ifsc], ['PAN', bank.pan], ['UAN', bank.uan], ['PF shop', bank.pf]]
      .map(([l, v]) => `<div class="bg-[#f0fdf4] rounded-lg p-2.5"><div class="text-[10px] uppercase tracking-widest text-[#94a3b8] font-semibold">${l}</div><div class="font-medium num mt-0.5">${esc(v || '—')}</div></div>`).join('')}</div>
    <p class="text-[11px] text-[#94a3b8] mt-4">System generated payslip · ${esc(s.generated_at ? fmtDate(s.generated_at) : fmtDate(todayIso()))}${s.generated_by ? ' · prepared by ' + esc(s.generated_by) : ''}</p></div>`,
    foot);
}

/* ================================================================== EXPENSES */
async function loadExpenses(refresh) {
  await loadLookups();
  const p = new URLSearchParams();
  const st = $('#expStatusFilter').value;
  if (st && st !== 'All') p.set('status', st);
  let rows = [], summary = null;
  try { [rows, summary] = await Promise.all([api('/api/reimbursements?' + p.toString()), api('/api/reimbursements/summary')]); } catch (e) { return; }
  APP.expenses = rows;
  if (summary) $('#expenseStats').innerHTML = [
    kpiCard('Total claimed', compactInr(summary.total), `${summary.count} claims`, { tone: 'brand' }),
    kpiCard('Pending', compactInr(summary.pending), `${summary.pending_count} awaiting you`, { tone: summary.pending_count ? 'warn' : 'default', onclick: isAdmin() ? "$('#expStatusFilter').value='Pending';loadExpenses()" : '' }),
    kpiCard('Approved', compactInr(summary.approved), 'ready to pay', { tone: 'good' }),
    kpiCard('Paid out', compactInr(summary.paid), 'reimbursed'),
    kpiCard('Rejected', compactInr(summary.rejected), 'with a reason'),
  ].join('');
  const cats = Object.entries(summary?.by_category || {}).sort((a, b) => b[1] - a[1]);
  const catTotal = cats.reduce((s, c) => s + c[1], 0) || 1;
  $('#expCatChart').innerHTML = cats.map(([k, v]) => `<span class="flex items-center gap-1.5 bg-[#f0fdf4] rounded-full px-2.5 py-1"><b class="num">${compactInr(v)}</b> ${esc(k)} <span class="text-[#94a3b8] num">${Math.round(v / catTotal * 100)}%</span></span>`).join('');
  const tb = $('#expensesTable');
  if (!rows.length) { tb.innerHTML = `<tr><td colspan="8">${emptyState('No claims here', 'Submit a bill and it lands in your manager’s inbox.', '<button class="btn btn-primary btn-xs" onclick="openExpenseModal()">New claim</button>')}</td></tr>`; return; }
  tb.innerHTML = rows.map(c => `<tr>
    <td class="num">${fmtDayShort(c.date)}</td>${isAdmin() ? `<td>${personLine(c.employee, c.employee?.department, 28)}</td>` : ''}
    <td><span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(c.category)}</span></td>
    <td class="text-[12.5px] max-w-[280px]"><div class="line-clamp-2">${esc(c.description)}</div>${c.reviewer_remark ? `<div class="text-[11px] text-[#15803d]">Reviewer: ${esc(c.reviewer_remark)}</div>` : ''}</td>
    <td>${c.has_receipt ? '<span class="text-[#0f9d58] text-[12px]"><i class="fas fa-paperclip"></i> attached</span>' : '<span class="text-[#b7791f] text-[12px]"><i class="far fa-circle"></i> missing</span>'}</td>
    <td class="num font-semibold">${inr(c.amount)}</td><td>${statusPill(c.status)}</td>
    <td class="text-right"><div class="row-actions force inline-flex gap-1">
      ${isAdmin() && c.status === 'Pending' ? `<button onclick="expAction('${c.id}','approve')" class="btn btn-ghost btn-xs !py-1 text-[#0f9d58]" title="Approve"><i class="fas fa-check"></i></button><button onclick="expPay('${c.id}')" class="btn btn-ghost btn-xs !py-1 text-[#15803d]" title="Mark paid"><i class="fas fa-money-bill-wave"></i></button><button onclick="expReject('${c.id}')" class="btn btn-ghost btn-xs !py-1 text-[#c0392b]" title="Reject"><i class="fas fa-xmark"></i></button>` : ''}
      ${!isAdmin() && c.status === 'Pending' ? `<button onclick="deleteExpense('${c.id}')" class="btn btn-ghost btn-xs !py-1" title="Delete"><i class="far fa-trash-alt"></i></button>` : ''}
    </div></td></tr>`).join('');
}
function openExpenseModal() {
  const cats = APP.lookups.expense_categories || ['Travel', 'Food', 'Other'];
  const body = `<div class="space-y-3">${grid('md:grid-cols-2 gap-3', [
    fieldRow('Category', 'ex_cat', 'Travel', { type: 'select', options: cats }),
    fieldRow('Amount (₹)', 'ex_amt', '', { type: 'number', step: 1, required: true, placeholder: '4250' }),
    fieldRow('Date of expense', 'ex_date', todayIso(), { type: 'date', required: true }),
    fieldRow('Payment mode', 'ex_mode', 'Card', { type: 'select', options: ['Card', 'UPI', 'Cash', 'Wallet'] }),
    fieldRow('Description', 'ex_desc', '', { type: 'textarea', rows: 2, required: true, placeholder: 'Delhi–Bengaluru return flight for the Axis go-live' }),
    fieldRow('Receipt / bill reference', 'ex_receipt', '', { placeholder: 'PNR 4HK2L1 · invoice #2291' })].join(''))}
    <div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">Claims above ₹1,00,000 need written Finance approval before submission. ${isAdmin() ? 'You are filing as HR Admin.' : ''}</div></div>`;
  openModal('New expense claim', body, modalFootSave('submitExpense()', 'Submit claim'));
}
async function submitExpense() {
  const body = { category: $('#ex_cat').value, amount: num($('#ex_amt').value), date: $('#ex_date').value, description: needValue('ex_desc', 'Describe the expense'), receipt_url: $('#ex_receipt').value || null, has_receipt: !!$('#ex_receipt').value || confirmHasReceipt() };
  try { const r = await api('/api/reimbursements', { method: 'POST', body }); toast(r.message, 'success'); closeAllModals(); loadExpenses(true); loadDashboard(true); } catch (e) { }
}
function confirmHasReceipt() { return true; }
async function expAction(id, action) { try { const r = await api(`/api/reimbursements/${id}/action`, { method: 'POST', body: { action } }); toast(r.message, 'success'); loadExpenses(true); loadDashboard(true); } catch (e) { } }
function expPay(id) { expAction(id, 'pay'); }
function expReject(id) { openModal('Reject this claim', fieldRow('Why? (required)', 'ex_remark', '', { type: 'textarea', rows: 3, required: true, placeholder: 'No boarding pass attached — resend with the ticket.' }), modalFootSave(`exRejectGo('${id}')`, 'Reject claim')); }
async function exRejectGo(id) { const remark = needValue('ex_remark', 'A reason is required'); try { const r = await api(`/api/reimbursements/${id}/action`, { method: 'POST', body: { action: 'reject', remark } }); toast(r.message, 'success'); closeAllModals(); loadExpenses(true); } catch (e) { } }
async function deleteExpense(id) { await confirmAction('Delete this claim?', async () => { const r = await api('/api/reimbursements/' + id, { method: 'DELETE' }); toast(r.message || 'Deleted', 'success'); loadExpenses(true); loadDashboard(true); }, 'Delete claim'); }


/* ================================================================== HIRING */
function setHiringTab(t) { $$('#module-hiring [data-hiringtab]').forEach(x => x.classList.toggle('active', x.dataset.hiringtab === t)); if (t === 'funnel') loadFunnel(); if (t === 'pipeline') loadCandidates(); }
async function loadHiring(refresh) {
  await loadLookups();
  if (refresh) $('#jobsList').innerHTML = '<div class="spin"></div>';
  let jobs = [], pipe = null;
  try { jobs = await api('/api/jobs'); pipe = await api('/api/hiring/pipeline'); } catch (e) { return; }
  APP.jobs = jobs; APP.pipe = pipe;
  fillSelect('#candJobFilter', [{ value: '', label: 'All requisitions' }, ...jobs.map(j => ({ value: j.id, label: `${j.title} · ${j.status}` }))], $('#candJobFilter')?.value, false);
  $('#jobsCount').textContent = jobs.length;
  $('#hiringStats').innerHTML = [
    kpiCard('Open roles', pipe.open_roles, `${pipe.open_positions} positions to fill`, { tone: 'brand' }),
    kpiCard('Candidates', pipe.total, `${pipe.stages.reduce((s, x) => s + x.count, 0)} in play · ${pipe.rejected} rejected`),
    kpiCard('Interviews', (pipe.time_in_stage.Interview?.count || 0) + (pipe.time_in_stage.Offer?.count || 0), 'interview + offer stage'),
    kpiCard('Hires', pipe.hired, `${pipe.hire_rate}% of all candidates`, { tone: 'good' }),
  ].join('');
  renderJobs();
  loadCandidates();
  loadFunnel();
}
function renderJobs() {
  const jobs = APP.jobs || [];
  const box = $('#jobsList');
  if (!jobs.length) { box.innerHTML = section('No requisitions yet', '', emptyState('Nothing posted', 'Post the first job to start a pipeline.', '<button class="btn btn-primary btn-xs" onclick="openJobForm()">Post a job</button>')); return; }
  box.innerHTML = jobs.map(j => {
    const stages = j.pipeline || {};
    return `<div class="keka-card p-5 ${j.status !== 'Open' ? 'opacity-90' : ''}">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0"><div class="flex items-center gap-2 flex-wrap"><h3 class="font-display font-semibold text-[15px] truncate">${esc(j.title)}</h3>${statusPill(j.status)}${j.status === 'Closed' && j.closed_label ? `<span class="text-[11px] text-[#94a3b8]">closed ${esc(j.closed_label)}</span>` : ''}</div>
          <div class="text-[12px] text-[#64748b] mt-1">${esc(j.department)} · ${esc(j.location || '—')} · ${esc(j.employment_type || 'Full-time')} · ${esc(j.experience || '—')}</div>
          <div class="text-[11.5px] text-[#94a3b8] mt-1">Posted ${fmtDate(j.posted_at)} · ${j.days_open} days open · owner ${esc(j.hiring_manager || '—')}</div></div>
        ${isAdmin() ? `<div class="flex gap-1 flex-shrink-0">
          <button onclick="openJobForm('${j.id}')" class="btn btn-ghost btn-xs !py-1" title="Update job"><i class="far fa-pen"></i></button>
          ${j.status === 'Open' ? `<button onclick="closeJobForm('${j.id}')" class="btn btn-ghost btn-xs !py-1 text-[#b7791f]" title="Close / keep on hold"><i class="fas fa-lock"></i></button>` : `<button onclick="reopenJob('${j.id}')" class="btn btn-ghost btn-xs !py-1 text-[#0f9d58]" title="Reopen"><i class="fas fa-rotate-left"></i></button>`}
          <button onclick="deleteJob('${j.id}')" class="btn btn-ghost btn-xs !py-1 text-[#c0392b]" title="Delete"><i class="far fa-trash-alt"></i></button></div>` : ''}
      </div>
      ${j.status === 'Closed' && j.closure_reason ? `<div class="mt-3 text-[12.5px] bg-[#fff4e6] text-[#8a5a12] rounded-xl p-3"><b>Closure note:</b> ${esc(j.closure_reason)}</div>` : ''}
      ${j.description ? `<div class="text-[12.5px] text-[#64748b] mt-3 line-clamp-2">${esc(j.description)}</div>` : ''}
      <div class="mt-4"><div class="flex items-center justify-between text-[11.5px] text-[#94a3b8] mb-1.5"><span>Requisitions filled</span><span class="num">${j.hired}/${j.openings}</span></div>
        <div class="bar"><span style="width:${j.fill_pct}%;background:${j.fill_pct >= 100 ? '#0f9d58' : '#15803d'}"></span></div></div>
      <div class="grid grid-cols-5 gap-1.5 mt-3.5">${Object.entries(stages).map(([k, v]) => `<button onclick="viewJobCandidates('${j.id}','${esc(k)}')" class="rounded-lg py-2 text-center transition ${v ? 'bg-[#f0fdf4] hover:bg-[#d1fae5]' : 'bg-[#f8fafc]'} ${k === 'Rejected' ? 'opacity-70' : ''}"><div class="font-display font-bold text-[15px] num ${v ? '' : 'text-[#cbd5e1]'}">${v}</div><div class="text-[9.5px] uppercase tracking-wider text-[#94a3b8]">${esc(k)}</div></button>`).join('')}</div>
      <div class="flex items-center gap-2 mt-3.5 pt-3 border-t border-[#f1f5f9] text-[12px] text-[#94a3b8]"><span>${j.applicants} applicants · ${j.in_progress} still in process</span>
        <div class="ml-auto flex gap-2">${isAdmin() ? `<button onclick="openCandidateForm(null,'${j.id}')" class="btn btn-ghost btn-xs !py-1"><i class="fas fa-user-plus"></i> Add candidate</button><button onclick="viewJobCandidates('${j.id}')" class="btn btn-ghost btn-xs !py-1">Open pipeline</button>` : ''}</div></div></div>`;
  }).join('');
}
function viewJobCandidates(jobId, stage) {
  setHiringTab('pipeline');
  $$('#module-hiring [data-hiringtab]').forEach(x => x.classList.toggle('active', x.dataset.hiringtab === 'pipeline'));
  $('#candJobFilter').value = jobId;
  APP.candStageFocus = stage || null;
  loadCandidates();
  document.querySelector('[data-hiringpane="pipeline"]').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function loadCandidates() {
  const p = new URLSearchParams();
  if ($('#candJobFilter')?.value) p.set('job_id', $('#candJobFilter').value);
  if ($('#candSearch')?.value.trim()) p.set('q', $('#candSearch').value.trim());
  let rows = [];
  try { rows = await api('/api/candidates?' + p.toString()); } catch (e) { return; }
  APP.candidates = rows;
  renderPipeline(rows);
}
function renderPipeline(rows) {
  const stages = APP.lookups.candidate_stages || ['Applied', 'Screening', 'Interview', 'Offer', 'Hired'];
  const cols = [...stages, 'Rejected'];
  const box = $('#pipelineBoard');
  const byStage = s => rows.filter(c => (c.stage || 'Applied') === s);
  box.innerHTML = cols.map(s => `<div class="kcol" data-stage="${esc(s)}" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="dropCandidate(event,'${esc(s)}')">
      <div class="flex items-center justify-between px-1 mb-2"><div class="text-[12px] font-semibold ${s === 'Hired' ? 'text-[#0f9d58]' : s === 'Rejected' ? 'text-[#c0392b]' : ''}">${esc(s)}</div><span class="pill bg-white text-[#94a3b8]">${byStage(s).length}</span></div>
      ${byStage(s).map(c => `<div class="kcard" draggable="true" ondragstart="event.dataTransfer.setData('text/plain','${c.id}')" onclick="openCandidateForm('${c.id}')">
        <div class="flex items-start gap-2">${avatar(c, 30)}<div class="min-w-0 flex-1"><div class="text-[12.5px] font-semibold truncate">${esc(c.full_name)}</div><div class="text-[11px] text-[#94a3b8] truncate">${esc(c.current_role || c.email || '')}</div></div>
          ${c.stage_changed_at ? `<span class="text-[10px] ${c.age_in_stage_days > 7 ? 'text-[#c0392b]' : 'text-[#94a3b8]'} num flex-shrink-0" title="Days in this stage">${c.age_in_stage_days}d</span>` : ''}</div>
        <div class="flex flex-wrap items-center gap-1.5 mt-2 text-[10.5px] text-[#64748b]"><span class="pill bg-[#f0fdf4]">${num(c.experience_years)} yr</span>${c.expected_ctc ? `<span class="pill bg-[#f0fdf4]">exp ${compactInr(c.expected_ctc)}</span>` : ''}${c.rating ? `<span class="pill bg-[#fff4e6] text-[#b7791f]">★ ${num(c.rating)}</span>` : ''}${c.source ? `<span class="pill bg-[#d1fae5] text-[#15803d]">${esc(c.source)}</span>` : ''}</div>
        ${c.notes ? `<div class="text-[11px] text-[#94a3b8] mt-1.5 line-clamp-2">${esc(c.notes)}</div>` : ''}
        ${c.converted_employee ? `<div class="mt-1.5 text-[10.5px] text-[#0f9d58]"><i class="fas fa-user-check"></i> Joined as ${esc(c.converted_employee.employee_code)} — <button class="underline" onclick="event.stopPropagation();openEmployeeDetail('${c.converted_employee.id}')">view profile</button></div>` : ''}
        <div class="flex items-center gap-1 mt-2 pt-2 border-t border-[#f1f5f9]">
          <button onclick="event.stopPropagation();openCandidateForm('${c.id}')" class="btn btn-ghost !py-0.5 !px-2 text-[11px]" title="Update candidate details"><i class="far fa-pen"></i> Update</button>
          ${(c.stage !== 'Hired' && !c.converted_employee_id) ? `<button onclick="event.stopPropagation();openHireForm('${c.id}')" class="btn btn-ghost !py-0.5 !px-2 text-[11px] text-[#0f9d58]" title="Convert to employee"><i class="fas fa-user-plus"></i> Hire</button>` : ''}
          ${s !== 'Rejected' ? `<button onclick="event.stopPropagation();moveCandidate('${c.id}','Rejected')" class="btn btn-ghost !py-0.5 !px-2 text-[11px] text-[#c0392b] ml-auto" title="Reject"><i class="fas fa-xmark"></i></button>` : ''}</div></div>`).join('')
      || `<div class="text-[11.5px] text-[#cbd5e1] text-center py-6">drop here</div>`}</div>`).join('');
}
function dropCandidate(ev, stage) {
  ev.preventDefault(); ev.currentTarget.classList.remove('dragover');
  const id = ev.dataTransfer.getData('text/plain');
  if (id) moveCandidate(id, stage);
}
async function moveCandidate(id, stage) {
  try { const r = await api('/api/candidates/' + id, { method: 'PUT', body: { stage } }); toast(r.message, 'success'); loadCandidates(); loadHiring(true); loadDashboard(true); } catch (e) { }
}
async function openCandidateForm(id) {
  const c = id ? (APP.candidates || []).find(x => String(x.id) === String(id)) : {};
  const jobs = (APP.jobs || []).map(j => ({ value: j.id, label: `${j.title} · ${j.status}` }));
  const body = `<div class="space-y-3">${grid('md:grid-cols-2 gap-3', [
    fieldRow('Full name', 'cf_name', c.full_name, { required: true }), fieldRow('Email', 'cf_email', c.email, { type: 'email', required: true }),
    fieldRow('Phone', 'cf_phone', c.phone), fieldRow('Requisition', 'cf_job', c.job_id, { type: 'select', options: jobs, placeholder: 'Unassigned' }),
    fieldRow('Stage', 'cf_stage', c.stage || 'Applied', { type: 'select', options: [...(APP.lookups.candidate_stages || []), 'Rejected'] }),
    fieldRow('Experience (years)', 'cf_exp', c.experience_years, { type: 'number', step: 0.5 }),
    fieldRow('Current role / company', 'cf_role', c.current_role, { placeholder: 'Sr. Engineer, Zeta' }),
    fieldRow('Source', 'cf_source', c.source, { type: 'select', options: ['LinkedIn', 'Referral', 'Naukri', 'Career page', 'Instahyre', 'Agency', 'Other'] }),
    fieldRow('Current CTC', 'cf_cctc', c.current_ctc, { type: 'number', step: 10000 }), fieldRow('Expected CTC', 'cf_octc', c.expected_ctc, { type: 'number', step: 10000 }),
    fieldRow('Rating', 'cf_rating', c.rating, { type: 'number', step: 0.5, min: 0, max: 5 }),
    fieldRow('Owner', 'cf_owner', c.owner_id || APP.user.employee_id, { type: 'select', options: employeeOptions(false), placeholder: 'Unassigned' }),
    fieldRow('Resume link', 'cf_resume', c.resume_url, { placeholder: 'https://…' }),
    fieldRow('Notes for the panel', 'cf_notes', c.notes, { type: 'textarea', rows: 2 })].join(''))}
    ${id && c.converted_employee_id ? `<div class="text-[12px] text-[#0f9d58] bg-[#e6f9f0] rounded-xl p-3"><i class="fas fa-user-check"></i> Already converted — edit their employee record from the directory instead.</div>` : ''}</div>`;
  openModal(id ? `Update ${c.full_name}` : 'Add candidate', body, modalFootSave(`submitCandidate('${id || ''}')`, id ? 'Save changes' : 'Add to pipeline'));
}
async function submitCandidate(id) {
  const v = formValues(['cf_name', 'cf_email', 'cf_phone', 'cf_job', 'cf_stage', 'cf_exp', 'cf_role', 'cf_source', 'cf_cctc', 'cf_octc', 'cf_rating', 'cf_owner', 'cf_resume', 'cf_notes']);
  if (!v.cf_name || !v.cf_email) { toast('Name and email are required', 'error'); return; }
  const body = { full_name: v.cf_name, email: v.cf_email, phone: v.cf_phone, job_id: v.cf_job || null, stage: v.cf_stage, experience_years: num(v.cf_exp), current_role: v.cf_role, source: v.cf_source, current_ctc: num(v.cf_cctc), expected_ctc: num(v.cf_octc), rating: num(v.cf_rating), owner_id: v.cf_owner || null, resume_url: v.cf_resume, notes: v.cf_notes };
  try { const r = await api(id ? '/api/candidates/' + id : '/api/candidates', { method: id ? 'PUT' : 'POST', body }); toast(r.message, 'success'); closeAllModals(); loadHiring(true); loadDashboard(true); } catch (e) { }
}
function openCandidateFormNew(jobId) { openCandidateForm(); if (jobId) $('#cf_job').value = jobId; }
async function deleteJob(id) { await confirmAction('Delete this requisition? Candidates attached to it must be moved or rejected first.', async () => { const r = await api('/api/jobs/' + id, { method: 'DELETE' }); toast(r.message, 'success'); loadHiring(true); }, 'Delete job'); }
async function reopenJob(id) { try { const r = await api('/api/jobs/' + id, { method: 'PUT', body: { action: 'reopen' } }); toast(r.message, 'success'); loadHiring(true); } catch (e) { } }
function closeJobForm(id) {
  const j = (APP.jobs || []).find(x => String(x.id) === String(id)) || {};
  const remaining = (j.applicants || 0) - (j.hired || 0) - (j.pipeline?.Rejected || 0);
  const body = `<div class="space-y-3">
    <div class="text-[13px] text-[#64748b]"><b>${esc(j.title)}</b> — ${j.in_progress || 0} candidate(s) are still in the pipeline. Closing stops new applications; you can reopen it any time.</div>
    ${fieldRow('What are you doing with this job?', 'cj_action', 'close', { type: 'select', options: [{ value: 'close', label: 'Close it (filled, cancelled or budget pulled)' }, { value: 'hold', label: 'Put it on hold for now' }] })}
    ${fieldRow('Closure reason (required, kept on record)', 'cj_reason', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Filled internally — two lateral hires accepted offers on 28 Aug.' })}
    ${fieldRow('Keep openings at', 'cj_openings', j.openings || 0, { type: 'number', hint: 'set to 0 once every position is filled' })}
  </div>`;
  openModal('Update / close job', body, modalFootSave(`submitJobClose('${id}')`, 'Save'));
}
async function submitJobClose(id) {
  const action = $('#cj_action').value === 'hold' ? null : 'close';
  const body = { closure_reason: $('#cj_reason').value.trim() || null, openings: num($('#cj_openings').value) };
  if (action) body.action = action;
  if (!body.closure_reason) { toast('Add the closing note — it stays on the requisition history', 'error'); return; }
  try { const r = await api('/api/jobs/' + id, { method: 'PUT', body: action ? body : { ...body, status: 'On Hold' } }); toast(r.message, 'success'); closeAllModals(); loadHiring(true); loadDashboard(true); } catch (e) { }
}
async function openJobForm(id) {
  const j = id ? (APP.jobs || []).find(x => String(x.id) === String(id)) : {};
  const body = `<div class="space-y-3">${grid('md:grid-cols-2 gap-3', [
    fieldRow('Job title', 'j_title', j.title, { required: true }),
    typeOrAddField('Department', 'j_dept_name', (APP.lookups.departments || []).map(d => d.name), 'Pick an existing department or type a new one - it is created when you publish.', deptName(j.department_id) !== '—' ? deptName(j.department_id) : ''),
    fieldRow('Location', 'j_loc', j.location, { placeholder: 'Bengaluru / Hybrid' }),
    fieldRow('Employment type', 'j_type', j.employment_type || 'Full-time', { type: 'select', options: ['Full-time', 'Part-time', 'Contract', 'Intern'] }),
    fieldRow('Experience', 'j_exp', j.experience, { placeholder: '2-4 years' }),
    fieldRow('Salary range', 'j_range', j.salary_range, { placeholder: '₹12-18 LPA' }),
    fieldRow('Openings', 'j_openings', j.openings ?? 1, { type: 'number', min: 1 }),
    fieldRow('Hiring manager', 'j_hm', j.hiring_manager_id, { type: 'select', options: employeeOptions(false), placeholder: 'Unassigned' }),
    fieldRow('Status', 'j_status', j.status || 'Open', { type: 'select', options: ['Open', 'On Hold', 'Closed'] }),
    fieldRow('Posted on', 'j_posted', j.posted_at || todayIso(), { type: 'date' })].join(''))}
    ${fieldRow('Description shown to candidates', 'j_desc', j.description, { type: 'textarea', rows: 4, placeholder: 'What the team owns, the stack, the interview process…' })}
    <div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">Marking a job <b>Closed</b> here asks for a closure reason. Use the lock button on the card for the full close flow.</div></div>`;
  openModal(id ? 'Update job' : 'Post a job', body, modalFootSave(`submitJob('${id || ''}')`, id ? 'Save changes' : 'Publish job'));
}
async function submitJob(id) {
  const v = formValues(['j_title', 'j_dept_name', 'j_loc', 'j_type', 'j_exp', 'j_range', 'j_openings', 'j_hm', 'j_status', 'j_posted', 'j_desc']);
  if (!v.j_title) { toast('A title is required', 'error'); return; }
  try {
    const body = { title: v.j_title, department_id: await resolveTypeOrAdd('department', 'j_dept_name'), location: v.j_loc, employment_type: v.j_type, experience: v.j_exp, salary_range: v.j_range, openings: num(v.j_openings) || 1, hiring_manager_id: v.j_hm || null, status: v.j_status, posted_at: v.j_posted, description: v.j_desc };
    const r = await api(id ? '/api/jobs/' + id : '/api/jobs', { method: id ? 'PUT' : 'POST', body }); toast(r.message || 'Saved', 'success'); closeAllModals(); loadHiring(true); loadDashboard(true);
  } catch (e) { }
}
function openHireForm(id) {
  const c = (APP.candidates || []).find(x => String(x.id) === String(id)) || {};
  const job = (APP.jobs || []).find(x => String(x.id) === String(c.job_id)) || {};
  const body = `<div class="text-[12.5px] text-[#64748b] mb-3 bg-[#d1fae5] rounded-xl p-3">Converting <b>${esc(c.full_name)}</b> creates the employee record, a payroll structure from this CTC, prorated leave quotas, and moves the candidate to <b>Hired</b>.</div>
    <div class="space-y-3">${grid('md:grid-cols-2 gap-3', [
      fieldRow('Full name', 'h_name', c.full_name, { required: true }),
      fieldRow('Work email', 'h_email', (String(c.email || '').split('@')[0] || 'new.hire') + '@company.com', { type: 'email', required: true }),
      fieldRow('Phone', 'h_phone', c.phone),
      fieldRow('Date of joining', 'h_doj', todayIso(), { type: 'date', required: true }),
      typeOrAddField('Department', 'h_dept_name', (APP.lookups.departments || []).map(d => d.name), 'From the requisition - pick an existing department or type a new one.', deptName(job.department_id) !== '—' ? deptName(job.department_id) : ''),
      typeOrAddField('Designation', 'h_desig_name', (APP.lookups.designations || []).map(d => d.title), 'From the requisition - pick an existing title or type a new one.', job.designation_id ? (desigName(job.designation_id) !== '—' ? desigName(job.designation_id) : '') : ''),
      fieldRow('Reports to', 'h_mgr', job.hiring_manager_id, { type: 'select', options: employeeOptions(false), placeholder: 'Hiring manager from the job' }),
      fieldRow('Employment type', 'h_type', job.employment_type || 'Full-time', { type: 'select', options: ['Full-time', 'Part-time', 'Contract', 'Intern'] }),
      fieldRow('Work location', 'h_loc', job.location || 'Bengaluru'),
      fieldRow('Accepted CTC (₹ / yr)', 'h_ctc', c.expected_ctc || '', { type: 'number', step: 10000 })].join(''))}
      ${grid('md:grid-cols-3 gap-3', [fieldRow('Date of birth', 'h_dob', '', { type: 'date' }), fieldRow('PAN', 'h_pan', ''), fieldRow('Gender', 'h_gender', '', { type: 'select', options: ['Male', 'Female', 'Other'], placeholder: 'Select' })].join(''))}</div>`;
  openModal('Convert candidate to employee', body, modalFootSave(`submitHire('${id}')`, 'Create employee record'));
}
async function submitHire(id) {
  const v = formValues(['h_name', 'h_email', 'h_phone', 'h_doj', 'h_dept_name', 'h_desig_name', 'h_mgr', 'h_type', 'h_loc', 'h_ctc', 'h_dob', 'h_pan', 'h_gender']);
  const body = { full_name: v.h_name, email: v.h_email, phone: v.h_phone, date_of_joining: v.h_doj, salary_ctc: num(v.h_ctc), employment_type: v.h_type, work_location: v.h_loc, date_of_birth: v.h_dob || null, pan_no: v.h_pan || null, gender: v.h_gender || null };
  if (v.h_mgr) body.manager_id = v.h_mgr;
  try {
    const deptId = await resolveTypeOrAdd('department', 'h_dept_name');
    if (deptId) body.department_id = deptId;
    const desigId = await resolveTypeOrAdd('designation', 'h_desig_name', deptId);
    if (desigId) body.designation_id = desigId;
    const r = await api(`/api/candidates/${id}/hire`, { method: 'POST', body });
    toast(r.message, 'success'); closeAllModals();
    APP.lookups = null; await loadLookups(true);
    loadHiring(true); loadDashboard(true); if (currentModule === 'employees') loadEmployees(true);
  } catch (e) { }
}
async function loadFunnel() {
  let pipe;
  try { pipe = await api('/api/hiring/pipeline'); } catch (e) { return; }
  const stages = pipe.stages || [];
  makeChart('funnelChart', { type: 'bar', data: { labels: stages.map(s => s.name), datasets: [{ data: stages.map(s => s.count), backgroundColor: ['#15803d', '#4ade80', '#0d9488', '#f59e0b', '#0f9d58'], borderRadius: 7 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0, font: { size: 10 } }, grid: { color: '#f1f5f9' } }, y: { ticks: { font: { size: 11 } }, grid: { display: false } } } } });
  const ages = pipe.time_in_stage || {};
  $('#stageAgeing').innerHTML = stages.map(s => {
    const a = ages[s.name] || { count: 0, over_7_days: 0 };
    const stuck = a.count ? Math.round(a.over_7_days / a.count * 100) : 0;
    return `<div><div class="flex items-center justify-between text-[12.5px]"><span class="font-medium">${esc(s.name)}</span><span class="text-[#94a3b8] num">${a.count} here · ${a.over_7_days} over 7 days</span></div><div class="bar mt-1"><span style="width:${stuck}%;background:${stuck > 50 ? '#c0392b' : stuck > 25 ? '#f59e0b' : '#0f9d58'}"></span></div></div>`;
  }).join('');
  $('#sourceMix').innerHTML = Object.entries(pipe.by_source || {}).map(([k, v]) => `<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(k)} <b class="num ml-1">${v}</b></span>`).join('') || '<span class="text-[12px] text-[#94a3b8]">No candidates yet</span>';
}

/* ================================================================== PERFORMANCE */
function setPerfTab(t) { $$('#module-performance [data-perftab]').forEach(x => x.classList.toggle('active', x.dataset.perftab === t)); if (t === 'matrix') loadPerfMatrix(); }
async function loadPerformance(refresh) {
  await loadLookups();
  if (refresh) $('#goalsList').innerHTML = '<div class="spin"></div>';
  let goals = [], reviews = [], feedback = [], checkins = [], overview = null;
  try {
    [goals, reviews, feedback, checkins, overview] = await Promise.all([api('/api/goals'), api('/api/reviews'), api('/api/feedback'), api('/api/checkins'), api('/api/performance/overview')]);
  } catch (e) { return; }
  APP.goals = goals; APP.reviews = reviews; APP.feedback = feedback; APP.checkins = checkins; APP.perfOverview = overview;
  renderGoals(goals); renderReviews(reviews); renderFeedback(feedback); renderCheckins(checkins); renderPerfSummary(overview); renderPerfForms();
  if (document.querySelector('#module-performance [data-perftab="matrix"].active')) loadPerfMatrix();
}
function renderGoals(goals) {
  const box = $('#goalsList');
  if (!goals.length) { box.innerHTML = emptyState('No goals yet for this login', 'Add one with a measurable target so the health flag can track it.', '<button class="btn btn-primary btn-xs" onclick="openGoalModal()">New goal</button>'); return; }
  box.innerHTML = goals.map(g => `<div class="p-4 rounded-xl border border-[#f1f5f9] ${g.health === 'overdue' ? 'bg-[#fff8f8]' : g.health === 'at_risk' ? 'bg-[#fffdf7]' : ''}">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0"><div class="flex items-center gap-2 flex-wrap"><span class="text-[13.5px] font-semibold">${esc(g.title)}</span>
        ${g.category ? `<span class="pill bg-[#f0fdf4] text-[#64748b]">${esc(g.category)}</span>` : ''}
        <span class="pill ${g.health === 'achieved' ? 'bg-[#d1fae5] text-[#15803d]' : g.health === 'on_track' ? 'bg-[#e6f9f0] text-[#0f9d58]' : g.health === 'at_risk' ? 'bg-[#fff4e6] text-[#b7791f]' : 'bg-[#fff1f1] text-[#c0392b]'}">${esc(g.health_label)}</span></div>
        ${g.description ? `<div class="text-[12.5px] text-[#64748b] mt-1.5 leading-relaxed">${esc(g.description)}</div>` : ''}
        <div class="text-[11.5px] text-[#94a3b8] mt-1.5">${g.metric ? `<b>Target:</b> ${esc(g.metric)} ${esc(g.target || '')} · ` : ''}${g.due_date ? `due ${fmtDate(g.due_date)}${g.days_left < 0 ? ' <span class="text-[#c0392b]">(overdue)</span>' : g.days_left <= 14 ? ` <span class="text-[#b7791f]">(in ${g.days_left}d)</span>` : ''}` : ''}</div></div>
      <div class="text-right flex-shrink-0"><div class="font-display font-bold text-[20px] num" style="color:${g.progress >= 100 ? '#15803d' : g.progress >= 50 ? '#0f9d58' : '#b7791f'}">${g.progress}%</div>
        ${isAdmin() || true ? `<button onclick="updateGoalProgress('${g.id}',${g.progress})" class="text-[11px] text-[#15803d] hover:underline">update</button>` : ''}</div></div>
    <div class="bar mt-3"><span style="width:${g.progress}%;background:${g.progress >= 100 ? '#15803d' : g.progress >= 50 ? '#0f9d58' : '#f59e0b'}"></span></div>
    <div class="flex items-center gap-2 mt-3">
      <input type="range" min="0" max="100" step="5" value="${g.progress}" class="flex-1 accent-[#15803d]" onchange="quickGoalProgress('${g.id}', this.value)">
      <span class="text-[11.5px] text-[#94a3b8] num" id="gp${g.id}">${g.progress}%</span>
      <button onclick="deleteGoal('${g.id}')" class="btn btn-ghost !py-1 !px-2 text-[#cbd5e1] hover:text-[#c0392b]" title="Delete goal"><i class="far fa-trash-alt text-[11px]"></i></button></div></div>`).join('');
}
async function quickGoalProgress(id, value) {
  try { const r = await api('/api/goals/' + id, { method: 'PUT', body: { progress: num(value) } }); $('#gp' + id).textContent = r.goal.progress + '%'; toast(r.message, 'success'); APP.dirty.performance = false; } catch (e) { }
}
function updateGoalProgress(id, current) {
  const g = (APP.goals || []).find(x => String(x.id) === String(id));
  const body = `<div class="space-y-3">${grid('md:grid-cols-2 gap-3', [fieldRow('Progress %', 'gp_val', current, { type: 'number', min: 0, max: 100, step: 5 }), fieldRow('Status', 'gp_status', g.status, { type: 'select', options: ['Not Started', 'On Track', 'At Risk', 'Achieved', 'Closed'] })].join(''))}${fieldRow('Update note for your manager', 'gp_note', '', { type: 'textarea', rows: 2, placeholder: 'Shipped the cache layer; p95 is at 480ms now.' })}</div>`;
  openModal('Update goal', body, modalFootSave(`submitGoalProgress('${id}')`, 'Save progress'));
}
async function submitGoalProgress(id) {
  const v = formValues(['gp_val', 'gp_status', 'gp_note']);
  try { const r = await api('/api/goals/' + id, { method: 'PUT', body: { progress: Math.min(100, Math.max(0, num(v.gp_val))), status: v.gp_status, note: v.gp_note || undefined } }); toast(r.message, 'success'); closeAllModals(); loadPerformance(true); } catch (e) { }
}
async function deleteGoal(id) { await confirmAction('Delete this goal?', async () => { await api('/api/goals/' + id, { method: 'DELETE' }); toast('Goal removed', 'success'); loadPerformance(true); }, 'Delete goal'); }
function openGoalModal() {
  const body = `<div class="space-y-3">${fieldRow('Goal title', 'gl_title', '', { required: true, placeholder: 'Cut p95 API latency below 400ms' })}
    ${fieldRow('Why it matters / scope', 'gl_desc', '', { type: 'textarea', rows: 2 })}
    ${grid('md:grid-cols-2 gap-3', [fieldRow('Category', 'gl_cat', 'Individual', { type: 'select', options: ['Individual', 'Team', 'Learning', 'Process', 'Customer'] }), fieldRow('Due date', 'gl_due', isoDay(new Date(Date.now() + 90 * 864e5)), { type: 'date' }), fieldRow('Metric', 'gl_metric', '', { placeholder: 'p95 latency' }), fieldRow('Target', 'gl_target', '', { placeholder: '400 ms' })].join(''))}
    ${grid('md:grid-cols-2 gap-3', [fieldRow('Starting progress %', 'gl_prog', 0, { type: 'number', min: 0, max: 100, step: 5 }), fieldRow('Status', 'gl_status', 'On Track', { type: 'select', options: ['Not Started', 'On Track', 'At Risk', 'Achieved'] })].join(''))}</div>`;
  openModal('New goal', body, modalFootSave('submitGoal()', 'Add goal'));
}
async function submitGoal() {
  const v = formValues(['gl_title', 'gl_desc', 'gl_cat', 'gl_due', 'gl_metric', 'gl_target', 'gl_prog', 'gl_status']);
  if (!v.gl_title) { toast('Give the goal a title', 'error'); return; }
  try { const r = await api('/api/goals', { method: 'POST', body: { title: v.gl_title, description: v.gl_desc, category: v.gl_cat, due_date: v.gl_due, metric: v.gl_metric, target: v.gl_target, progress: num(v.gl_prog), status: v.gl_status } }); toast(r.message, 'success'); closeAllModals(); loadPerformance(true); } catch (e) { }
}
function renderReviews(reviews) {
  const box = $('#reviewsList');
  if (!reviews.length) { box.innerHTML = emptyState('No reviews in this cycle', isAdmin() ? 'Open a review to start the self-assessment round.' : 'HR will open the cycle for you.'); return; }
  box.innerHTML = reviews.map(r => {
    const canSelf = String(r.employee_id) === String(APP.user.employee_id) && r.status === 'Self Review Pending';
    const canManager = (isAdmin() || String(r.reviewer_id) === String(APP.user.employee_id)) && r.status === 'Manager Review Pending';
    const comps = Object.entries(r.competencies || {});
    return `<div class="border border-[#f1f5f9] rounded-xl p-4">
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div class="min-w-0 flex-1"><div class="flex items-center gap-2 flex-wrap"><span class="font-display font-semibold text-[14px]">${esc(r.period || 'Review cycle')}</span>${statusPill(r.status)}${r.overdue ? '<span class="pill bg-[#fff1f1] text-[#c0392b]">overdue by ' + Math.abs(r.days_left) + 'd</span>' : r.days_left !== null && r.days_left >= 0 ? `<span class="pill bg-[#f0fdf4] text-[#64748b]">${r.days_left} days left</span>` : ''}</div>
          <div class="text-[12.5px] text-[#64748b] mt-1.5">${personLine(r.employee, '', 24)} · reviewed by ${esc(r.reviewer?.full_name || '—')}</div>
          <div class="text-[11.5px] text-[#94a3b8] mt-1">${esc(r.cycle_label || '')} · due ${fmtDate(r.due_date)}</div></div>
        <div class="text-right"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">Final rating</div><div class="font-display font-bold text-[22px] num" style="color:${num(r.final_rating) >= 4 ? '#0f9d58' : num(r.final_rating) > 0 ? '#b7791f' : '#cbd5e1'}">${num(r.final_rating) ? num(r.final_rating).toFixed(1) : '—'}</div>
          <div class="text-[11px] text-[#94a3b8] num">self ${r.self_rating ?? '—'} · mgr ${r.manager_rating ?? '—'}</div></div></div>
      ${comps.length ? `<div class="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">${comps.map(([k, v]) => `<div class="bg-[#f0fdf4] rounded-lg p-2"><div class="text-[10.5px] text-[#94a3b8] truncate">${esc(k)}</div><div class="text-[12.5px] font-semibold num">${v.toFixed(1)}</div></div>`).join('')}</div>` : ''}
      ${(r.strengths || r.improvements || r.comments) ? `<div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
        ${r.strengths ? `<div class="bg-[#e6f9f0] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#0f9d58] font-semibold mb-1">Strengths</div><div class="text-[12.5px] leading-relaxed">${esc(r.strengths)}</div></div>` : ''}
        ${r.improvements ? `<div class="bg-[#fff4e6] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#b7791f] font-semibold mb-1">To improve</div><div class="text-[12.5px] leading-relaxed">${esc(r.improvements)}</div></div>` : ''}
        ${r.comments ? `<div class="bg-[#d1fae5] rounded-xl p-3"><div class="text-[10.5px] uppercase tracking-widest text-[#15803d] font-semibold mb-1">${r.status === 'Self Review Pending' ? 'Self review' : 'Reviewer comments'}</div><div class="text-[12.5px] leading-relaxed">${esc(r.comments)}</div></div>` : ''}</div>` : ''}
      <div class="flex gap-2 mt-3 pt-3 border-t border-[#f1f5f9]">${canSelf ? `<button onclick="openReviewSelf('${r.id}')" class="btn btn-primary btn-xs"><i class="far fa-pen"></i> Write my self review</button>` : ''}
        ${canManager ? `<button onclick="openReviewManager('${r.id}')" class="btn btn-primary btn-xs"><i class="fas fa-star"></i> Give the manager rating</button>` : ''}
        ${isAdmin() ? `<button onclick="openReviewManager('${r.id}', true)" class="btn btn-ghost btn-xs ml-auto">Edit as HR</button>` : ''}
        ${!canSelf && !canManager && !isAdmin() ? '<span class="text-[12px] text-[#94a3b8]">Nothing for you to do on this review right now.</span>' : ''}</div></div>`;
  }).join('');
}
function ratingSelect(name, value) { return Array.from({ length: 9 }, (_, i) => ({ value: (1 + i * 0.5).toFixed(1), label: `${(1 + i * 0.5).toFixed(1)}${i === 6 ? ' · Meets expectations' : i === 8 ? ' · Outstanding' : i === 0 ? ' · Below bar' : ''}` })).map(o => `<option value="${o.value}" ${String(o.value) === String(value ?? '') ? 'selected' : ''}>${o.label}</option>`).join(''); }
function openReviewSelf(id) {
  const r = (APP.reviews || []).find(x => String(x.id) === String(id)) || {};
  const body = `<div class="space-y-3">
    <div><div class="lbl">How would you rate yourself?</div><select id="rs_rating" class="field">${ratingSelect('rs_rating', r.self_rating)}</select></div>
    ${fieldRow('What went well', 'rs_strengths', r.strengths, { type: 'textarea', rows: 2, placeholder: 'Owned the attendance rewrite end to end and cut review time for HR.' })}
    ${fieldRow('What you want to get better at', 'rs_improvements', r.improvements, { type: 'textarea', rows: 2 })}
    ${fieldRow('Self review comments (required)', 'rs_comments', r.comments, { type: 'textarea', rows: 3, required: true, placeholder: 'Context your reviewer should have: constraints, wins, help needed.' })}</div>`;
  openModal('Self review', body, modalFootSave(`submitReviewSelf('${id}')`, 'Submit to my reviewer'));
}
async function submitReviewSelf(id) {
  const v = formValues(['rs_rating', 'rs_strengths', 'rs_improvements', 'rs_comments']);
  if (!v.rs_comments || v.rs_comments.trim().length < 5) { toast('Write your self-review comments first', 'error'); return; }
  try { const r = await api('/api/reviews/' + id, { method: 'PUT', body: { action: 'self_review', self_rating: num(v.rs_rating), comments: v.rs_comments, strengths: v.rs_strengths, improvements: v.rs_improvements } }); toast(r.message, 'success'); closeAllModals(); loadPerformance(true); } catch (e) { }
}
function openReviewManager(id, asHr) {
  const r = (APP.reviews || []).find(x => String(x.id) === String(id)) || {};
  const comps = ['Delivery', 'Quality of work', 'Collaboration', 'Communication', 'Ownership', 'Customer impact'];
  const body = `<div class="space-y-3.5">
    ${r.employee ? `<div class="flex items-center gap-3 bg-[#f0fdf4] rounded-xl p-3">${avatar(r.employee, 36)}<div><div class="text-[13px] font-semibold">${esc(r.employee.full_name)}</div><div class="text-[11.5px] text-[#94a3b8]">${esc(r.employee.designation || '')} · self rated <b class="num">${r.self_rating ?? '—'}</b></div></div><div class="ml-auto text-right"><div class="text-[10.5px] uppercase tracking-widest text-[#94a3b8] font-semibold">Self review</div><div class="text-[12.5px] max-w-[280px] line-clamp-3">${esc(r.comments || 'not written yet')}</div></div></div>` : ''}
    ${fieldRow('Manager rating', 'rm_rating', r.manager_rating || '', { type: 'select', options: Array.from({ length: 9 }, (_, i) => ({ value: (1 + i * 0.5).toFixed(1), label: (1 + i * 0.5).toFixed(1) })) })}
    ${fieldRow('Final published rating (leave blank to copy the manager rating)', 'rm_final', r.final_rating || '', { type: 'number', step: 0.1, min: 0, max: 5 })}
    ${fieldRow('Potential', 'rm_pot', r.potential || 'Solid', { type: 'select', options: ['High', 'Solid', 'Needs development'] })}
    ${fieldRow('Reviewer comments (required)', 'rm_comments', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Strong delivery on the timesheet rebuild; needs to write decisions down so the team can follow.' })}
    ${fieldRow('Strengths', 'rm_strengths', r.strengths, { type: 'textarea', rows: 2 })}
    ${fieldRow('To improve', 'rm_improvements', r.improvements, { type: 'textarea', rows: 2 })}
    <div><div class="lbl">Competencies</div><div class="grid grid-cols-2 md:grid-cols-3 gap-2">${comps.map(c => `<div class="bg-[#f8fafc] border border-[#f1f5f9] rounded-xl p-2.5"><div class="text-[11.5px] font-medium mb-1.5 truncate">${esc(c)}</div><input class="field !py-1 !text-[12px]" data-comp="${esc(c)}" value="${num((r.competencies || {})[c]) || ''}" placeholder="1–5"></div>`).join('')}</div></div>
    ${asHr ? '' : '<label class="flex items-center gap-2 text-[12.5px] cursor-pointer"><input type="checkbox" id="rm_finalize" class="rounded border-[#cbd5e1] text-[#15803d]"> Publish this rating and close the review</label>'}</div>`;
  openModal(asHr ? 'Edit review as HR' : 'Manager review', body, modalFootSave(`submitReviewManager('${id}',${asHr ? 'true' : 'false'})`, 'Save review'));
}
async function submitReviewManager(id, asHr) {
  const v = formValues(['rm_rating', 'rm_final', 'rm_pot', 'rm_comments', 'rm_strengths', 'rm_improvements']);
  const competencies = {};
  $$('[data-comp]').forEach(el => { if (el.value !== '') competencies[el.dataset.comp] = Math.min(5, Math.max(1, num(el.value))); });
  if (!asHr && (!v.rm_comments || v.rm_comments.trim().length < 5)) { toast('Add reviewer comments — the employee sees them', 'error'); return; }
  const body = asHr ? { manager_rating: num(v.rm_rating) || undefined, final_rating: v.rm_final ? num(v.rm_final) : undefined, competencies, strengths: v.rm_strengths, improvements: v.rm_improvements, comments: v.rm_comments, potential: v.rm_pot } :
    { action: 'manager_review', manager_rating: num(v.rm_rating), comments: v.rm_comments, strengths: v.rm_strengths, improvements: v.rm_improvements, potential: v.rm_pot, competencies, finalize: $('#rm_finalize')?.checked };
  try { const r = await api('/api/reviews/' + id, { method: 'PUT', body }); toast(r.message, 'success'); closeAllModals(); loadPerformance(true); if (currentModule === 'inbox') loadInbox(); } catch (e) { }
}
function openReviewForm() {
  const body = grid('md:grid-cols-2 gap-3', [
    fieldRow('Employee', 'rf_emp', '', { type: 'select', options: employeeOptions(false), placeholder: 'Select', required: true }),
    fieldRow('Reviewer', 'rf_rev', APP.user.employee_id, { type: 'select', options: employeeOptions(false), placeholder: 'Me' }),
    fieldRow('Period label', 'rf_period', 'FY' + (new Date().getFullYear() % 100 + 1), { placeholder: 'FY27 H1' }),
    fieldRow('Cycle starts', 'rf_start', new Date(new Date().getFullYear(), 3, 1).toISOString().slice(0, 10), { type: 'date' }),
    fieldRow('Cycle ends', 'rf_end', new Date(new Date().getFullYear() + (new Date().getMonth() >= 3 ? 1 : 0), 2, 31).toISOString().slice(0, 10), { type: 'date' }),
    fieldRow('Due by', 'rf_due', isoDay(new Date(Date.now() + 14 * 864e5)), { type: 'date' })].join(''));
  openModal('Open a review', `<div class="space-y-3">${body}<div class="text-[11.5px] text-[#94a3b8] bg-[#f0fdf4] rounded-xl p-3">The employee gets a self-review task in their inbox; you score it afterwards.</div></div>`, modalFootSave('submitReviewCreate()', 'Open review'));
}
async function submitReviewCreate() {
  const v = formValues(['rf_emp', 'rf_rev', 'rf_period', 'rf_start', 'rf_end', 'rf_due']);
  if (!v.rf_emp) { toast('Choose the employee', 'error'); return; }
  try { const r = await api('/api/reviews', { method: 'POST', body: { employee_id: v.rf_emp, reviewer_id: v.rf_rev || null, period: v.rf_period, cycle_start: v.rf_start, cycle_end: v.rf_end, due_date: v.rf_due, status: 'Self Review Pending' } }); toast(r.message, 'success'); closeAllModals(); loadPerformance(true); } catch (e) { }
}
function renderFeedback(rows) { renderFeedbackInto('#feedbackList', rows, 6); renderFeedbackInto('#allFeedbackList', rows, 40); }
function renderFeedbackInto(sel, rows, limit) {
  const box = $(sel); if (!box) return;
  if (!rows.length) { box.innerHTML = '<div class="text-[12.5px] text-[#94a3b8]">No feedback yet.</div>'; return; }
  box.innerHTML = rows.slice(0, limit).map(f => `<div class="p-3 rounded-xl bg-[#f8fafc] border border-[#f1f5f9]">
    <div class="flex items-center gap-2 mb-1.5">${avatar(f.from?.avatar ? f.from : { full_name: f.from_label }, 24)}<span class="text-[12.5px] font-medium">${esc(f.from_label)}</span><span class="text-[11.5px] text-[#94a3b8]">→ ${esc(f.to?.full_name || 'you')}</span><span class="ml-auto text-[11px] text-[#94a3b8] num">${esc(f.date_label || '')}</span></div>
    <div class="text-[12.5px] leading-relaxed">${esc(f.message)}</div>
    ${f.tag_list?.length ? `<div class="flex flex-wrap gap-1.5 mt-2">${f.tag_list.map(t => `<span class="pill bg-[#d1fae5] text-[#15803d]">${esc(t)}</span>`).join('')}</div>` : ''}</div>`).join('');
}
function renderPerfForms() {
  const empOpts = employeeOptions(false);
  $('#feedbackForm').innerHTML = `<div class="space-y-3">${fieldRow('Recognise', 'fb_to', '', { type: 'select', options: empOpts, placeholder: 'Who?', required: true })}${fieldRow('What they did', 'fb_msg', '', { type: 'textarea', rows: 3, required: true, placeholder: 'Your runbook saved us an hour of paging during the go-live.' })}${fieldRow('Tags', 'fb_tags', '', { placeholder: 'Teamwork, Ownership' })}${grid('grid-cols-2 gap-3', [fieldRow('Category', 'fb_cat', 'Appreciation', { type: 'select', options: ['Appreciation', 'Constructive', 'Values', 'Client feedback'] }), fieldRow('Send anonymously', 'fb_anon', false, { type: 'checkbox' })].join(''))}<button onclick="submitFeedback()" class="btn btn-primary btn-xs w-full justify-center">Send feedback</button></div>`;
  $('#checkinForm').innerHTML = `<div class="space-y-3">${fieldRow('With', 'ck_emp', '', { type: 'select', options: empOpts, placeholder: 'Team member', required: true })}${fieldRow('Date', 'ck_date', isoDay(new Date(Date.now() + 2 * 864e5)), { type: 'date' })}${fieldRow('Agenda', 'ck_agenda', '', { type: 'textarea', rows: 2, placeholder: 'Sprint retro follow-ups' })}${fieldRow('Notes', 'ck_notes', '', { type: 'textarea', rows: 2 })}${fieldRow('Next steps', 'ck_next', '', { placeholder: 'Pair on the alerting rules' })}<button onclick="submitCheckin()" class="btn btn-primary btn-xs w-full justify-center">Schedule check-in</button></div>`;
}
function openFeedbackModal() { setPerfTab('feedback'); $$('#module-performance [data-perftab]').forEach(x => x.classList.toggle('active', x.dataset.perftab === 'feedback')); setTimeout(() => $('#fb_to')?.focus(), 60); }
async function submitFeedback() {
  const body = { to_employee_id: needValue('fb_to', 'Choose who you are recognising'), message: needValue('fb_msg', 'Write at least a line'), tags: $('#fb_tags').value, category: $('#fb_cat').value, is_anonymous: $('#fb_anon').checked };
  try { const r = await api('/api/feedback', { method: 'POST', body }); toast(r.message, 'success'); loadPerformance(true); } catch (e) { }
}
async function submitCheckin() {
  const body = { employee_id: needValue('ck_emp', 'Choose the team member'), date: $('#ck_date').value, agenda: $('#ck_agenda').value, notes: $('#ck_notes').value, next_steps: $('#ck_next').value };
  try { const r = await api('/api/checkins', { method: 'POST', body }); toast(r.message, 'success'); loadPerformance(true); } catch (e) { }
}
function renderCheckins(rows) {
  const box = $('#checkinList');
  if (!rows.length) { box.innerHTML = emptyState('No check-ins logged', 'Schedule one from the panel on the right.'); return; }
  box.innerHTML = `<table class="kt"><thead><tr><th>Date</th><th>With</th><th>Agenda</th><th>Next steps</th><th>Status</th>${isAdmin() ? '<th></th>' : ''}</tr></thead><tbody>${rows.map(c => `<tr><td class="num">${fmtDayShort(c.date)}${c.days_ago > 45 ? '<div class="text-[10.5px] text-[#b7791f]">overdue cadence</div>' : ''}</td><td>${personLine(c.employee, '', 26)}</td><td class="text-[12.5px] max-w-[260px]">${esc(c.agenda || '—')}${c.notes ? `<div class="text-[11px] text-[#94a3b8] truncate">${esc(c.notes)}</div>` : ''}</td><td class="text-[12.5px] max-w-[200px]">${esc(c.next_steps || '—')}</td><td>${statusPill(c.status)}</td>${isAdmin() ? `<td class="text-right">${c.status !== 'Done' ? `<button onclick="api('/api/checkins/${c.id}',{method:'PUT',body:{status:'Done'}}).then(()=>{toast('Marked done','success');loadPerformance(true)})" class="btn btn-ghost btn-xs !py-1">Mark done</button>` : ''}</td>` : ''}</tr>`).join('')}</tbody></table>`;
}
function renderPerfSummary(o) {
  if (!o) return;
  $('#perfSummary').innerHTML = `<div class="space-y-2.5">
    ${[['Goals open', o.goals_open, `${o.goals_total} total`], ['Avg progress', o.avg_goal_progress + '%', `${o.at_risk.length} at risk or overdue`], ['Reviews to close', o.reviews_open, `${o.pending_self_review} self · ${o.pending_manager_review} manager`], ['Avg rating', o.avg_rating || '—', `${o.completed_reviews} completed`]].map(([l, v, h]) => `<div class="flex items-center gap-3"><div class="text-[12.5px] flex-1">${esc(l)}</div><div class="font-display font-bold text-[15px] num">${v}</div></div><div class="text-[11px] text-[#94a3b8] -mt-2">${esc(h)}</div><div class="border-b border-[#f1f5f9]"></div>`).join('')}</div>`;
}
async function loadPerfMatrix() {
  const o = APP.perfOverview; if (!o) return;
  const buckets = ['Needs development', 'Solid', 'High'];
  const perfAxis = ['Low', 'Medium', 'High'];
  let html = '';
  for (let y = 2; y >= 0; y--) {
    for (let x = 0; x < 3; x++) {
      const key = `${buckets[y]} potential / ${perfAxis[x]} performance`;
      const people = o.nine_box?.[key] || [];
      const tone = (x === 2 && y === 2) ? 'bg-[#e6f9f0]' : (x === 0 && y === 0) ? 'bg-[#fff1f1]' : 'bg-[#f8fafc]';
      html += `<div class="rounded-xl p-2.5 ${tone} border border-[#f1f5f9] min-h-[104px]"><div class="text-[9.5px] uppercase tracking-widest text-[#94a3b8] font-semibold mb-1.5">${esc(y === 2 ? 'High' : y === 1 ? 'Solid' : 'Dev')} · ${esc(perfAxis[x])}</div>
        <div class="flex flex-wrap gap-1">${people.slice(0, 8).map(p => `<span title="${esc(p.name)} · ${p.rating} · goals ${p.goal_progress}%" class="inline-flex items-center gap-1 bg-white rounded-full pl-0.5 pr-2 py-0.5 text-[10.5px] border border-[#dcfce7]"><span style="width:17px;height:17px;font-size:7.5px" class="avatar">${esc(p.avatar || initialsOf(p.name))}</span>${esc((p.name || '').split(' ')[0])}<b class="num">${p.rating.toFixed(1)}</b></span>`).join('')}${people.length > 8 ? `<span class="text-[10.5px] text-[#94a3b8]">+${people.length - 8}</span>` : ''}${!people.length ? '<span class="text-[10.5px] text-[#cbd5e1]">empty</span>' : ''}</div></div>`;
    }
  }
  $('#nineBox').innerHTML = html;
  const max = Math.max(1, ...Object.values(o.rating_distribution || {}));
  $('#ratingDist').innerHTML = Object.entries(o.rating_distribution || {}).map(([k, v]) => `<div><div class="flex justify-between text-[12px]"><span>${esc(k)}</span><b class="num">${v}</b></div><div class="bar mt-1"><span style="width:${v / max * 100}%;background:#15803d"></span></div></div>`).join('');
  $('#goalsAtRisk').innerHTML = (o.at_risk || []).length ? o.at_risk.map(g => `<div class="flex items-center gap-2 text-[12.5px] py-1.5 border-b border-[#f8fafc] last:border-0"><span class="w-1.5 h-1.5 rounded-full ${g.health === 'overdue' ? 'bg-[#c0392b]' : 'bg-[#f59e0b]'}"></span><div class="min-w-0 flex-1"><div class="truncate">${esc(g.title)}</div><div class="text-[11px] text-[#94a3b8]">${esc(g.employee?.full_name || '')} · ${g.progress}%</div></div>${g.due_date ? `<span class="num text-[11px] text-[#94a3b8]">${fmtDayShort(g.due_date)}</span>` : ''}</div>`).join('') : '<div class="text-[12.5px] text-[#0f9d58]">Nothing at risk. </div>';
  $('#perfDeptTable').innerHTML = (o.departments || []).length ? `<table class="kt"><thead><tr><th>Department</th><th>People</th><th>Reviews</th><th>Avg rating</th><th>Avg goal progress</th><th></th></tr></thead><tbody>${o.departments.map(d => `<tr><td class="font-medium">${esc(d.department)}</td><td class="num">${d.people}</td><td class="num">${d.reviews}</td><td class="num">${d.avg_rating || '—'}</td><td><div class="flex items-center gap-2"><div class="bar" style="width:110px"><span style="width:${Math.round(d.avg_goal || 0)}%;background:#15803d"></span></div><span class="num text-[12px]">${Math.round(d.avg_goal || 0)}%</span></div></td><td class="text-right"><button class="btn btn-ghost btn-xs !py-1" onclick="$('#reportDept').value='${esc(d.department)}';switchModule('reports');loadReport()">Report</button></td></tr>`).join('')}</tbody></table>` : emptyState('No department data');
}


/* ================================================================== REPORTS */
// Only used if /api/lookups is unreachable; the real list comes from the server.
const DEFAULT_REPORT_DATASETS = ['employees', 'attendance', 'leave_requests', 'payslips', 'candidates',
  'documents', 'reimbursements', 'timesheet_entries', 'goals', 'performance_reviews'];

async function loadReports(refresh) {
  await loadLookups();
  let list = [];
  try { list = await api('/api/reports'); } catch (e) { return; }
  APP.reportList = list;
  if (!$('#reportPick').options.length || refresh) {
    fillSelect('#reportPick', list.map(r => ({ value: r.id, label: `${r.name}` })), $('#reportPick')?.value || 'headcount', false);
    fillSelect('#reportDept', [{ value: '', label: 'All departments' }, ...(APP.lookups.departments || []).map(d => ({ value: d.name, label: d.name }))], $('#reportDept')?.value, false);
    const dsFromApi = (APP.lookups.custom_datasets || []).map(x => ({ value: x.table, label: x.label || x.table.replace(/_/g, ' ') }));
    const dsList = dsFromApi.length ? dsFromApi : DEFAULT_REPORT_DATASETS.map(x => ({ value: x, label: x.replace(/_/g, ' ') }));
    const keep = $('#csDataset')?.value && dsList.some(d => d.value === $('#csDataset').value) ? $('#csDataset').value
      : (dsList.some(d => d.value === 'attendance') ? 'attendance' : dsList[0].value);
    fillSelect('#csDataset', dsList, keep, false);
    $('#reportTo').value = todayIso();
    $('#reportFrom').value = isoDay(new Date(Date.now() - 89 * 864e5));
    customSchema();
  }
  const pick = list.find(r => r.id === $('#reportPick').value) || list[0];
  if (pick) $('#reportNote').innerHTML = `${esc(pick.description)} <span class="text-[#15803d]">Good for: ${esc(pick.suits || '')}</span>`;
  loadReport();
}
function quickPeriod(days) { $('#reportFrom').value = isoDay(new Date(Date.now() - (days - 1) * 864e5)); $('#reportTo').value = todayIso(); loadReport(); }
async function loadReport() {
  const name = $('#reportPick').value;
  if (!name) return;
  $('#reportKpis').innerHTML = '<div class="spin"></div>';
  const p = new URLSearchParams({ from: $('#reportFrom').value, to: $('#reportTo').value });
  if ($('#reportDept').value) p.set('department', $('#reportDept').value);
  let d;
  try { d = await api(`/api/reports/${name}?` + p.toString()); } catch (e) { $('#reportKpis').innerHTML = emptyState('Report failed to run'); return; }
  APP.report = d;
  $('#reportNote').innerHTML = `${esc(d.note || '')}${d.meta ? ` · <span class="text-[#94a3b8]">${d.meta.rows} rows · ${esc(d.meta.department)} · ${esc(d.meta.from)} → ${esc(d.meta.to)} · by ${esc(d.meta.generated_by)}</span>` : ''}`;
  $('#reportKpis').innerHTML = (d.kpis || []).map(k => kpiCard(k.label, typeof k.value === 'number' ? k.value.toLocaleString('en-IN') : esc(k.value), esc(k.hint || ''))).join('') || '';
  renderReportChart(d);
  APP.reportCols = d.table?.columns || [];
  APP.reportLabels = d.table?.labels || {};
  APP.reportRows = d.table?.rows || [];
  renderReportTable(APP.reportRows);
}
function renderReportChart(d) {
  const ch = d.chart || {};
  const kind = ch.kind === 'line' ? 'line' : ch.kind === 'doughnut' ? 'doughnut' : 'bar';
  const palette = ['#15803d', '#0d9488', '#f59e0b', '#f472b6', '#60a5fa', '#4ade80', '#0f9d58', '#c0392b', '#94a3b8'];
  $('#reportChartTitle').textContent = `${ch.series_name || 'Trend'} · ${kind === 'doughnut' ? 'share' : 'by period'}`;
  makeChart('reportChart', {
    type: kind,
    data: { labels: ch.labels || [], datasets: [{ label: ch.series_name || 'Value', data: ch.values || [], backgroundColor: kind === 'doughnut' ? palette : kind === 'line' ? 'rgba(21,128,61,.12)' : '#15803d', borderColor: '#15803d', borderWidth: kind === 'line' ? 2.4 : 0, borderRadius: kind === 'bar' ? 6 : 0, tension: .34, fill: kind === 'line', cutout: kind === 'doughnut' ? '60%' : undefined }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: kind === 'doughnut', position: 'right', labels: { boxWidth: 9, font: { size: 10.5 } } }, tooltip: { callbacks: { label: c => kind === 'doughnut' ? ` ${c.label}: ${c.parsed}` : ` ${c.parsed.y ?? c.parsed}` } } },
      scales: kind === 'doughnut' ? {} : { y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: '#f1f5f9' } }, x: { ticks: { font: { size: 9.5 }, maxRotation: 40, autoSkipPadding: 6 }, grid: { display: false } } } }
  });
}
function renderReportTable(rows) {
  const cols = APP.reportCols, labels = APP.reportLabels;
  const box = $('#reportTable');
  if (!rows.length) { box.innerHTML = emptyState('No rows for this period', 'Widen the date range or clear the department filter.'); return; }
  const moneyCols = /amount|cost|net|gross|salary|ctc|value|deduction/i;
  box.innerHTML = `<table class="kt"><thead><tr>${cols.map(c => `<th>${esc((labels[c] || c).replace(/_/g, ' '))}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => {
    let v = r[c];
    if (v === null || v === undefined) v = '—';
    else if (Array.isArray(v)) v = v.join(', ');
    else if (typeof v === 'object') v = JSON.stringify(v);
    else if (moneyCols.test(c) && typeof v === 'number') v = inr(v);
    return `<td class="${typeof v === 'number' || /^\d/.test(String(v)) ? 'num' : ''}">${esc(v)}</td>`;
  }).join('')}</tr>`).join('')}</tbody></table><div class="px-1 pt-3 text-[11.5px] text-[#94a3b8]">${rows.length} row(s)${APP.report?.meta?.rows > rows.length ? ` of ${APP.report.meta.rows}` : ''}</div>`;
}
function filterReportTable() {
  const q = ($('#reportTableSearch').value || '').toLowerCase();
  renderReportTable(!q ? APP.reportRows : APP.reportRows.filter(r => Object.values(r).some(v => String(v ?? '').toLowerCase().includes(q))));
}
function exportReportCsv() {
  const p = new URLSearchParams({ from: $('#reportFrom').value, to: $('#reportTo').value, format: 'csv' });
  if ($('#reportDept').value) p.set('department', $('#reportDept').value);
  window.location.href = `/api/reports/${$('#reportPick').value}?` + p.toString();
}
function exportCsv(path) {
  // /api/export/<module> always answers with CSV; the report endpoints need ?format=csv
  window.location.href = path.includes('/api/export/') ? path
    : path + (path.includes('?') ? '&' : '?') + 'format=csv';
}

function downloadCsv(name, columns, rows) {
  const cell = v => { const t = v === null || v === undefined ? '' : String(v); return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; };
  const csv = [columns.map(cell).join(','), ...(rows || []).map(r => columns.map(c => cell(r[c])).join(','))].join('\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url; a.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  toast(`${(rows || []).length} rows exported as CSV`, 'success');
}
async function customSchema() {
  const ds = $('#csDataset').value;
  if (!ds) return;
  let cols = (APP.lookups.report_schemas || {})[ds];
  if (!cols || !cols.length) {
    // No schema in the lookup payload: ask the report endpoint itself, which answers
    // with the column set the table really has. Never guess a field name here.
    try { cols = (await api('/api/reports/custom', { method: 'POST', body: { dataset: ds, columns: [], filters: {}, limit: 1 } })).available_columns || []; } catch (e) { cols = null; }
  }
  APP.csSchema = cols;
  const list = (cols && cols.length) ? cols : Object.keys((APP.customRows && APP.customRows[0]) || {});
  if (!list.length) { $('#csColumns').innerHTML = emptyState('This table has no columns to report on yet'); return; }
  $('#csColumns').innerHTML = list.map(c => `<label class="flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded-lg bg-[#f0fdf4] cursor-pointer hover:bg-[#d1fae5]"><input type="checkbox" data-cscol="${esc(c)}" checked class="rounded border-[#cbd5e1] text-[#15803d]">${esc(c)}</label>`).join('');
  fillSelect('#csFilterKey', list.map(c => ({ value: c, label: c })), list[0], false);
  $('#csResult').innerHTML = `<div class="text-[12.5px] text-[#94a3b8]">Pick columns and filters, then Run. ${cols ? '' : 'The column list comes from the last fetched rows.'}</div>`;
  renderCsFilters();
}
function addCustomFilter() {
  const k = $('#csFilterKey').value, v = $('#csFilterVal').value;
  if (!k || v === '') { toast('Pick a field and a value first', 'error'); return; }
  APP.customFilters[k] = v; $('#csFilterVal').value = ''; renderCsFilters();
}
function renderCsFilters() {
  const e = $('#csActiveFilters'); if (!e) return;
  e.innerHTML = Object.entries(APP.customFilters).map(([k, v]) => `<span class="pill bg-[#d1fae5] text-[#15803d]">${esc(k)} = ${esc(v)} <button class="ml-1 hover:text-[#c0392b]" onclick="delete APP.customFilters['${esc(k)}'];renderCsFilters()">×</button></span>`).join('');
}
async function runCustomReport(asCsv) {
  const cols = $$('[data-cscol]:checked').map(x => x.dataset.cscol);
  if (!cols.length) { toast('Select at least one column', 'error'); return; }
  const body = { dataset: $('#csDataset').value, columns: cols, filters: APP.customFilters, limit: num($('#csLimit').value) || 200 };
  try {
    const d = await api('/api/reports/custom', { method: 'POST', body });
    APP.customRows = d.rows;
    if (asCsv) { downloadCsv(`${body.dataset}-report`, d.columns, d.rows); return; }
    $('#csResult').innerHTML = `<div class="text-[12px] text-[#94a3b8] mb-2">${d.rows.length} of ${d.total} rows${d.truncated ? ' (truncated)' : ''} · ${esc($('#csDataset').value)}</div>` +
      (d.rows.length ? `<table class="kt"><thead><tr>${d.columns.map(c => `<th>${esc(c.replace(/_/g, ' '))}</th>`).join('')}</tr></thead><tbody>${d.rows.slice(0, 300).map(r => `<tr>${d.columns.map(c => `<td class="num">${esc(r[c] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table>` : emptyState('No rows match those filters'));
  } catch (e) { }
}

/* ================================================================== INBOX */
async function loadInbox(refresh) {
  if (refresh) $('#inboxGroups').innerHTML = '<div class="spin"></div>';
  let d;
  try { d = await api('/api/inbox'); } catch (e) { return; }
  APP.inbox = d;
  const total = d.total || 0;
  $('#inboxTitle').textContent = total ? `Inbox (${total} pending)` : 'Inbox';
  $('#inboxSub').textContent = isAdmin() ? 'Approvals waiting on HR, grouped by module. You can action them right here.' : 'What you have submitted and who is sitting on it.';
  const box = $('#inboxGroups');
  if (!d.groups?.length) { box.innerHTML = `<div class="keka-card">${emptyState('Nothing waiting', 'When someone applies for leave, files a claim or uploads a document it lands here.')}</div>`; return; }
  box.innerHTML = d.groups.map(g => `<div class="keka-card p-5">
    <div class="flex items-center gap-2 mb-3"><h3 class="font-display font-semibold text-[15px]">${esc(g.label || g.module)}</h3><span class="pill bg-[#f0fdf4] text-[#64748b]">${g.count}</span>${isAdmin() && g.count ? `<button class="btn btn-ghost btn-xs ml-auto" onclick="approveGroup('${g.module}','${esc(g.items[0].kind)}')">Approve first</button>` : ''}</div>
    <div class="space-y-2">${g.items.map(a => `<div class="flex items-start gap-3 p-3 rounded-xl border ${a.tone === 'rose' ? 'border-[#ffd9d9] bg-[#fffafa]' : 'border-[#f1f5f9]'}">
      <div class="w-8 h-8 rounded-lg bg-[#f0fdf4] flex items-center justify-center text-[15px] flex-shrink-0">${a.icon || '📌'}</div>
      <div class="min-w-0 flex-1"><div class="text-[13px] font-medium truncate">${esc(a.title)}</div><div class="text-[11.5px] text-[#94a3b8] line-clamp-2">${esc(a.subtitle)}</div>
        ${(a.meta || []).length ? `<div class="flex flex-wrap gap-2 mt-1.5 text-[10.5px] text-[#94a3b8]">${a.meta.map(m => `<span>${esc(m[0])}: <b>${esc(m[1])}</b></span>`).join('')}</div>` : ''}</div>
      <div class="flex items-center gap-1.5 flex-shrink-0">
        ${a.approve_endpoint ? `<button onclick="quickApprove('${a.kind}','${a.id}','${esc(a.approve_endpoint)}')" class="btn btn-primary btn-xs !py-1" title="Approve"><i class="fas fa-check"></i> Approve</button>` : ''}
        ${isAdmin() && a.kind === 'leave' ? `<button onclick="rejectLeaveModal('${a.id}')" class="btn btn-danger btn-xs !py-1" title="Reject"><i class="fas fa-xmark"></i></button>` : ''}
        <button onclick="switchModule('${a.module}')" class="btn btn-ghost btn-xs !py-1" title="Open module"><i class="fas fa-arrow-up-right-from-square"></i></button></div></div>`).join('')}</div></div>`).join('');
}
async function approveGroup(module, kind) {
  const g = (APP.inbox?.groups || []).find(x => x.module === module);
  if (g?.items?.length) { const a = g.items[0]; await quickApprove(a.kind, a.id, a.approve_endpoint); }
}

/* ================================================================== announcements / misc */
async function loadAnnouncements() {
  let rows = [];
  try { rows = await api('/api/announcements'); } catch (e) { return; }
  APP.announcements = rows;
  const box = $('#announcementsList');
  if (!box) return;
  if (!rows.length) { box.innerHTML = emptyState('No announcements', isAdmin() ? 'Post the first one.' : ''); return; }
  box.innerHTML = rows.slice(0, 4).map(a => `<div class="flex gap-3 p-3 rounded-xl ${a.is_pinned ? 'bg-[#fffdf7] border border-[#f6e7c1]' : 'bg-[#f8fafc] border border-[#f1f5f9]'}">
    <div class="w-8 h-8 rounded-lg bg-[#d1fae5] text-[#15803d] flex items-center justify-center flex-shrink-0 text-[13px]"><i class="fas ${a.type === 'Holiday' ? 'fa-umbrella-beach' : a.type === 'Policy' ? 'fa-gavel' : a.type === 'Event' ? 'fa-calendar-star' : 'fa-bullhorn'}"></i></div>
    <div class="min-w-0 flex-1"><div class="flex items-center gap-2"><span class="text-[13px] font-semibold truncate">${esc(a.title)}</span>${a.is_pinned ? '<span class="pill bg-[#fff4e6] text-[#b7791f]">pinned</span>' : ''}</div>
      <div class="text-[12px] text-[#64748b] mt-1 line-clamp-2 leading-relaxed">${esc(a.content)}</div>
      <div class="text-[11px] text-[#94a3b8] mt-1.5">${esc(a.created_by || 'HR')} · ${esc(a.date)}</div></div></div>`).join('');
}
function openAnnouncementsModal() {
  const rows = APP.announcements || [];
  const body = `${isAdmin() ? '<div class="flex justify-end mb-3"><button onclick="openAnnouncementForm()" class="btn btn-primary btn-xs"><i class="fas fa-plus"></i> New announcement</button></div>' : ''}` +
    (rows.length ? `<div class="space-y-3">${rows.map(a => `<div class="p-4 rounded-xl border border-[#f1f5f9]">
      <div class="flex items-start justify-between gap-3"><div><div class="text-[13.5px] font-semibold">${esc(a.title)}</div><div class="text-[11px] text-[#94a3b8] mt-0.5">${esc(a.type || 'Update')} · ${esc(a.created_by || 'HR')} · ${esc(a.date)}</div></div>
        <div class="flex items-center gap-1">${statusPill(a.type)}${isAdmin() ? `<button onclick="togglePin(${a.id},${!a.is_pinned})" class="btn btn-ghost !py-1 !px-2" title="Pin"><i class="fas fa-thumbtack ${a.is_pinned ? 'text-[#b7791f]' : 'text-[#cbd5e1]'}"></i></button><button onclick="deleteAnnouncement(${a.id})" class="btn btn-ghost !py-1 !px-2 text-[#c0392b]"><i class="far fa-trash-alt"></i></button>` : ''}</div></div>
      <div class="text-[13px] text-[#475569] mt-2 leading-relaxed whitespace-pre-line">${esc(a.content)}</div></div>`).join('')}</div>` : emptyState('No announcements yet'));
  openModal('Announcements', body, '<button onclick="closeAllModals()" class="btn btn-ghost">Close</button>');
}
function openAnnouncementForm() {
  const body = grid('md:grid-cols-2 gap-3', [fieldRow('Headline', 'an_title', '', { required: true, placeholder: 'Office closed on Gandhi Jayanti' }), fieldRow('Type', 'an_type', 'Update', { type: 'select', options: ['Update', 'Policy', 'Event', 'Holiday'] })].join('')) +
    fieldRow('Details', 'an_content', '', { type: 'textarea', rows: 5, required: true }) + fieldRow('Pin to the top', 'an_pin', true, { type: 'checkbox' });
  openModal('New announcement', `<div class="space-y-3">${body}</div>`, modalFootSave('submitAnnouncement()', 'Publish'));
}
async function submitAnnouncement() {
  const body = { title: needValue('an_title', 'A headline is required'), content: needValue('an_content', 'Write the details'), type: $('#an_type').value, is_pinned: $('#an_pin').checked };
  try { const r = await api('/api/announcements', { method: 'POST', body }); toast(r.message || 'Published', 'success'); closeAllModals(); await loadAnnouncements(); } catch (e) { }
}
async function togglePin(id, pinned) { try { await api('/api/announcements/' + id, { method: 'PUT', body: { is_pinned: pinned } }); await loadAnnouncements(); openAnnouncementsModal(); toast(pinned ? 'Pinned' : 'Unpinned', 'success'); } catch (e) { } }
async function deleteAnnouncement(id) { await confirmAction('Delete this announcement?', async () => { await api('/api/announcements/' + id, { method: 'DELETE' }); await loadAnnouncements(); openAnnouncementsModal(); }, 'Delete'); }
async function resetDemoData() { await confirmAction('Reset the demo data to its seeded state? Everything you added in this browser session is discarded.', async () => { const r = await api('/api/demo/reset', { method: 'POST' }); toast(r.message, 'success'); location.reload(); }, 'Reset demo'); }
async function healthCheck() {
  const h = await apiQuiet('/api/health');
  if (!h) return;
  if (h.supabase && !h.supabase_connected) toast('Supabase is configured but not reachable — running on demo data', 'warn');
  const tag = $('#dataModeTag');
  if (tag) tag.textContent = h.mock_mode ? 'Demo data' : (h.supabase_connected ? 'Supabase' : 'Database');
}
window.addEventListener('error', e => { if (e.message && /fetch|Network/i.test(e.message)) toast('Lost connection to the server', 'error'); });

document.addEventListener('DOMContentLoaded', () => { bootApp().catch(e => console.error(e)); });
