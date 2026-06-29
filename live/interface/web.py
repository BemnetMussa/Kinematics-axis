"""User-facing web view -- PRESENTATION ONLY. Reflects the readings the pipeline already
produced; no new classification, no new scores. A tiny HTTP server in a background thread
serves the page and a /state JSON the page polls every ~1s.

Pure refactor: moved verbatim from the original live_hsi.py.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.config import WEB_PORT

_LATEST = {"ready": False}                          # latest reading set, shared with the web thread
_LATEST_LOCK = threading.Lock()


def _set_latest(snap):
    with _LATEST_LOCK:
        _LATEST.clear(); _LATEST.update(snap)


def _get_latest():
    with _LATEST_LOCK:
        return dict(_LATEST)


def _secondary(act, reg, pos, loco):
    """The small for-the-curious line: the individual verdicts, verbatim."""
    rs = reg.get("score")
    return "  ·  ".join([
        f"activity {act.get('label') or '—'}",
        f"regularity {rs:.2f}" if rs is not None else "regularity —",
        f"posture {(pos.get('label') or '—').replace('_', ' ')}",
        f"locomotion {(loco.get('label') or '—').replace('_', ' ')}",
    ])


# Low-confidence phrasings for the activity-driven situations (where a numeric margin exists).
_LOW_PHRASE = {"walking": "Possibly walking…", "running": "Possibly running…", "cycling": "Possibly cycling…"}


def humanize(act, reg, pos, loco, ov):
    """Pure lookup: turn the existing verdicts into one plain sentence + an honest confidence word
    + an icon key. No thresholds, no scoring -- it only reads what the axes already decided."""
    if ov is None:                                  # a core axis is null/unavailable
        return {"sentence": "Not sure yet.", "confidence_word": "uncertain",
                "icon": "unknown", "secondary": _secondary(act, reg, pos, loco)}
    sit = ov["situation"]
    steady = reg.get("score") is not None and reg["score"] >= 0.5
    if sit == "in vehicle":
        sentence, icon = "You're in a vehicle.", "vehicle"
    elif sit == "resting (lying)":
        sentence, icon = "Lying down.", "lying"
    elif sit == "running":
        sentence, icon = "You're running.", "running"
    elif sit == "walking":
        sentence, icon = ("You're walking — calm, steady pace." if steady else "You're walking."), "walking"
    elif sit == "cycling":
        sentence, icon = "You're cycling.", "cycling"
    elif sit == "restless":
        sentence, icon = "Still, but a little restless.", "restless"
    else:                                           # "still"
        p = pos.get("label")
        sentence, icon = ({"sitting": ("Sitting still.", "sitting"),
                           "standing": ("Standing still.", "standing")}).get(p, ("Still.", "still"))
    # Confidence, stated honestly: hedge only the activity-driven calls, where a margin proxy exists.
    word = "high"
    conf = act.get("conf")
    if sit in _LOW_PHRASE and conf is not None and conf < 0.65:
        word, sentence = "low", _LOW_PHRASE[sit]
    return {"sentence": sentence, "confidence_word": word, "icon": icon,
            "secondary": _secondary(act, reg, pos, loco)}


def _publish(source, act, reg, pos, loco, ov, mag):
    """Snapshot the current readings for the web view. Called after the terminal print; changes nothing there."""
    # Extract high-ROI numeric features for live graphing
    # Note: these are proxies derived from the axis notes or calculated again if needed.
    # For efficiency in the presentation layer, we just extract what we need.
    
    metrics = {
        "move": float(act.get("move") or pos.get("move") or 0.0),
        "energy": float(act.get("energy") or 1.0),
        "gyro": float(act.get("gyro") or 0.0),
        "tilt": float(pos.get("tilt") or 0.0),
        "mag_dist": float(mag.get("dmag") or 0.0) if mag else 0.0,
        "speed": 0.0
    }
    
    # Check for speed in source/window if we want to be explicit, 
    # but here we can just check if source.get_window returned it indirectly.
    # Actually, dashboard.py already calculated speed_kmh. 
    # To keep it simple, I'll let dashboard pass it or I'll extract it from source here.
    from interface.sources import get_sensor_window
    w = get_sensor_window(1.0) # short window for live speed
    if w.get("speed") is not None:
        metrics["speed"] = float(np.mean(w["speed"])) * 3.6

    _set_latest({
        "ready": True,
        "t": round(source.now(), 1),
        "readings": {
            "activity":   {"label": act.get("label"), "conf": act.get("conf")},
            "regularity": {"score": reg.get("score"), "reason": reg.get("reason")},
            "postural":   {"label": pos.get("label")},
            "locomotion": {"label": loco.get("label")},
            "overall":    ({"situation": ov["situation"], "exertion": ov["exertion"]} if ov else None),
        },
        "metrics": metrics,
        "human": humanize(act, reg, pos, loco, ov),
    })


HTML_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SynHeart — Kinematic Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
  
  :root { 
    --bg: #050506; 
    --glass: rgba(255, 255, 255, 0.03);
    --glass-border: rgba(255, 255, 255, 0.1);
    --fg: #ffffff; 
    --muted: #a0a0a0; 
    --accent: #3a86ff;
    --danger: #ff006e;
    --success: #06d6a0;
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: var(--bg); color: var(--fg); font-family: 'Outfit', sans-serif; overflow-x: hidden; }
  
  body {
    display: flex;
    flex-direction: column;
    padding: 2rem;
    gap: 2rem;
    align-items: center;
    background: radial-gradient(circle at top right, #1a1a2e 0%, #050506 100%);
  }

  .container {
    max-width: 1000px;
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1.5fr;
    gap: 1.5rem;
  }

  @media (max-width: 800px) {
    .container { grid-template-columns: 1fr; }
  }

  .card {
    background: var(--glass);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--glass-border);
    border-radius: 24px;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
    transition: transform 0.3s ease;
  }

  .status-card { text-align: center; min-height: 400px; }
  
  .icon { 
    font-size: 6rem; 
    margin-bottom: 1rem;
    filter: drop-shadow(0 0 20px rgba(58, 134, 255, 0.3));
    animation: pulse 4s infinite ease-in-out;
  }

  @keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.05); opacity: 0.8; }
  }

  .sentence { 
    font-size: 2.2rem; 
    font-weight: 600; 
    margin: 0.5rem 0;
    background: linear-gradient(to right, #fff, #a0a0a0);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .conf { font-size: 1rem; color: var(--muted); margin-bottom: 2rem; text-transform: uppercase; letter-spacing: 2px; }

  .charts-container {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .chart-card {
    height: 200px;
    padding: 1rem 1.5rem;
  }

  .chart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }

  .chart-title { font-size: 0.8rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
  .chart-value { font-size: 1.2rem; font-weight: 600; color: var(--accent); }

  .secondary {
    grid-column: 1 / -1;
    font-family: 'DM Mono', monospace;
    font-size: 0.8rem;
    color: rgba(255,255,255,0.3);
    text-align: center;
    margin-top: 1rem;
  }

  .dim { opacity: 0.3; filter: grayscale(1); }

  canvas { width: 100% !important; height: 120px !important; }

</style></head>
<body>
  <div class="container">
    <div class="card status-card" id="main-status">
      <div id="icon" class="icon">🛰️</div>
      <div id="sentence" class="sentence">Connecting...</div>
      <div id="conf" class="conf">SYSTEMS INITIALIZING</div>
      <div id="indicator" style="display:flex; justify-content:center; gap:8px;">
         <div class="dot" style="width:8px; height:8px; background:var(--accent); border-radius:50%; animation: blink 1s infinite;"></div>
      </div>
    </div>

    <div class="charts-container">
      <div class="card chart-card">
        <div class="chart-header">
          <span class="chart-title">Movement Magnitude</span>
          <span id="v-move" class="chart-value">0.00g</span>
        </div>
        <canvas id="chart-move"></canvas>
      </div>

      <div class="card chart-card">
        <div class="chart-header">
          <span class="chart-title">Postural Tilt</span>
          <span id="v-tilt" class="chart-value">0°</span>
        </div>
        <canvas id="chart-tilt"></canvas>
      </div>
      
      <div class="card chart-card">
        <div class="chart-header">
          <span class="chart-title">Magnetic Disturbance</span>
          <span id="v-mag" class="chart-value">0.0µT</span>
        </div>
        <canvas id="chart-mag"></canvas>
      </div>

      <div class="card chart-card">
        <div class="chart-header">
          <span class="chart-title">Ground Speed</span>
          <span id="v-speed" class="chart-value">0 km/h</span>
        </div>
        <canvas id="chart-speed"></canvas>
      </div>
    </div>

    <div id="secondary" class="secondary"></div>
  </div>

<script>
  const ICON = {walking:"🚶",running:"🏃",cycling:"🚴",vehicle:"🚗",lying:"🛌",
                sitting:"🪑",standing:"🧍",restless:"🤚",still:"⏸",unknown:"🛰️"};
  
  const ctx_move = document.getElementById('chart-move').getContext('2d');
  const ctx_tilt = document.getElementById('chart-tilt').getContext('2d');
  const ctx_mag = document.getElementById('chart-mag').getContext('2d');
  const ctx_speed = document.getElementById('chart-speed').getContext('2d');

  const chartCfg = (color) => ({
    type: 'line',
    data: {
      labels: Array(20).fill(''),
      datasets: [{
        data: Array(20).fill(0),
        borderColor: color,
        borderWidth: 3,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
        backgroundColor: color + '15'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { 
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: 'rgba(255,255,255,0.2)', font: { size: 10 } }
        }
      },
      animation: { duration: 400 }
    }
  });

  const c_move = new Chart(ctx_move, chartCfg('#3a86ff'));
  const c_tilt = new Chart(ctx_tilt, chartCfg('#06d6a0'));
  const c_mag = new Chart(ctx_mag, chartCfg('#ff006e'));
  const c_speed = new Chart(ctx_speed, chartCfg('#ffbe0b'));

  function updateChart(chart, val) {
    chart.data.datasets[0].data.push(val);
    chart.data.datasets[0].data.shift();
    chart.update('none');
  }

  async function tick(){
    const sEl=document.getElementById('sentence'), iEl=document.getElementById('icon'),
          cEl=document.getElementById('conf'), secEl=document.getElementById('secondary');
    
    try {
      const resp = await fetch('/state',{cache:'no-store'});
      const s = await resp.json();
      
      if(!s.ready){ 
        iEl.textContent='🛰️'; 
        sEl.textContent='Calibrating...';
        sEl.parentElement.classList.add('dim');
        return; 
      }
      
      sEl.parentElement.classList.remove('dim');
      const h=s.human;
      const m=s.metrics;
      
      iEl.textContent=ICON[h.icon]||'🛰️';
      sEl.textContent=h.sentence;
      cEl.textContent = h.confidence_word==='low' ? 'Low Confidence — Settling'
                      : h.confidence_word==='uncertain' ? 'Uncertain State' : 'Confident Signal';
      
      secEl.textContent=h.secondary;
      
      // Update values
      document.getElementById('v-move').textContent = m.move.toFixed(2) + 'g';
      document.getElementById('v-tilt').textContent = m.tilt.toFixed(0) + '°';
      document.getElementById('v-mag').textContent = m.mag_dist.toFixed(1) + 'µT';
      document.getElementById('v-speed').textContent = m.speed.toFixed(1) + ' km/h';
      
      // Update charts
      updateChart(c_move, m.move);
      updateChart(c_tilt, m.tilt);
      updateChart(c_mag, m.mag_dist);
      updateChart(c_speed, m.speed);

    } catch(e) { 
      sEl.textContent='Disconnected'; 
      sEl.parentElement.classList.add('dim');
    }
  }
  
  setInterval(tick, 1000); 
  tick();
</script></body></html>"""


class _ViewHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):                      # silence access logs -> keep the terminal clean
        pass

    def _send(self, body, ctype):
        b = body.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try:
            self.wfile.write(b)
        except BrokenPipeError:
            pass

    def do_GET(self):
        if self.path.startswith("/state"):
            self._send(json.dumps(_get_latest()), "application/json")
        else:
            self._send(HTML_PAGE, "text/html; charset=utf-8")


def start_web(port=WEB_PORT):
    """Start the view server in a daemon thread so it never blocks the sensor loop."""
    srv = ThreadingHTTPServer(("0.0.0.0", port), _ViewHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
