import atexit
import json
import os
import subprocess
import threading
from pathlib import Path

from logger import logger

_SELF_DIR = Path(__file__).parent.resolve()
_ORIG_DIR = _SELF_DIR.parent / "durandal-bot"

_proc: subprocess.Popen | None = None


def _find_webui():
    local = _SELF_DIR / "models" / "rvc_webui"
    if (local / "tools" / "infer_cli.py").exists():
        return local
    orig = _ORIG_DIR / "rvc_webui"
    if (orig / "tools" / "infer_cli.py").exists():
        return orig
    return None


def _find_weights_dir():
    webui = _find_webui()
    if webui:
        w = webui / "assets" / "weights"
        if w.exists():
            return webui, w
    orig = _ORIG_DIR / "rvc_webui"
    w2 = orig / "assets" / "weights"
    if w2.exists():
        return orig, w2
    return None, None


def _find_rvc_env():
    exe = _ORIG_DIR / "rvc_env" / "Scripts" / "python.exe"
    if exe.exists():
        return str(exe)
    return None


def _get_model():
    _, weights_dir = _find_weights_dir()
    if weights_dir is None:
        raise RuntimeError("RVC weights not found")
    models = sorted(
        [f for f in os.listdir(str(weights_dir)) if f.endswith(".pth") and "_e" in f],
        key=lambda x: int(x.split("_e")[1].split("_")[0]),
    )
    return models[-1] if models else None


def _find_index(weights_dir, model_name):
    base = model_name.rsplit(".", 1)[0]
    candidates = [
        weights_dir / f"added_{base}.index",
        weights_dir / f"trained_{base}.index",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _ensure_daemon():
    global _proc
    if _proc is not None:
        ret = _proc.poll()
        if ret is None:
            return
        logger.warning(f"RVC daemon мёртв (код {ret}), перезапуск...")
        _stop_daemon()

    rvc_python = _find_rvc_env()
    rvc_dir, weights_dir = _find_weights_dir()
    model = _get_model()

    if not rvc_python or not rvc_dir:
        raise RuntimeError("RVC environment or webui not found")

    daemon_script = str(_SELF_DIR / "rvc_daemon.py")

    env = os.environ.copy()
    env["USE_LIBUV"] = "0"
    env["weight_root"] = str(weights_dir)
    env["index_root"] = str(weights_dir)
    env["rmvpe_root"] = str(rvc_dir / "assets" / "rmvpe")
    env["weight_uvr5_root"] = str(rvc_dir / "assets" / "uvr5_weights")

    _proc = subprocess.Popen(
        [rvc_python, daemon_script, model or ""],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(rvc_dir),
        env=env,
        text=True,
        bufsize=1,
    )

    def _log_err():
        for line in _proc.stderr:
            line = line.strip()
            if not line:
                continue
            if line.startswith("ERROR") or line.startswith("Traceback"):
                logger.error(f"RVC daemon: {line}")
            elif line.startswith("WARNING"):
                logger.warning(f"RVC daemon: {line}")
            else:
                logger.info(f"RVC daemon: {line}")
    threading.Thread(target=_log_err, daemon=True).start()

    atexit.register(_stop_daemon)


def _stop_daemon():
    global _proc
    if _proc:
        try:
            _proc.stdin.close()
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
        _proc = None


def rvc_convert(
    input_wav: str,
    output_wav: str | None = None,
    f0up_key: int = 0,
    f0method: str = "rmvpe",
    index_rate: float = 0.66,
    protect: float = 0.5,
    filter_radius: int = 3,
    resample_sr: int = 24000,
    rms_mix_rate: float = 1.0,
) -> str:
    for attempt in range(3):
        _ensure_daemon()

        _, weights_dir = _find_weights_dir()
        model = _get_model()

        if output_wav is None:
            output_wav = str(_SELF_DIR / "temp" / f"rvc_{Path(input_wav).stem}.wav")
            os.makedirs(str(Path(output_wav).parent), exist_ok=True)

        index_path = _find_index(weights_dir, model)

        request = {
            "input_path": input_wav,
            "opt_path": output_wav,
            "f0up_key": f0up_key,
            "f0method": f0method,
            "index_path": index_path,
            "index_rate": index_rate,
            "filter_radius": filter_radius,
            "resample_sr": resample_sr,
            "rms_mix_rate": rms_mix_rate,
            "protect": protect,
        }

        _proc.stdin.write(json.dumps(request) + "\n")
        _proc.stdin.flush()

        line = _proc.stdout.readline()
        if not line:
            logger.warning("RVC daemon умер, перезапуск...")
            _stop_daemon()
            continue

        result = json.loads(line.strip())
        if result["status"] == "error":
            raise RuntimeError(f"RVC inference: {result['message']}")

        return output_wav

    raise RuntimeError("RVC daemon не смог обработать запрос после 3 попыток")
