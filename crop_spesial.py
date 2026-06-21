import cv2
import numpy as np
from ultralytics import YOLO
from paddleocr import PaddleOCR
import re


# ========================
# GEOMETRY HELPERS
# ========================

def order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image, pts):
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (maxWidth, maxHeight))


# ========================
# CORNER DETECTION
# ========================

def _find_quad_contour(binary_img, total_area, min_ratio=0.25):
    """Cari kontur segi-4 terbesar yang valid dari binary/edge image."""
    contours, _ = cv2.findContours(binary_img.copy(),
                                   cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours[:10]:
        peri = cv2.arcLength(c, True)
        for eps_factor in [0.02, 0.03, 0.04, 0.05, 0.06]:
            approx = cv2.approxPolyDP(c, eps_factor * peri, True)
            if len(approx) == 4:
                area = cv2.contourArea(approx)
                if area > total_area * min_ratio:
                    return approx.reshape(4, 2).astype("float32")
    return None


def detect_plate_corners_v2(plate_crop, debug=False):
    """
    Multi-strategy corner detection untuk plat miring.
    Strategy 1 : Canny + approxPolyDP (threshold adaptif)
    Strategy 2 : Threshold OTSU + approxPolyDP
    Strategy 3 : MinAreaRect (selalu berhasil, akurasi lebih rendah)
    """
    h, w = plate_crop.shape[:2]
    gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)

    # ── Strategy 1: Canny dengan beberapa threshold ──────────────────────────
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    canny_params = [(30, 150), (50, 200), (20, 80)]

    for lo, hi in canny_params:
        edged = cv2.Canny(blurred, lo, hi)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edged = cv2.dilate(edged, kernel, iterations=2)

        if debug:
            cv2.imshow(f"Edge Canny {lo}-{hi}", edged)
            cv2.waitKey(0)

        corners = _find_quad_contour(edged, h * w, min_ratio=0.25)
        if corners is not None:
            print(f"✅ Strategy 1 berhasil (Canny {lo}-{hi})")
            return corners

    # ── Strategy 2: OTSU threshold ────────────────────────────────────────────
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    if debug:
        cv2.imshow("OTSU Thresh", thresh)
        cv2.waitKey(0)

    corners = _find_quad_contour(thresh, h * w, min_ratio=0.25)
    if corners is not None:
        print("✅ Strategy 2 berhasil (OTSU)")
        return corners

    # ── Strategy 3: MinAreaRect (fallback geometris) ──────────────────────────
    print("⚠️  Strategy 1 & 2 gagal → pakai MinAreaRect")
    _, thresh2 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        largest = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(largest)
        box = cv2.boxPoints(rect).astype("float32")
        if debug:
            vis = plate_crop.copy()
            cv2.drawContours(vis, [box.astype(int)], 0, (0, 255, 0), 2)
            cv2.imshow("MinAreaRect", vis)
            cv2.waitKey(0)
        return box

    return None


# ========================
# CROP + PERSPECTIVE
# ========================

