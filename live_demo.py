import cv2, numpy as np, psycopg2, time, asyncio, base64, json, threading
from datetime import datetime
from insightface.app import FaceAnalysis
import websockets

# ── Config ─────────────────────────────────────────────────────
DB_CONFIG    = dict(host='localhost', dbname='attendance_db',
                    user='postgres', password='Mahima@123')
VIDEO_SOURCE = r'demo\test_entry.mp4'   # 0 = webcam
GATE_TYPE    = 'entry'
COMPANY_ID   = 1
THRESHOLD    = 0.28
DASH_WS_URL  = 'ws://localhost:8000/ws/dashboard'

# ── Colors ─────────────────────────────────────────────────────
GREEN = (0, 210, 70)
RED   = (0, 0, 200)
WHITE = (255, 255, 255)
DARK  = (12, 18, 26)
CYAN  = (200, 200, 0)

# ── Model load ──────────────────────────────────────────────────
print("Model load ho raha hai...")
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(320, 320))
print("Model ready!\n")

# ── DB ─────────────────────────────────────────────────────────
conn = psycopg2.connect(**DB_CONFIG)
cur  = conn.cursor()
cur.execute("""SELECT id, employee_code, name, department, face_embedding
               FROM employees WHERE face_embedding IS NOT NULL""")
employees = []
for r in cur.fetchall():
    emb = np.array(r[4], dtype=np.float32)
    emb /= np.linalg.norm(emb) + 1e-8
    employees.append({'id':r[0],'code':r[1],'name':r[2],
                      'dept':r[3] or '','emb':emb})
cur.close()
print(f"{len(employees)} employees loaded\n")

# ── State ──────────────────────────────────────────────────────
marked   = set()
events   = []
count    = 0
cooldown = {}

# ── Dashboard WS events queue ───────────────────────────────────
event_queue = []
event_lock  = threading.Lock()

# ── Dashboard WebSocket thread ──────────────────────────────────
def ws_sender():
    """Background thread — dashboard ko events bhejta hai"""
    async def _send():
        while True:
            try:
                async with websockets.connect(
                    DASH_WS_URL,
                    ping_interval=None,
                    ping_timeout=None
                ) as ws:
                    print("Dashboard connected!\n")
                    while True:
                        with event_lock:
                            pending = list(event_queue)
                            event_queue.clear()
                        for evt in pending:
                            try:
                                await ws.send(json.dumps(evt))
                            except Exception:
                                pass
                        await asyncio.sleep(0.1)
            except Exception:
                await asyncio.sleep(2)   # reconnect

    asyncio.run(_send())

# Start WS thread
ws_thread = threading.Thread(target=ws_sender, daemon=True)
ws_thread.start()

# ── Helpers ─────────────────────────────────────────────────────
def best_match(emb):
    emb = emb / (np.linalg.norm(emb) + 1e-8)
    best, bsim = None, -1
    for e in employees:
        s = float(np.dot(emb, e['emb']))
        if s > bsim:
            bsim, best = s, e
    return best, bsim


def mark(emp, sim):
    global count
    now = time.time()
    # Debounce 8 seconds
    if now - cooldown.get(emp['id'], 0) < 30:
        return
    cooldown[emp['id']] = now

    ts = datetime.now()

    if emp['id'] not in marked:
        marked.add(emp['id'])
        count += 1
        c = conn.cursor()
        c.execute("""INSERT INTO attendance_events
            (employee_id,employee_name,company_id,camera_id,
             event_type,timestamp,confidence_score)
            VALUES (%s,%s,%s,1,%s,%s,%s)""",
            (emp['id'],emp['name'],COMPANY_ID,GATE_TYPE,ts,sim))
        c.execute("""INSERT INTO attendance
            (employee_id,employee_name,company_id,date,entry_time,status)
            VALUES (%s,%s,%s,CURRENT_DATE,%s,'present')
            ON CONFLICT (employee_id,date) DO NOTHING""",
            (emp['id'],emp['name'],COMPANY_ID,ts))
        conn.commit()
        c.close()

    # Dashboard event push
    evt = {
        "type":          "attendance_event",
        "gate":          GATE_TYPE,
        "employee_name": emp['name'],
        "employee_code": emp['code'],
        "confidence":    round(sim, 3),
        "timestamp":     ts.isoformat(),
        "proc_ms":       0,
    }
    with event_lock:
        event_queue.append(evt)

    events.insert(0, {
        'name': emp['name'], 'code': emp['code'],
        'dept': emp['dept'], 'sim': sim,
        'time': ts.strftime('%H:%M:%S')
    })
    if len(events) > 6:
        events.pop()

    print(f"  ENTRY: {emp['name']:<28} ({emp['code']})  {sim:.0%}  {ts.strftime('%H:%M:%S')}")


