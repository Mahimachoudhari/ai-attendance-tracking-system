/**
 * clock.js
 * --------
 * Updates the header clock (#clock) every second.
 * Simple, self-contained, no dependencies.
 */

'use strict';

const Clock = {

  _el:    null,
  _timer: null,

  init() {
    this._el = document.getElementById('clock');
    if (!this._el) return;
    this._tick();
    this._timer = setInterval(() => this._tick(), 1000);
  },

  _tick() {
    if (!this._el) return;
    this._el.textContent = new Date().toLocaleTimeString('en-IN', { hour12: false });
  },
};