def process_plate(image, x1, y1, x2, y2, keep_height_ratio=0.72,
                  side_padding_ratio=0.0,
                  corner_expand=1.15,      # perlebar corner 15% agar tepi tidak terpotong
                  debug=False):
    """
    Pipeline:
    1. Crop kasar dari bbox YOLO (+ padding asimetris: kanan lebih lebar)
    2. Deteksi 4 sudut → warp perspective agar plat lurus
       KHUSUS PLAT GELAP: warp sering merusak geometri karena corner detection
       menangkap kontur teks bukan bingkai plat → skip warp, pakai rough_crop langsung
    3. Buang bagian bawah (zona tanggal TNKB)

    corner_expand: faktor ekspansi sudut terdeteksi sebelum warp.
                   1.05 = 5%, 1.15 = 15%. Naikkan jika huruf tepi masih terpotong.
    """
    pad_top    = 15
    pad_bottom = 15
    pad_left   = 40    # kiri lebih lebar agar huruf prefix tidak terpotong
    pad_right  = 40    # kanan lebih lebar karena huruf suffix sering terpotong di kanan

    h_img, w_img = image.shape[:2]
    rx1 = max(0, x1 - pad_left)
    ry1 = max(0, y1 - pad_top)
    rx2 = min(w_img, x2 + pad_right)
    ry2 = min(h_img, y2 + pad_bottom)

    rough_crop = image[ry1:ry2, rx1:rx2]
    if rough_crop.size == 0:
        return None

    # Cek apakah plat gelap SEBELUM corner detection
    # Plat gelap: corner detection sering salah tangkap kontur teks → skip warp
    gray_check = cv2.cvtColor(rough_crop, cv2.COLOR_BGR2GRAY)
    mean_brightness = np.mean(gray_check)
    plate_is_dark = mean_brightness < 100

    if plate_is_dark:
        # Plat gelap: langsung pakai rough_crop tanpa warp
        # Warp pada plat gelap sering salah karena edge detection menangkap teks
        # bukan bingkai luar plat, menghasilkan perspektif yang justru lebih buruk
        print("ℹ️  Plat gelap terdeteksi → skip warp, pakai rough_crop langsung.")
        warped = rough_crop
    else:
        corners = detect_plate_corners_v2(rough_crop, debug=debug)

        if corners is not None:
            # Perlebar area corner agar huruf di tepi kiri/kanan tidak terpotong warp
            center  = np.mean(corners, axis=0)
            corners = center + (corners - center) * corner_expand

            # Klem corner agar tidak keluar dari batas gambar
            h_rc, w_rc = rough_crop.shape[:2]
            corners[:, 0] = np.clip(corners[:, 0], 0, w_rc - 1)
            corners[:, 1] = np.clip(corners[:, 1], 0, h_rc - 1)
            corners = corners.astype("float32")
            warped  = four_point_transform(rough_crop, corners)

            # Sanity check: jika hasil warp jauh lebih sempit dari rough_crop,
            # berarti corner detection salah tangkap → fallback ke rough_crop
            if warped.shape[1] < rough_crop.shape[1] * 0.7:
                print("⚠️  Warp terlalu sempit, fallback ke rough_crop.")
                warped = rough_crop
        else:
            print("❌ Semua strategy gagal, pakai crop mentah.")
            warped = rough_crop

    h, w = warped.shape[:2]
    pad_x = int(w * side_padding_ratio)
    new_h = int(h * keep_height_ratio)
    final = warped[0:new_h, :] if pad_x == 0 else warped[0:new_h, pad_x:w - pad_x]
    return final


# ========================
# PREPROCESSING
# ========================

def is_dark_plate(gray):
    """
    Deteksi otomatis apakah plat berwarna gelap (teks putih di atas background hitam).
    Cara: jika rata-rata brightness < 100 → plat gelap → perlu diinversi.
    Plat hitam Indonesia (uji coba, kendaraan dinas, dll) masuk kategori ini.
    """
    mean_brightness = np.mean(gray)
    is_dark = mean_brightness < 100
    print(f"  Brightness rata-rata: {mean_brightness:.1f} → "
          f"{'PLAT GELAP (inversi)' if is_dark else 'PLAT TERANG (normal)'}")
    return is_dark


