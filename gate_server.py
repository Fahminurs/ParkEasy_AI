# ============================================================
#  gate_server.py - ParkEasy Web Gate Server
#  Menggantikan main_app.py (Tkinter) dengan FastAPI + WebSocket
#
#  Cara menjalankan:
#      python gate_server.py
#
#  Dependensi tambahan:
#      pip install fastapi uvicorn[standard] websockets
# ============================================================

import asyncio
import base64
import json
import os
import re
import sys
import threading
import time
from datetime import datetime

import cv2
import serial
import uvicorn
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import (
    SERIAL_PORT, BAUD_RATE, SERIAL_TIMEOUT,
    GATE_ID_MASUK, GATE_ID_KELUAR,
    CAMERA_INDEX_MASUK, CAMERA_INDEX_KELUAR,
    SERVER_HOST, SERVER_PORT
)
from supabase_client import (
    find_vehicle,
    get_latest_session,
    create_session,
    insert_gate_log,
    calculate_bill,
    update_parking_slot,
    update_session_photos,
    update_session_exit
)
from anpr_service import run_anpr_on_image

# â"€â"€ App â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
app = FastAPI(title="ParkEasy Gate Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# â"€â"€ Global State â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
ser = None
cap_masuk = None
cap_keluar = None
running = True

is_processing_masuk = False
is_processing_keluar = False
consecutive_masuk = 0
consecutive_keluar = 0
pending_photos_masuk = {}
pending_photos_keluar = {}
pending_manual_actions = {}
recent_gate_events = {}
recent_gate_events_lock = threading.Lock()

distance_masuk = 0.0
distance_keluar = 0.0

# Sensor status yang dikirim ke web
sensor_state = {
    "hcsr04": {"status": "ok", "units": [
        {"name": "Sensor Masuk",  "value": "---", "unit": "cm", "status": "ok"},
        {"name": "Sensor Keluar", "value": "---", "unit": "cm", "status": "ok"},
    ]},
    "lcd": {"status": "ok", "units": [
        {"name": "LCD Masuk",  "value": "Siap", "unit": "", "status": "ok"},
        {"name": "LCD Keluar", "value": "Siap", "unit": "", "status": "ok"},
    ]},
    "buzzer": {"status": "ok", "units": [
        {"name": "Buzzer Masuk",  "value": "Aktif", "unit": "", "status": "ok"},
        {"name": "Buzzer Keluar", "value": "Aktif", "unit": "", "status": "ok"},
    ]},
    "servo": {"status": "ok", "units": [
        {"name": "Servo Masuk",  "value": "Tutup", "unit": "", "status": "ok"},
        {"name": "Servo Keluar", "value": "Tutup", "unit": "", "status": "ok"},
    ]},
    "tca": {"status": "ok", "units": [
        {"name": "VL53L1X - Slot A1", "value": "Terhubung", "unit": "", "status": "ok"},
        {"name": "VL53L1X - Slot A2", "value": "Terhubung", "unit": "", "status": "ok"},
        {"name": "VL53L1X - Slot B1", "value": "Terhubung", "unit": "", "status": "ok"},
    ]},
}

FOTO_DIR = r"D:\Website\Park Easy\Back-End\Foto_Parkir_Deteksi"
os.makedirs(FOTO_DIR, exist_ok=True)

# â"€â"€ WebSocket Connection Manager â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

manager = ConnectionManager()

# â"€â"€ Event loop helper (broadcast dari thread) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
_loop: asyncio.AbstractEventLoop | None = None

def broadcast_from_thread(data: dict):
    """Kirim pesan WebSocket dari background thread."""
    if _loop and _loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(data), _loop)

