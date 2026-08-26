# VoZii Troubleshooting

Where to look first: the **log file**. Its location depends on your install:

| Install type | Log location |
| --- | --- |
| Normal | `%LOCALAPPDATA%\VoZii\vozii.log` |
| Portable (a `config.yaml` / `whisper-cpp` folder sits next to `VoZii.exe`) | `vozii.log` next to the `.exe` |
| App crashed before any window appeared | `%TEMP%\vozii_boot_error.log` |

Open it quickly from the tray menu: **right-click the VoZii tray icon → Open log**.

---

## Recording works, but no text appears

The most common causes are Windows blocking the (unsigned) speech engine, or a
missing system runtime. Since v1.8 VoZii detects both and shows a dialog with
the exact reason — but here is the background:

### Smart App Control blocks the speech engine

**Symptom:** the settings window opens, recording starts, but every dictation
comes back empty. The log shows:

```
whisper-server sofort beendet (Code 3236495362)
```

`3236495362` = `0xC0E90002` — Windows **Smart App Control** (SAC) refuses to
load the unsigned `ggml-*.dll`. You can confirm it in Event Viewer under
*Applications and Services → Microsoft → Windows → CodeIntegrity → Operational*
(event **3077**, policy `VerifiedAndReputableDesktop`).

**Fix:** Windows Security → **App & browser control** → **Smart App Control**
→ **Off**.

> ⚠️ SAC is a one-way switch: once turned off, it can only be re-enabled by
> reinstalling Windows. SAC also has **no per-app exceptions**, and Defender
> exclusions do not help — turning it off (or a signed VoZii build in the
> future) are the only options.

### Missing VC++ Runtime (fresh Windows)

**Symptom:** on a freshly installed Windows, dictation stays empty; the log
shows exit code `3221225781` (= `0xC0000135`, *DLL not found*).

The whisper.cpp binaries need the **Microsoft Visual C++ 2015–2022
Redistributable (x64)**. VoZii checks for it at startup and shows a download
dialog; you can also install it directly:
<https://aka.ms/vs/17/release/vc_redist.x64.exe>

---

## The app does not start at all

- **SmartScreen** ("Windows protected your PC"): expected for an unsigned
  `.exe` — click *More info → Run anyway*, or right-click the file →
  *Properties → Unblock → Apply*. Verify your download against the
  `SHA256SUMS.txt` attached to each release.
- **Nothing happens, no window:** VoZii is a onefile `.exe` that unpacks itself
  into `%TEMP%\_MEI...` at launch. Corporate policies (AppLocker, WDAC) or
  aggressive antivirus can block execution from `%TEMP%`. Check
  `%TEMP%\vozii_boot_error.log` and your AV quarantine, and allow the app.
- **"VoZii is already running":** check the tray (bottom-right, behind the ^
  arrow). If no icon is there, end a stale `VoZii.exe` in Task Manager.

---

## Microphone issues

- Use the built-in **Test** button (settings → Microphone) — a live level meter
  confirms the signal.
- If your configured microphone was unplugged, VoZii automatically falls back
  to the system default and logs a warning.
- USB microphones sometimes re-enumerate after standby; VoZii reopens the
  stream on the next recording automatically.

## Model / download issues

- Downloads resume automatically after a connection loss — just press the
  button again.
- Every download is verified against a pinned SHA-256 checksum; a corrupted
  file is discarded automatically. Retry, and if it persists, open an issue.
- To force a fresh model download: delete the model file under
  `whisper-cpp\models\` and press **Download** again.
- After a GPU/backend change (e.g. new graphics card), the settings window
  offers an **Update** button that reinstalls the matching whisper.cpp build.

## Slow or delayed transcription

- VoZii keeps a `whisper-server` in RAM (the model stays loaded). If that
  fails, it silently falls back to a slower per-call CLI mode — the log tells
  you which backend is active (`Transcriber-Backend: server` vs `cli`).
- On weak CPUs prefer the **Recommended** (turbo q5) model over *Best*, and
  the **Fast** decoding mode.
