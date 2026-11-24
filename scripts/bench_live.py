"""Live-Vorschau-Benchmark: Wie lange rechnet EIN Vorschau-Durchlauf je
Fenstergroesse? Das ist die Zeit, um die eine laufende Vorschau die echte
Transkription im schlechtesten Fall verzoegert (Hotkey wird genau beim
Start eines Durchlaufs losgelassen); im Mittel ist es etwa die Haelfte mal
dem Anteil der Zeit, in dem ueberhaupt ein Durchlauf laeuft.

    python scripts/bench_live.py sprache.wav --base dist --model large-v3-turbo

--base: Ordner mit whisper-cpp/ (Standard: BASE_DIR). Nimmt Parakeet, wenn
installiert und --engine parakeet, sonst den whisper-server. WAV: 16 kHz /
16 Bit / mono, mindestens so lang wie das groesste Fenster.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import transcriber as tr  # noqa: E402
from src.downloader import MODEL_FILES  # noqa: E402
from src.parakeet import ParakeetBackend, _read_wav  # noqa: E402
from src.session import LIVE_INTERVAL_S  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("wav")
    ap.add_argument("--base", default=None)
    ap.add_argument("--engine", choices=("whisper", "parakeet"), default="whisper")
    ap.add_argument("--model", default="large-v3-turbo-q5_0")
    ap.add_argument("--language", default="de")
    ap.add_argument("--windows", default="4,6,8,12")
    ap.add_argument("--runs", type=int, default=8)
    args = ap.parse_args()

    whisper_dir = tr.WHISPER_DIR
    if args.base:
        whisper_dir = os.path.join(os.path.abspath(args.base), "whisper-cpp")
        tr.WHISPER_SERVER = os.path.join(whisper_dir, "whisper-server.exe")
        tr.WHISPER_CLI = os.path.join(whisper_dir, "whisper-cli.exe")
    models = os.path.join(whisper_dir, "models")

    audio = _read_wav(args.wav)
    if args.engine == "parakeet":
        backend = ParakeetBackend(tr._threads(), os.path.join(models, "parakeet-v3-int8"))
        backend.warmup()
    else:
        backend = tr.ServerBackend(os.path.join(models, MODEL_FILES[args.model]),
                                   args.language, "speed", "")
        backend.ensure_started()
    try:
        backend.preview(audio[:16000])  # Aufwaermen
        print(f"{'Fenster':>8} {'Median':>8} {'Max':>8}  Anteil am Intervall")
        for w in (float(x) for x in args.windows.split(",")):
            clip = audio[-int(w * 16000):]
            times = []
            for _ in range(args.runs):
                t0 = time.perf_counter()
                if backend.preview(clip) is None:
                    sys.exit("Vorschau lieferte None (Backend nicht bereit)")
                times.append(time.perf_counter() - t0)
            med = statistics.median(times)
            busy = med / (med + LIVE_INTERVAL_S)
            print(f"{w:7.0f}s {med * 1000:6.0f}ms {max(times) * 1000:6.0f}ms  {busy:5.0%}"
                  f"  -> mittlere Mehr-Latenz ~{busy * med / 2 * 1000:.0f} ms")
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