def log_broadcast(msg: str, level: str = "info"):
    """Kirim log ke semua web client."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")
    broadcast_from_thread({"type": "log", "time": timestamp, "msg": msg, "level": level})

def broadcast_hcsr04():
    broadcast_from_thread({
        "type": "hcsr04",
        "masuk": distance_masuk,
        "keluar": distance_keluar
    })

def broadcast_sensors():
    broadcast_from_thread({"type": "sensors", "data": sensor_state})


def mark_manual_action(gate: str, plate: str):
    """Simpan konteks aksi darurat hingga ESP32 mengirim status selesai."""
    pending_manual_actions[f"{gate}|{plate}"] = time.time()


def consume_manual_action(gate: str, plate: str) -> bool:
    """Ambil dan hapus penanda aksi darurat yang sudah dipicu sebelumnya."""
    return pending_manual_actions.pop(f"{gate}|{plate}", None) is not None


def should_skip_duplicate_gate_event(gate: str, plate: str, window_seconds: int = 5) -> bool:
    """Cegah event selesai yang sama diproses dua kali dalam waktu singkat."""
    now = time.time()
    key = f"{gate}|{plate}"
    with recent_gate_events_lock:
        last_time = recent_gate_events.get(key)
        recent_gate_events[key] = now

        # Bersihkan cache lama agar tidak terus membesar
        expired_keys = [k for k, ts in recent_gate_events.items() if now - ts > 60]
        for expired_key in expired_keys:
            if expired_key != key:
                recent_gate_events.pop(expired_key, None)

    return last_time is not None and (now - last_time) < window_seconds


def encode_frame_to_b64(frame, quality: int = 85) -> str:
    """Encode frame OpenCV menjadi base64 JPEG untuk disimpan sementara."""
    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError('Gagal encode frame JPEG')
    return base64.b64encode(buf.tobytes()).decode('ascii')


def capture_manual_photos(gate: str, plate: str):
    """Ambil foto terkini dari kamera gerbang untuk mode darurat."""
    global cap_masuk, cap_keluar, pending_photos_masuk, pending_photos_keluar

    camera = cap_masuk if gate == 'MASUK' else cap_keluar
    if not camera or not camera.isOpened():
        log_broadcast(f'[WARN] Kamera {gate.lower()} tidak aktif, foto darurat untuk {plate} dilewati.', 'warn')
        return

    frame = None
    for _ in range(3):
        ret, latest_frame = camera.read()
        if ret and latest_frame is not None:
            frame = latest_frame
            break
        time.sleep(0.1)

    if frame is None:
        log_broadcast(f'[WARN] Gagal mengambil foto darurat dari kamera {gate.lower()} untuk {plate}.', 'warn')
        return

    crop_b64 = ''
    proc_b64 = ''

    try:
        anpr_result = run_anpr_on_image(frame)
        plates = anpr_result.get('plates') or []
        if plates:
            best_plate = plates[0]
            crop_b64 = best_plate.get('crop_image') or ''
            proc_b64 = best_plate.get('processed_image') or ''
    except Exception as e:
        log_broadcast(f'[WARN] ANPR darurat gagal untuk {plate}: {e}', 'warn')

    if not crop_b64:
        crop_b64 = encode_frame_to_b64(frame)
    if not proc_b64:
        proc_b64 = crop_b64

    photo_payload = {
        'crop': crop_b64,
        'proc': proc_b64,
    }

    if gate == 'MASUK':
        pending_photos_masuk[plate] = photo_payload
    else:
        pending_photos_keluar[plate] = photo_payload

    log_broadcast(f'[OK] Foto darurat {gate.lower()} untuk {plate} berhasil diambil.', 'ok')


def restart_gate_server_process():
    """Restart proses gate_server.py setelah resource dilepas dengan aman."""
    global running, ser, cap_masuk, cap_keluar
    running = False

    try:
        if ser and ser.is_open:
            ser.close()
    except Exception:
        pass

    try:
        if cap_masuk and cap_masuk.isOpened():
            cap_masuk.release()
    except Exception:
        pass

    try:
        if cap_keluar and cap_keluar.isOpened():
            cap_keluar.release()
    except Exception:
        pass

    time.sleep(1.0)
    python_exe = sys.executable
    script_path = os.path.abspath(__file__)
    os.execv(python_exe, [python_exe, script_path])


def schedule_full_system_reset():
    """Reset ESP32 lalu restart ulang gate server di Laptop."""
    def worker():
        try:
            log_broadcast('[WARN] Reset sistem dimulai. Mengirim perintah reset ke ESP32...', 'warn')
            send_uart('reset')
            time.sleep(1.5)
            log_broadcast('[WARN] Merestart gate server di Laptop...', 'warn')
            restart_gate_server_process()
        except Exception as e:
            log_broadcast(f'[ERROR] Reset sistem gagal: {e}', 'error')

    threading.Thread(target=worker, daemon=True).start()


def trigger_manual_gate(gate: str, plate: str):
    """Trigger buka palang manual ke ESP32 melalui UART."""
    gate = (gate or "").strip().upper()
    plate = format_plate((plate or "").strip().upper())
    if gate not in {"MASUK", "KELUAR"}:
        raise ValueError("Gate tidak valid. Gunakan MASUK atau KELUAR.")
    if not plate:
        raise ValueError("Plat nomor wajib diisi.")
    if not ser or not ser.is_open:
        raise RuntimeError("Serial ESP32 tidak terhubung.")

    mark_manual_action(gate, plate)
    capture_manual_photos(gate, plate)

    now_str = datetime.now().strftime("%H:%M:%S")
    if gate == "MASUK":
        sensor_state["servo"]["units"][0]["value"] = "Buka"
        sensor_state["servo"]["status"] = "ok"
        broadcast_sensors()
        log_broadcast(f"[DARURAT] Membuka gerbang masuk untuk {plate}.", "warn")
        send_uart(f"MASUK:DARURAT|{plate}|{now_str}")
    else:
        sensor_state["servo"]["units"][1]["value"] = "Buka"
        sensor_state["servo"]["status"] = "ok"
        broadcast_sensors()
        log_broadcast(f"[DARURAT] Membuka gerbang keluar untuk {plate}.", "warn")
        send_uart(f"KELUAR:DARURAT|{plate}")


# â"€â"€ Helper: Format Plate â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def format_plate(text: str) -> str:
    text = text.replace(" ", "").replace("-", "")
    match = re.match(r'^([A-Z]{1,2})(\d{1,4})([A-Z]{1,3})$', text)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)}"
    return text

# â"€â"€ Helper: UART Send â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def send_uart(command: str):
    global ser
    if ser and ser.is_open:
        try:
            ser.write((command.strip() + "\n").encode("utf-8"))
            log_broadcast(f"-> ESP32: {command}", "uart")
        except Exception as e:
            log_broadcast(f"[ERROR] UART Error: {e}", "error")

def esp32_log_level(line: str) -> str:
    """Deteksi level log otomatis dari isi pesan ESP32."""
    l = line.lower()
    if "gagal" in l or "error" in l or "fail" in l:
        return "error"
    if "[ok]" in l or "siap" in l or "berhasil" in l:
        return "ok"
    if "[WARN]" in l or "peringatan" in l or "warn" in l:
        return "warn"
    return "info"

# â"€â"€ Sensor state update helper â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def update_sensor_from_esp(line: str):
    """
    Parse pesan inisialisasi ESP32 dan update sensor_state.
    Contoh pesan:
      [OK] Buzzer siap          -> buzzer semua unit OK
      [OK] Servo siap           -> servo semua unit OK
      [OK] LCD siap             -> lcd semua unit OK
      [OK] HCSR04 siap          -> hcsr04 semua unit OK
      [TOF] Gagal init sensor slot A2  -> tca channel 0 (Slot A) error
      [TOF] Gagal init sensor slot B1  -> tca channel 1 (Slot B) error
      [TOF] Gagal init sensor slot B2  -> tca channel 1 (Slot B) error
      [OK] TOF sensor siap      -> tca: channel yang belum error = ok
    """
    lower = line.lower()
    changed = False

    # â"€â"€ Deteksi jenis sensor â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    if "buzzer" in lower:
        key = "buzzer"
        if "[ok]" in lower:
            sensor_state[key]["status"] = "ok"
            for u in sensor_state[key]["units"]:
                u["status"] = "ok"
                u["value"]  = "Aktif"
            changed = True
        elif "gagal" in lower:
            sensor_state[key]["status"] = "error"
            for u in sensor_state[key]["units"]:
                u["status"] = "error"
                u["value"]  = "Gagal"
            changed = True

    elif "servo" in lower:
        key = "servo"
        if "[ok]" in lower:
            sensor_state[key]["status"] = "ok"
            for u in sensor_state[key]["units"]:
                u["status"] = "ok"
            changed = True
        elif "gagal" in lower or "rusak" in lower:
            sensor_state[key]["status"] = "error"
            for u in sensor_state[key]["units"]:
                u["status"] = "error"
            changed = True

    elif "lcd" in lower:
        key = "lcd"
        if "[ok]" in lower:
            sensor_state[key]["status"] = "ok"
            for u in sensor_state[key]["units"]:
                u["status"] = "ok"
                u["value"]  = "Siap"
            changed = True
        elif "gagal" in lower:
            sensor_state[key]["status"] = "error"
            for u in sensor_state[key]["units"]:
                u["status"] = "error"
                u["value"]  = "Gagal"
            changed = True

    elif "hcsr04" in lower:
        key = "hcsr04"
        if "[ok]" in lower:
            sensor_state[key]["status"] = "ok"
            for u in sensor_state[key]["units"]:
                u["status"] = "ok"
            changed = True
        elif "gagal" in lower:
            sensor_state[key]["status"] = "error"
            for u in sensor_state[key]["units"]:
                u["status"] = "error"
            changed = True

    elif "tof" in lower or "slot" in lower:
        key = "tca"
        # Mapping nama slot ESP32 -> index unit dalam tca.units
        # ESP32: slotCodes = {"A1", "A2", "B1"} pada channel TCA 2,3,4
        # Di sini index 0-2 mewakili Slot A1-A2 & B1 sesuai tof_sensor.h
        SLOT_CHANNEL = {
            "a1": 0, "a2": 1,
            "b1": 2,
        }

        if "gagal" in lower:
            # Cari nama slot spesifik: pola "slot XN" (contoh: slot A2, slot B1)
            m = re.search(r'slot\s+([a-d]\d)', lower)
            if m:
                slot_name = m.group(1)  # contoh: "a2", "b1"
                ch = SLOT_CHANNEL.get(slot_name)
                if ch is not None and ch < len(sensor_state[key]["units"]):
                    sensor_state[key]["units"][ch]["status"] = "error"
                    sensor_state[key]["units"][ch]["value"]  = "Gagal"
            else:
                # Tidak ada info slot spesifik -> error semua TOF unit
                for u in sensor_state[key]["units"]:
                    u["status"] = "error"
                    u["value"]  = "Gagal"
            sensor_state[key]["status"] = "error"
            changed = True

        elif "ok" in lower and "sensor slot" in lower:
            # "[TOF] OK sensor slot A2" - sensor kembali terhubung saat runtime
            m = re.search(r'slot\s+([a-d]\d)', lower)
            if m:
                slot_name = m.group(1)
                ch = {"a1": 0, "a2": 1, "b1": 2}.get(slot_name)
                if ch is not None and ch < len(sensor_state[key]["units"]):
                    sensor_state[key]["units"][ch]["status"] = "ok"
                    sensor_state[key]["units"][ch]["value"]  = "Terhubung"
            # Sync parent status
            tof_statuses = [u["status"] for u in sensor_state[key]["units"]]
            if all(s == "ok" for s in tof_statuses):
                sensor_state[key]["status"] = "ok"
            elif all(s == "error" for s in tof_statuses):
                sensor_state[key]["status"] = "error"
            else:
                sensor_state[key]["status"] = "warn"
            changed = True

        elif "[ok]" in lower and "siap" in lower:
            # "[OK] TOF sensor siap" - pesan akhir inisialisasi: unit yg belum error = ok
            for u in sensor_state[key]["units"]:
                if u["status"] != "error":
                    u["status"] = "ok"
                    u["value"]  = "Terhubung"
            tof_statuses = [u["status"] for u in sensor_state[key]["units"]]
            if all(s == "ok" for s in tof_statuses):
                sensor_state[key]["status"] = "ok"
            elif all(s == "error" for s in tof_statuses):
                sensor_state[key]["status"] = "error"
            else:
                sensor_state[key]["status"] = "warn"
            changed = True

    if changed:
        broadcast_sensors()

# â"€â"€ Logika Gerbang Masuk â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def proses_masuk_auto():
    global is_processing_masuk
    is_processing_masuk = True
    log_broadcast("[Gerbang Masuk] Mendeteksi kendaraan...", "info")
    send_uart("ANIM_KAMERA:MASUK")

    # Update servo state
    sensor_state["servo"]["units"][0]["value"] = "Buka"
    broadcast_sensors()

    def finish_task():
        global is_processing_masuk
        time.sleep(4)
        is_processing_masuk = False
        sensor_state["servo"]["units"][0]["value"] = "Tutup"
        broadcast_sensors()

    def db_task():
        time.sleep(1)

        if not cap_masuk or not cap_masuk.isOpened():
            log_broadcast("[ERROR] [Masuk] Kamera tidak aktif.", "error")
            send_uart("MASUK:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        ret, frame = cap_masuk.read()
        if not ret:
            log_broadcast("[ERROR] [Masuk] Gagal mengambil foto.", "error")
            send_uart("MASUK:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        anpr_result = run_anpr_on_image(frame)
        plates = anpr_result.get("plates", [])

        if not plates:
            log_broadcast("[ERROR] [Masuk] Tidak Terdeteksi Plat Nomor. Coba mundur atau maju.", "warn")
            send_uart("MASUK:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        plate_text = plates[0].get("plate_text", "")
        if not plate_text:
            log_broadcast("[ERROR] [Masuk] Plat terdeteksi YOLO tapi OCR gagal.", "warn")
            send_uart("MASUK:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        plate = format_plate(plate_text)
        log_broadcast(f"[OK] [Masuk] OCR Terbaca: {plate}", "ok")

        pending_photos_masuk[plate] = {
            "crop": plates[0].get("crop_image", ""),
            "proc": plates[0].get("processed_image", "")
        }

        send_uart("ANIM_DATABASE:MASUK")
        time.sleep(1)

        try:
            vehicle = find_vehicle(plate)
            if not vehicle:
                log_broadcast(f"[ERROR] [Masuk] {plate} Belum Terdaftar.", "error")
                send_uart(f"MASUK:GAGAL|{plate}|Belum Terdaftar!    ")
                threading.Thread(target=finish_task, daemon=True).start()
                return

            vehicle_id = vehicle["vehicle_id"]
            latest = get_latest_session(vehicle_id)
            if latest and latest["status"] == "aktif":
                log_broadcast(f"[WARN] [Masuk] {plate} Masih terdata di dalam (sesi aktif)!", "warn")
                send_uart(f"MASUK:GAGAL|{plate}|Sesi Masih Aktif!   ")
                threading.Thread(target=finish_task, daemon=True).start()
                return

            now_str = datetime.now().strftime("%H:%M:%S")
            log_broadcast(f"[OK] [Masuk] {plate} Valid! Palang dibuka. Menunggu mobil lewat...", "ok")
            send_uart(f"MASUK:BERHASIL|{plate}|{now_str}")

        except Exception as e:
            log_broadcast(f"[ERROR] [Masuk DB Err] {e}", "error")
            send_uart(f"MASUK:GAGAL|{plate}|Error Database!     ")

        threading.Thread(target=finish_task, daemon=True).start()

    threading.Thread(target=db_task, daemon=True).start()

# â"€â"€ Logika Gerbang Keluar â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def proses_keluar_auto():
    global is_processing_keluar
    is_processing_keluar = True
    log_broadcast("[Gerbang Keluar] Mendeteksi kendaraan...", "info")
    send_uart("ANIM_KAMERA:KELUAR")

    sensor_state["servo"]["units"][1]["value"] = "Buka"
    broadcast_sensors()

    def finish_task():
        global is_processing_keluar
        time.sleep(4)
        is_processing_keluar = False
        sensor_state["servo"]["units"][1]["value"] = "Tutup"
        broadcast_sensors()

    def db_task():
        time.sleep(1)

        if not cap_keluar or not cap_keluar.isOpened():
            log_broadcast("[ERROR] [Keluar] Kamera tidak aktif.", "error")
            send_uart("KELUAR:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        ret, frame = cap_keluar.read()
        if not ret:
            log_broadcast("[ERROR] [Keluar] Gagal mengambil foto.", "error")
            send_uart("KELUAR:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        anpr_result = run_anpr_on_image(frame)
        plates = anpr_result.get("plates", [])

        if not plates:
            log_broadcast("[ERROR] [Keluar] Tidak Terdeteksi Plat Nomor. Coba mundur atau maju.", "warn")
            send_uart("KELUAR:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        plate_text = plates[0].get("plate_text", "")
        if not plate_text:
            log_broadcast("[ERROR] [Keluar] Plat terdeteksi YOLO tapi OCR gagal.", "warn")
            send_uart("KELUAR:TIDAK_TERDETEKSI")
            threading.Thread(target=finish_task, daemon=True).start()
            return

        plate = format_plate(plate_text)
        log_broadcast(f"[OK] [Keluar] OCR Terbaca: {plate}", "ok")

        pending_photos_keluar[plate] = {
            "crop": plates[0].get("crop_image", ""),
            "proc": plates[0].get("processed_image", "")
        }

        send_uart("ANIM_DATABASE:KELUAR")
        time.sleep(1)

        try:
            vehicle = find_vehicle(plate)
            if not vehicle:
                log_broadcast(f"[ERROR] [Keluar] {plate} Tidak Dikenali.", "error")
                send_uart(f"KELUAR:GAGAL|{plate}|Tidak Terdaftar!    ")
                threading.Thread(target=finish_task, daemon=True).start()
                return

            vehicle_id = vehicle["vehicle_id"]
            latest = get_latest_session(vehicle_id)

            if not latest:
                log_broadcast(f"[ERROR] [Keluar] {plate} Tidak ada sesi sama sekali.", "error")
                send_uart(f"KELUAR:GAGAL|{plate}|Belum Ada Sesi!     ")
                threading.Thread(target=finish_task, daemon=True).start()
                return

            if latest["status"] == "selesai":
                log_broadcast(f"[OK] [Keluar] {plate} Sudah Bayar! Palang dibuka.", "ok")
                send_uart(f"KELUAR:BERHASIL|{plate}")
                threading.Thread(target=finish_task, daemon=True).start()
                return

            if latest["status"] == "aktif":
                total_minutes, duration_hours, total_price = calculate_bill(latest["entry_time"])
                log_broadcast(f"[WARN] [Keluar] {plate} Belum Bayar. Tagihan: Rp {total_price}", "warn")
                send_uart(f"KELUAR:BELUM_BAYAR|{plate}|{total_price}")
                threading.Thread(target=finish_task, daemon=True).start()
                return

        except Exception as e:
            log_broadcast(f"[ERROR] [Keluar DB Err] {e}", "error")
            send_uart(f"KELUAR:GAGAL|{plate}|Error Database!     ")

        threading.Thread(target=finish_task, daemon=True).start()

    threading.Thread(target=db_task, daemon=True).start()

# â"€â"€ Background Thread: UART Listener â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def uart_listener():
    global ser, consecutive_masuk, consecutive_keluar, distance_masuk, distance_keluar

    while running:
        if ser and ser.is_open:
            try:
                line = ser.readline().decode("utf-8").strip()
                if not line:
                    continue

                # â"€ LCD ERR/OK (I2C Ping) â"€
                if line == "[LCD_MASUK] ERR":
                    sensor_state["lcd"]["units"][0]["status"] = "error"
                    sensor_state["lcd"]["units"][0]["value"]  = "Gagal I2C"
                    sensor_state["lcd"]["status"] = "error"
                    broadcast_sensors()
                    log_broadcast("LCD Masuk: Terputus dari I2C!", "error")
                    continue
                if line == "[LCD_MASUK] OK":
                    sensor_state["lcd"]["units"][0]["status"] = "ok"
                    sensor_state["lcd"]["units"][0]["value"]  = "Siap"
                    all_ok = all(u["status"] == "ok" for u in sensor_state["lcd"]["units"])
                    sensor_state["lcd"]["status"] = "ok" if all_ok else "warn"
                    broadcast_sensors()
                    log_broadcast("LCD Masuk: Kembali Terhubung.", "ok")
                    continue
                if line == "[LCD_KELUAR] ERR":
                    sensor_state["lcd"]["units"][1]["status"] = "error"
                    sensor_state["lcd"]["units"][1]["value"]  = "Gagal I2C"
                    sensor_state["lcd"]["status"] = "error"
                    broadcast_sensors()
                    log_broadcast("LCD Keluar: Terputus dari I2C!", "error")
                    continue
                if line == "[LCD_KELUAR] OK":
                    sensor_state["lcd"]["units"][1]["status"] = "ok"
                    sensor_state["lcd"]["units"][1]["value"]  = "Siap"
                    all_ok = all(u["status"] == "ok" for u in sensor_state["lcd"]["units"])
                    sensor_state["lcd"]["status"] = "ok" if all_ok else "warn"
                    broadcast_sensors()
                    log_broadcast("LCD Keluar: Kembali Terhubung.", "ok")
                    continue

                # â"€ BUZZER MASUK ERR/OK (Koneksi Hardware) â"€
                if line == "[BUZZER_MASUK] ERR":
                    sensor_state["buzzer"]["units"][0]["status"] = "error"
                    sensor_state["buzzer"]["units"][0]["value"]  = "Disconnect"
                    sensor_state["buzzer"]["status"] = "error"
                    broadcast_sensors()
                    log_broadcast("Buzzer Masuk: Koneksi terputus / rusak!", "error")
                    continue
                if line == "[BUZZER_MASUK] OK":
                    sensor_state["buzzer"]["units"][0]["status"] = "ok"
                    sensor_state["buzzer"]["units"][0]["value"]  = "Aktif"
                    all_ok = all(u["status"] == "ok" for u in sensor_state["buzzer"]["units"])
                    sensor_state["buzzer"]["status"] = "ok" if all_ok else "warn"
                    broadcast_sensors()
                    log_broadcast("Buzzer Masuk: Terhubung.", "ok")
                    continue

                # â"€ BUZZER KELUAR ERR/OK (Koneksi Hardware) â"€
                if line == "[BUZZER_KELUAR] ERR":
                    sensor_state["buzzer"]["units"][1]["status"] = "error"
                    sensor_state["buzzer"]["units"][1]["value"]  = "Disconnect"
                    sensor_state["buzzer"]["status"] = "error"
                    broadcast_sensors()
                    log_broadcast("Buzzer Keluar: Koneksi terputus / rusak!", "error")
                    continue
                if line == "[BUZZER_KELUAR] OK":
                    sensor_state["buzzer"]["units"][1]["status"] = "ok"
                    sensor_state["buzzer"]["units"][1]["value"]  = "Aktif"
                    all_ok = all(u["status"] == "ok" for u in sensor_state["buzzer"]["units"])
                    sensor_state["buzzer"]["status"] = "ok" if all_ok else "warn"
                    broadcast_sensors()
                    log_broadcast("Buzzer Keluar: Terhubung.", "ok")
                    continue

                # SERVO Masuk Error/OK
                if "SERVO_MASUK" in line:
                    if "RUSAK" in line:
                        sensor_state["servo"]["units"][0]["status"] = "error"
                        sensor_state["servo"]["units"][0]["value"]  = "Lepas"
                        sensor_state["servo"]["status"] = "error"
                        broadcast_sensors()
                        log_broadcast("SERVO Masuk: Tidak terhubung - kabel servo dicabut atau rusak.", "error")
                    elif "Terhubung" in line:
                        sensor_state["servo"]["units"][0]["status"] = "ok"
                        sensor_state["servo"]["units"][0]["value"]  = "Tutup"
                        all_ok = all(u["status"] == "ok" for u in sensor_state["servo"]["units"])
                        sensor_state["servo"]["status"] = "ok" if all_ok else "warn"
                        broadcast_sensors()
                        if "KEMBALI" in line:
                            log_broadcast("SERVO Masuk: Terhubung kembali.", "ok")
                        else:
                            log_broadcast("SERVO Masuk: Terhubung.", "ok")
                    elif "Berfungsi normal" in line:
                        # Heartbeat periodik — hanya update jika belum ok
                        if sensor_state["servo"]["units"][0]["status"] != "ok":
                            sensor_state["servo"]["units"][0]["status"] = "ok"
                            sensor_state["servo"]["units"][0]["value"]  = "Tutup"
                            all_ok = all(u["status"] == "ok" for u in sensor_state["servo"]["units"])
                            sensor_state["servo"]["status"] = "ok" if all_ok else "warn"
                            broadcast_sensors()
                        log_broadcast("SERVO Masuk: Berfungsi normal.", "ok")
                    continue

                # SERVO Keluar Error/OK
                if "SERVO_KELUAR" in line:
                    if "RUSAK" in line:
                        sensor_state["servo"]["units"][1]["status"] = "error"
                        sensor_state["servo"]["units"][1]["value"]  = "Lepas"
                        sensor_state["servo"]["status"] = "error"
                        broadcast_sensors()
                        log_broadcast("SERVO Keluar: Tidak terhubung - kabel servo dicabut atau rusak.", "error")
                    elif "Terhubung" in line:
                        sensor_state["servo"]["units"][1]["status"] = "ok"
                        sensor_state["servo"]["units"][1]["value"]  = "Tutup"
                        all_ok = all(u["status"] == "ok" for u in sensor_state["servo"]["units"])
                        sensor_state["servo"]["status"] = "ok" if all_ok else "warn"
                        broadcast_sensors()
                        if "KEMBALI" in line:
                            log_broadcast("SERVO Keluar: Terhubung kembali.", "ok")
                        else:
                            log_broadcast("SERVO Keluar: Terhubung.", "ok")
                    elif "Berfungsi normal" in line:
                        # Heartbeat periodik — hanya update jika belum ok
                        if sensor_state["servo"]["units"][1]["status"] != "ok":
                            sensor_state["servo"]["units"][1]["status"] = "ok"
                            sensor_state["servo"]["units"][1]["value"]  = "Tutup"
                            all_ok = all(u["status"] == "ok" for u in sensor_state["servo"]["units"])
                            sensor_state["servo"]["status"] = "ok" if all_ok else "warn"
                            broadcast_sensors()
                        log_broadcast("SERVO Keluar: Berfungsi normal.", "ok")
                    continue

                # ── HCSR04 Masuk jarak ──
                if line.startswith("[HCSR04_MASUK]"):
                    # Cek sub-pesan non-angka terlebih dahulu
                    rest = line[len("[HCSR04_MASUK]"):].strip()
                    if "RUSAK" in rest:
                        sensor_state["hcsr04"]["units"][0]["status"] = "error"
                        sensor_state["hcsr04"]["units"][0]["value"]  = "Rusak"
                        sensor_state["hcsr04"]["status"] = "error"
                        broadcast_sensors()
                        log_broadcast("HCSR04 Masuk: Sensor RUSAK - Gagal membaca sensor.", "error")
                    elif "KEMBALI Terhubung" in rest:
                        sensor_state["hcsr04"]["units"][0]["status"] = "ok"
                        sensor_state["hcsr04"]["units"][0]["value"]  = "---"
                        all_ok = all(u["status"] == "ok" for u in sensor_state["hcsr04"]["units"])
                        sensor_state["hcsr04"]["status"] = "ok" if all_ok else "warn"
                        broadcast_sensors()
                        log_broadcast("HCSR04 Masuk: Sensor kembali terhubung.", "ok")
                    elif "Berfungsi normal" in rest:
                        if sensor_state["hcsr04"]["units"][0]["status"] != "ok":
                            sensor_state["hcsr04"]["units"][0]["status"] = "ok"
                            sensor_state["hcsr04"]["units"][0]["value"]  = "---"
                            all_ok = all(u["status"] == "ok" for u in sensor_state["hcsr04"]["units"])
                            sensor_state["hcsr04"]["status"] = "ok" if all_ok else "warn"
                            broadcast_sensors()
                        log_broadcast("HCSR04 Masuk: Berfungsi normal.", "ok")
                    else:
                        # Coba parse sebagai angka jarak
                        try:
                            dist = float(rest.split(" ")[0])
                            distance_masuk = dist
                            sensor_state["hcsr04"]["units"][0]["value"] = str(dist)
                            if sensor_state["hcsr04"]["units"][0]["status"] != "ok":
                                sensor_state["hcsr04"]["units"][0]["status"] = "ok"
                                sensor_state["hcsr04"]["status"] = "ok"
                                broadcast_sensors()
                            broadcast_hcsr04()
                            if not is_processing_masuk:
                                if 0 < dist <= 10:
                                    consecutive_masuk += 1
                                    if consecutive_masuk >= 2:
                                        consecutive_masuk = 0
                                        threading.Thread(target=proses_masuk_auto, daemon=True).start()
                                else:
                                    consecutive_masuk = 0
                        except Exception:
                            pass
                    continue

                # ── HCSR04 Keluar jarak ──
                elif line.startswith("[HCSR04_KELUAR]"):
                    rest = line[len("[HCSR04_KELUAR]"):].strip()
                    if "RUSAK" in rest:
                        sensor_state["hcsr04"]["units"][1]["status"] = "error"
                        sensor_state["hcsr04"]["units"][1]["value"]  = "Rusak"
                        sensor_state["hcsr04"]["status"] = "error"
                        broadcast_sensors()
                        log_broadcast("HCSR04 Keluar: Sensor RUSAK - Gagal membaca sensor.", "error")
                    elif "KEMBALI Terhubung" in rest:
                        sensor_state["hcsr04"]["units"][1]["status"] = "ok"
                        sensor_state["hcsr04"]["units"][1]["value"]  = "---"
                        all_ok = all(u["status"] == "ok" for u in sensor_state["hcsr04"]["units"])
                        sensor_state["hcsr04"]["status"] = "ok" if all_ok else "warn"
                        broadcast_sensors()
                        log_broadcast("HCSR04 Keluar: Sensor kembali terhubung.", "ok")
                    elif "Berfungsi normal" in rest:
                        if sensor_state["hcsr04"]["units"][1]["status"] != "ok":
                            sensor_state["hcsr04"]["units"][1]["status"] = "ok"
                            sensor_state["hcsr04"]["units"][1]["value"]  = "---"
                            all_ok = all(u["status"] == "ok" for u in sensor_state["hcsr04"]["units"])
                            sensor_state["hcsr04"]["status"] = "ok" if all_ok else "warn"
                            broadcast_sensors()
                        log_broadcast("HCSR04 Keluar: Berfungsi normal.", "ok")
                    else:
                        try:
                            dist = float(rest.split(" ")[0])
                            distance_keluar = dist
                            sensor_state["hcsr04"]["units"][1]["value"] = str(dist)
                            if sensor_state["hcsr04"]["units"][1]["status"] != "ok":
                                sensor_state["hcsr04"]["units"][1]["status"] = "ok"
                                sensor_state["hcsr04"]["status"] = "ok"
                                broadcast_sensors()
                            broadcast_hcsr04()
                            if not is_processing_keluar:
                                if 0 < dist <= 10:
                                    consecutive_keluar += 1
                                    if consecutive_keluar >= 2:
                                        consecutive_keluar = 0
                                        threading.Thread(target=proses_keluar_auto, daemon=True).start()
                                else:
                                    consecutive_keluar = 0
                        except Exception:
                            pass
                    continue

                # ── Slot VL53L1X ──
                if line.startswith("SLOT:"):
                    parts = line.split(":")
                    if len(parts) == 3:
                        slot_code, status = parts[1].upper(), parts[2]
                        slot_map = {"A1": 0, "A2": 1, "B1": 2}
                        idx = slot_map.get(slot_code)
                        if idx is not None and idx < len(sensor_state["tca"]["units"]):
                            sensor_state["tca"]["units"][idx]["value"] = "Terisi" if status == "DITEMPATI" else "Kosong"
                        broadcast_sensors()
                        log_broadcast(f"VL53L1X: Slot {slot_code} -> {status}", "info")

                        def update_db(sc, st):
                            try:
                                update_parking_slot(sc, st)
                                log_broadcast(f"[OK] DB Update: Slot {sc} {st}", "ok")
                            except Exception as e:
                                log_broadcast(f"[ERROR] DB Error: {e}", "error")
                        threading.Thread(target=update_db, args=(slot_code, status), daemon=True).start()

                # â"€ Heartbeat â"€
                elif line.startswith("[HEARTBEAT]"):
                    # ESP32 masih aktif - tidak perlu update sensor, cukup abaikan
                    continue

                # â"€ Konfirmasi Masuk Selesai â"€
                elif line.startswith("MASUK:SELESAI|"):
                    plate = line.split("|")[1]
                    log_broadcast(f"HCSR04: Mobil {plate} telah masuk! Menyimpan data...", "ok")

                    def finalize_masuk(p=plate):
                        try:
                            if should_skip_duplicate_gate_event("MASUK", p):
                                log_broadcast(f"[WARN] Event masuk duplikat diabaikan untuk {p}.", "warn")
                                return
                            photo_crop_name = None
                            photo_proc_name = None
                            if p in pending_photos_masuk:
                                photos = pending_photos_masuk[p]
                                ts = int(time.time())
                                safe = p.replace(" ", "")
                                if photos["crop"]:
                                    photo_crop_name = f"masuk_{ts}_{safe}_crop.jpg"
                                    with open(os.path.join(FOTO_DIR, photo_crop_name), "wb") as f:
                                        f.write(base64.b64decode(photos["crop"]))
                                if photos["proc"]:
                                    photo_proc_name = f"masuk_{ts}_{safe}_proc.jpg"
                                    with open(os.path.join(FOTO_DIR, photo_proc_name), "wb") as f:
                                        f.write(base64.b64decode(photos["proc"]))
                                del pending_photos_masuk[p]
                            vehicle = find_vehicle(p)
                            if vehicle:
                                is_manual_masuk = consume_manual_action("MASUK", p)
                                latest = get_latest_session(vehicle["vehicle_id"])
                                session = latest if latest and latest["status"] == "aktif" else None
                                if session is None:
                                    session = create_session(vehicle["vehicle_id"], vehicle["user_id"], photo_crop_name, photo_proc_name)
                                elif photo_crop_name or photo_proc_name:
                                    update_session_photos(session["session_id"], photo_crop_name, photo_proc_name, is_masuk=True)

                                event_type = "MANUAL_BUKA" if is_manual_masuk else "MASUK"
                                insert_gate_log(GATE_ID_MASUK, session["session_id"], p, event_type)
                                if is_manual_masuk:
                                    log_broadcast(f"[OK] DB: Darurat masuk {p} berhasil dicatat!", "ok")
                                else:
                                    log_broadcast(f"[OK] DB: Data parkir {p} berhasil disimpan!", "ok")
                                broadcast_from_thread({"type": "stats_refresh"})
                        except Exception as e:
                            log_broadcast(f"[ERROR] DB: {e}", "error")
                    threading.Thread(target=finalize_masuk, daemon=True).start()

                # â"€ Konfirmasi Keluar Selesai â"€
                elif line.startswith("KELUAR:SELESAI|"):
                    plate = line.split("|")[1]
                    log_broadcast(f"HCSR04: Mobil {plate} telah keluar! Menyimpan log...", "ok")

                    def finalize_keluar(p=plate):
                        try:
                            if should_skip_duplicate_gate_event("KELUAR", p):
                                log_broadcast(f"[WARN] Event keluar duplikat diabaikan untuk {p}.", "warn")
                                return
                            vehicle = find_vehicle(p)
                            if vehicle:
                                latest = get_latest_session(vehicle["vehicle_id"])
                                is_manual_keluar = consume_manual_action("KELUAR", p)
                                if latest and (latest["status"] == "selesai" or is_manual_keluar):
                                    photo_crop_name = None
                                    photo_proc_name = None
                                    if p in pending_photos_keluar:
                                        photos = pending_photos_keluar[p]
                                        ts = int(time.time())
                                        safe = p.replace(" ", "")
                                        if photos["crop"]:
                                            photo_crop_name = f"keluar_{ts}_{safe}_crop.jpg"
                                            with open(os.path.join(FOTO_DIR, photo_crop_name), "wb") as f:
                                                f.write(base64.b64decode(photos["crop"]))
                                        if photos["proc"]:
                                            photo_proc_name = f"keluar_{ts}_{safe}_proc.jpg"
                                            with open(os.path.join(FOTO_DIR, photo_proc_name), "wb") as f:
                                                f.write(base64.b64decode(photos["proc"]))
                                        del pending_photos_keluar[p]

                                    if photo_crop_name or photo_proc_name:
                                        update_session_photos(latest["session_id"], photo_crop_name, photo_proc_name, is_masuk=False)

                                    if is_manual_keluar and latest["status"] == "aktif":
                                        _total_minutes, duration_hours, total_price = calculate_bill(latest["entry_time"])
                                        update_session_exit(
                                            latest["session_id"],
                                            status="selesai",
                                            duration_hours=duration_hours,
                                            total_price=total_price,
                                        )
                                        insert_gate_log(GATE_ID_KELUAR, latest["session_id"], p, "MANUAL_BUKA")
                                        log_broadcast(f"[OK] DB: Darurat keluar {p} berhasil dicatat!", "ok")
                                    else:
                                        update_session_exit(latest["session_id"])
                                        insert_gate_log(GATE_ID_KELUAR, latest["session_id"], p, "KELUAR")
                                        log_broadcast(f"[OK] DB: Log keluar {p} disimpan beserta fotonya!", "ok")
                                    broadcast_from_thread({"type": "stats_refresh"})
                        except Exception as e:
                            log_broadcast(f"[ERROR] DB: {e}", "error")
                    threading.Thread(target=finalize_keluar, daemon=True).start()

                else:
                    # Pesan umum ESP32 - deteksi level otomatis lalu update sensor
                    lvl = esp32_log_level(line)
                    log_broadcast(f"ESP32: {line}", lvl)
                    update_sensor_from_esp(line)

            except Exception:
                pass
        time.sleep(0.01)

# â"€â"€ MJPEG Camera Stream â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def generate_frames(cap: cv2.VideoCapture):
    while running:
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buf.tobytes() +
                        b"\r\n"
                    )
        time.sleep(0.033)  # ~30 fps

@app.get("/stream/masuk")
def stream_masuk():
    return StreamingResponse(
        generate_frames(cap_masuk),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/stream/keluar")
def stream_keluar():
    return StreamingResponse(
        generate_frames(cap_keluar),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# â"€â"€ Health Check â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.post("/manual/open")
def manual_open(payload: dict = Body(...)):
    gate = payload.get("gate")
    plate = payload.get("plate")
    trigger_manual_gate(gate, plate)
    return {
        "ok": True,
        "gate": (gate or "").strip().upper(),
        "plate": format_plate((plate or "").strip().upper()),
    }

@app.post("/system/reset")
def system_reset(payload: dict = Body(None)):
    keyword = ((payload or {}).get('keyword') or '').strip().upper()
    if keyword != 'RESET':
        return {
            'ok': False,
            'message': 'Keyword reset tidak valid. Ketik RESET untuk melanjutkan.',
        }

    schedule_full_system_reset()
    return {
        'ok': True,
        'message': 'Reset ESP32 dan Laptop sedang diproses.',
    }

@app.get("/status")
def status():
    return {
        "ok": True,
        "serial": ser.is_open if ser else False,
        "cam_masuk": cap_masuk.isOpened() if cap_masuk else False,
        "cam_keluar": cap_keluar.isOpened() if cap_keluar else False,
    }

# â"€â"€ WebSocket Endpoint â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Kirim state awal saat client connect
    await ws.send_text(json.dumps({"type": "sensors", "data": sensor_state}))
    await ws.send_text(json.dumps({
        "type": "hcsr04",
        "masuk": distance_masuk,
        "keluar": distance_keluar
    }))
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        await manager.disconnect(ws)

# â"€â"€ Startup â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.on_event("startup")
async def startup():
    global _loop, ser, cap_masuk, cap_keluar

    _loop = asyncio.get_running_loop()

    # Init Kamera
    cap_masuk = cv2.VideoCapture(CAMERA_INDEX_MASUK, cv2.CAP_DSHOW)
    if not cap_masuk.isOpened():
        print(f"[WARN] Kamera Masuk (index {CAMERA_INDEX_MASUK}) tidak ditemukan, fallback ke 1")
        cap_masuk = cv2.VideoCapture(1, cv2.CAP_DSHOW)

    cap_keluar = cv2.VideoCapture(CAMERA_INDEX_KELUAR, cv2.CAP_DSHOW)
    if not cap_keluar.isOpened():
        print(f"[WARN] Kamera Keluar (index {CAMERA_INDEX_KELUAR}) tidak ditemukan, fallback ke 1")
        cap_keluar = cv2.VideoCapture(1, cv2.CAP_DSHOW)

    # Init Serial
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=SERIAL_TIMEOUT)
        print(f"[OK] Serial terhubung di {SERIAL_PORT}")
        log_broadcast(f"Sistem terhubung ke {SERIAL_PORT}. Menunggu deteksi kendaraan...", "ok")
    except serial.SerialException as e:
        print(f"[ERROR] Gagal buka serial: {e}")
        log_broadcast(f"[ERROR] Gagal buka serial {SERIAL_PORT}: {e}", "error")

    # Start UART listener thread
    threading.Thread(target=uart_listener, daemon=True).start()

@app.on_event("shutdown")
async def shutdown():
    global running
    running = False
    if ser and ser.is_open:
        ser.close()
    if cap_masuk and cap_masuk.isOpened():
        cap_masuk.release()
    if cap_keluar and cap_keluar.isOpened():
        cap_keluar.release()

# â"€â"€ Entry Point â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
if __name__ == "__main__":
    uvicorn.run("gate_server:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)


