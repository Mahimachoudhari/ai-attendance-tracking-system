bash

cat > /home/claude/attendance-system/frontend/static/js/demo.js << 'EOF'
/**
 * demo.js
 * -------
 * COMPLETELY DISABLED — Koi fake/synthetic events fire nahi honge.
 *
 * Real attendance sirf tab hogi jab:
 *   1. Backend chal raha ho  (uvicorn backend.main:app)
 *   2. Camera feed connected ho  (python demo/run_demo.py ya real RTSP camera)
 *   3. Employees enrolled hon  (python database/seed_employees.py)
 *
 * Ye file sirf ek warning banner dikhati hai agar camera connected nahi hai.
 */

'use strict';

const Demo = {

  _bannerShown:   false,
  _realFrameSeen: false,
  _checkTimer:    null,

  // Kitne seconds baad check kare ki camera connected hai ya nahi
  CAMERA_CHECK_DELAY_MS: 8000,

  init() {
    // Real camera frame aate hi banner hatao
    window.addEventListener('camera_frame', () => {
      this._realFrameSeen = true;
      this._hideBanner();
      clearTimeout(this._checkTimer);
    }, { once: false });

    // 8 seconds baad check karo — agar camera connected nahi to sirf warning banner dikhao
    // KOI FAKE DATA FIRE NAHI HOGA
    this._checkTimer = setTimeout(() => {
      if (!this._realFrameSeen) {
        this._showNoCameraBanner();
      }
    }, this.CAMERA_CHECK_DELAY_MS);
  },

  // ── Banner: no camera warning ──────────────────────────────────
  _showNoCameraBanner() {
    if (this._bannerShown) return;
    this._bannerShown = true;

    const el = document.createElement('div');
    el.id = 'no-camera-banner';
    el.innerHTML = `
      <span style="font-size:16px">📷</span>
      <span>Camera feed connected nahi hai &mdash; Real attendance ke liye camera chalao</span>
      <span style="opacity:0.6;font-size:10px;display:block;margin-top:4px">
        Terminal mein run karo: &nbsp;<code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px">python demo/run_demo.py</code>
        &nbsp; ya real RTSP camera connect karo
      </span>
    `;
    el.style.cssText = `
      position:    fixed;
      bottom:      20px;
      left:        50%;
      transform:   translateX(-50%);
      background:  rgba(255, 184, 0, 0.1);
      border:      1px solid rgba(255, 184, 0, 0.45);
      color:       #ffb800;
      font-family: 'JetBrains Mono', monospace;
      font-size:   12px;
      padding:     12px 24px;
      border-radius: 10px;
      z-index:     9999;
      text-align:  center;
      max-width:   520px;
      line-height: 1.6;
      box-shadow:  0 4px 24px rgba(0,0,0,0.4);
    `;
    document.body.appendChild(el);
  },

  _hideBanner() {
    const el = document.getElementById('no-camera-banner');
    if (el) el.remove();
    this._bannerShown = false;
  },
};
/**EOF
echo "demo.js fixed - no fake data"
Output

demo.js fixed - no fake data*/