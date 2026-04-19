@echo off
REM GA Switch API Server Startup Script
echo Starting GA Switch API Server...
cd /d "%~dp0"
python api_server.py
pause
