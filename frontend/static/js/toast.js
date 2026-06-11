/**
 * toast.js
 * --------
 * Displays slide-in toast notifications for:
 *   → Entry recorded  (green left border)
 *   ← Exit recorded   (blue left border)
 *   🚨 Security alert (red left border)
 *
 * Auto-dismisses after 3.5 s with a shrinking progress bar.
 * Caps at 4 toasts visible at once (oldest removed first).
 *
 * Usage:
 *   Toast.show(msg)    → from attendance_event or security_alert payload
 *   Toast.alert(msg)   → shorthand for alert-type toast
 */

'use strict';

const Toast = {

  MAX_VISIBLE:    4,
  DISMISS_MS:     3500,
  _container:     null,

  init() {
    this._container = document.getElementById('toasts');

    window.addEventListener('attendance_event', (e) => this.show(e.detail));
    window.addEventListener('security_alert',   (e) => this.alert(e.detail));
  },

  // ── Show attendance event toast ───────────────────────────────
  show(msg) {
    const gate = msg.gate || 'entry';

    let extraClass = '';
    let label      = '→ Entry Recorded';
    if (gate === 'exit') {
      extraClass = 'exit';
      label      = '← Exit Recorded';
    } else if (gate === 'alert') {
      extraClass = 'alert';
      label      = '🚨 Security Alert';
    }

    const ts   = msg.timestamp
      ? new Date(msg.timestamp).toLocaleTimeString('en-IN', { hour12: false })
      : '';
    const conf = msg.confidence
      ? `${(msg.confidence * 100).toFixed(0)}% confidence`
      : '';
    const name = msg.employee_name || 'Unknown';
    const barW = `${((msg.confidence || 0.9) * 100).toFixed(0)}%`;

    const el = document.createElement('div');
    el.className = `toast${extraClass ? ' ' + extraClass : ''}`;
    el.innerHTML = `
      <div class="toast-label">${label}</div>
      <div class="toast-name">${this._esc(name)}</div>
      <div class="toast-meta">${ts}${conf ? ' · ' + conf : ''}</div>
      <div class="toast-bar" style="width:${barW}"></div>`;

    this._container.appendChild(el);

    // Shrink progress bar immediately after paint
    requestAnimationFrame(() => {
      const bar = el.querySelector('.toast-bar');
      if (bar) bar.style.width = '0%';
    });

    // Auto-dismiss
    setTimeout(() => this._dismiss(el), this.DISMISS_MS);

    // Cap visible toasts
    while (this._container.children.length > this.MAX_VISIBLE) {
      this._dismiss(this._container.firstElementChild);
    }
  },

  // ── Show security alert toast ─────────────────────────────────
  alert(msg) {
    this.show({
      gate:          'alert',
      employee_name: msg.alert || 'Security Alert',
      confidence:    msg.confidence,
      timestamp:     msg.timestamp,
    });
  },

  // ── Dismiss with fade-out ─────────────────────────────────────
  _dismiss(el) {
    if (!el || !el.parentNode) return;
    el.classList.add('toast-out');
    setTimeout(() => el.remove(), 300);
  },

  // ── HTML escape ───────────────────────────────────────────────
  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};