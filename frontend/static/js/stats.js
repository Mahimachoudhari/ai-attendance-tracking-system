/**
 * stats.js
 * --------
 * Manages the six stat counter cards:
 *   Entered  |  Exited  |  On Premises  |  Late  |  Avg Hours  |  Alerts
 *
 * Exposes:
 *   Stats.set(key, value)        → update a counter silently
 *   Stats.bump(key, value)       → update + play bump animation
 *   Stats.fromSummary(summary)   → bulk-update from API response
 *
 * Keys: 'entered' | 'exited' | 'onsite' | 'late' | 'hours' | 'alerts'
 */

'use strict';

const Stats = {

  // In-memory counters (keep local copy for onsite calculation)
  _counts: { entered: 0, exited: 0, onsite: 0, late: 0, hours: '--', alerts: 0 },

  // Map key → DOM element id
  _ids: {
    entered: 's-entered',
    exited:  's-exited',
    onsite:  's-onsite',
    late:    's-late',
    hours:   's-hours',
    alerts:  's-alerts',
  },

  init() {
    // Listen for real-time events to keep counters in sync
    window.addEventListener('attendance_event', (e) => this._onEvent(e.detail));
    window.addEventListener('security_alert',   ()  => this._onAlert());
  },

  // ── Handle incoming attendance event ─────────────────────────
  _onEvent(msg) {
    const gate = msg.gate || 'entry';
    if (gate === 'entry') {
      this._counts.entered++;
      this.bump('entered', this._counts.entered);
    } else if (gate === 'exit') {
      this._counts.exited++;
      this.bump('exited', this._counts.exited);
    }
    this._counts.onsite = Math.max(0, this._counts.entered - this._counts.exited);
    this.set('onsite', this._counts.onsite);
  },

  _onAlert() {
    this._counts.alerts++;
    this.bump('alerts', this._counts.alerts);
    // Flash the alerts card border red
    const card = document.querySelector('.stat.s-alerts');
    if (card) {
      card.style.borderColor = 'rgba(255,59,92,0.6)';
      card.style.boxShadow   = '0 0 16px rgba(255,59,92,0.2)';
      setTimeout(() => {
        card.style.borderColor = '';
        card.style.boxShadow   = '';
      }, 3000);
    }
  },

  // ── Bulk-update from /api/attendance/today response ───────────
  fromSummary(summary) {
    if (summary.present  != null) this.set('entered', summary.present);
    if (summary.exited   != null) this.set('exited',  summary.exited);
    if (summary.late     != null) this.set('late',    summary.late);
    if (summary.avg_hours != null) this.set('hours', summary.avg_hours + ' h');

    const onsite = Math.max(0, (summary.present || 0) - (summary.exited || 0));
    this.set('onsite', onsite);

    // Sync internal counters so increments stay accurate
    this._counts.entered = summary.present || 0;
    this._counts.exited  = summary.exited  || 0;
    this._counts.onsite  = onsite;
    this._counts.late    = summary.late    || 0;
  },

  // ── Set a value silently ──────────────────────────────────────
  set(key, value) {
    const el = document.getElementById(this._ids[key]);
    if (el) el.textContent = value;
    if (key in this._counts) this._counts[key] = value;
  },

  // ── Set a value + play bump animation ─────────────────────────
  bump(key, value) {
    const el = document.getElementById(this._ids[key]);
    if (!el) return;
    el.textContent = value;
    el.classList.remove('bump');
    void el.offsetWidth;          // force reflow to restart animation
    el.classList.add('bump');
    if (key in this._counts) this._counts[key] = value;
  },

  get(key) {
    return this._counts[key];
  },
};