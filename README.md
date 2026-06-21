
<p align="center">

```
                    ╔══════════════════════════════════════════════════════╗
                    ║                                                      ║
                    ║        ██████╗  █████╗ ██████╗ ██╗  ██╗              ║
                    ║        ██╔══██╗██╔══██╗██╔══██╗██║ ██╔╝              ║
                    ║        ██████╔╝███████║██████╔╝█████╔╝               ║
                    ║        ██╔═══╝ ██╔══██║██╔══██╗██╔═██╗               ║
                    ║        ██║     ██║  ██║██║  ██║██║  ██╗              ║
                    ║        ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝              ║
                    ║                                                      ║
                    ║    ███████╗ █████╗ ███████╗██╗   ██╗                  ║
                    ║    ██╔════╝██╔══██╗██╔════╝╚██╗ ██╔╝                  ║
                    ║    █████╗  ███████║███████╗ ╚████╔╝                   ║
                    ║    ██╔══╝  ██╔══██║╚════██║  ╚██╔╝                    ║
                    ║    ███████╗██║  ██║███████║   ██║                     ║
                    ║    ╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝                     ║
                    ║                                                      ║
                    ║          🤖  A I   E N G I N E  🧠                   ║
                    ║                                                      ║
                    ║    ┌─────────────────────────────────────────────┐    ║
                    ║    │  Automatic Number Plate Recognition System  │    ║
                    ║    │     Powered by YOLOv8 + PaddleOCR          │    ║
                    ║    └─────────────────────────────────────────────┘    ║
                    ║                                                      ║
                    ╚══════════════════════════════════════════════════════╝
```

</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/OpenCV-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white" alt="OpenCV"/>
  <img src="https://img.shields.io/badge/YOLOv8-FF6F00?style=for-the-badge&logo=yolo&logoColor=white" alt="YOLOv8"/>
  <img src="https://img.shields.io/badge/Supabase-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white" alt="Supabase"/>
  <img src="https://img.shields.io/badge/ESP32-E7352C?style=for-the-badge&logo=espressif&logoColor=white" alt="ESP32"/>
  <img src="https://img.shields.io/badge/WebSocket-010101?style=for-the-badge&logo=socketdotio&logoColor=white" alt="WebSocket"/>
  <img src="https://img.shields.io/badge/PaddleOCR-0062B0?style=for-the-badge&logo=paddlepaddle&logoColor=white" alt="PaddleOCR"/>
</p>

<p align="center">
  <b>🚗 Sistem Pengenalan Plat Nomor Otomatis & Kontrol Gerbang Parkir Cerdas 🚗</b>
</p>

---

## 📋 Deskripsi

**ParkEasy AI** adalah *otak kecerdasan buatan* dari ekosistem **ParkEasy** — sebuah sistem parkir pintar yang terintegrasi penuh. Modul ini bertugas sebagai **mesin ANPR (Automatic Number Plate Recognition)** dan **pengendali gerbang parkir** yang berjalan di sisi server (laptop/PC).

Sistem ini menangkap gambar kendaraan melalui kamera, mendeteksi plat nomor menggunakan **YOLOv8**, membaca teks plat dengan **PaddleOCR**, memvalidasi kendaraan melalui database **Supabase**, lalu mengirimkan perintah buka/tutup gerbang ke mikrokontroler **ESP32** melalui komunikasi **UART Serial**.

