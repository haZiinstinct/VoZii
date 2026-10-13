# Audit Oktober 2026 — Maßnahmenliste

Abarbeitbare Fassung der offenen Punkte aus [AUDIT-2026-10.md](AUDIT-2026-10.md).
Jeder Punkt: Priorität, geschätzter Aufwand, Fundstelle, konkreter Vorschlag,
Nachweis. Haken setzen, wenn erledigt; Zeilennummern beziehen sich auf den
Stand von Commit `b314b77` (Branch `claude/full-stack-audit-k36vla`).

Reihenfolge-Empfehlung: erst Block A (eine Stunde, schließt die größten
Lücken), dann B, dann C/D nach Lust und Laune. Block E ist Kleinkram für
zwischendurch.

Aufwand: **S** = unter 30 min, **M** = 1–2 h, **L** = halber Tag oder mehr.

---

## A — Supply Chain / CI (Priorität hoch, Aufwand klein)

- [x] **A1 · GitHub Actions auf Commit-SHA pinnen** · S
  Fundstelle: `.github/workflows/ci.yml:13-14, 34-35, 52` und `build-backend.yml:23`
  Warum: Ein Tag wie `@v7` ist beweglich. Wer das Action-Repo übernimmt, baut
  das nächste VoZii-Release. Das Projekt bewirbt „verified downloads“ — das
  Release-Werkzeug selbst ist aber nicht verifiziert.
  Vorschlag: `uses: actions/checkout@<40-stelliger-sha> # v7.x.y` für alle vier
  Actions. SHAs auf der Release-Seite der jeweiligen Action ablesen.
  Nachweis: CI läuft grün; Dependabot (A2) hält die SHAs künftig aktuell.

