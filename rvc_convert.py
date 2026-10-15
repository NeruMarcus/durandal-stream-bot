import atexit
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from config import Config
from logger import logger

_SELF_DIR = Path(__file__).parent.resolve()

_proc: subprocess.Popen | None = None
# RLock на весь запрос (ensure + write + read): warmup и озвучка делят
# одни пайпы демона, два параллельных write/read склеивают строки
# и съедают чужие ответы. Реентрантность — для _ensure внутри запроса.
_daemon_lock = threading.RLock()


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


def _ensure_daemon_locked():
    # Вызывать только под _daemon_lock (в rvc_convert им обёрнут весь запрос:
    # warmup и озвучка делят одни пайпы демона).
    global _proc
    if _proc is not None:
        ret = _proc.poll()
        if ret is None:
            return
        logger.warning(f"RVC daemon мёртв (код {ret}), перезапуск...")
        _stop_daemon_locked()

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
    device = (Config.RVC_DEVICE or "cpu").strip().lower()
    if device == "cuda":
        device = "cuda:0"
    if device not in ("cpu", "cuda:0"):
        logger.warning(f"RVC_DEVICE={Config.RVC_DEVICE!r} непонятен, еду на cpu")
        device = "cpu"
    env["RVC_DEVICE"] = device

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
    logger.info(f"RVC демон: pid={_proc.pid} device={env['RVC_DEVICE']} модель={model}")


def _stop_daemon_locked():
    # Вызывать только под _daemon_lock.
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


def _stop_daemon():
    # Best-effort снаружи запроса (atexit): если замок занят висящим
    # запросом — не виснем на выходе, демон умрёт вместе с процессом.
    if _daemon_lock.acquire(blocking=False):
        try:
            _stop_daemon_locked()
        finally:
            _daemon_lock.release()


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
    f0method: str = Config.RVC_F0METHOD,
    index_rate: float = Config.RVC_INDEX_RATE,
    protect: float = Config.RVC_PROTECT,
    filter_radius: int = 3,
    resample_sr: int = Config.RVC_RESAMPLE_SR,
    rms_mix_rate: float = Config.RVC_RMS_MIX_RATE,
) -> str:
    # Весь запрос под RLock (см. _daemon_lock): иначе warmup и озвучка
    # пишут/читают одни пайпы одновременно и забирают чужие ответы.
    with _daemon_lock:
        for attempt in range(1, 3):
            _ensure_daemon_locked()

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

            proc = _proc  # снапшот: чужой _stop не подменит объект между write и read
            t0 = time.monotonic()
            try:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError) as e:
                # Демон умер между _ensure и записью: убиваем остаток и тратим
                # вторую попытку на чистый рестарт, а не падаем сразу.
                logger.warning(f"RVC daemon pipe: {type(e).__name__}, попытка {attempt}/2, перезапуск...")
                _stop_daemon_locked()
                continue

            line = _readline_timeout(proc, _READ_TIMEOUT)
            elapsed = time.monotonic() - t0
            if not line:
                # Пусто = таймаут ИЛИ демон закрыл stdout (умер). poll
                # различает: None — висит (CUDA под нагрузкой игры).
                logger.warning(
                    f"RVC daemon завис/умер (попытка {attempt}/2, ждали {elapsed:.0f}с, "
                    f"pid={proc.pid}, жив={proc.poll() is None}), перезапуск..."
                )
                _stop_daemon_locked()
                continue

            try:
                result = json.loads(line.strip())
                status = result.get("status")
            except (ValueError, AttributeError) as e:
                # Битый ответ рассинхронизирует протокол: только рестарт.
                logger.warning(f"RVC daemon вернул мусор ({type(e).__name__}), попытка {attempt}/2, перезапуск...")
                _stop_daemon_locked()
                continue
            if status == "error":
                raise RuntimeError(f"RVC inference: {result.get('message')}")
            if status != "ok" or not os.path.exists(output_wav):
                # Демон соврал "ok" без файла — отдавать нечего, только рестарт.
                logger.warning(f"RVC daemon ok без файла ({output_wav}), попытка {attempt}/2, перезапуск...")
                _stop_daemon_locked()
                continue

            logger.info(f"RVC конверсия ok ({elapsed:.1f}с, {os.path.basename(input_wav)})")
            return output_wav

    raise RuntimeError("RVC daemon не смог обработать запрос после 2 попыток")
