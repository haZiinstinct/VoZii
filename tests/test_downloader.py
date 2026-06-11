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
