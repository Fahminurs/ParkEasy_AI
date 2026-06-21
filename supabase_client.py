# ============================================================
#  supabase_client.py â€” Wrapper HTTP Request ke Supabase REST
# ============================================================
import requests
import re
from datetime import datetime, timezone
from config import SUPABASE_URL, SUPABASE_ANON_KEY, LOCATION_ID, REQUEST_TIMEOUT


# â”€â”€ Header standar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _headers() -> dict:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _get(endpoint: str, params: dict = None):
    """HTTP GET ke Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, body: dict):
    """HTTP POST ke Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    resp = requests.post(url, headers=_headers(), json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# â”€â”€ Fungsi Kendaraan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _format_plate_number_for_log(plate_number: str) -> str:
    """Format plat agar konsisten menjadi contoh: AB 123 AR."""
    text = (plate_number or "").strip().upper().replace(" ", "").replace("-", "")
    match = re.match(r'^([A-Z]{1,2})(\d{1,4})([A-Z]{1,3})$', text)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)}"
    return (plate_number or "").strip().upper()

def find_vehicle(plate_number: str) -> dict | None:
    """
    Cari kendaraan berdasarkan plate_number (sudah dinormalisasi).
    Mengembalikan dict vehicle atau None jika tidak ditemukan.
    """
    rows = _get("vehicles", params={
        "plate_number": f"eq.{plate_number}",
        "select": "vehicle_id,user_id,plate_number,vehicle_name",
        "limit": "1",
    })
    return rows[0] if rows else None


# â”€â”€ Fungsi Sesi Parkir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_latest_session(vehicle_id: str) -> dict | None:
    """
    Cari sesi parkir terakhir untuk kendaraan tertentu (apapun statusnya).
    Ini penting agar gerbang keluar mengecek sesi SAAT INI, bukan sesi lama yang sudah dibayar.
    """
    rows = _get("parking_sessions", params={
        "vehicle_id": f"eq.{vehicle_id}",
        "select": "session_id,status,entry_time,total_price",
        "order": "entry_time.desc",
        "limit": "1",
    })
    return rows[0] if rows else None


def create_session(vehicle_id: str, user_id: str, photo_crop: str = None, photo_processed: str = None) -> dict:
    """
    Buat sesi parkir baru dengan status 'aktif' dan entry_time sekarang.
    Mengembalikan dict session yang baru dibuat.
    """
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "vehicle_id":  vehicle_id,
        "user_id":     user_id,
        "location_id": LOCATION_ID,
        "status":      "aktif",
        "entry_time":  now,
        "total_price": 0,
    }
    if photo_crop:
        body["photo_in_crop"] = photo_crop
    if photo_processed:
        body["photo_in_processed"] = photo_processed
        
    result = _post("parking_sessions", body)
    return result[0] if isinstance(result, list) else result

def update_session_photos(session_id: str, photo_crop: str, photo_processed: str, is_masuk: bool):
    """
    Update field foto (crop & processed) pada parking_sessions.
    is_masuk=True -> update photo_in_crop, photo_in_processed
    is_masuk=False -> update photo_out_crop, photo_out_processed
    """
    body = {}
    if is_masuk:
        body["photo_in_crop"] = photo_crop
        body["photo_in_processed"] = photo_processed
    else:
        body["photo_out_crop"] = photo_crop
        body["photo_out_processed"] = photo_processed
        
    url = f"{SUPABASE_URL}/rest/v1/parking_sessions?session_id=eq.{session_id}"
    resp = requests.patch(url, headers=_headers(), json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()



def update_session_exit(session_id: str, status: str = None,
                        duration_hours: int = None, total_price: int = None):
    """
    Isi exit_time saat kendaraan benar-benar sudah melewati gerbang keluar.
    Dapat sekaligus menutup sesi darurat agar kendaraan bisa masuk lagi.
    """
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "exit_time": now,
        "updated_at": now,
    }
    if status is not None:
        body["status"] = status
    if duration_hours is not None:
        body["duration_hours"] = duration_hours
    if total_price is not None:
        body["total_price"] = total_price
    url = f"{SUPABASE_URL}/rest/v1/parking_sessions?session_id=eq.{session_id}"
    resp = requests.patch(url, headers=_headers(), json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


# â”€â”€ Fungsi Gate Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def insert_gate_log(gate_id: str, session_id: str | None,
                    plate_number: str, event_type: str) -> dict:
    """
    Catat event gerbang ke tabel gate_logs.
    event_type: 'MASUK' | 'KELUAR' | 'MANUAL_BUKA'
    """
    body = {
        "gate_id":      gate_id,
        "session_id":   session_id,
        "plate_number": _format_plate_number_for_log(plate_number),
        "event_type":   event_type,
    }
    result = _post("gate_logs", body)
    return result[0] if isinstance(result, list) else result


# â”€â”€ Fungsi Tarif & Durasi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_price_per_hour() -> int:
    """Ambil tarif parkir per jam dari parking_locations."""
    rows = _get("parking_locations", params={
        "location_id": f"eq.{LOCATION_ID}",
        "select": "price_per_hour",
        "limit": "1",
    })
    return rows[0]["price_per_hour"] if rows else 5000  # fallback 5000


def calculate_bill(entry_time_str: str) -> tuple[int, int, int]:
    """
    Hitung durasi dan tagihan dari entry_time.
    Returns:
        (total_minutes, duration_hours_ceil, total_price)
    """
    import math
    
    # Supabase mengembalikan format: '2026-05-10T19:29:57.12334+00:00' atau berakhiran 'Z'
    # fromisoformat() di Python lawas tidak bisa memparsing fraction 5 digit dengan baik.
    # Jadi kita hilangkan timezone offset dan fraction detiknya agar aman:
    clean_str = entry_time_str.replace("Z", "+00:00").split("+")[0].split(".")[0]
    entry_dt = datetime.fromisoformat(clean_str).replace(tzinfo=timezone.utc)
    
    now_dt   = datetime.now(timezone.utc)
    delta    = now_dt - entry_dt
    total_minutes = int(delta.total_seconds() / 60)
    duration_hours_ceil = math.ceil(total_minutes / 60) or 1  # minimal 1 jam
    price_per_hour = get_price_per_hour()
    total_price = duration_hours_ceil * price_per_hour
    return total_minutes, duration_hours_ceil, total_price


def update_parking_slot(slot_code: str, status: str):
    """
    Update status slot parkir berdasarkan data TOF (TERSEDIA / DITEMPATI).
    """
    body = {"status": status}
    url = f"{SUPABASE_URL}/rest/v1/parking_slots?slot_code=eq.{slot_code}"
    resp = requests.patch(url, headers=_headers(), json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

