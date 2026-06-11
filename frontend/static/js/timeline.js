/**
 * timeline.js
 * -----------
 * Renders real-time entry / exit / alert events into the
 * scrollable timeline panel on the right side of the dashboard.
 *
 * Listens for:
 *   'attendance_event'  → green (entry) or blue (exit) event card
 *   'security_alert'    → red alert card
 *
 * Also exposes Timeline.add(msg) so dashboard.js can call it
 * directly when seeding demo events.
 *
 * Max 120 items kept in DOM (oldest removed automatically).
 */

'use strict';

const Timeline = {

  MAX_ITEMS: 120,

  _container: null,
  _counter:   null,
  _total:     0,

  init() {
    this._container = document.getElementById('timeline');
    this._counter   = document.getElementById('evt-count');

    window.addEventListener('attendance_event', (e) => this.add(e.detail));
    window.addEventListener('security_alert',   (e) => this.add({ ...e.detail, gate: 'alert', employee_name: '⚠ Security Alert' }));
  },

  // ── Add one event card ────────────────────────────────────────
  add(msg) {
    if (!this._container) return;

    const gate = msg.gate || 'entry';
    const cls  = gate === 'entry' ? 'en' : gate === 'exit' ? 'ex' : 'al';
    const ts   = msg.timestamp
      ? new Date(msg.timestamp).toLocaleTimeString('en-IN', { hour12: false })
      : '--:--:--';

    const name   = msg.employee_name || 'Unknown';
    const initials = name
      .split(' ')
      .slice(0, 2)
      .map((w) => w[0] || '')
      .join('')
      .toUpperCase();

    const conf   = msg.confidence ? `${(msg.confidence * 100).toFixed(0)}%` : '';
    const procMs = msg.proc_ms    ? `${msg.proc_ms}ms`                       : '';

    const el = document.createElement('div');
    el.className = 'evt';
    el.innerHTML = `
      <div class="evt-av ${cls}">${initials}</div>
      <div class="evt-body">
        <div class="evt-name">${this._esc(name)}</div>
        <div class="evt-row">
          <span class="evt-tag ${cls}">${gate.toUpperCase()}</span>
          <span class="evt-time">${ts}</span>
          ${conf   ? `<span class="evt-conf">${conf}</span>`   : ''}
          ${procMs ? `<span class="evt-conf">${procMs}</span>` : ''}
        </div>
      </div>`;

    this._container.insertBefore(el, this._container.firstChild);

    // Trim old entries
    while (this._container.children.length > this.MAX_ITEMS) {
      this._container.removeChild(this._container.lastChild);
    }

    // Update counter
    this._total++;
    if (this._counter) this._counter.textContent = this._total;
  },

  // ── HTML escape helper ────────────────────────────────────────
  _esc(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};