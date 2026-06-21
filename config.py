# ============================================================
#  config.py — Konfigurasi Sistem Gerbang Parkir ParkEasy
# ============================================================
# Ganti nilai di bawah jika port / ID berubah.

# --- Supabase ---
SUPABASE_URL = "https://jjgtdimfjjigzrbzwrch.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpqZ3RkaW1mamppZ3pyYnp3cmNoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY1MDcwNTQsImV4cCI6MjA5MjA4MzA1NH0."
    "Kmv2SkQA-d57DGhHlkVO42aKZzzC-afygwdSAhzMv2I"
)

# --- ID Tetap (hardcoded dari Supabase) ---
LOCATION_ID   = "1835b728-7640-46fe-9e57-96e7511fafd3"   # Parkir Mall Central
GATE_ID_MASUK = "8153d381-69ef-41ca-abf4-d4c4365f36d1"   # GT-IN-01
GATE_ID_KELUAR = "aa1609e8-f3a8-4f51-9bbd-56cd5a2e2d33"  # GT-OUT-01

# --- UART / Serial ---
# Ganti dengan port COM ESP32 Anda (cek Device Manager → Ports)
SERIAL_PORT  = "COM3"
BAUD_RATE    = 115200
SERIAL_TIMEOUT = 3  # detik

# --- Timeout & Tampilan ---
REQUEST_TIMEOUT = 10  # detik untuk HTTP request ke Supabase

# --- Pengaturan Kamera ---
# Ubah angka index di bawah ini sesuai dengan urutan USB Camera Anda (0, 1, 2, dst)
CAMERA_INDEX_MASUK = 1
CAMERA_INDEX_KELUAR = 0

# --- Gate Web Server ---
# Alamat dan port server gate_server.py
SERVER_HOST = "0.0.0.0"   # 0.0.0.0 = bisa diakses dari mana saja di jaringan lokal
SERVER_PORT = 8765
