@echo off
cd /d "%~dp0"
echo Memulai ParkEasy Web Gate Server di venv_yolo_ocr...
.\venv_yolo_ocr\Scripts\python.exe gate_server.py
pause
