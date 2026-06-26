import platform, os, shutil
import numpy as np
import traceback
import re


_ffmpeg_path = shutil.which("ffmpeg")


def _load_audio_ffmpeg(file, sr):
    import ffmpeg
    file = clean_path(file)
    out, _ = (
        ffmpeg.input(file, threads=0)
        .output("-", format="f32le", acodec="pcm_f32le", ac=1, ar=sr)
        .run(cmd=["ffmpeg", "-nostdin"], capture_stdout=True, capture_stderr=True)
    )
    return np.frombuffer(out, np.float32).flatten()


def _load_audio_soundfile(file, sr):
    import soundfile as sf
    import librosa
    data, orig_sr = sf.read(file)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if orig_sr != sr:
        data = librosa.resample(data.astype(np.float32), orig_sr=orig_sr, target_sr=sr)
    return data.astype(np.float32)


def load_audio(file, sr):
    file = clean_path(file)
    if os.path.exists(file) == False:
        raise RuntimeError(
            "You input a wrong audio path that does not exists, please fix it!"
        )
    if _ffmpeg_path:
        return _load_audio_ffmpeg(file, sr)
    else:
        return _load_audio_soundfile(file, sr)


def wav2(i, o, format):
    import av
    inp = av.open(i, "rb")
    if format == "m4a":
        format = "mp4"
    out = av.open(o, "wb", format=format)
    if format == "ogg":
        format = "libvorbis"
    if format == "mp4":
        format = "aac"
    ostream = out.add_stream(format)
    for frame in inp.decode(audio=0):
        for p in ostream.encode(frame):
            out.mux(p)
    for p in ostream.encode(None):
        out.mux(p)
    out.close()
    inp.close()



def clean_path(path_str):
    if platform.system() == "Windows":
        path_str = path_str.replace("/", "\\")
    path_str = re.sub(r'[\u202a\u202b\u202c\u202d\u202e]', '', path_str)  # 移除 Unicode 控制字符
    return path_str.strip(" ").strip('"').strip("\n").strip('"').strip(" ")