> 💡 *Bagian ini adalah komponen AI/Backend dari sistem ParkEasy yang lebih besar, yang juga mencakup [Front-End Web](https://github.com/Fahminurs/Parkeasy-FrontEnd), [Back-End API](https://github.com/Fahminurs/ParkEasy-BackEnd), dan firmware ESP32.*

---

## ✨ Fitur Utama

| Fitur | Deskripsi |
|:------|:----------|
| 🔍 **ANPR dengan YOLOv8 + PaddleOCR** | Deteksi plat nomor kendaraan Indonesia secara real-time dengan koreksi karakter otomatis |
| 📷 **Streaming Kamera Real-Time** | MJPEG stream dari 2 kamera (gerbang masuk & keluar) via HTTP endpoint |
| 🌐 **WebSocket Communication** | Broadcast status sensor, log, dan event ke dashboard web secara real-time |
| 🔌 **Serial UART ke ESP32** | Komunikasi dua arah dengan mikrokontroler untuk kontrol palang, sensor ultrasonik, LCD, buzzer, dan servo |
| 🚧 **Logika Gerbang Otomatis** | Deteksi kendaraan → ANPR → Validasi database → Buka palang → Konfirmasi lewat → Simpan log |
| 🅿️ **Monitoring Slot Parkir** | Integrasi sensor VL53L1X (ToF) via ESP32 untuk deteksi ketersediaan slot real-time |
| 🆘 **Mode Darurat (Manual Override)** | Pembukaan palang manual via API dengan tetap mencatat log dan foto |
| 🔄 **System Reset** | Reset ESP32 dan restart server secara remote via API endpoint |
| 🖼️ **Perspective Correction** | Koreksi perspektif plat miring menggunakan deteksi sudut multi-strategi (Canny, OTSU, MinAreaRect) |
| 🌙 **Dukungan Plat Gelap** | Deteksi otomatis plat berwarna gelap dan inversi adaptif untuk akurasi OCR maksimal |

---

## 🏗️ Arsitektur Sistem

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        🏢 ARSITEKTUR PARKEASY AI                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   📷 Kamera USB                    💻 ParkEasy AI Server (Laptop)           │
│   ┌──────────┐                     ┌─────────────────────────────────┐      │
│   │ Kamera   │ ──── USB ────────── │                                 │      │
│   │ Masuk    │                     │   ┌─────────────────────────┐   │      │
│   └──────────┘                     │   │   📡 FastAPI Server     │   │      │
│   ┌──────────┐                     │   │   (Port 8765)           │   │      │
│   │ Kamera   │ ──── USB ────────── │   │                         │   │      │
│   │ Keluar   │                     │   │   /stream/masuk         │   │      │
│   └──────────┘                     │   │   /stream/keluar        │   │      │
│                                    │   │   /ws (WebSocket)       │   │      │
│                                    │   │   /manual/open          │   │      │
│                                    │   │   /status               │   │      │
│                                    │   └────────────┬────────────┘   │      │
│                                    │                │                │      │
│                                    │   ┌────────────▼────────────┐   │      │
│                                    │   │   🤖 ANPR Engine        │   │      │
│                                    │   │                         │   │      │
│                                    │   │   YOLOv8 (Deteksi)     │   │      │
│                                    │   │       ▼                 │   │      │
│                                    │   │   Perspective Fix       │   │      │
│                                    │   │       ▼                 │   │      │
│                                    │   │   Preprocessing         │   │      │
│                                    │   │       ▼                 │   │      │
│                                    │   │   PaddleOCR (Baca)     │   │      │
│                                    │   │       ▼                 │   │      │
│                                    │   │   Koreksi Karakter     │   │      │
│                                    │   └────────────┬────────────┘   │      │
│                                    │                │                │      │
│                                    └────────────────┼────────────────┘      │
│                                                     │                       │
│                          ┌──────────────────────────┼───────────────┐       │
│                          │                          │               │       │
│                          ▼                          ▼               ▼       │
│                   ┌─────────────┐          ┌──────────────┐  ┌──────────┐  │
│                   │ 🔌 UART     │          │ ☁️ Supabase   │  │ 🌐 Web   │  │
│                   │ Serial COM  │          │ Database     │  │ Dashboard│  │
│                   └──────┬──────┘          └──────────────┘  └──────────┘  │
│                          │                                                  │
│                          ▼                                                  │
│                   ┌─────────────────────────────────────────────┐           │
│                   │           ⚡ ESP32 Microcontroller          │           │
│                   │                                             │           │
│                   │  🔊 Buzzer   🖥️ LCD    🔧 Servo (Palang)   │           │
│                   │  📏 HC-SR04  📡 VL53L1X (Slot Parkir)      │           │
│                   └─────────────────────────────────────────────┘           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 🔄 Alur Proses Gerbang Masuk

```
  Kendaraan Mendekat
        │
        ▼
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │  HC-SR04     │────▶│  Deteksi     │────▶│  Ambil Foto     │
  │  Jarak ≤10cm │     │  Kendaraan   │     │  dari Kamera    │
  └─────────────┘     └──────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │  Kirim UART │◀────│  Validasi    │◀────│  ANPR: YOLO     │
  │  ke ESP32   │     │  di Supabase │     │  + PaddleOCR    │
  └──────┬──────┘     └──────────────┘     └─────────────────┘
         │
         ▼
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │  Palang     │────▶│  Kendaraan   │────▶│  Simpan Sesi    │
  │  Terbuka    │     │  Lewat       │     │  ke Database    │
  └─────────────┘     └──────────────┘     └─────────────────┘
```

---

## 🛠️ Tech Stack

| Kategori | Teknologi |
|:---------|:----------|
| **Bahasa** | Python 3.10+ |
| **Web Framework** | FastAPI + Uvicorn |
| **Computer Vision** | OpenCV (cv2) |
| **Object Detection** | YOLOv8 (Ultralytics) |
| **OCR Engine** | PaddleOCR |
| **Database** | Supabase (PostgreSQL) |
| **Komunikasi Hardware** | PySerial (UART) |
| **Real-time** | WebSocket |
| **Streaming** | MJPEG over HTTP |
| **Mikrokontroler** | ESP32 (via Serial) |

---

## 📁 Struktur File

```
ParkEasy_AI/
│
├── 📄 gate_server.py        # Server utama FastAPI + WebSocket
│                              # - Endpoint kamera streaming (MJPEG)
│                              # - WebSocket broadcast (log, sensor, event)
│                              # - UART listener (komunikasi ESP32)
│                              # - Logika gerbang masuk & keluar
│                              # - Manual override & system reset
│
├── 📄 anpr_service.py        # Service ANPR (Automatic Number Plate Recognition)
│                              # - Deteksi plat dengan YOLOv8
│                              # - Baca teks plat dengan PaddleOCR
│                              # - Return hasil lengkap (bbox, crop, teks)
│
├── 📄 crop_spesial.py        # Utilitas crop & preprocessing plat nomor
│                              # - Perspective correction (4-point transform)
│                              # - Multi-strategy corner detection
│                              # - Adaptive preprocessing (dark/light plate)
│                              # - Koreksi karakter plat Indonesia
│                              # - Load model YOLO & PaddleOCR
│
├── 📄 config.py              # Konfigurasi sistem
│                              # - Supabase URL & API key
│                              # - Serial port & baud rate
│                              # - Camera index
│                              # - Server host & port
│
├── 📄 supabase_client.py     # Wrapper HTTP ke Supabase REST API
│                              # - CRUD kendaraan & sesi parkir
│                              # - Gate log & billing
│                              # - Update slot parkir
│
├── 📄 run_gate_server.bat    # Script Windows untuk menjalankan server
│
├── 📄 .gitignore             # File yang diabaikan git
└── 📄 README.md              # Dokumentasi ini
```

---

## 🚀 Cara Menjalankan

### 1️⃣ Prasyarat

- **Python 3.10+** terinstal
- **2 USB Webcam** (gerbang masuk & keluar)
- **ESP32** terhubung via kabel USB (serial COM)
- **Model YOLOv8** (file `best.pt`) untuk deteksi plat nomor

### 2️⃣ Instalasi Dependensi

```bash
# Buat virtual environment
python -m venv venv_yolo_ocr

# Aktifkan virtual environment (Windows)
.\venv_yolo_ocr\Scripts\activate

# Install dependensi
pip install fastapi uvicorn[standard] websockets
pip install opencv-python numpy
pip install ultralytics
pip install paddlepaddle paddleocr
pip install pyserial
pip install requests
```

### 3️⃣ Konfigurasi

Edit file `config.py` sesuai kebutuhan:

```python
# Serial port ESP32 (cek Device Manager → Ports)
SERIAL_PORT = "COM3"

# Index kamera (0, 1, 2, dst)
CAMERA_INDEX_MASUK = 1
CAMERA_INDEX_KELUAR = 0

# Server
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8765
```

### 4️⃣ Jalankan Server

```bash
# Cara 1: Langsung
python gate_server.py

# Cara 2: Menggunakan batch file (Windows)
run_gate_server.bat
```

Server akan berjalan di `http://0.0.0.0:8765`

---

## 📡 API Endpoints

### HTTP Endpoints

| Method | Endpoint | Deskripsi |
|:-------|:---------|:----------|
| `GET` | `/stream/masuk` | Stream MJPEG kamera gerbang masuk |
| `GET` | `/stream/keluar` | Stream MJPEG kamera gerbang keluar |
| `GET` | `/status` | Status koneksi serial & kamera |
| `POST` | `/manual/open` | Buka palang manual (mode darurat) |
| `POST` | `/system/reset` | Reset ESP32 & restart server |

### WebSocket

| Endpoint | Deskripsi |
|:---------|:----------|
| `ws://host:8765/ws` | Real-time log, status sensor, dan event gerbang |

### Contoh Penggunaan API

```bash
# Cek status sistem
curl http://localhost:8765/status

# Buka palang manual (darurat)
curl -X POST http://localhost:8765/manual/open \
  -H "Content-Type: application/json" \
  -d '{"gate": "MASUK", "plate": "AB 1234 CD"}'

# Reset sistem
curl -X POST http://localhost:8765/system/reset \
  -H "Content-Type: application/json" \
  -d '{"keyword": "RESET"}'
```

---

## 🔌 Komunikasi UART dengan ESP32

### Format Pesan ke ESP32 (Laptop → ESP32)

| Perintah | Deskripsi |
|:---------|:----------|
| `MASUK:BERHASIL\|PLAT\|JAM` | Buka gerbang masuk |
| `MASUK:GAGAL\|PLAT\|ALASAN` | Tolak gerbang masuk |
| `MASUK:TIDAK_TERDETEKSI` | Plat tidak terdeteksi |
| `KELUAR:BERHASIL\|PLAT` | Buka gerbang keluar |
| `KELUAR:BELUM_BAYAR\|PLAT\|HARGA` | Belum bayar |
| `MASUK:DARURAT\|PLAT\|JAM` | Buka paksa gerbang masuk |
| `KELUAR:DARURAT\|PLAT` | Buka paksa gerbang keluar |
| `ANIM_KAMERA:MASUK/KELUAR` | Animasi LCD "memindai kamera" |
| `ANIM_DATABASE:MASUK/KELUAR` | Animasi LCD "mengecek database" |
| `reset` | Reset ESP32 |

### Format Pesan dari ESP32 (ESP32 → Laptop)

| Pesan | Deskripsi |
|:------|:----------|
| `[HCSR04_MASUK] <jarak>` | Jarak sensor ultrasonik masuk (cm) |
| `[HCSR04_KELUAR] <jarak>` | Jarak sensor ultrasonik keluar (cm) |
| `MASUK:SELESAI\|PLAT` | Kendaraan sudah melewati gerbang masuk |
| `KELUAR:SELESAI\|PLAT` | Kendaraan sudah melewati gerbang keluar |
| `SLOT:KODE:STATUS` | Update status slot parkir (VL53L1X) |

---

## 📊 Alur Data WebSocket

Pesan WebSocket yang di-broadcast ke semua client yang terhubung:

```json
// Log event
{"type": "log", "time": "14:30:25", "msg": "...", "level": "info|ok|warn|error|uart"}

// Status sensor
{"type": "sensors", "data": {"hcsr04": {...}, "lcd": {...}, "buzzer": {...}, "servo": {...}, "tca": {...}}}

// Jarak HC-SR04
{"type": "hcsr04", "masuk": 5.2, "keluar": 150.0}

// Refresh statistik
{"type": "stats_refresh"}
```

---

## 🧩 Bagian dari Ekosistem ParkEasy

ParkEasy AI adalah satu komponen dari sistem parkir pintar **ParkEasy** yang lengkap:

| Komponen | Deskripsi |
|:---------|:----------|
| 🤖 **ParkEasy AI** *(repo ini)* | Mesin ANPR & kontrol gerbang |
| 🌐 **ParkEasy Front-End** | Dashboard web untuk monitoring |
| ⚙️ **ParkEasy Back-End** | API server & business logic |
| 🔧 **ESP32 Firmware** | Firmware mikrokontroler gerbang |

---

<p align="center">
  <b>Dibuat dengan ❤️ untuk Skripsi</b><br>
  <sub>ParkEasy — Solusi Parkir Cerdas Berbasis IoT & AI</sub>
</p>
