"""
demo/run_demo.py
-----------------
Simulates two live gate cameras by reading video files and streaming
base64-encoded frames to the backend via WebSocket.

Works WITHOUT physical cameras — just drop two MP4 files:
  demo/entry_gate.mp4
  demo/exit_gate.mp4

If no MP4 found, falls back to a synthetic colour-noise frame (still exercises
the full pipeline — AI pipeline will use mock detect).

Usage:
  # In terminal 1 — start the backend first
  uvicorn backend.main:app --port 8000

  # In terminal 2
  python demo/run_demo.py

  # Or choose custom videos
  python demo/run_demo.py --entry path/to/entry.mp4 --exit path/to/exit.mp4

Then open:  http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time

import cv2
import numpy as np
import websockets

# ── Defaults ──────────────────────────────────────────────────────────────────
WS_BASE       = "ws://localhost:8000"
DEMO_DIR      = os.path.dirname(os.path.abspath(__file__))
ENTRY_DEFAULT = os.path.join(DEMO_DIR, "entry_gate.mp4")
EXIT_DEFAULT  = os.path.join(DEMO_DIR, "exit_gate.mp4")
TARGET_FPS    = 10        # frames per second sent to server
JPEG_QUALITY  = 65
FRAME_SKIP    = 2         # send every Nth frame from the video


def _make_synthetic_frame(width: int = 640, height: int = 480, label: str = "") -> np.ndarray:
    """Generate a noise frame (for demo when no video file available)."""
    rng   = np.random.default_rng(seed=int(time.time() * 10) % 10000)
    frame = rng.integers(30, 80, (height, width, 3), dtype=np.uint8)
    # Draw a fake "face" rectangle
    cx, cy = width // 2 + rng.integers(-80, 80), height // 2 + rng.integers(-60, 60)
    cv2.rectangle(frame, (cx - 50, cy - 60), (cx + 50, cy + 60), (180, 180, 180), 2)
    cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 100), 2)
    cv2.putText(
        frame, time.strftime("%H:%M:%S"),
        (width - 100, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1,
    )
    return frame


def encode_frame(frame: np.ndarray) -> str:
    """Encode BGR frame as base64 JPEG string."""
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return base64.b64encode(buf).decode("ascii")


async def stream_camera(camera_id: int, video_path: str, gate_label: str) -> None:
    """Stream one camera to the backend WebSocket."""
    url = f"{WS_BASE}/ws/camera/{camera_id}"

    has_video = os.path.isfile(video_path)
    if has_video:
        print(f"[CAM {camera_id}] Using video: {video_path}")
        cap = cv2.VideoCapture(video_path)
    else:
        print(f"[CAM {camera_id}] No video found at {video_path} — using synthetic frames")
        cap = None

    interval   = 1.0 / TARGET_FPS
    frame_idx  = 0
    sent       = 0
    errors     = 0
    MAX_ERRORS = 5

    print(f"[CAM {camera_id}] Connecting to {url} …")

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                print(f"[CAM {camera_id}] ✅  WebSocket connected ({gate_label})")
                errors = 0

                while True:
                    t_start = time.monotonic()

                    # Get frame
                    if cap is not None and cap.isOpened():
                        ret, frame = cap.read()
                        if not ret:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # loop video
                            ret, frame = cap.read()
                        if not ret:
                            frame = _make_synthetic_frame(label=gate_label)
                    else:
                        frame = _make_synthetic_frame(label=gate_label)

                    frame_idx += 1
                    if frame_idx % FRAME_SKIP != 0:
                        await asyncio.sleep(max(0, interval - (time.monotonic() - t_start)))
                        continue

                    # Resize to save bandwidth
                    if frame.shape[1] > 854:
                        frame = cv2.resize(frame, (854, 480))

                    # Overlay camera label + timestamp
                    cv2.putText(
                        frame, f"CAM {camera_id} | {gate_label}",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 100), 2,
                    )
                    cv2.putText(
                        frame, time.strftime("%Y-%m-%d %H:%M:%S"),
                        (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1,
                    )

                    payload = {"type": "frame", "data": encode_frame(frame)}

                    await ws.send(str(__import__("json").dumps(payload)))
                    sent += 1

                    # Read and discard the annotated frame response
                    try:
                        _ = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass

                    elapsed  = time.monotonic() - t_start
                    wait_for = max(0, interval - elapsed)
                    await asyncio.sleep(wait_for)

        except (websockets.exceptions.ConnectionClosed,
                OSError, ConnectionRefusedError) as e:
            errors += 1
            print(f"[CAM {camera_id}] ⚠️  Connection error ({e}). "
                  f"Retry {errors}/{MAX_ERRORS} in 3s …")
            if errors >= MAX_ERRORS:
                print(f"[CAM {camera_id}] ❌  Too many errors, giving up.")
                break
            await asyncio.sleep(3)

    if cap:
        cap.release()


async def main(entry_path: str, exit_path: str) -> None:
    print("=" * 55)
    print("  AI Attendance System — Demo Camera Streamer")
    print(f"  Server: {WS_BASE}")
    print("=" * 55)
    print("  Open http://localhost:8000 to view the dashboard")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    await asyncio.gather(
        stream_camera(1, entry_path, "ENTRY GATE"),
        stream_camera(2, exit_path,  "EXIT GATE"),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Attendance Demo — Camera Streamer")
    parser.add_argument("--entry",  default=ENTRY_DEFAULT, help="Entry gate video path")
    parser.add_argument("--exit",   default=EXIT_DEFAULT,  help="Exit gate video path")
    parser.add_argument("--server", default=WS_BASE,       help="WebSocket server base URL")
    args = parser.parse_args()

    WS_BASE = args.server.rstrip("/")

    try:
        asyncio.run(main(args.entry, args.exit))
    except KeyboardInterrupt:
        print("\nDemo stopped.")