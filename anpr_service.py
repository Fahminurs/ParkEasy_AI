import base64
import io
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# IMPORTANT:
# Kita memakai fungsi & object dari crop_spesial.py agar tidak ada yang terlewat.
import crop_spesial as cs


def _bgr_to_jpeg_b64(img_bgr: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("Gagal encode JPEG")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _safe_imread_from_bytes(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Gambar tidak valid / tidak bisa dibaca (pastikan JPG/PNG/WEBP)")
    return img


def _plate_format_score(text: str) -> int:
    """
    Skor sederhana 0..120 untuk UI bar:
    - Cocok pola Indonesia: [A-Z]{1,2}\d{1,4}[A-Z]{1,3}
    - Panjang ideal 6..9
    """
    if not text:
        return 0
    t = "".join([c for c in text.upper() if c.isalnum()])
    score = 0
    # Panjang
    if 3 <= len(t) <= 9:
        score += 35
    if 6 <= len(t) <= 9:
        score += 25
    # Komposisi
    has_letter = any(c.isalpha() for c in t)
    has_digit = any(c.isdigit() for c in t)
    if has_letter:
        score += 15
    if has_digit:
        score += 15
    # Pola Indonesia (aproksimasi)
    import re

    if re.match(r"^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$", t):
        score += 40
    return int(min(120, score))


def _ocr_extract(processed_bgr: np.ndarray) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Return:
    - raw_ocr: hasil extract_valid_plate (sebelum koreksi karakter)
    - corrected: hasil correct_plate_indonesia(raw)
    - candidates: list untuk UI
    """
    ocr_results = cs.ocr.ocr(processed_bgr)
    if not ocr_results:
        return "", "", []

    raw = cs.extract_valid_plate(
        ocr_results,
        plate_height=processed_bgr.shape[0],
        max_y_ratio=0.75,
    )
    corrected = cs.correct_plate_indonesia(raw)

    cand: List[Dict[str, Any]] = []
    if corrected:
        cand.append(
            {
                "text": corrected,
                "variant": "corrected",
                "score": _plate_format_score(corrected),
            }
        )
    if raw and raw != corrected:
        cand.append(
            {
                "text": raw,
                "variant": "raw",
                "score": _plate_format_score(raw),
            }
        )

    return raw, corrected, cand


def _detect_boxes(image_bgr: np.ndarray) -> List[Dict[str, Any]]:
    results = cs.model(image_bgr)
    out: List[Dict[str, Any]] = []

    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "conf": conf})

    # Urutkan confidence desc
    out.sort(key=lambda b: b["conf"], reverse=True)
    return out


def run_anpr_on_image(image_bgr: np.ndarray) -> Dict[str, Any]:
    h, w = image_bgr.shape[:2]

    boxes = _detect_boxes(image_bgr)
    detected_vis = image_bgr.copy()

    plates: List[Dict[str, Any]] = []
    for b in boxes:
        x1, y1, x2, y2, conf = b["x1"], b["y1"], b["x2"], b["y2"], b["conf"]

        # Draw YOLO detection
        cv2.rectangle(detected_vis, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(
            detected_vis,
            f"{conf:.2f}",
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 255),
            2,
            cv2.LINE_AA,
        )

        crop = cs.process_plate(
            image_bgr,
            x1,
            y1,
            x2,
            y2,
            corner_expand=1.15,
            debug=False,
        )

        crop_b64 = ""
        processed_b64 = ""
        raw_ocr = ""
        plate_text = ""
        candidates: List[Dict[str, Any]] = []

        if crop is not None and crop.size != 0:
            crop_b64 = _bgr_to_jpeg_b64(crop)
            processed = cs.preprocess_plate(crop, min_width=400, debug=False)
            processed_b64 = _bgr_to_jpeg_b64(processed)
            raw_ocr, plate_text, candidates = _ocr_extract(processed)

        plates.append(
            {
                "conf": float(conf),
                "bbox": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)},
                "plate_text": plate_text,
                "raw_ocr": raw_ocr,
                "candidates": candidates,
                "crop_image": crop_b64,
                "processed_image": processed_b64,
            }
        )

    return {
        "width": int(w),
        "height": int(h),
        "detected_image": _bgr_to_jpeg_b64(detected_vis),
        "plates": plates,
    }


def run_anpr_on_bytes(image_bytes: bytes) -> Dict[str, Any]:
    img = _safe_imread_from_bytes(image_bytes)
    return run_anpr_on_image(img)

