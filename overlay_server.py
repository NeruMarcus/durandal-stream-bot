from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import os
import time

from config import Config

_STATE_PATH = Config.OVERLAY_STATE
# Локальный шрифт (SIL OFL): кириллица + офлайн, без CDN.
_FONT_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "fonts", "JetBrainsMono-Regular.ttf"
)

# Дизайн — общий язык с overlay/MRTHN/WEB (SPEC / CAM_BADGE / SIGNAL_LOST):
#   кислотный #befd00 + красный #ff4444 на чёрном, monospace-капс с трекингом,
#   красные «ключи»-подписи, разделители |, CRT-скан-линии, плоские плашки.
#   Шапка — сплошная зелёная полоса с логотипом-кругом (как CAM_BADGE),
#   тело — чёрный терминал: текст ПЕЧАТАЕТСЯ по буквам с курсором █,
#   за текстом — большой эквалайзер, реагирующий на голос (energy).
#   Статус бота: TRANSMITTING (говорит) / RENDERING (печатает) /
#   LISTENING (пусто) / STANDBY. Бэкенд может прислать своё поле
#   "status" в состоянии — оно имеет приоритет над выводимым.
_OVERLAY_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
/* JetBrains Mono — SIL OFL 1.1, локально: кириллица + офлайн. */
@font-face{
  font-family:'JetBrains Mono';font-style:normal;font-weight:400;
  src:url('/font') format('truetype');font-display:swap;
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  width:845px;height:230px;
  background:transparent;
  font-family:'JetBrains Mono','Consolas','Lucida Console',monospace;
  color:#befd00;
  overflow:hidden;
  position:relative;
}
.panel{
  position:absolute;inset:0;
  background:rgba(0,0,0,0.88);
  display:flex;flex-direction:column;
  overflow:hidden;
}
/* Шапка — сплошная зелёная плашка, как SPEC / CAM_BADGE. */
.header{
  flex-shrink:0;height:46px;
  background:#befd00;color:#000;
  display:flex;align-items:center;gap:10px;
  padding:0 12px;
  font-size:14px;letter-spacing:0.1em;
  text-shadow:0 0 5px #befd00;
  overflow:hidden;
}
/* Логотип-круг из CAM_BADGE, чёрным по зелёному. */
.logo{flex-shrink:0;width:30px;height:30px;position:relative}
.lo{
  position:absolute;inset:0;border-radius:50%;
  border:3px solid #000;
}
.li{position:absolute;inset:6px;border-radius:50%;border:2px solid #000}
.lb{
  position:absolute;left:50%;top:3px;bottom:3px;width:5px;
  transform:translateX(-50%);background:#000;
}
.title{letter-spacing:0.14em;white-space:nowrap;flex-shrink:0}
/* Метка эмоции — чёрный чип на зелёном, текст цветом эмоции. */
.emotion-badge{
  background:#000;
  font-size:12px;letter-spacing:0.12em;
  padding:2px 9px;white-space:nowrap;flex-shrink:0;
}
.emotion-sarcastic{color:#ff8800}
.emotion-angry{color:#ff4444}
.emotion-mocking{color:#cc66ff}
.emotion-calm{color:#66ccff}
.emotion-neutral{color:#befd00}
.hstatus{margin-left:auto;font-size:12px;white-space:nowrap;overflow:hidden;flex-shrink:0}
.hkey{color:#ff4444;margin-right:0.6em}
.livedot{
  display:none;width:8px;height:8px;background:#ff4444;margin-left:8px;
  animation:blink 0.5s step-end infinite;
}
.livedot.on{display:inline-block}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.2}}
/* Тело — чёрный терминал. */
.body{flex:1;position:relative;overflow:hidden;padding:8px 18px}
.eq{
  position:absolute;inset:0;z-index:0;pointer-events:none;
  display:flex;align-items:flex-end;gap:3px;padding:0 6px;
}
.eq i{
  flex:1 1 0;height:2%;
  background:linear-gradient(to top,rgba(190,253,0,0.5),rgba(190,253,0,0.08));
}
.term{position:absolute;inset:8px 18px;z-index:1;overflow:hidden}
.src{
  font-size:11px;letter-spacing:0.14em;
  color:rgba(190,253,0,0.5);text-transform:uppercase;
  white-space:nowrap;overflow:hidden;
}
.line{margin-top:5px;font-size:23px;line-height:1.3;max-height:130px;overflow:hidden}
.prompt{color:#ff4444;margin-right:10px}
#text{text-shadow:0 0 10px #000,0 0 4px #000,0 0 2px #000;word-wrap:break-word}
.cursor{animation:blink 1s step-end infinite}
.line.idle #text{color:#ff4444;opacity:0.75;font-size:19px;letter-spacing:0.1em}
/* Подвал — dim-зелёный, разделители |, как SPEC. */
.footer{
  flex-shrink:0;height:28px;
  display:flex;align-items:center;gap:10px;
  padding:0 14px;
  font-size:11px;letter-spacing:0.12em;text-transform:uppercase;
  color:rgba(190,253,0,0.5);
}
.footer .sep{opacity:0.6}
.footer .right{margin-left:auto}
.crt{
  position:absolute;inset:0;pointer-events:none;z-index:10;
  background:repeating-linear-gradient(
    to bottom,transparent 0,rgba(0,0,0,0.09) 1px,transparent 3px
  );
  opacity:0.65;
}
@media (prefers-reduced-motion:reduce){
  .cursor,.livedot{animation:none}
}
</style>
</head>
<body>

<div class="panel">
  <div class="header">
    <div class="logo"><div class="lo"></div><div class="li"></div><div class="lb"></div></div>
    <span class="title" translate="no">// DURANDAL //</span>
    <span class="emotion-badge emotion-neutral" id="emotion" translate="no">NEUTRAL</span>
    <span class="hstatus"><span class="hkey">STATUS</span><span id="status">STANDBY</span><span class="livedot" id="livedot"></span></span>
  </div>

  <div class="body">
    <div class="eq" id="eq"></div>
    <div class="term">
      <div class="src">UESC // TAU CETI IV // INCOMING TRANSMISSION</div>
      <div class="line" id="line"><span class="prompt">&gt;</span><span id="text"></span><span class="cursor">█</span></div>
    </div>
  </div>

  <div class="footer">
    <span id="ts">SIGMA-17 // UESC</span>
    <span class="sep">|</span>
    <span>FEED: COMMENTARY</span>
    <span class="right" id="seq">FRAME 0000</span>
  </div>
</div>

<div class="crt"></div>

<script>
let target='',shown=0,seq=0,speaking=false,typing=false,energy=0,level=0;
let explicitStatus=null;
function pad(n,w){return String(n).padStart(w,'0')}

const elText=document.getElementById('text');
const elLine=document.getElementById('line');
const elStatus=document.getElementById('status');
const elEmotion=document.getElementById('emotion');
const elLive=document.getElementById('livedot');
const elTs=document.getElementById('ts');
const elSeq=document.getElementById('seq');

const eq=document.getElementById('eq');
const bars=[];
const BARS=48;
for(let i=0;i<BARS;i++){const b=document.createElement('i');eq.appendChild(b);bars.push(b);}

function deriveStatus(){
  if(speaking) return 'TRANSMITTING // VOICE';
  if(typing) return 'RENDERING // TEXT';
  if(!target) return 'LISTENING // CHAT';
  return 'STANDBY // ONLINE';
}
function refreshStatus(){elStatus.textContent=explicitStatus||deriveStatus();}

async function poll(){
  try{
    const r=await fetch('/state',{cache:'no-store'});
    const d=await r.json();
    const t=(d.text||'').trim();
    if(t!==target){
      target=t;shown=0;seq++;
      elSeq.textContent='FRAME '+pad(seq,4);
    }
    if(d.emotion){
      elEmotion.textContent=d.emotion.toUpperCase();
      elEmotion.className='emotion-badge emotion-'+d.emotion;
    }
    speaking=!!d.speaking;
    energy=(typeof d.energy==='number')?Math.max(0,Math.min(1,d.energy)):0;
    elLive.className='livedot'+(speaking?' on':'');
    explicitStatus=(d.status&&typeof d.status==='string'&&d.status.trim())
      ? d.status.trim().toUpperCase().slice(0,40) : null;
    refreshStatus();
    if(d.timestamp){
      const dt=new Date(d.timestamp*1000);
      elTs.textContent='SIGMA-17 // UESC // '+
        dt.toLocaleTimeString('ru-RU',{hour12:false});
    }
  }catch(e){}
}

/* Печать текста по буквам, как терминал. */
function tick(){
  if(shown<target.length){
    const rest=target.length-shown;
    shown+=rest>120?2:1;
    typing=true;
  }else typing=false;
  if(!target){
    elLine.className='line idle';
    elText.textContent='ОЖИДАНИЕ СИГНАЛА…';
  }else{
    elLine.className='line';
    elText.textContent=target.slice(0,shown);
  }
  refreshStatus();
}
setInterval(tick,18);

/* Эквалайзер за текстом: амплитуда от реальной громкости (energy). */
function render(ts){
  level+=(energy-level)*0.25;
  const t=ts/1000;
  const drive=Math.pow(Math.max(level,0.04),0.7);
  for(let i=0;i<bars.length;i++){
    const pos=i/(bars.length-1);
    const shape=Math.max(0.08,0.3+0.7*Math.cos((pos-0.35)*2.6));
    let v;
    if(speaking){
      const o1=0.5+0.5*Math.sin(t*(7+i*0.9)+i*2.3);
      const o2=0.5+0.5*Math.sin(t*3.3+i*0.6);
      v=shape*(0.25+0.75*o1)*(0.55+0.45*o2)*drive;
    }else{
      v=0.02+0.015*(0.5+0.5*Math.sin(ts/900+i*0.35));
    }
    bars[i].style.height=(Math.max(0.015,Math.min(1,v))*100).toFixed(1)+'%';
  }
  requestAnimationFrame(render);
}
requestAnimationFrame(render);

setInterval(poll,120);
poll();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: OBS поллит /state 8 раз/сек
    def do_GET(self):
        if self.path == "/state":
            try:
                with open(_STATE_PATH, encoding="utf-8") as f:
                    body = f.read()
            except OSError:
                body = json.dumps({"text": "", "emotion": "neutral",
                                   "speaking": False, "energy": 0.0,
                                   "timestamp": time.time()}, ensure_ascii=False)
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)
        elif self.path in ("/overlay", "/", "/overlay/"):
            raw = _OVERLAY_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == "/font":
            try:
                with open(_FONT_PATH, "rb") as f:
                    raw = f.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "font/ttf")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass  # /state поллится 8 раз/сек — не спамим в stderr/bot.log


def main(host: str = "127.0.0.1", port: int = 9733) -> None:
    """Запуск оверлей-сервера (используется и из main.py)."""
    # Threading: OBS + вкладки поллят /state параллельно, один медленный
    # /font не должен подвешивать опрос состояния.
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"Overlay: http://{host}:{port}/overlay")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
