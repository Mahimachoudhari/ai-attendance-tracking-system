bash

cat > /home/claude/attendance-system/frontend/static/js/websocket.js << 'EOF'
/**
 * websocket.js
 * ------------
 * Real WebSocket connections ONLY.
 * Koi fake/synthetic data dispatch NAHI hoga yahan se.
 *
 * Connections:
 *   /ws/dashboard  → real attendance + alert events receive karta hai
 *   /ws/camera/1   → entry gate annotated frames
 *   /ws/camera/2   → exit gate annotated frames
 *
 * Also: /api/health poll karta hai model status check ke liye
 */

'use strict';

const WS = {

  BASE_URL:         window.location.origin.replace(/^http/, 'ws'),
  API_BASE:         window.location.origin,
  PING_INTERVAL_MS: 25_000,
  MAX_BACKOFF_MS:   16_000,
  HEALTH_CHECK_MS:  5_000,    // har 5s mein model status check

  _dashWs:    null,
  _cam1Ws:    null,
  _cam2Ws:    null,
  _pingTimer: null,

  init() {
    this._connectDashboard(1);
    this._connectCamera(1, 1);
    this._connectCamera(2, 1);
    this._pollModelStatus();
  },

  // ── Dashboard WebSocket ─────────────────────────────────────
  _connectDashboard(attempt) {
    const url = `${this.BASE_URL}/ws/dashboard`;
    const ws  = new WebSocket(url);
    this._dashWs = ws;

    ws.onopen = () => {
      attempt = 1;
      this._setWsStatus(true);
      this._startPing(ws);
    };

    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }

      // Sirf real server-side events forward karo
      if (msg.type === 'attendance_event') {
        window.dispatchEvent(new CustomEvent('attendance_event', { detail: msg }));
      } else if (msg.type === 'security_alert') {
        window.dispatchEvent(new CustomEvent('security_alert', { detail: msg }));
      }
    };

    ws.onclose = () => {
      this._setWsStatus(false);
      clearInterval(this._pingTimer);
      const delay = Math.min(1000 * attempt, this.MAX_BACKOFF_MS);
      setTimeout(() => this._connectDashboard(attempt + 1), delay);
    };

    ws.onerror = () => ws.close();
  },

  // ── Camera WebSocket ────────────────────────────────────────
  _connectCamera(cameraId, attempt) {
    const url = `${this.BASE_URL}/ws/camera/${cameraId}`;
    const ws  = new WebSocket(url);

    if (cameraId === 1) this._cam1Ws = ws;
    else                this._cam2Ws = ws;

    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }

      if (msg.type === 'annotated_frame') {
        window.dispatchEvent(new CustomEvent('camera_frame', {
          detail: {
            cameraId,
            data:      msg.data,
            procMs:    msg.proc_ms    ?? 0,
            faceCount: msg.face_count ?? 0,
            events:    msg.events     ?? [],
          },
        }));
      }
    };

    ws.onclose = () => {
      const delay = Math.min(1000 * attempt, this.MAX_BACKOFF_MS);
      setTimeout(() => this._connectCamera(cameraId, attempt + 1), delay);
    };

    ws.onerror = () => ws.close();
  },

  // ── Keep-alive ───────────────────────────────────────────────
  _startPing(ws) {
    clearInterval(this._pingTimer);
    this._pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, this.PING_INTERVAL_MS);
  },

  // ── Poll /api/health to show AI model status ────────────────
  async _pollModelStatus() {
    try {
      const res  = await fetch(`${this.API_BASE}/api/health`);
      if (!res.ok) return;
      const data = await res.json();

      const dot   = document.getElementById('model-dot');
      const label = document.getElementById('model-label');
      if (!dot || !label) return;

      // employees_cached > 0 means model loaded + employees enrolled
      if (data.employees_cached > 0) {
        dot.className     = 'dot dot-g';
        label.textContent = `Model Ready · ${data.employees_cached} employees`;
      } else if (data.db_connected) {
        dot.className     = 'dot dot-w';
        label.textContent = 'Model Ready · No employees enrolled';
      } else {
        dot.className     = 'dot dot-r';
        label.textContent = 'DB Not Connected';
      }
    } catch (_) {
      const label = document.getElementById('model-label');
      if (label) label.textContent = 'Backend Offline';
    }

    setTimeout(() => this._pollModelStatus(), this.HEALTH_CHECK_MS);
  },

  // ── WS status indicator ─────────────────────────────────────
  _setWsStatus(connected) {
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
/**EOF
echo "websocket.js updated"
Output

websocket.js updated*/