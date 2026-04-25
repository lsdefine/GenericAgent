@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
.venv\Scripts\python.exe launch.pyw