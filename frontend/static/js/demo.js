/**
 * demo.js
 * -------
 * Demo / fallback mode.
 *
 * When the backend is available but no camera is streaming frames,
 * this module fires synthetic attendance events at random intervals
 * so the dashboard looks live during a presentation.
 *
 * It fires a burst of 4 events on load, then one every 3.5–8 s.
 *
 * To DISABLE demo mode, remove the <script> tag for this file
 * from dashboard.html, or set:
 *   window.DEMO_MODE = false;
 * before the scripts load.
 */

'use strict';

const Demo = {

  NAMES: [
    'Aarav Sharma',    'Priya Patel',    'Rohan Mehta',
    'Ananya Singh',    'Vikram Joshi',   'Neha Gupta',
    'Arjun Verma',     'Pooja Nair',     'Karan Malhotra',
    'Divya Rao',       'Siddharth Kumar','Kavya Reddy',
    'Aditya Iyer',     'Shreya Pillai',  'Rahul Das',
    'Ishaan Chopra',   'Meera Menon',    'Varun Bhatt',
    'Riya Kapoor',     'Akash Tiwari',
  ],

  DEPTS: ['Engineering','HR','Operations','Finance','Logistics','Security'],

  _idx:   0,
  _timer: null,

  init() {
    // Respect opt-out
    if (window.DEMO_MODE === false) return;

    // Burst: 4 events, 350 ms apart
    for (let i = 0; i < 4; i++) {
      setTimeout(() => this._fire(), 800 + i * 350);
    }

    // Trickle: random interval
    this._schedule();
  },

  _schedule() {
    const delay = 3500 + Math.random() * 4500;
    this._timer = setTimeout(() => {
      this._fire();
      this._schedule();
    }, delay);
  },

  _fire() {
    const name = this.NAMES[this._idx % this.NAMES.length];
    this._idx++;

    // Every 4th event is an exit; every 15th is a security alert
    let gate = 'entry';
    if (this._idx % 15 === 0) gate = 'alert';
    else if (this._idx % 4 === 0) gate = 'exit';

    const payload = {
      type:          'attendance_event',
      gate,
      employee_name: gate === 'alert' ? '⚠ Unknown Person' : name,
      employee_code: `ACME${String(this._idx).padStart(4, '0')}`,
      confidence:    parseFloat((0.88 + Math.random() * 0.11).toFixed(3)),
      timestamp:     new Date().toISOString(),
      proc_ms:       Math.floor(1700 + Math.random() * 700),
      department:    this.DEPTS[this._idx % this.DEPTS.length],
    };

    if (gate === 'alert') {
      window.dispatchEvent(new CustomEvent('security_alert', { detail: {
        type:       'security_alert',
        alert:      'unknown_person',
        camera_id:  (this._idx % 2) + 1,
        confidence: payload.confidence,
        timestamp:  payload.timestamp,
      }}));
    } else {
      window.dispatchEvent(new CustomEvent('attendance_event', { detail: payload }));
    }
  },
};