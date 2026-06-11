/**
 * alerts.js
 * ---------
 * Polls GET /api/alerts every 30 s and keeps the
 * "Security Alerts" stat card in sync.
 *
 * Also listens for real-time 'security_alert' WebSocket events
 * so the counter updates instantly without waiting for the next poll.
 */

'use strict';

const Alerts = {

  REFRESH_MS: 30_000,
  _timer:     null,

  init() {
    this.refresh();
    this._timer = setInterval(() => this.refresh(), this.REFRESH_MS);

    // Immediate update on real-time WS event
    window.addEventListener('security_alert', () => this.refresh());
  },

  async refresh() {
    try {
      const res = await fetch('/api/alerts');
      if (!res.ok) return;
      const data = await res.json();
      const count = (data.alerts || []).length;

      if (window.Stats) {
        Stats.set('alerts', count);
      } else {
        const el = document.getElementById('s-alerts');
        if (el) el.textContent = count;
      }
    } catch (_) {
      // No-op in demo / offline mode
    }
  },
};