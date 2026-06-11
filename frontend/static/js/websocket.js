/**
 * websocket.js
 * ------------
 * Manages two WebSocket connections:
 *   1. /ws/dashboard  → receives real-time attendance + alert events
 *   2. /ws/camera/1   → receives annotated frames from Entry gate
 *   3. /ws/camera/2   → receives annotated frames from Exit gate
 *
 * Auto-reconnects on disconnect with exponential backoff.
 * Dispatches CustomEvents on window so other modules can listen
 * without tight coupling.
 *
 * Events dispatched:
 *   'attendance_event'  → { detail: eventPayload }
 *   'security_alert'    → { detail: alertPayload }
 *   'camera_frame'      → { detail: { cameraId, data, procMs, faceCount } }
 */

'use strict';

const WS = {

  // ── Config ──────────────────────────────────────────────────
  BASE_URL:         window.location.origin.replace(/^http/, 'ws'),
  PING_INTERVAL_MS: 25_000,
  MAX_BACKOFF_MS:   16_000,

  // ── Internal state ──────────────────────────────────────────
  _dashWs:    null,
  _cam1Ws:    null,
  _cam2Ws:    null,
  _pingTimer: null,

  // ── Public: init all connections ────────────────────────────
  init() {
    this._connectDashboard(1);
    this._connectCamera(1, 1);
    this._connectCamera(2, 1);
  },

  // ── Dashboard WebSocket ──────────────────────────────────────
  _connectDashboard(attempt) {
    const url = `${this.BASE_URL}/ws/dashboard`;

    const ws = new WebSocket(url);
    this._dashWs = ws;

    ws.onopen = () => {
      console.info('[WS] Dashboard connected');
      attempt = 1;
      this._setStatus(true);
      this._startPing(ws);
    };

    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }

      if (msg.type === 'attendance_event') {
        window.dispatchEvent(new CustomEvent('attendance_event', { detail: msg }));
      } else if (msg.type === 'security_alert') {
        window.dispatchEvent(new CustomEvent('security_alert',  { detail: msg }));
      }
    };

    ws.onclose = () => {
      this._setStatus(false);
      clearInterval(this._pingTimer);
      const delay = Math.min(1000 * attempt, this.MAX_BACKOFF_MS);
      console.warn(`[WS] Dashboard closed — retry in ${delay}ms`);
      setTimeout(() => this._connectDashboard(attempt + 1), delay);
    };

    ws.onerror = () => ws.close();
  },

  // ── Camera WebSocket ─────────────────────────────────────────
  _connectCamera(cameraId, attempt) {
    const url = `${this.BASE_URL}/ws/camera/${cameraId}`;
    const ws  = new WebSocket(url);

    if (cameraId === 1) this._cam1Ws = ws;
    else                this._cam2Ws = ws;

    ws.onopen = () => {
      attempt = 1;
      console.info(`[WS] Camera ${cameraId} connected`);
    };

    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }

      if (msg.type === 'annotated_frame') {
        window.dispatchEvent(new CustomEvent('camera_frame', {
          detail: {
            cameraId,
            data:      msg.data,
            procMs:    msg.proc_ms   ?? 0,
            faceCount: msg.face_count ?? 0,
            events:    msg.events    ?? [],
          },
        }));
      }
    };

    ws.onclose = () => {
      const delay = Math.min(1000 * attempt, this.MAX_BACKOFF_MS);
      console.warn(`[WS] Camera ${cameraId} closed — retry in ${delay}ms`);
      setTimeout(() => this._connectCamera(cameraId, attempt + 1), delay);
    };

    ws.onerror = () => ws.close();
  },

  // ── Keep-alive ping ──────────────────────────────────────────
  _startPing(ws) {
    clearInterval(this._pingTimer);
    this._pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, this.PING_INTERVAL_MS);
  },

  // ── Update header status indicator ───────────────────────────
  _setStatus(connected) {
    const dot   = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    if (!dot || !label) return;
    if (connected) {
      dot.classList.add('connected');
      label.textContent = 'Connected';
    } else {
      dot.classList.remove('connected');
      label.textContent = 'Reconnecting…';
    }
  },
};