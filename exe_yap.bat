@echo off
rem StoreOps.exe'yi yeniden üretir (gerekli: pip install -r requirements.txt). Çıktı: dist\StoreOps.exe
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name StoreOps --add-data "index.html;." --clean -y server.py
rmdir /s /q build
del StoreOps.spec
pause
