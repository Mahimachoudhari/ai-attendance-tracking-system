from __future__ import annotations
import argparse, asyncio, base64, json, os, sys, time, threading
from datetime import datetime
from typing import Optional
import cv2, numpy as np

WS_BASE      = "ws://localhost:8000"
TARGET_FPS   = 10
JPEG_QUALITY = 70
FRAME_SKIP   = 2
RECONNECT_DELAY = 3
MAX_RECONNECTS  = 20

class CameraReader:
    def __init__(self, source, camera_id: int, gate_label: str):
        self.source = source
        self.camera_id = camera_id
        self.gate_label = gate_label
        self.cap = None
        self.latest_frame: Optional[np.ndarray] = None
        self.running = False
        self._lock = threading.Lock()
        self._thread = None
        self.is_video_file = False
        self.fps_actual = 0.0

    def _parse_source(self):
        s = str(self.source).strip()
        try:
            return int(s)
        except ValueError:
            pass
        return s

    def start(self) -> bool:
        src = self._parse_source()
        self.cap = cv2.VideoCapture(src)
        if isinstance(src, str) and src.startswith("rtsp"):
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            print(f"  ❌ Camera {self.camera_id} open nahi hua: {self.source}")
            return False
        self.is_video_file = isinstance(src, str) and os.path.isfile(src)
        self.fps_actual = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        print(f"  ✅ Camera {self.camera_id} ({self.gate_label}) connected")
        self.running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def _read_loop(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if not ret:
                if self.is_video_file:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    print(f"  ⚠️  Camera {self.camera_id} reconnecting...")
                    time.sleep(2)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self._parse_source())
                    continue
            with self._lock:
                self.latest_frame = frame

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()

def encode_frame(frame: np.ndarray) -> str:
    h, w = frame.shape[:2]
    if w > 960:
        frame = cv2.resize(frame, (960, int(h * 960 / w)))
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return base64.b64encode(buf).decode("ascii")

def overlay_info(frame: np.ndarray, gate_label: str, cam_id: int) -> np.ndarray:
    out = frame.copy()
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(out, f"CAM {cam_id} | {gate_label}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 100), 2, cv2.LINE_AA)
    cv2.putText(out, ts, (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)
    return out

async def stream_camera(camera_reader: CameraReader, camera_id: int, gate_label: str) -> None:
    import websockets
    url = f"{WS_BASE}/ws/camera/{camera_id}"
    interval = 1.0 / TARGET_FPS
    frame_idx = 0
    reconnect_cnt = 0
    print(f"\n[CAM {camera_id}] Connecting to backend: {url}")

    while reconnect_cnt < MAX_RECONNECTS:
        try:
            async with websockets.connect(url, ping_interval=None, ping_timeout=None, max_size=10*1024*1024) as ws:
                print(f"[CAM {camera_id}] ✅ Backend WebSocket connected ({gate_label})")
                reconnect_cnt = 0
                while True:
                    t_start = time.monotonic()
                    frame = camera_reader.get_frame()
                    if frame is None:
                        await asyncio.sleep(0.05)
                        continue
                    frame_idx += 1
                    if frame_idx % FRAME_SKIP != 0:
                        await asyncio.sleep(max(0, interval - (time.monotonic() - t_start)))
                        continue
                    frame = overlay_info(frame, gate_label, camera_id)
                    await ws.send(json.dumps({"type": "frame", "data": encode_frame(frame)}))
                    try:
                        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
                        for evt in resp.get("events", []):
                            print(f"  [CAM {camera_id}] ✅ {evt['gate'].upper()}: {evt['employee_name']} ({evt['employee_code']})  confidence={evt['confidence']:.2%}  {datetime.now().strftime('%H:%M:%S')}")
                    except asyncio.TimeoutError:
                        pass
                    await asyncio.sleep(max(0, interval - (time.monotonic() - t_start)))

        except (websockets.exceptions.ConnectionClosed, OSError, ConnectionRefusedError) as e:
            reconnect_cnt += 1
            print(f"[CAM {camera_id}] ⚠️ Reconnect {reconnect_cnt}/{MAX_RECONNECTS} in {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)
        except Exception as e:
            print(f"[CAM {camera_id}] ❌ Error: {e}")
            reconnect_cnt += 1
            await asyncio.sleep(RECONNECT_DELAY)

    print(f"[CAM {camera_id}] ❌ Max reconnects reached.")

async def main(args) -> None:
    global WS_BASE
    WS_BASE = args.server.rstrip("/")
    print("=" * 60)
    print("  AI Attendance System — Real Camera Stream")
    print(f"  Backend: {WS_BASE}")
    print("=" * 60)
    cameras, tasks = [], []

    entry_reader = CameraReader(args.entry, camera_id=1, gate_label="ENTRY GATE")
    if not entry_reader.start():
        print(f"❌ Entry camera nahi mila: {args.entry}")
        sys.exit(1)
    cameras.append(entry_reader)
    tasks.append(stream_camera(entry_reader, 1, "ENTRY GATE"))

    if not args.no_exit:
        exit_reader = CameraReader(args.exit, camera_id=2, gate_label="EXIT GATE")
        if exit_reader.start():
            cameras.append(exit_reader)
            tasks.append(stream_camera(exit_reader, 2, "EXIT GATE"))
        else:
            print("⚠️  Exit camera nahi mila — sirf entry chal raha hai")

    print(f"\n  {len(cameras)} camera(s) active")
    print(f"  Dashboard: http://localhost:8000")
    print(f"\n  Ctrl+C dabao band karne ke liye...\n")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for cam in cameras:
            cam.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real camera se live attendance")
    parser.add_argument("--entry",   default="0",                    help="Entry camera (0,1,2 / rtsp:// / file.mp4)")
    parser.add_argument("--exit",    default="1",                    help="Exit camera")
    parser.add_argument("--no-exit", action="store_true",            help="Sirf entry camera")
    parser.add_argument("--server",  default="ws://localhost:8000",  help="Backend URL")
    parser.add_argument("--fps",     type=int, default=10)
    parser.add_argument("--quality", type=int, default=70)
    args = parser.parse_args()
    TARGET_FPS   = args.fps
    JPEG_QUALITY = args.quality
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nCamera stream band ho gaya.")
