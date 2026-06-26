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


def _publish(source, act, reg, pos, loco, ov):
    """Snapshot the current readings for the web view. Called after the terminal print; changes nothing there."""
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
        "human": humanize(act, reg, pos, loco, ov),
    })


HTML_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SynHeart — kinematic state</title>
<style>
  :root { --bg:#0e0e0f; --fg:#f2f2f0; --muted:#7a7a7a; --line:#222; }
  html,body { height:100%; margin:0; }
  body { background:var(--bg); color:var(--fg); display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  .card { text-align:center; padding:2rem; max-width:660px; width:100%; }
  .icon { font-size:5rem; line-height:1; filter:grayscale(1); opacity:.92; }
  .sentence { font-size:2.3rem; font-weight:300; letter-spacing:.2px; margin:1.4rem 0 .5rem;
              transition:opacity .25s; min-height:1.3em; }
  .conf { font-size:.95rem; color:var(--muted); min-height:1.2em; }
  .secondary { margin-top:2.2rem; padding-top:1rem; border-top:1px solid var(--line);
               font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.8rem; color:var(--muted); }
  .dim { opacity:.4; }
</style></head>
<body><div class="card">
  <div id="icon" class="icon">…</div>
  <div id="sentence" class="sentence dim">Connecting…</div>
  <div id="conf" class="conf"></div>
  <div id="secondary" class="secondary"></div>
</div>
<script>
  const ICON = {walking:"🚶",running:"🏃",cycling:"🚴",vehicle:"🚗",lying:"🛌",
                sitting:"🪑",standing:"🧍",restless:"🤚",still:"⏸",unknown:"…"};
  async function tick(){
    const sEl=document.getElementById('sentence'), iEl=document.getElementById('icon'),
          cEl=document.getElementById('conf'), secEl=document.getElementById('secondary');
    try{
      const s = await (await fetch('/state',{cache:'no-store'})).json();
      if(!s.ready){ iEl.textContent='…'; sEl.textContent='Calibrating — hold still…';
        sEl.className='sentence dim'; cEl.textContent=''; secEl.textContent='waiting for sensors'; return; }
      const h=s.human;
      iEl.textContent=ICON[h.icon]||'…';
      sEl.textContent=h.sentence; sEl.className='sentence';
      cEl.textContent = h.confidence_word==='low' ? 'low confidence — still settling'
                      : h.confidence_word==='uncertain' ? 'uncertain' : '';
      secEl.textContent=h.secondary;
    }catch(e){ sEl.textContent='Disconnected…'; sEl.className='sentence dim'; cEl.textContent=''; }
  }
  setInterval(tick,1000); tick();
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
