/**
 * table.js
 * --------
 * Renders and manages the "Today's Attendance" data table.
 *
 * Features:
 *   • Fetches data from GET /api/attendance/today every 12 s
 *   • Live search / filter (name, code, department)
 *   • Status badge colouring (present / late / exited / absent / half-day)
 *   • "Last updated" timestamp in card header
 *   • Empty-state row when no records yet
 *
 * Depends on: nothing (standalone module, uses fetch API)
 */

'use strict';

const Table = {

  REFRESH_MS:  12_000,
  _allRecords: [],
  _timer:      null,

  // ── DOM refs ──────────────────────────────────────────────────
  _tbody:   null,
  _search:  null,
  _updated: null,

  init() {
    this._tbody   = document.getElementById('tbl-body');
    this._search  = document.getElementById('search');
    this._updated = document.getElementById('tbl-updated');

    if (this._search) {
      this._search.addEventListener('input', () => this._filter());
    }

    // Initial load then poll
    this.refresh();
    this._timer = setInterval(() => this.refresh(), this.REFRESH_MS);

    // Refresh immediately on any new attendance event
    window.addEventListener('attendance_event', () => {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this.refresh(), 800);
    });
  },

  // ── Fetch from API ────────────────────────────────────────────
  async refresh() {
    try {
      const res = await fetch('/api/attendance/today');
      if (!res.ok) return;
      const data = await res.json();

      this._allRecords = data.records || [];
      this._render(this._allRecords);

      // Update "Last updated" badge
      if (this._updated) {
        this._updated.textContent =
          'Updated ' + new Date().toLocaleTimeString('en-IN', { hour12: false });
      }

      // Let Stats module consume the summary too
      if (data.summary && window.Stats) {
        Stats.fromSummary(data.summary);
      }
    } catch (_) {
      // Silently fail — no DB in demo mode
    }
  },

  // ── Filter by search query ────────────────────────────────────
  _filter() {
    const q = (this._search?.value || '').toLowerCase();
    if (!q) {
      this._render(this._allRecords);
      return;
    }
    const filtered = this._allRecords.filter((r) =>
      (r.employee_name || '').toLowerCase().includes(q) ||
      (r.employee_code || '').toLowerCase().includes(q) ||
      (r.department    || '').toLowerCase().includes(q)
    );
    this._render(filtered);
  },

  // ── Render rows ───────────────────────────────────────────────
  _render(rows) {
    if (!this._tbody) return;

    if (!rows || rows.length === 0) {
      this._tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align:center;color:var(--muted);padding:28px 0;font-size:12px">
            No attendance records yet today
          </td>
        </tr>`;
      return;
    }

    this._tbody.innerHTML = rows.map((r) => {
      const statusCls = r.exit_time ? 'exited' : (r.status || 'present');
      return `
        <tr>
          <td style="font-weight:600">${this._esc(r.employee_name || '—')}</td>
          <td style="font-family:var(--font-mono);font-size:11px;color:var(--muted)">${this._esc(r.employee_code || '—')}</td>
          <td style="color:var(--text2);font-size:11px">${this._esc(r.department || '—')}</td>
          <td style="font-family:var(--font-mono)">${this._fmtTime(r.entry_time)}</td>
          <td style="font-family:var(--font-mono)">${this._fmtTime(r.exit_time)}</td>
          <td style="font-family:var(--font-mono);color:var(--accent2)">${this._esc(r.work_duration || '—')}</td>
          <td><span class="sbadge ${statusCls}">${statusCls}</span></td>
        </tr>`;
    }).join('');
  },

  // ── Format ISO timestamp → HH:MM:SS ───────────────────────────
  _fmtTime(ts) {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleTimeString('en-IN', { hour12: false });
    } catch (_) {
      return '—';
    }
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