def preprocess_plate(crop, min_width=400, debug=False):
    """
    Preprocessing bertahap untuk memaksimalkan akurasi OCR:
    1. Upscale      — resolusi minimum 400px lebar
    2. Auto-invert  — deteksi plat gelap & inversi agar teks selalu gelap di atas terang
    3. Bilateral    — denoise tanpa mengaburkan tepi karakter
    4. CLAHE        — perbaiki kontras lokal
    5. Sharpen      — perjelas tepi karakter
    6. Border putih — agar karakter di tepi tidak diabaikan OCR
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Step 1: Upscale jika resolusi terlalu kecil
    h_crop, w_crop = gray.shape[:2]
    if w_crop < min_width:
        scale = min_width / w_crop
        gray = cv2.resize(gray, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)
        print(f"  Upscale {w_crop}px → {gray.shape[1]}px (scale {scale:.2f}x)")

    # Step 2: Auto-invert untuk plat gelap (teks putih → teks hitam)
    # PaddleOCR bekerja lebih baik dengan teks gelap di atas background terang
    if is_dark_plate(gray):
        gray = cv2.bitwise_not(gray)
        if debug:
            cv2.imshow("After Invert", gray)
            cv2.waitKey(0)

    # Step 3: Bilateral filter — denoise tanpa blur tepi karakter
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    # Step 4: CLAHE — perbaiki kontras lokal
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    gray = clahe.apply(gray)

    # Step 5: Sharpen lebih kuat
    kernel_sharp = np.array([[-1, -1, -1],
                              [-1,  9, -1],
                              [-1, -1, -1]])
    gray = cv2.filter2D(gray, -1, kernel_sharp)
    gray = np.clip(gray, 0, 255).astype(np.uint8)

    if debug:
        cv2.imshow("After Sharpen", gray)
        cv2.waitKey(0)

    # Step 6: Kembalikan dalam format BGR tanpa threshold
    # Biarkan PaddleOCR handle sendiri — lebih baik untuk karakter ambigu
    processed = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Tambahkan border putih agar karakter di tepi tidak terpotong OCR
    processed = cv2.copyMakeBorder(processed, 20, 20, 20, 20,
                                   cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return processed


# ========================
# OCR FILTER
# ========================

def extract_valid_plate(ocr_results, plate_height, max_y_ratio=0.75):
    """
    Filter hasil OCR dengan 4 lapis:
    1. Posisi Y       — buang teks di bawah max_y_ratio * tinggi plat
    2. Confidence     — buang teks dengan score < 0.4
    3. Angka pendek   — buang token 2-4 digit MURNI jika plat sudah punya
                        prefix huruf + digit + suffix huruf (lengkap 3 segmen)
    4. Post-trim      — setelah semua token terkumpul, potong token tanggal
                        di akhir jika total panjang melebihi 9 karakter
                        (panjang maksimum plat Indonesia: 2+4+3=9)
    """
    DATE_PATTERN    = re.compile(r'^\d{2,4}$')
    MAX_PLATE_LEN   = 9   # prefix(2) + digit(4) + suffix(3)

    tokens    = []
    raw_texts = []

    for line in ocr_results:
        if line is None:
            continue
        for word in line:
            if word is None:
                continue

            bbox  = word[0]
            text  = word[1][0]
            score = word[1][1]

            y_center = sum(pt[1] for pt in bbox) / 4
            y_ratio  = y_center / plate_height

            clean = re.sub(r'[^A-Z0-9]', '', text.upper())

            print(f"  Teks: {text!r:15} clean: {clean!r:12} "
                  f"score: {score:.2f}  y_ratio: {y_ratio:.2f}")

            # Filter 1: posisi Y — zona tanggal TNKB
            if y_ratio > max_y_ratio:
                print(f"    ↳ DIBUANG — zona tanggal (y_ratio {y_ratio:.2f} > {max_y_ratio})")
                continue

            # Filter 2: confidence terlalu rendah
            if score < 0.4:
                print(f"    ↳ DIBUANG — confidence rendah ({score:.2f})")
                continue

            # Filter 3: buang token MURNI digit pendek jika plat sudah 3 segmen lengkap
            if DATE_PATTERN.match(clean):
                joined_so_far = ''.join(tokens)
                has_prefix = bool(re.match(r'^[A-Z]', joined_so_far))
                has_digits = bool(re.search(r'\d', joined_so_far))
                has_suffix = bool(re.search(r'\d[A-Z]', joined_so_far))
                if has_prefix and has_digits and has_suffix:
                    print(f"    ↳ DIBUANG — digit murni setelah plat lengkap (tanggal TNKB)")
                    continue

            tokens.append(clean)
            raw_texts.append(text)

    # Filter 4: post-trim — buang token terakhir jika total > MAX_PLATE_LEN
    # Ini menangkap kasus tanggal yang lolos filter 3 (misal plat prefix terpotong)
    while tokens:
        joined = ''.join(tokens)
        if len(joined) <= MAX_PLATE_LEN:
            break
        last = tokens[-1]
        # Hanya buang token terakhir jika MURNI digit (kemungkinan tanggal)
        if DATE_PATTERN.match(last):
            print(f"    ↳ POST-TRIM: buang '{last}' — total {len(joined)} > {MAX_PLATE_LEN}")
            tokens.pop()
            raw_texts.pop() if raw_texts else None
        else:
            break   # token terakhir bukan angka murni, biarkan

    return ''.join(tokens)


# ========================
# KOREKSI KARAKTER PLAT INDONESIA
# ========================

def correct_plate_indonesia(text):
    """
    Koreksi kesalahan OCR berdasarkan FORMAT plat Indonesia.
    Format: [1-2 HURUF][1-4 ANGKA][1-3 HURUF]
    Contoh: DK4071IP, AB3513XV, D5363ZAZ

    Kasus khusus — prefix hilang:
    Jika teks diawali digit DAN diikuti 3+ digit berturut (misal '5363ZAZ'),
    ini menandakan prefix huruf terpotong di kiri. Dalam kondisi ini kita tidak
    bisa tahu huruf prefix aslinya → output apa adanya dengan peringatan.
    Solusi terbaik ada di level crop (perbesar padding kiri).

    Strategi segmentasi:
    - Cari semua kombinasi (p, d, s) yang valid untuk panjang teks
    - Pilih kombinasi dengan biaya koreksi terendah
    - Jika seri, prioritaskan d_len terpanjang (plat Indonesia umumnya 4 digit)

    Tabel koreksi:
    - Prefix/Suffix (huruf): 0→D, 1→I, 2→Z, 5→S, 6→G, 8→B
    - Tengah (angka)       : O→0, I→1, Z→2, S→5, G→6, B→8, D→0, A→4, T→1
    """

    DIGIT_TO_LETTER = {
        '0': 'D', '1': 'I', '2': 'Z',
        '5': 'S', '6': 'G', '8': 'B'
    }
    LETTER_TO_DIGIT = {
        'O': '0', 'I': '1', 'Z': '2',
        'S': '5', 'G': '6', 'B': '8',
        'D': '0', 'A': '4', 'T': '1'
    }

    if not text:
        return text

    n = len(text)

    # ── Deteksi prefix hilang ────────────────────────────────────────────────
    # Kondisi: teks diawali digit DAN 3 karakter berikutnya juga digit
    # Contoh: '5363ZAZ' → '5','3','6','3' = 4 digit di awal → prefix huruf hilang
    prefix_missing = False
    if n >= 4 and text[0].isdigit():
        digit_run = sum(1 for c in text[:4] if c.isdigit())
        if digit_run >= 3:
            prefix_missing = True
            print(f"  ⚠️  Prefix huruf kemungkinan hilang (teks diawali {digit_run} digit): '{text}'")
            print(f"      → Tambah padding kiri crop untuk menangkap huruf prefix.")

    # ── Hitung semua kandidat segmentasi ────────────────────────────────────
    candidates = []
    for p_len in range(1, 3):
        for d_len in range(1, 5):
            for s_len in range(1, 4):
                if p_len + d_len + s_len == n:
                    sg1 = text[:p_len]
                    sg2 = text[p_len:p_len + d_len]
                    sg3 = text[p_len + d_len:]
                    cost1 = sum(1 for c in sg1 if c.isdigit())
                    cost2 = sum(1 for c in sg2 if c.isalpha())
                    cost3 = sum(1 for c in sg3 if c.isdigit())
                    candidates.append((cost1 + cost2 + cost3, -d_len,
                                       p_len, d_len, s_len, sg1, sg2, sg3))

    if not candidates:
        print(f"  ⚠️  Panjang teks tidak sesuai pola plat Indonesia: '{text}' (len={n})")
        return text

    candidates.sort(key=lambda x: (x[0], x[1], -x[2]))
    best = candidates[0]
    total_cost, _, p_len, d_len, s_len, seg1_raw, seg2_raw, seg3_raw = best

    print(f"  Segmentasi terbaik: '{seg1_raw}' + '{seg2_raw}' + '{seg3_raw}' "
          f"(cost={total_cost}, p={p_len} d={d_len} s={s_len})")

    seg1 = ''.join(DIGIT_TO_LETTER.get(c, c) for c in seg1_raw)
    seg2 = ''.join(LETTER_TO_DIGIT.get(c, c) for c in seg2_raw)
    seg3 = ''.join(DIGIT_TO_LETTER.get(c, c) for c in seg3_raw)
    corrected = seg1 + seg2 + seg3

    if corrected != text:
        print(f"  Koreksi karakter: {text} → {corrected}")
    else:
        print(f"  Tidak ada koreksi diperlukan: {text}")

    return corrected


# ========================
# LOAD MODEL YOLO
# ========================
model = YOLO(r"D:\AI\Number_Plate_internasional + Paddle OCR\train\weights\best.pt")

# ========================
# LOAD OCR
# ========================
ocr = PaddleOCR(use_angle_cls=False, lang='en')

if __name__ == "__main__":
    # ========================
    # LOAD GAMBAR
    # ========================
    image_path = r"D:\AI\Bahan\miringEdit.png"
    image = cv2.imread(image_path)

    if image is None:
        print("Gambar tidak ditemukan!")
        exit()

    # ========================
    # DETEKSI YOLO
    # ========================
    results = model(image)

    print("\n=== HASIL OCR PLAT NOMOR ===")

    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])

            print(f"\nBox: {x1}, {y1}, {x2}, {y2} | Confidence: {conf:.2f}")

            # ========================
            # CROP + PERSPECTIVE CORRECTION
            # ========================
            crop = process_plate(image, x1, y1, x2, y2,
                                 corner_expand=1.15,   # naikkan ke 1.20 jika huruf tepi masih terpotong
                                 debug=False)

            if crop is None or crop.size == 0:
                print("Crop kosong, dilewati.")
                continue

            cv2.imshow("Crop Plat (Fixed)", crop)
            cv2.waitKey(0)

            # ========================
            # PREPROCESSING
            # ========================
            processed = preprocess_plate(crop, min_width=400, debug=False)

            # ========================
            # OCR + FILTER 3 LAPIS
            # ========================
            ocr_results = ocr.ocr(processed)

            if ocr_results:
                plate_text = extract_valid_plate(
                    ocr_results,
                    plate_height=processed.shape[0],
                    max_y_ratio=0.75
                )
                # Koreksi karakter berdasarkan segmentasi plat Indonesia
                plate_text = correct_plate_indonesia(plate_text)
                print("Plat Terdeteksi:", plate_text)
            else:
                print("Tidak ada teks terdeteksi.")

    cv2.destroyAllWindows()

