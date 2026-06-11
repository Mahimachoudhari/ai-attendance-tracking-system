/**
 * camera.js
 * ---------
 * Listens for 'camera_frame' CustomEvents dispatched by websocket.js
 * and renders annotated frames into the two camera feed <img> elements.
 *
 * Also updates per-camera HUD pills:
 *   fps  |  face count  |  processing time  |  timestamp
 *
 * Shows / hides the "no-signal" placeholder automatically.
 */

'use strict';

const Camera = {

  // ── Per-camera state ─────────────────────────────────────────
  _cams: {
    1: { frames: 0, lastFpsTick: 0 },
    2: { frames: 0, lastFpsTick: 0 },
  },

  // ── DOM refs (populated in init) ─────────────────────────────
  _el: {},

  init() {
    this._el = {
      // Camera 1
      img1:     document.getElementById('cam1-img'),
      ns1:      document.getElementById('cam1-ns'),
      fps1:     document.getElementById('c1-fps'),
      faces1:   document.getElementById('c1-faces'),
      ms1:      document.getElementById('c1-ms'),
      time1:    document.getElementById('c1-time'),
      // Camera 2
      img2:     document.getElementById('cam2-img'),
      ns2:      document.getElementById('cam2-ns'),
      fps2:     document.getElementById('c2-fps'),
      faces2:   document.getElementById('c2-faces'),
      ms2:      document.getElementById('c2-ms'),
      time2:    document.getElementById('c2-time'),
    };

    window.addEventListener('camera_frame', (e) => this._onFrame(e.detail));
  },

  // ── Handle incoming frame ─────────────────────────────────────
  _onFrame({ cameraId, data, procMs, faceCount }) {
    const id = cameraId === 1 ? '1' : '2';
    const el = this._el;

    // Swap no-signal → live image
    const img = el[`img${id}`];
    const ns  = el[`ns${id}`];
    if (img && data) {
      img.src          = `data:image/jpeg;base64,${data}`;
      img.style.display = 'block';
      if (ns) ns.style.display = 'none';
    }

    // FPS counter (calculated per-second)
    const state = this._cams[cameraId];
    state.frames++;
    const now = performance.now();
    if (now - state.lastFpsTick >= 1000) {
      const fpsEl = el[`fps${id}`];
      if (fpsEl) fpsEl.textContent = `${state.frames} fps`;
      state.frames     = 0;
      state.lastFpsTick = now;
    }

    // HUD pills
    const facesEl = el[`faces${id}`];
    const msEl    = el[`ms${id}`];
    const timeEl  = el[`time${id}`];

    if (facesEl) facesEl.textContent = `${faceCount} faces`;
    if (msEl)    msEl.textContent    = `${procMs} ms`;
    if (timeEl)  timeEl.textContent  = new Date().toLocaleTimeString('en-IN', { hour12: false });
  },
};