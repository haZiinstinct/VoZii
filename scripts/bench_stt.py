"""STT-Benchmark: Parakeet (in-process) vs. whisper.cpp auf der CPU.

Nutzt die installierten Modelle/Binaries aus BASE_DIR. Beispiel:

    python scripts/bench_stt.py aufnahme1.wav aufnahme2.wav --whisper large-v3-turbo-q5_0

Ausgabe je Datei: Audiolaenge, Latenz, RTF (Rechenzeit / Audiolaenge) und
der erkannte Text. WAVs muessen 16 kHz / 16 Bit / mono sein (wie VoZii sie
aufnimmt).
"""

import argparse
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.downloader import MODEL_FILES, PARAKEET_MODEL, is_model_installed  # noqa: E402
from src.parakeet import ParakeetBackend  # noqa: E402
from src.transcriber import MODELS_DIR, CliBackend, _clean_output, _threads  # noqa: E402


def _duration(path: str) -> float:
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _run(name: str, transcribe, wavs: list[str]):
    print(f"\n=== {name} ===")
    for path in wavs:
        dur = _duration(path)
        t0 = time.perf_counter()
        text = transcribe(path)
        dt = time.perf_counter() - t0
        print(f"{os.path.basename(path):>20}  {dur:5.1f}s Audio  {dt:6.2f}s  "
              f"RTF {dt / dur:.3f}  |  {text}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--whisper", help="zusaetzlich whisper-cli mit diesem Modell (CPU, -ng)")
    ap.add_argument("--language", default="de")
    args = ap.parse_args()

    print(f"Threads: {_threads()}")
    if is_model_installed(PARAKEET_MODEL):
        backend = ParakeetBackend(_threads())
        t0 = time.perf_counter()
        backend.warmup()
        print(f"Parakeet laden + Warmup: {time.perf_counter() - t0:.2f}s")
        _run("Parakeet v3 int8 (CPU)",
             lambda p: _clean_output(backend.transcribe(p)), args.wavs)
    else:
        print("Parakeet nicht installiert — uebersprungen")

    if args.whisper:
        cli = CliBackend(os.path.join(MODELS_DIR, MODEL_FILES[args.whisper]),
                         args.language, "speed")
        cli.no_gpu = True
        # Hinweis: CLI laedt das Modell pro Aufruf neu (wie der VoZii-Fallback)
        _run(f"whisper-cli {args.whisper} (CPU, -ng, inkl. Modell-Laden)",
             lambda p: _clean_output(cli.transcribe(p)), args.wavs)


if __name__ == "__main__":
    main()