- [x] **A2 · Dependabot einrichten** · S
  Fundstelle: neu `.github/dependabot.yml`
  Vorschlag:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: pip
      directory: /
      schedule: { interval: weekly }
    - package-ecosystem: github-actions
      directory: /
      schedule: { interval: weekly }
  ```
  Nachweis: innerhalb einer Woche erscheinen erste Dependabot-PRs (oder keine,
  weil alles aktuell ist — beides ok).

- [x] **A3 · Build-Werkzeuge pinnen** · S
  Fundstelle: `.github/workflows/ci.yml:21` (`ruff pytest`) und `:42` (`pyinstaller`)
  Warum: Ein neues PyInstaller-Release ändert still das Release-Artefakt
  (Bootloader, Hidden-Import-Verhalten, AV-Signaturen). Ein neues ruff kann
  die CI mit neuen Regeln brechen.
  Vorschlag: `requirements-dev.txt` mit `ruff==0.17.0`, `pytest==9.1.1`,
  `pyinstaller==<aktuelle Version>` anlegen; in beiden Jobs
  `pip install -r requirements.txt -r requirements-dev.txt`. Optional für das
  Release: `pip install --require-hashes` mit `pip-compile --generate-hashes`.
  Nachweis: `pip freeze` im CI-Log zeigt die gepinnten Versionen.

- [x] **A4 · build-backend.yml härten** · S
  Fundstelle: `.github/workflows/build-backend.yml:26` (Tag statt SHA),
  `:30` (Vulkan-SDK ohne Checksumme), `:55` (`--clobber`)
  Vorschlag:
  1. Input `whisper_ref` zusätzlich als Commit-SHA zulassen und im Kommentar
     empfehlen (Upstream-Tag `v1.9.4` → SHA aus `git rev-parse v1.9.4`).
  2. Nach dem `curl`: `(Get-FileHash $env:RUNNER_TEMP/VulkanSDK-Installer.exe).Hash`
     gegen einen im Workflow hinterlegten SHA-256 prüfen (LunarG veröffentlicht
     die Summen auf der Download-Seite).
  3. Kommentar über `--clobber`: *„Überschreibt das Asset, dessen SHA in
     src/hardware.py BINARY_SHA256['amd'] gepinnt ist — nach jedem Lauf neu
     pinnen, sonst schlagen alle AMD-Downloads fehl.“*
  Nachweis: Workflow manuell gegen eine Test-Ref laufen lassen.

- [x] **A5 · Doppelte CI-Läufe bei eigenen PRs vermeiden** · S
  Fundstelle: `.github/workflows/ci.yml:5` (`branches: ["**"]` + `pull_request`)
  Vorschlag: entweder `push` auf `master` und Tags beschränken und PRs über
  `pull_request` laufen lassen, oder `pull_request` streichen (Forks bekommen
  dann keinen CI-Lauf). Empfehlung: ersteres.
  Nachweis: ein Test-PR erzeugt nur noch einen Lauf.

---

## B — Robustheit (Priorität mittel)

- [x] **B1 · `save_config()` atomar + gegen Threads absichern** · M
  Fundstelle: `src/config.py:143-145`; zweiter Schreiber `src/hardware.py:196-207`
  (`_store_gpu_cache` aus dem Thread `gpu-cache-refresh`)
  Warum: Zwei Threads schreiben dieselbe Datei ohne Lock (Lost Update), und
  ein Absturz mitten im `yaml.dump` hinterlässt eine halbe Datei. `load_config`
  fängt das zwar, aber dann sind alle Einstellungen weg.
  Vorschlag: Muster aus `src/history.py:66-74` übernehmen — in `config.yaml.tmp`
  schreiben, `os.replace()`; dazu ein modulweites `threading.Lock()` um
  `load_config`+`save_config`. Für den GPU-Cache besser: nur die drei
  `gpu_cache_*`-Keys unter dem Lock lesen-ändern-schreiben, nicht die ganze
  Config aus dem Thread heraus.
  Nachweis: neuer Test, der `save_config` mit einem Mock unterbricht
  (Exception im Dump) und prüft, dass die alte Datei unversehrt bleibt;
  `test_config.py` bleibt grün.

- [x] **B2 · Server-Timeout nicht als Server-Crash behandeln** · M
  Fundstelle: `src/transcriber.py:236-245` (`ServerBackend.transcribe`) und
  `:350-362` (CLI-Fallback in `Transcriber.transcribe`)
  Warum: Läuft ein langes Diktat im Qualitätsmodus auf CPU in den Timeout,
  wird der Server gekillt, neu gestartet (Modell laden), derselbe Request
  wiederholt, und danach läuft die CLI ein drittes Mal — bis zu 3 × Timeout,
  in denen der Worker steht und keine weitere Aufnahme verarbeitet wird.
  Vorschlag: `socket.timeout` / `TimeoutError` in `transcribe()` gesondert
  fangen: Server **nicht** neu starten, Request **nicht** wiederholen,
  stattdessen direkt `""` zurückgeben und `last_error_hint` mit einem
  i18n-Text setzen („Aufnahme zu lang für diesen Modus“). Neustart nur bei
  Verbindungsfehlern (`URLError`, `ConnectionResetError`) oder wenn
  `self._proc.poll()` nicht `None` ist.
  Nachweis: Test mit `fake_server`, dessen Handler länger als der (gemockte)
  Timeout schläft; Assertion: genau ein Request, kein `shutdown()`.

- [x] **B3 · Hotkey-Aufnahme: Hinweis statt stilles Verwerfen** · S (Code) + M (9 Übersetzungen)
  Fundstelle: `src/settings_gui.py:1191-1206` (`_finalize`),
  i18n-Nachbar `src/i18n.py:170` (`hotkey.press`)
  Warum: Seit dem Audit-Fix wird eine nicht abbildbare Taste (Win, Numpad,
  Medientasten) verworfen und der alte Hotkey bleibt — aber ohne Erklärung.
  Vorschlag: neuen Key `hotkey.unsupported` („Taste nicht unterstützt — bitte
  andere wählen“) in allen 9 Sprachen anlegen; in `_finalize` das Label 2 s
  amber mit diesem Text zeigen, dann den alten Hotkey. Alternativ oder
  zusätzlich `SPECIAL_KEYS` in `src/hotkey.py:17-39` um `cmd`/`win`, Numpad
  (`vk 0x60-0x69`) und `media_*` erweitern und `_PART_VKS` nachziehen.
  Nachweis: `test_i18n.py` (Key-Vollständigkeit) grün; manueller Test mit
  Win-Taste.

- [x] **B4 · `download_model`: Rename kollidiert mit vorhandener `.part`** · S
  Fundstelle: `src/downloader.py:366-369`
  Warum: Existieren `ggml-x.bin` (zu klein, Altlast) **und** `ggml-x.bin.part`,
  wirft `os.rename` auf Windows `FileExistsError` — Download bricht mit
  unverständlicher Meldung ab.
  Vorschlag: vor dem Rename `.part` löschen (die kleine `.bin` ist die bessere
  Resume-Basis), oder `os.replace()` verwenden.
  Nachweis: Test in `test_downloader.py`, der beide Dateien anlegt.

- [x] **B5 · Zwischenablage mit Bild/Dateien wird nicht wiederhergestellt** · S (Doku) / L (Code)
  Fundstelle: `src/text_inserter.py:89` und `:107`
  Warum: `winclip.get_text()` liefert `None` für Nicht-Text (Screenshot,
  kopierte Dateien). Nach dem Einfügen bleibt dann der Diktat-Text in der
  Ablage, das Bild ist weg.
  Vorschlag (minimal): in README „Privacy“ oder Troubleshooting als bekannte
  Einschränkung aufführen. Vollständig: in `winclip` alle Formate per
  `EnumClipboardFormats` + `GetClipboardData` sichern und zurückschreiben —
  aufwendig, nur wenn Nutzer es vermissen.
  Nachweis: Doku-Zeile vorhanden.

- [x] **B6 · Backend-Override in die GUI + inaktive Adapter ignorieren** · M
  Fundstelle: `src/hardware.py:60-87` (`_try_registry`), Override nur in
  `src/app.py:167` per `config.yaml`
  Warum: Die Registry-Enumeration listet auch ausgebaute oder deaktivierte
  Adapter (NVIDIA-Treiberleiche auf einem AMD-System → CUDA-Backend → Server
  startet nicht, CLI auch nicht). Der Nutzer kann das nur per Hand in der
  YAML korrigieren.
  Vorschlag: (1) im Options-Abschnitt der Settings ein OptionMenu
  „Beschleunigung: Automatisch / NVIDIA / AMD / CPU“, das `gpu_type` setzt;
  (2) in `_try_registry` zusätzlich `winreg.QueryValueEx(key, "MatchingDeviceId")`
  lesen und gegen `SYSTEM\CurrentControlSet\Enum\PCI` prüfen, ob das Gerät
  aktuell vorhanden ist — oder einfacher: wenn NVIDIA erkannt, aber
  `nvcuda.dll` nicht in System32 liegt, auf den nächsten Treffer zurückfallen.
  Nachweis: Test für die `nvcuda.dll`-Prüfung mit gemocktem `os.path.isfile`.

- [x] **B7 · `show_error()` aus Worker-Threads** · M
  Fundstelle: `src/app.py:39-49`, Aufruf aus `transcription_worker` (`:~380`)
  Warum: Erzeugt eine zweite `tk.Tk()`-Instanz in einem Nicht-UI-Thread,
  während das Overlay in seinem eigenen Thread eine hält. Funktioniert mit
  threaded Tcl, ist aber die Art von Konstruktion, die nach einem
  Python/Tk-Update plötzlich hängt.
  Vorschlag: Dialog über `ctypes.windll.user32.MessageBoxW` zeigen (wie schon
  in `src/main.py:_emergency`) — kein Tk nötig, thread-sicher, zweisprachig
  via i18n weiterhin möglich.
  Nachweis: Hint-Dialog (SAC-Block simulieren) erscheint aus dem Worker.

---

## C — Sicherheit, Defense in depth (Priorität mittel-niedrig)

- [x] **C1 · Systemwerkzeuge mit absolutem Pfad starten** · S
  Fundstelle: `src/hardware.py:94` (`wmic`), `:109` (`powershell`);
  `src/text_processor.py:223` (`taskkill`), `:276` (`powershell`)
  Warum: Alle vier werden über `PATH` aufgelöst. Ein beschreibbares
  Verzeichnis vor `System32` im Nutzer-PATH könnte sie ersetzen. Kritisch ist
  `_verify_authenticode` (`text_processor.py:266-292`): das ist die einzige
  Prüfung, bevor der Ollama-Installer ausgeführt wird.
  Vorschlag: Helfer in `src/winutil.py`:
  ```python
  def system32(*parts: str) -> str:
      root = os.environ.get("SystemRoot", r"C:\Windows")
      return os.path.join(root, "System32", *parts)
  ```
  und dann `system32("wbem", "wmic.exe")`, `system32("WindowsPowerShell", "v1.0", "powershell.exe")`,
  `system32("taskkill.exe")`.
  Nachweis: `test_win11.py`-Test, der `subprocess.run` mockt und den
  absoluten Pfad als `cmd[0]` prüft.

- [x] **C2 · Authenticode-Subject exakt vergleichen** · S
  Fundstelle: `src/text_processor.py:286`
  Warum: `"ollama" in subject.lower()` akzeptiert jedes Zertifikat, dessen
  Subject den Teilstring enthält.
  Vorschlag: Subject parsen und `CN=` exakt gegen den bekannten Wert prüfen
  (einmal mit `Get-AuthenticodeSignature` am echten Installer ablesen und als
  Konstante hinterlegen); bei Abweichung ablehnen und den gesehenen Subject
  loggen.
  Nachweis: Unit-Test mit gemockter PowerShell-Ausgabe (gültig / falscher CN).

- [x] **C3 · whisper-server ohne Auth auf localhost — dokumentieren** · S
  Fundstelle: `src/transcriber.py:192-199` (`--host 127.0.0.1`)
  Warum: Jeder lokale Prozess kann Audio einreichen und die Antwort lesen.
  Für eine Desktop-App akzeptabel, aber im README-Privacy-Abschnitt fehlt der
  Hinweis.
  Vorschlag: ein Satz unter „Privacy“: *„Die Spracherkennung läuft als
  lokaler Hilfsprozess auf 127.0.0.1 mit zufälligem Port; nur Programme auf
  demselben Rechner können ihn erreichen.“* Technisch ginge ein
  Zufalls-Token im Pfad, whisper-server unterstützt das aber nicht nativ.
  Nachweis: README-Zeile.

---

## D — Tests (Priorität mittel, Aufwand größer)

- [x] **D1 · Zykluslogik in `app.py` testbar machen** · L
  Fundstelle: `src/app.py:154-450` (`_run_cycle`, 0 % Coverage)
  Warum: Alle vier Bugs des Audits lagen in oder an dieser Nahtstelle
  (Hotkey ↔ Recorder ↔ Worker). Nichts davon hätte ein Test gefangen.
  Vorschlag: die inneren Closures (`on_activate`, `on_deactivate`,
  `transcription_worker`, `auto_stop`, `health_watchdog`) in eine Klasse
  `RunSession` mit injizierbaren `recorder`, `transcriber`, `hotkey_mgr`,
  `overlay`, `history` ziehen. `_run_cycle` baut nur noch zusammen. Dann:
  Test „Auto-Stop → nächster Druck startet sofort“, Test „leere Aufnahme bei
  totem Stream → `err_mic`“, Test „Worker löscht WAV auch bei Exception“.
  Nachweis: Coverage `app.py` > 60 %.

- [x] **D2 · Suite plattformunabhängig sammelbar machen** · S
  Fundstelle: `tests/conftest.py:12`
  Warum: Auf Linux/macOS scheitert schon das Sammeln (pynput braucht X,
  pystray ein Display, sounddevice PortAudio). Mit zwei Umgebungsvariablen
  läuft fast alles.
  Vorschlag: ganz oben in `conftest.py`, vor jedem Import:
  ```python
  os.environ.setdefault("PYNPUT_BACKEND", "dummy")
  os.environ.setdefault("PYSTRAY_BACKEND", "dummy")
  ```
  plus `pytest.importorskip("sounddevice")` in `test_audio.py` und
  `pytest.mark.skipif(sys.platform != "win32")` an den vier Windows-Tests
  (`test_logger.py` ×3, `test_transcriber.py::test_cli_cmd_…`). Im README
  unter „Build from source“ einen Satz dazu.
  Nachweis: `pytest` auf Linux: 0 failed.

- [x] **D3 · Überdeckungslücken mit gezielten Tests schließen** · M
  Fundstellen und Vorschläge:
  - `src/hardware.py:121-154` `detect_gpu`: Parsing der Registry-Ausgabe
    (NVIDIA vor AMD vor Intel, leere Ausgabe → cpu).
  - `src/config.py:95-105` `_validate`: `auto_stop_silence_s`-Clamping
    (0 bleibt 0, 0.5 → 1.5, 99 → 10, `True` → 0).
  - `src/text_processor.py:266-292` `_verify_authenticode` (siehe C2).
  - `src/text_inserter.py:37-42` `_wait_for_modifier_release` mit gemockter Uhr.
  Nachweis: Coverage gesamt > 45 %.

---

## E — Kleinkram (Priorität niedrig, je unter 15 min)

- [x] **E1** `src/app.py:217` — Fallback `"llama3.2:3b"` durch
  `text_processor.DEFAULT_MODEL` ersetzen (ist seit 1.6 `qwen2.5:3b`).
- [x] **E2** `THIRDPARTY-LICENSES.md:16-20` — Abschnitt „whisper.cpp Vulkan
  Build (Jerry Shell)“ entfernen, seit 1.8 Eigenbau aus Upstream-Source;
  `:77` „Python 3.14“ → „Python 3.12“ (CI-Build) oder „3.12+“.
- [x] **E3** `src/settings_gui.py:209` — `check_async` nur beim ersten
  `run()` je Prozess ausführen (Flag auf Modulebene), nicht bei jedem
  Sprachwechsel-Rebuild und jeder Rückkehr aus dem Tray.
- [x] **E4** `src/config.py:56` + `scripts/build.py:63` — entweder
  `DEFAULT_CONFIG_PATH` auf `sys._MEIPASS` zeigen lassen (dann wirkt die
  gebündelte YAML auch in der Exe) oder die `--add-data`-Zeile streichen
  (totes Gewicht). Empfehlung: streichen, `DEFAULT_CONFIG` ist die eine
  Wahrheit; die YAML bleibt als Doku im Repo.
- [x] **E5** `src/text_processor.py:49-84` — System-Prompts und Few-Shots sind
  deutsch. Für nicht-deutsche UI-Sprachen: Anweisungen auf Englisch
  formulieren („Keep the language of the input“), Few-Shot-Paare je
  Diktat-Sprache aus einer kleinen Tabelle wählen (de/en reichen als Start).
- [x] **E6** `src/filters.py:27-31` — Umlaute direkt im Code
  (`dankeschön`, `tschüss`); Rest des Projekts schreibt `ae/oe/ue`. Stilfrage,
  die Normalisierung in `_normalize` ist davon unberührt.

---

## Stand der Umsetzung (Branch `fix/audit-2026-10`)

Alle Punkte A–E umgesetzt, je Block ein Commit. Abweichungen vom Vorschlag:

- **A1:** `softprops/action-gh-release` auf v2.6.2 gepinnt (letzte v2), nicht auf
  das inzwischen erschienene v3 — Major-Update gern über Dependabot.
- **A4:** Vulkan-SHA-256 aus LunarGs Hash-API
  (`sdk.lunarg.com/sdk/sha/<version>/windows/...exe.json`); neuer Input
  `release_tag`, da ein SHA als `whisper_ref` sonst `backend-<sha>` ergäbe.
- **B1:** zusätzlich `update_config(**keys)` — der GPU-Cache-Thread schreibt nur
  noch seine drei Keys unter dem Lock.
- **B2:** eigene Exception `TranscriptionTimeout`; Overlay zeigt `ZU LANG`
  (neuer Key `overlay.too_long`) statt eines Dialogs.
- **B3:** nur der Hinweis; `SPECIAL_KEYS` nicht erweitert.
- **B5:** nur Doku (README-Troubleshooting).
- **B6:** `nvcuda.dll`-Variante; die Settings-Option schaltet Badge und
  Update-Button sofort um.
- **C1:** Helfer `winutil.system32()`.
- **C2:** CN `Ollama Inc.` am installierten `ollama.exe` abgelesen.
- **D1:** Klasse liegt in eigenem Modul `src/session.py` (ohne Tk/pystray-Importe).
  `session.py` 82 % abgedeckt; `app.py` selbst bleibt Bootstrap ohne Tests.
- **D2:** nicht auf Linux verifiziert (kein Docker/WSL verfügbar). `test_audio`
  fängt auch `OSError` (sounddevice ohne PortAudio).
- **D3:** Gesamtabdeckung 42 % statt > 45 % — der Rest steckt in GUI-Modulen
  (`settings_gui`, `overlay`, `tray`).
- **E5:** Deutsch behält die deutschen Prompts; alle anderen Sprachen bekommen
  englische Anweisungen + Few-Shots (`prompt_language()`).
- **E6:** Umlaute bleiben — Whisper liefert echte Umlaute, beide Varianten sind
  nötig; Kommentar ergänzt.

Manuell noch zu prüfen: Win-Taste in der Hotkey-Aufnahme (B3), Beschleunigungs-
Menü in den Settings (B6), Backend-Workflow gegen eine Test-Ref (A4).

## Erledigt im Audit-Branch (zur Erinnerung, nicht mehr offen)

- [x] Umschalt-Modus: Tasten-Auto-Repeat schaltete die Aufnahme sofort aus
- [x] Auto-Stop bei Stille: nächstes Diktat brauchte zwei Hotkey-Drücke; Stopp lief im Audio-Thread
- [x] Download-Abbruch meldete „Festplatte voll“; zweiter Klick startete Parallel-Thread
- [x] Download ohne Socket-Timeout
- [x] Nicht abbildbare Hotkey-Aufnahme wurde als toter Hotkey gespeichert
- [x] `config.default.yaml` um drei fehlende Keys ergänzt
