@echo off
cd /d "%~dp0"
:: ====== 硬编码虚拟环境路径（绕过 activate.bat）=====
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "LITELLM_EXE=%~dp0.venv\Scripts\litellm.exe"
%PYTHON_EXE% launch.pyw --feishu