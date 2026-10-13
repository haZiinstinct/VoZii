"""Downloader: Resume (206 vs. 200), SHA256-Pins, Disk-Space, Safe-Extract."""

import hashlib
import os
import zipfile
from collections import namedtuple

import pytest

from src import downloader


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200, headers: dict | None = None):
        self._data = data
        self.status = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Ersetzt urlopen; Test setzt holder['response'] und liest holder['request']."""
    holder = {}

    def _urlopen(req, *args, **kwargs):
        holder["request"] = req
        return holder["response"]

    monkeypatch.setattr(downloader.urllib.request, "urlopen", _urlopen)
    return holder


def test_fresh_download(tmp_path, fake_urlopen):
    dest = str(tmp_path / "file.bin")
    fake_urlopen["response"] = FakeResponse(b"hello world")
    downloader.download_file("https://example.com/f", dest)
    assert open(dest, "rb").read() == b"hello world"


def test_resume_206_appends(tmp_path, fake_urlopen):
    dest = str(tmp_path / "file.bin")
    with open(dest + ".part", "wb") as f:
        f.write(b"AAAA")
    fake_urlopen["response"] = FakeResponse(
        b"BBBB", status=206, headers={"Content-Length": "4"})
    downloader.download_file("https://example.com/f", dest)
    assert open(dest, "rb").read() == b"AAAABBBB"
    assert fake_urlopen["request"].get_header("Range") == "bytes=4-"


def test_resume_200_restarts(tmp_path, fake_urlopen):
    """Server ohne Range-Support liefert 200 + ganze Datei -> .part verwerfen."""
    dest = str(tmp_path / "file.bin")
    with open(dest + ".part", "wb") as f:
        f.write(b"AAAA")
    fake_urlopen["response"] = FakeResponse(b"CCCCCCCC", status=200)
    downloader.download_file("https://example.com/f", dest)
    assert open(dest, "rb").read() == b"CCCCCCCC"


def test_sha256_ok(tmp_path, fake_urlopen):
    dest = str(tmp_path / "file.bin")
    data = b"verified content"
    fake_urlopen["response"] = FakeResponse(data)
    downloader.download_file("https://example.com/f", dest,
                             expected_sha256=hashlib.sha256(data).hexdigest())
    assert os.path.exists(dest)


def test_sha256_mismatch_deletes_file(tmp_path, fake_urlopen):
    dest = str(tmp_path / "file.bin")
    fake_urlopen["response"] = FakeResponse(b"tampered content")
    with pytest.raises(RuntimeError, match="Checksumme"):
        downloader.download_file("https://example.com/f", dest,
                                 expected_sha256="00" * 32)
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_disk_space_preflight(tmp_path, fake_urlopen, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(downloader.shutil, "disk_usage",
                        lambda _: usage(total=10**12, used=10**12, free=1024))
    dest = str(tmp_path / "file.bin")
    fake_urlopen["response"] = FakeResponse(b"x" * 4096)
    with pytest.raises(RuntimeError, match="Speicherplatz"):
        downloader.download_file("https://example.com/f", dest)


def test_safe_extract_rejects_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.exe", b"x")
    with zipfile.ZipFile(zip_path) as zf:
        with pytest.raises(RuntimeError, match="Unsicherer Pfad"):
            downloader._safe_extract(zf, str(tmp_path / "out"))


def test_extract_binaries_whitelist(tmp_path, monkeypatch):
    whisper_dir = tmp_path / "whisper-cpp"
    whisper_dir.mkdir()
    monkeypatch.setattr(downloader, "WHISPER_DIR", str(whisper_dir))

    zip_path = str(whisper_dir / "whisper-cpp.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Release/whisper-cli.exe", b"cli")
        zf.writestr("Release/whisper-server.exe", b"server")
        zf.writestr("Release/ggml.dll", b"dll")
        zf.writestr("Release/bench.exe", b"bench")

    downloader._extract_binaries(zip_path, want_cli=True, want_server=True, with_dlls=True)

    assert (whisper_dir / "whisper-cli.exe").read_bytes() == b"cli"
    assert (whisper_dir / "whisper-server.exe").read_bytes() == b"server"
    assert (whisper_dir / "ggml.dll").exists()
    assert not (whisper_dir / "bench.exe").exists()
    assert not os.path.exists(zip_path)  # Zip wird aufgeraeumt


def test_extract_binaries_server_only(tmp_path, monkeypatch):
    whisper_dir = tmp_path / "whisper-cpp"
    whisper_dir.mkdir()
    monkeypatch.setattr(downloader, "WHISPER_DIR", str(whisper_dir))

    zip_path = str(whisper_dir / "whisper-cpp.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Release/whisper-cli.exe", b"cli")
        zf.writestr("Release/whisper-server.exe", b"server")
        zf.writestr("Release/ggml.dll", b"dll")

    downloader._extract_binaries(zip_path, want_cli=False, want_server=True, with_dlls=False)

    assert (whisper_dir / "whisper-server.exe").exists()
    assert not (whisper_dir / "whisper-cli.exe").exists()
    assert not (whisper_dir / "ggml.dll").exists()


def test_old_release_main_exe_is_renamed(tmp_path, monkeypatch):
    whisper_dir = tmp_path / "whisper-cpp"
    whisper_dir.mkdir()
    monkeypatch.setattr(downloader, "WHISPER_DIR", str(whisper_dir))

    zip_path = str(whisper_dir / "whisper-cpp.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("main.exe", b"oldcli")

    downloader._extract_binaries(zip_path, want_cli=True, want_server=True, with_dlls=True)
    assert (whisper_dir / "whisper-cli.exe").read_bytes() == b"oldcli"


def test_model_sha_pins_present():
    """Jedes Modell mit URL braucht einen SHA256-Pin."""
    assert set(downloader.MODEL_SHA256) == set(downloader.MODEL_URLS)
    assert all(len(h) == 64 for h in downloader.MODEL_SHA256.values())


def test_model_urls_pinnen_feste_hf_revision():
    """Regression-Guard: /resolve/main waere ein beweglicher Ref — aendert
    Upstream eine Datei, braechen alle Downloads am SHA-Mismatch."""
    for url in downloader.MODEL_URLS.values():
        assert "/resolve/main/" not in url
        assert "/resolve/" in url
    import re
    assert re.search(r"/resolve/[0-9a-f]{40}$", downloader._HF)


def test_binary_urls_zeigen_auf_eigenes_mirror_release():
    from src import hardware
    for url in hardware.BINARY_URLS.values():
        assert url.startswith(
            "https://github.com/haZiinstinct/VoZii/releases/download/backend-v"
            + hardware.BACKEND_VERSION)
    assert set(hardware.BINARY_SHA256) == set(hardware.BINARY_URLS)


@pytest.fixture
def whisper_dir(tmp_path, monkeypatch):
    d = tmp_path / "whisper-cpp"
    d.mkdir()
    monkeypatch.setattr(downloader, "WHISPER_DIR", str(d))
    return d


def test_backend_marker_roundtrip(whisper_dir):
    assert downloader.read_backend_marker() is None
    downloader._write_backend_marker("amd")
    marker = downloader.read_backend_marker()
    assert marker["gpu_type"] == "amd"
    assert marker["version"] == downloader.BACKEND_VERSION
    assert downloader.is_backend_current("amd") is False  # kein Binary da

    (whisper_dir / "whisper-cli.exe").write_bytes(b"MZ")
    assert downloader.is_backend_current("amd") is True
    assert downloader.is_backend_current("nvidia") is False  # Typ-Wechsel


def test_bestand_ohne_marker_wird_per_dll_sniff_erkannt(whisper_dir):
    (whisper_dir / "whisper-cli.exe").write_bytes(b"MZ")
    (whisper_dir / "ggml-vulkan.dll").write_bytes(b"x")
    assert downloader.installed_backend_type() == "amd"
    # ohne Marker gilt der Bestand als veraltet -> Update-Button
    assert downloader.is_backend_current("amd") is False

    (whisper_dir / "cublas64_12.dll").write_bytes(b"x")
    assert downloader.installed_backend_type() == "nvidia"  # nvidia hat Prioritaet


def test_backend_wechsel_laedt_neu_und_raeumt_alte_dlls_weg(whisper_dir, monkeypatch):
    """Frueher: Early-Return sobald irgendein whisper-cli.exe existierte."""
    import zipfile as zf_mod

    (whisper_dir / "whisper-cli.exe").write_bytes(b"altes-cpu-cli")
    (whisper_dir / "libopenblas.dll").write_bytes(b"altes-blas")
    downloader._write_backend_marker("cpu")

    def fake_download(url, dest, progress_callback=None, expected_sha256=None):
        with zf_mod.ZipFile(dest, "w") as zf:
            zf.writestr("whisper-cli.exe", b"neues-vulkan-cli")
            zf.writestr("whisper-server.exe", b"srv")
            zf.writestr("ggml-vulkan.dll", b"vulkan")
        return True

    monkeypatch.setattr(downloader, "download_file", fake_download)

    assert downloader.download_and_extract_binary("amd") is True
    assert (whisper_dir / "whisper-cli.exe").read_bytes() == b"neues-vulkan-cli"
    assert (whisper_dir / "ggml-vulkan.dll").exists()
    assert not (whisper_dir / "libopenblas.dll").exists()  # kein DLL-Mischmasch
    assert downloader.read_backend_marker()["gpu_type"] == "amd"


def test_passendes_backend_wird_nicht_neu_geladen(whisper_dir, monkeypatch):
    (whisper_dir / "whisper-cli.exe").write_bytes(b"MZ")
    downloader._write_backend_marker("cpu")

    def boom(*a, **k):
        raise AssertionError("darf nicht downloaden")

    monkeypatch.setattr(downloader, "download_file", boom)
    assert downloader.download_and_extract_binary("cpu") is True


def test_cancel_im_download_loop_bleibt_interrupted_error(tmp_path, fake_urlopen, monkeypatch):
    """Abbrechen-Button: der Progress-Callback wirft InterruptedError — eine
    OSError-Unterklasse. Frueher fing `except OSError` sie und meldete
    'Schreiben fehlgeschlagen (Festplatte voll)' statt 'Abgebrochen'."""
    import itertools

    clock = itertools.count(0, 1.0)  # jeder time.time()-Aufruf +1 s -> Callback feuert im Loop
    monkeypatch.setattr(downloader.time, "time", lambda: float(next(clock)))
    dest = str(tmp_path / "file.bin")
    fake_urlopen["response"] = FakeResponse(b"x" * 200_000)

    def cancel(*_):
        raise InterruptedError

    with pytest.raises(InterruptedError):
        downloader.download_file("https://example.com/f", dest, cancel)
    assert not os.path.exists(dest)


def test_download_nutzt_socket_timeout(tmp_path, monkeypatch):
    """Ohne Timeout haengt ein eingeschlafener Download endlos und der
    Abbrechen-Button greift nie (Callback laeuft nur zwischen Chunks)."""
    seen = {}

    def _urlopen(req, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return FakeResponse(b"ok")

    monkeypatch.setattr(downloader.urllib.request, "urlopen", _urlopen)
    downloader.download_file("https://example.com/f", str(tmp_path / "f.bin"))
    assert seen["timeout"] == downloader._NET_TIMEOUT_S


def test_download_model_zu_kleine_bin_und_part_kollidieren_nicht(tmp_path, monkeypatch):
    """Altlast ggml-x.bin (zu klein) + ggml-x.bin.part: kein FileExistsError,
    die laengere Datei bleibt als Resume-Basis."""
    monkeypatch.setattr(downloader, "MODELS_DIR", str(tmp_path))
    filename = downloader.MODEL_FILES["tiny"]
    model = tmp_path / filename
    part = tmp_path / (filename + ".part")
    model.write_bytes(b"x" * 10)
    part.write_bytes(b"y" * 20)

    seen = {}

    def fake_download(url, dest, progress=None, expected_sha256=None):
        seen["part"] = (tmp_path / (filename + ".part")).read_bytes()
        seen["bin_exists"] = os.path.exists(dest)

    monkeypatch.setattr(downloader, "download_file", fake_download)
    downloader.download_model("tiny")
    assert seen == {"part": b"y" * 20, "bin_exists": False}

    # Umgekehrt: die .bin ist laenger -> sie ersetzt die .part
    model.write_bytes(b"x" * 30)
    part.write_bytes(b"y" * 5)
    downloader.download_model("tiny")
    assert seen == {"part": b"x" * 30, "bin_exists": False}