def draw(frame, results):
    W, H   = frame.shape[1], frame.shape[0]
    PANEL  = 250
    canvas = np.zeros((H, W + PANEL, 3), dtype=np.uint8)
    canvas[:, :W] = frame

    # Face boxes
    for (x1,y1,x2,y2,name,dept,sim,ok) in results:
        c = GREEN if ok else RED
        cv2.rectangle(canvas,(x1,y1),(x2,y2),c,2)
        # Corners
        L = 14
        for px,py,dx,dy in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
            cv2.line(canvas,(px,py),(px+dx*L,py),c,3)
            cv2.line(canvas,(px,py),(px,py+dy*L),c,3)
        # Label
        lbl = f"{name[:22]}  {sim:.0%}"
        cv2.rectangle(canvas,(x1,y2),(x2,y2+22),DARK,-1)
        cv2.putText(canvas,lbl,(x1+4,y2+15),
                    cv2.FONT_HERSHEY_SIMPLEX,0.42,c,1,cv2.LINE_AA)
        if ok and dept:
            cv2.rectangle(canvas,(x1,y2+22),(x2,y2+36),DARK,-1)
            cv2.putText(canvas,dept,(x1+4,y2+33),
                        cv2.FONT_HERSHEY_SIMPLEX,0.34,(160,160,160),1,cv2.LINE_AA)

    # Top bar
    cv2.rectangle(canvas,(0,0),(W,36),DARK,-1)
    cv2.line(canvas,(0,36),(W,36),GREEN,1)
    cv2.putText(canvas,"AI ATTENDANCE SYSTEM",(10,24),
                cv2.FONT_HERSHEY_SIMPLEX,0.62,WHITE,1,cv2.LINE_AA)
    cv2.putText(canvas,f"ENTRY GATE | {len(results)} face(s)",(10,H-8),
                cv2.FONT_HERSHEY_SIMPLEX,0.36,(130,130,130),1,cv2.LINE_AA)

    # Right panel
    px = W
    canvas[:,px:] = (14,20,28)
    cv2.line(canvas,(px,0),(px,H),GREEN,1)

    cv2.putText(canvas,"LIVE TRACKING",(px+10,28),
                cv2.FONT_HERSHEY_SIMPLEX,0.52,GREEN,1,cv2.LINE_AA)
    cv2.line(canvas,(px+8,34),(px+PANEL-8,34),(25,35,45),1)

    # Counter
    cv2.putText(canvas,"ENTERED",(px+10,58),
                cv2.FONT_HERSHEY_SIMPLEX,0.38,(140,140,140),1,cv2.LINE_AA)
    cv2.putText(canvas,str(count),(px+18,110),
                cv2.FONT_HERSHEY_SIMPLEX,2.4,GREEN,3,cv2.LINE_AA)
    cv2.putText(canvas,f"/ {len(employees)}",(px+18,128),
                cv2.FONT_HERSHEY_SIMPLEX,0.36,(120,120,120),1,cv2.LINE_AA)

    # Progress bar
    bar_w = PANEL - 20
    prog  = int((count / max(len(employees),1)) * bar_w)
    cv2.rectangle(canvas,(px+10,136),(px+10+bar_w,142),(25,35,45),-1)
    if prog > 0:
        cv2.rectangle(canvas,(px+10,136),(px+10+prog,142),GREEN,-1)

    # Time
    cv2.putText(canvas,datetime.now().strftime("%H:%M:%S"),(px+10,164),
                cv2.FONT_HERSHEY_SIMPLEX,0.52,(200,200,200),1,cv2.LINE_AA)
    cv2.putText(canvas,datetime.now().strftime("%d %b %Y"),(px+10,180),
                cv2.FONT_HERSHEY_SIMPLEX,0.36,(120,120,120),1,cv2.LINE_AA)

    cv2.line(canvas,(px+8,188),(px+PANEL-8,188),(25,35,45),1)
    cv2.putText(canvas,"RECENT",(px+10,204),
                cv2.FONT_HERSHEY_SIMPLEX,0.36,(140,140,140),1,cv2.LINE_AA)

    # Recent list
    for i,ev in enumerate(events[:5]):
        y = 220 + i*52
        cv2.rectangle(canvas,(px+8,y),(px+PANEL-8,y+48),(16,24,34),-1)
        cv2.line(canvas,(px+8,y),(px+8,y+48),GREEN,2)
        nm = ev['name'][:20]+'..' if len(ev['name'])>20 else ev['name']
        cv2.putText(canvas,nm,(px+14,y+14),
                    cv2.FONT_HERSHEY_SIMPLEX,0.4,(230,230,230),1,cv2.LINE_AA)
        cv2.putText(canvas,ev['code'],(px+14,y+28),
                    cv2.FONT_HERSHEY_SIMPLEX,0.34,(0,190,170),1,cv2.LINE_AA)
        cv2.putText(canvas,f"{ev['time']}  {ev['sim']:.0%}",(px+14,y+42),
                    cv2.FONT_HERSHEY_SIMPLEX,0.32,GREEN,1,cv2.LINE_AA)

    # Dashboard hint
    cv2.putText(canvas,"Dashboard:",(px+10,H-36),
                cv2.FONT_HERSHEY_SIMPLEX,0.34,(100,100,100),1,cv2.LINE_AA)
    cv2.putText(canvas,"localhost:8000",(px+10,H-20),
                cv2.FONT_HERSHEY_SIMPLEX,0.36,CYAN,1,cv2.LINE_AA)

    return canvas


