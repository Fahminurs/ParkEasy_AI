# ParkEasy AI: terminal recording

`parkeasy-ai.cast` is an [asciinema](https://asciinema.org) v2 recording of `python gate_server.py`
running from this repo. It was captured on 2026-10-29 in a headless Linux sandbox (Python 3.13, asciinema 2.4.0):

```
asciinema rec --cols 100 --rows 28 --idle-time-limit 1.5 -c "bash --noprofile --norc -i" portfolio-cast/parkeasy-ai.cast
```

- **Length:** 30.7 s of playback. `--idle-time-limit 1.5` caps each pause at 1.5 s; that is asciinema's own option, applied while recording.
- **Size:** about 5 KB, 64 output events.
- **Not edited:** the event stream is exactly what asciinema wrote. Nothing was cut, re-timed or retouched.

The shell is a real interactive bash. A small driver script typed into it through a pty: the
keystrokes `python gate_server.py⏎`, then a real Ctrl+C (the `^C` you see), then `exit`. The prompt
`fahmi@parkeasy:~/ParkEasy_AI$` is a custom `PS1` set for the recording, not the sandbox's real hostname.

## What was real and what was simulated

`gate_server.py` and the rest of the repo's code ran **unmodified**. A `sitecustomize.py` on
`PYTHONPATH` swapped in stand-ins for the hardware and assets that the sandbox doesn't have, before the
server started. These are the same stand-ins used for `../portfolio-screenshots/`. None of the
launcher or stub code is committed.

| Missing in sandbox | Stand-in used |
|---|---|
| USB cameras (`cv2.VideoCapture(index, CAP_DSHOW)`) | a looping **synthetic test video** (a drawn car with the fake plate `B 1234 TES`, labelled "SYNTHETIC TEST FEED" in the frame) |
| ESP32 on `COM3` | a Linux **pty** (`/dev/pts/0` in the log), driven by a script that sends real protocol lines (`[HCSR04_MASUK] 7.9`, `SLOT:A1:DITEMPATI`, …) |
| Supabase | a dummy unreachable URL (`http://supabase.invalid`), so DB calls fail. The real project was never contacted. |
| YOLOv8 `best.pt` (gitignored, so not in the repo) | a placeholder that returns **no detections** (it prints the `[STUB] YOLO …` line) |
| PaddleOCR models | a placeholder that returns nothing (it prints the `[STUB] PaddleOCR …` line). The sandbox's network policy blocks the model download hosts. |

**YOLO and PaddleOCR never ran in this recording**, so it shows no real model output.

## What happens in the recording

| Time in log | What you see | Real or not |
|---|---|---|
| boot | The `[STUB]` lines, then two FastAPI `on_event is deprecated` warnings, then uvicorn startup, `[OK] Serial terhubung di /dev/pts/0` | Real output. The warnings come from the installed FastAPI version. |
| 09:41:34–38 | LCD / Buzzer / Servo handshakes (`LCD Masuk: Kembali Terhubung.`, …) and `ESP32: [OK] TOF sensor siap` | The server's parsing and log lines are real. The ESP32 lines that trigger them are scripted. |
| 09:41:40–43 | `VL53L1X: Slot A1 -> DITEMPATI`, `A2 -> KOSONG`, `B1 -> DITEMPATI`, each followed by `[ERROR] DB Error: … supabase.invalid …` | Real handling. The DB errors are real failures against the dummy URL. They were left in because the recording is unedited. |
| 09:41:47–48 | HC-SR04 distance at the entry gate drops 96.4 → 42.0 → 18.5 → 8.3 → 7.9 cm. The server triggers `[Gerbang Masuk] Mendeteksi kendaraan...` and sends `ANIM_KAMERA:MASUK` over UART. One second later it sends `MASUK:TIDAK_TERDETEKSI` | The trigger logic and UART replies are real. The distances are scripted, and the distance lines don't appear in the log because the server only broadcasts them over WebSocket. "Tidak Terdeteksi Plat Nomor" is shown because the YOLO stand-in returns nothing. |
| 09:41:54 | Emergency open: `[OK] Foto darurat masuk …`, `[DARURAT] Membuka gerbang masuk untuk B 1234 TES.`, UART `MASUK:DARURAT\|B 1234 TES\|09:41:54`, then `POST /manual/open … 200 OK` | Real. It was started from a second shell (not visible in the recording) with `curl -X POST http://127.0.0.1:8765/manual/open -d '{"gate":"MASUK","plate":"B1234TES"}'`, which returned `{"ok":true,"gate":"MASUK","plate":"B 1234 TES"}`. The "photo" is a frame from the synthetic video. |
| end | `^C`, then uvicorn shuts down cleanly (`Shutting down` … `Finished server process`), then `exit` | Real |

On the ESP32 side the pty received exactly three lines from the server: `ANIM_KAMERA:MASUK`,
`MASUK:TIDAK_TERDETEKSI` and `MASUK:DARURAT|B 1234 TES|09:41:54`.

## Playing it

```
asciinema play portfolio-cast/parkeasy-ai.cast
```

Or load it with [asciinema-player](https://github.com/asciinema/asciinema-player) on a web page.
