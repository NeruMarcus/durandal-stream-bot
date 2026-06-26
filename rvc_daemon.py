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

from configs.config import Config
from infer.modules.vc.modules import VC


def main():
    config = Config()
    config.device = "cuda:0"
    config.is_half = True
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
