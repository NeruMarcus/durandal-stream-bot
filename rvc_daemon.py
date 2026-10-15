import json
import os
import sys

_model_name = sys.argv[1] if len(sys.argv) > 1 else ""
sys.argv = sys.argv[:1]

now_dir = os.getcwd()
sys.path.append(now_dir)

from dotenv import load_dotenv
from scipy.io import wavfile

load_dotenv()

# torch>=2.6 грузит чекпоинты только в weights_only-режиме, а fairseq-чекпоинты
# (hubert, веса RVC) так не открываются. Файлы у нас локальные и доверенные.
import torch as _torch

_torch_load = _torch.load


def _trusted_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _torch_load(*args, **kwargs)


_torch.load = _trusted_load

from configs.config import Config
from infer.modules.vc.modules import VC


def main():
    # Устройство — из окружения (rvc_convert кладёт RVC_DEVICE).
    # CPU: rmvpe/hubert/net_g едут в fp32 — half на CPU не поддерживается.
    _device = os.environ.get("RVC_DEVICE", "cpu").strip().lower()
    _on_cpu = _device == "cpu"
    config = Config()
    config.device = "cpu" if _on_cpu else "cuda:0"
    config.is_half = not _on_cpu
    vc = VC(config)

    if _model_name:
        vc.get_vc(_model_name)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            input_path = req.get("input_path", "")
            opt_path = req.get("opt_path", input_path + ".out.wav")

            if req.get("model_name"):
                vc.get_vc(req["model_name"])

            _, wav_opt = vc.vc_single(
                0,
                input_path,
                req.get("f0up_key", 0),
                None,
                req.get("f0method", "rmvpe"),
                req.get("index_path", ""),
                None,
                req.get("index_rate", 0.66),
                req.get("filter_radius", 3),
                req.get("resample_sr", 0),
                req.get("rms_mix_rate", 1.0),
                req.get("protect", 0.33),
            )
            wavfile.write(opt_path, wav_opt[0], wav_opt[1])
            result = {"status": "ok", "output": opt_path}
        except Exception as e:
            result = {"status": "error", "message": str(e)}

        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