# ── Main ────────────────────────────────────────────────────────
cap = cv2.VideoCapture(VIDEO_SOURCE)
if not cap.isOpened():
    print(f"ERROR: {VIDEO_SOURCE} open nahi hua!")
    exit(1)

cv2.namedWindow("AI Attendance System", cv2.WINDOW_NORMAL)
cv2.resizeWindow("AI Attendance System", 1080, 580)

W, H     = 820, 520
fnum     = 0
curr     = []
fps_t    = time.time()
fps_val  = 0

print("="*55)
print("  Video chal rahi hai!")
print("  Dashboard: http://localhost:8000")
print("  Q dabao band karne ke liye")
print("="*55 + "\n")

while True:
    ret, frame = cap.read()
    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue

    fnum += 1

    # FPS
    if fnum % 30 == 0:
        fps_val = 30 / (time.time() - fps_t + 0.001)
        fps_t   = time.time()

    # Resize — HIGH QUALITY
    frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_LINEAR)

    # Detection har 6th frame
    if fnum % 6 == 0:
        small = cv2.resize(frame, (W//2, H//2))
        faces = app.get(small)
        curr  = []
        for f in faces:
            if f.det_score < 0.45 or f.embedding is None:
                continue
            x1,y1,x2,y2 = [int(v*2) for v in f.bbox]
            x1,y1 = max(0,x1), max(0,y1)
            x2,y2 = min(W,x2), min(H,y2)
            emp, sim = best_match(f.embedding)
            if sim >= THRESHOLD and emp:
                mark(emp, sim)
                curr.append((x1,y1,x2,y2,emp['name'],emp['dept'],sim,True))
            else:
                curr.append((x1,y1,x2,y2,'Unknown','',sim,False))

    # Draw + show
    canvas = draw(frame, curr)
    cv2.putText(canvas, f"FPS:{fps_val:.0f}", (W-60,24),
                cv2.FONT_HERSHEY_SIMPLEX,0.45,GREEN,1,cv2.LINE_AA)
    cv2.imshow("AI Attendance System", canvas)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
conn.close()
cv2.destroyAllWindows()
print(f"\nTotal entered: {count}")
