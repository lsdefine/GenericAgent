#!/usr/bin/env bash
# GenericAgent - Ubuntu system dependency installer
# Run once before installing Python dependencies:
#   chmod +x setup_ubuntu.sh && ./setup_ubuntu.sh
set -e

echo "=== GenericAgent Ubuntu Setup ==="
echo "Installing system packages needed for pywebview, Pillow, PySide6, and other deps..."

sudo apt update
sudo apt install -y \
    python3-dev \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    gir1.2-webkit2-4.1 \
    libgtk-3-dev \
    libwebkit2gtk-4.1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    libxcb-cursor0 \
    libxcb-xinerama0 \
    libxcb-randr0 \
    libxcb-shape0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-image0 \
    libxcb-render-util0 \
    libxcb-util1 \
    libegl1 \
    libgl1 \
    libopengl0

echo ""
echo "=== Done! ==="
echo "Now install Python dependencies:"
echo "  pip install -r requirements.txt"
echo ""
echo "Or for minimal install:"
echo "  pip install requests beautifulsoup4 bottle simple-websocket-server"
echo "  pip install streamlit pywebview Pillow  # for GUI"
