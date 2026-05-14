@echo off
cd /d "%~dp0"
.venv\Scripts\streamlit.exe run frontends/stapp.py --server.port 8501
pause
