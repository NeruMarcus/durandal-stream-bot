_OVERLAY_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=VT323&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  width:845px;height:230px;
  background:transparent;
  font-family:'VT323',monospace;
  color:#befd00;
  overflow:hidden;
  position:relative;
}
.frame{
  position:absolute;inset:8px;
  border:1px solid #befd00;
  background:rgba(0,0,0,0.85);
  display:flex;flex-direction:column;
  padding:10px 16px 8px;
}
.header{
  display:flex;align-items:center;gap:12px;
  font-size:15px;letter-spacing:0.12em;
  text-transform:uppercase;
  border-bottom:1px solid rgba(190,253,0,0.25);
  padding-bottom:6px;margin-bottom:6px;
  flex-shrink:0;
}
.dot{
  display:inline-block;width:8px;height:8px;
  background:#befd00;border-radius:50%;
  animation:blink 1s step-end infinite;
}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.prefix{color:#ff4444;letter-spacing:0.18em}
.status{color:#befd00;margin-left:auto;font-size:13px;letter-spacing:0.08em}
.emotion-badge{
  font-size:11px;letter-spacing:0.1em;padding:2px 8px;
  border:1px solid;border-radius:2px;text-transform:uppercase;
}
.emotion-sarcastic{color:#ff8800;border-color:#ff8800}
.emotion-angry{color:#ff4444;border-color:#ff4444}
.emotion-mocking{color:#cc66ff;border-color:#cc66ff}
.emotion-calm{color:#66ccff;border-color:#66ccff}
.emotion-neutral{color:#befd00;border-color:#befd00}
.body{
  flex:1;display:flex;align-items:center;
  overflow:hidden;position:relative;
}
.text{
  font-size:clamp(18px,3.6vh,28px);
  line-height:1.3;
  max-height:120px;overflow:hidden;
  word-wrap:break-word;
  text-shadow:0 0 6px rgba(190,253,0,0.3);
  padding:4px 0;
  transition:opacity 0.2s;
}
.text.changed{animation:glitch 0.12s}
@keyframes glitch{
  0%{opacity:0.4;transform:translateX(-1px)}
  50%{opacity:1;transform:translateX(1px)}
  100%{opacity:1;transform:translateX(0)}
}
.idle-text{color:#ff4444;text-shadow:0 0 10px rgba(255,68,68,0.4)}
.footer{
  display:flex;justify-content:space-between;
  font-size:11px;letter-spacing:0.1em;
  color:rgba(190,253,0,0.5);text-transform:uppercase;
  border-top:1px solid rgba(190,253,0,0.15);
  padding-top:4px;margin-top:4px;flex-shrink:0;
}
.crt{
  position:absolute;inset:0;pointer-events:none;z-index:10;
  background:repeating-linear-gradient(
    to bottom,transparent 0,rgba(0,0,0,0.10) 1px,transparent 3px
  );
  opacity:0.6;
}
.corner{position:absolute;width:10px;height:10px;border-color:#befd00;border-style:solid}
.corner.tl{top:6px;left:6px;border-width:1px 0 0 1px}
.corner.tr{top:6px;right:6px;border-width:1px 1px 0 0}
.corner.bl{bottom:6px;left:6px;border-width:0 0 1px 1px}
.corner.br{bottom:6px;right:6px;border-width:0 1px 1px 0}
</style>
</head>
<body>

<div class="frame">
  <div class="header">
    <span class="dot"></span>
    <span class="prefix">// DURANDAL //</span>
    <span class="emotion-badge" id="emotion">NEUTRAL</span>
    <span class="status">COMMENTARY &gt; ONLINE</span>
  </div>
  <div class="body">
    <div class="text" id="text">Загрузка...</div>
  </div>
  <div class="footer">
    <span id="ts">SIGMA-17 // UESC</span>
    <span id="seq">FRAME 0000</span>
  </div>
</div>

<div class="crt"></div>
<div class="corner tl"></div><div class="corner tr"></div>
<div class="corner bl"></div><div class="corner br"></div>

<script>
let prev=''; let seq=0;
function pad(n,w){return String(n).padStart(w,'0')}
async function poll(){
  try{
    const r=await fetch('/state');
    const d=await r.json();
    const el=document.getElementById('text');
    let t=(d.text||'').trim();
    if(!t){t='ОЖИДАНИЕ...';el.className='text idle-text';}
    else{
      seq++;
      if(t!==prev){el.className='text changed';setTimeout(()=>el.className='text',250);}
      else el.className='text';
    }
    el.textContent=t;
    document.getElementById('seq').textContent='FRAME '+pad(seq,4);
    if(d.emotion){
      const badge=document.getElementById('emotion');
      badge.textContent=d.emotion.toUpperCase();
      badge.className='emotion-badge emotion-'+d.emotion;
    }
    if(d.timestamp){
      const dt=new Date(d.timestamp*1000);
      document.getElementById('ts').textContent=
        'SIGMA-17 // '+pad(dt.getHours(),2)+':'+pad(dt.getMinutes(),2)+':'+pad(dt.getSeconds(),2);
    }
    prev=t;
  }catch(e){}
}
setInterval(poll,1500);
poll();
</script>
</body>
</html>"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, time


_OVERLAY_STATE = os.path.join(os.path.dirname(__file__), "temp", "overlay_state.json")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/state":
            data = {"text": "", "emotion": "neutral", "timestamp": time.time()}
            try:
                with open(_OVERLAY_STATE, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif self.path == "/overlay":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_OVERLAY_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


def main():
    server = HTTPServer(("127.0.0.1", 9733), _Handler)
    server.serve_forever()
