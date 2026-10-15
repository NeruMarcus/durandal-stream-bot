import atexit
import json
import os
import subprocess
import threading
from pathlib import Path

from logger import logger

_SELF_DIR = Path(__file__).parent.resolve()

_proc: subprocess.Popen | None = None
_daemon_lock = threading.Lock()


def _find_webui():
    local = _SELF_DIR / "models" / "rvc_webui"
    if (local / "tools" / "infer_cli.py").exists():
        return local
    return None


def _find_weights_dir():
    webui = _find_webui()
    if webui:
        w = webui / "assets" / "weights"
        if w.exists():
            return webui, w
    return None, None


def _find_rvc_env():
    local = _SELF_DIR / "rvc_env" / "Scripts" / "python.exe"
    return str(local) if local.exists() else None


def _get_model():
    _, weights_dir = _find_weights_dir()
    if weights_dir is None:
        raise RuntimeError("RVC weights not found")

    def epoch(name: str) -> int:
        try:
            return int(name.split("_e")[1].split("_")[0])
        except (IndexError, ValueError):
            return -1

    models = sorted(
        (f for f in os.listdir(str(weights_dir)) if f.endswith(".pth") and "_e" in f),
        key=epoch,
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
    # warmup и озвучка могут дёрнуть одновременно: без лока родятся два
    # демона, а глобальный _proc перезапишется — второй утечёт с пайпами.
    with _daemon_lock:
        _ensure_daemon_locked()


def _ensure_daemon_locked():
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
    if not model:
        raise RuntimeError("RVC weights: .pth с эпохой (_e123) не найден в assets/weights")

    daemon_script = str(_SELF_DIR / "rvc_daemon.py")

    env = os.environ.copy()
    env["USE_LIBUV"] = "0"
    env["weight_root"] = str(weights_dir)
    env["index_root"] = str(weights_dir)
    env["rmvpe_root"] = str(rvc_dir / "assets" / "rmvpe")
    env["weight_uvr5_root"] = str(rvc_dir / "assets" / "uvr5_weights")

    _proc = subprocess.Popen(
        [rvc_python, daemon_script, model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(rvc_dir),
        env=env,
        text=True,
        bufsize=1,
    )

    def _log_err(proc):
        # proc берём аргументом: после рестарта глобальный _proc уже другой,
        # а старый поток обязан читать только свой (мёртвый) pipe.
        _NOISE = ("tensorboardX", "weight_norm", "FutureWarning", "WeightNorm.apply")
        for line in proc.stderr:
            line = line.strip()
            if not line or any(n in line for n in _NOISE):
                continue
            if line.startswith("ERROR") or line.startswith("Traceback"):
                logger.error(f"RVC daemon: {line}")
            elif line.startswith("WARNING"):
                logger.warning(f"RVC daemon: {line}")
            else:
                logger.info(f"RVC daemon: {line}")

    threading.Thread(target=_log_err, args=(_proc,), daemon=True).start()


def _stop_daemon():
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return
    try:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    finally:
        # Иначе зомби-хендлы и висячий _log_err на закрываемом stderr.
        for fh in (proc.stdout, proc.stderr):
            try:
                fh.close()
            except Exception:
                pass


atexit.register(_stop_daemon)  # один раз на модуль, не на каждый рестарт


_READ_TIMEOUT = 40  # сек: сколько ждём ответ демона на один запрос


def _readline_timeout(proc, timeout: float) -> str:
    """ readline с лимитом: демон, зависший на GPU, иначе держит поток вечно. """
    box: list[str] = []
    done = threading.Event()

    def _reader():
        try:
            box.append(proc.stdout.readline())
        except Exception:
            box.append("")
        finally:
            done.set()

    threading.Thread(target=_reader, daemon=True).start()
    if not done.wait(timeout):
        return ""
    return box[0] if box else ""


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
    for attempt in range(2):
        _ensure_daemon()

        _, weights_dir = _find_weights_dir()
        model = _get_model()
        if not model or weights_dir is None:
            raise RuntimeError("RVC weights: .pth с эпохой (_e123) не найден в assets/weights")

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

        try:
            _proc.stdin.write(json.dumps(request) + "\n")
            _proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as e:
            # Демон умер между _ensure и записью: убиваем остаток и тратим
            # вторую попытку на чистый рестарт, а не падаем сразу.
            logger.warning(f"RVC daemon pipe: {type(e).__name__}, перезапуск...")
            _stop_daemon()
            continue

        line = _readline_timeout(_proc, _READ_TIMEOUT)
        if not line:
            # Демон завис (CUDA под нагрузкой игры) или умер: убиваем его,
            # иначе заблокированный GPU-контекст висит до конца стрима.
            logger.warning("RVC daemon завис/умер, перезапуск...")
            _stop_daemon()
            continue

        result = json.loads(line.strip())
        if result["status"] == "error":
            raise RuntimeError(f"RVC inference: {result['message']}")

        return output_wav

    raise RuntimeError("RVC daemon не смог обработать запрос после 2 попыток")
