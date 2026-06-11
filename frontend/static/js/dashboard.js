/**
 * dashboard.js
 * ------------
 * Application entry point.
 *
 * Initialises every module in dependency order:
 *   Clock → Stats → Toast → Timeline → Table → Alerts → Camera → WS → Demo
 *
 * Load order in dashboard.html (bottom of <body>):
 *   clock.js  →  stats.js  →  toast.js  →  timeline.js
 *   →  table.js  →  alerts.js  →  camera.js
 *   →  websocket.js  →  demo.js  →  dashboard.js   ← this file last
 */

'use strict';

document.addEventListener('DOMContentLoaded', () => {

  // 1. Clock — no dependencies
  Clock.init();

  // 2. Stats counters — listens to WS events
  Stats.init();

  // 3. Toast notifications — listens to WS events
  Toast.init();

  // 4. Timeline feed — listens to WS events
  Timeline.init();

  // 5. Attendance table — polls API + listens to WS events
  Table.init();

  // 6. Alerts poller — polls /api/alerts + listens to WS events
  Alerts.init();

  // 7. Camera frame renderer — listens to camera_frame events
  Camera.init();

  // 8. WebSocket connections — dispatches all events above
  WS.init();

  // 9. Demo mode — fires synthetic events (safe to remove in production)
  Demo.init();

  console.info('[Dashboard] All modules initialised ✅');
});