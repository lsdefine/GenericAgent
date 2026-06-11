#!/usr/bin/env bash
set -euo pipefail

# GenericAgent one-click portable deployer for macOS/Linux.
# Modes:
#   Default/Mainland: download GenericAgent.zip + uv from user's VPS, set China PyPI mirror.
#   GLOBAL=1: clone GenericAgent from GitHub; uv also from GitHub releases; no PyPI mirror.
# Portable components are installed under <INSTALL_DIR>/.portable:
#   uv, Python installed by uv. On macOS/Linux git is expected from system package manager.

INSTALL_DIR="${INSTALL_DIR:-$HOME/GenericAgent}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
FORCE="${FORCE:-0}"
GLOBAL="${GLOBAL:-0}"

REPO_URL="https://github.com/lsdefine/GenericAgent.git"
VPS_BASE="http://47.101.182.29:9000"
GA_ZIP_URL="$VPS_BASE/files/GenericAgent.zip"
MAINLAND_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
DEPS=("requests>=2.28" "beautifulsoup4>=4.12" "bottle>=0.12" "simple-websocket-server>=0.4" "streamlit>=1.28")

say(){ printf '\033[36m[ga-deploy]\033[0m %s\n' "$*"; }
ok(){ printf '\033[32m[ok]\033[0m %s\n' "$*"; }
die(){ printf '\033[31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

usage(){ cat <<'EOF'
Usage:
  bash install_portable_env.sh
  INSTALL_DIR="$HOME/GenericAgent" PYTHON_VERSION=3.12 FORCE=1 bash install_portable_env.sh
  GLOBAL=1 bash install_portable_env.sh

Environment variables:
  INSTALL_DIR     Install GenericAgent here. Default: ~/GenericAgent
  PYTHON_VERSION  Python version installed by uv. Default: 3.12
  FORCE=1         Replace existing source files while preserving/reinstalling portable tools.
  GLOBAL=1        Clone from GitHub directly and do not set China PyPI mirror.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS:$ARCH" in
  Darwin:x86_64) uv_file="uv-x86_64-apple-darwin.tar.gz" ;;
  Darwin:arm64) uv_file="uv-aarch64-apple-darwin.tar.gz" ;;
  Linux:x86_64) uv_file="uv-x86_64-unknown-linux-gnu.tar.gz" ;;
  Linux:aarch64|Linux:arm64) uv_file="uv-aarch64-unknown-linux-gnu.tar.gz" ;;
  *) die "Unsupported platform: $OS $ARCH" ;;
esac

GA_DIR="${INSTALL_DIR/#\~/$HOME}"
case "$GA_DIR" in
  /*) ;;
  *) GA_DIR="$PWD/$GA_DIR" ;;
esac
mkdir -p "$GA_DIR"
GA_DIR="$(cd "$GA_DIR" && pwd -P)"
PORTABLE_ROOT="$GA_DIR/.portable"
BIN="$PORTABLE_ROOT/bin"
CACHE="$PORTABLE_ROOT/cache"
UV_TGZ="$CACHE/$uv_file"
GA_ZIP="$CACHE/GenericAgent.zip"
UV_EXTRACT="$CACHE/uv-extract"
GA_EXTRACT="$CACHE/ga-extract"
UV_EXE="$BIN/uv"
ENV_SH="$GA_DIR/env.sh"

mkdir -p "$GA_DIR" "$PORTABLE_ROOT" "$BIN" "$CACHE"

say "Install dir: $GA_DIR"
if [[ "$GLOBAL" == "1" ]]; then say "Mode: GLOBAL=1 / GitHub clone"; else say "Mode: Mainland / VPS zip"; fi

if [[ "$FORCE" == "1" ]]; then
  # Preserve .portable if present; remove source files later before deploying.
  :
fi

download(){
  local url="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  say "Downloading $url"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 -A "ga-deploy" -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$out" "$url"
  else
    die "curl or wget is required"
  fi
  [[ -s "$out" ]] || die "Download failed: $url"
}

extract_tgz_clean(){
  local tgz="$1" dest="$2"
  rm -rf "$dest"; mkdir -p "$dest"
  tar -xzf "$tgz" -C "$dest"
}

extract_zip_clean(){
  local zip="$1" dest="$2"
  rm -rf "$dest"; mkdir -p "$dest"
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$zip" -d "$dest"
  else
    python3 - "$zip" "$dest" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    z.extractall(sys.argv[2])
PY
  fi
}

copy_contents(){
  local src="$1" dst="$2"
  mkdir -p "$dst"
  (cd "$src" && tar -cf - .) | (cd "$dst" && tar -xf -)
}

remove_source_files(){
  shopt -s dotglob nullglob
  for p in "$GA_DIR"/*; do
    [[ "$(basename "$p")" == ".portable" ]] && continue
    rm -rf "$p"
  done
  shopt -u dotglob nullglob
}

# uv: GitHub release in GLOBAL mode, user's VPS otherwise
if [[ ! -x "$UV_EXE" || "$FORCE" == "1" ]]; then
  if [[ "$GLOBAL" == "1" ]]; then
    download "https://github.com/astral-sh/uv/releases/latest/download/$uv_file" "$UV_TGZ"
  else
    download "$VPS_BASE/uv/$uv_file" "$UV_TGZ"
  fi
  extract_tgz_clean "$UV_TGZ" "$UV_EXTRACT"
  found_uv="$(find "$UV_EXTRACT" -type f -name uv | head -n 1 || true)"
  [[ -n "$found_uv" ]] || die "uv not found in archive"
  cp "$found_uv" "$UV_EXE"
  chmod +x "$UV_EXE"
fi
ok "uv: $($UV_EXE --version)"

export UV_PYTHON_INSTALL_DIR="$PORTABLE_ROOT/uv-python"
export UV_CACHE_DIR="$PORTABLE_ROOT/uv-cache"
if [[ "$GLOBAL" == "1" ]]; then
  unset UV_DEFAULT_INDEX PIP_INDEX_URL
else
  export UV_DEFAULT_INDEX="$MAINLAND_INDEX"
  export PIP_INDEX_URL="$MAINLAND_INDEX"
fi
export PATH="$BIN:$PATH"

say "Installing Python $PYTHON_VERSION via uv"
"$UV_EXE" python install "$PYTHON_VERSION"
PYTHON_EXE="$($UV_EXE python find "$PYTHON_VERSION")"
[[ -x "$PYTHON_EXE" ]] || die "uv installed Python but executable was not found"
ok "Python: $($PYTHON_EXE --version)"
PYTHON_DIR="$(dirname "$PYTHON_EXE")"
export PATH="$BIN:$PYTHON_DIR:$PATH"

# git: macOS/Linux use system git. In mainland mode it is not required for source fetch.
GIT_EXE=""
if command -v git >/dev/null 2>&1; then
  GIT_EXE="$(command -v git)"
  ok "git: $($GIT_EXE --version)"
elif [[ "$GLOBAL" == "1" ]]; then
  die "GLOBAL=1 requires git. Install git with your system package manager, then rerun."
else
  say "git not found; continuing because mainland mode uses VPS zip. Install git later if needed."
fi

# Fetch/update GenericAgent source.
if [[ "$GLOBAL" == "1" ]]; then
  say "Cloning GenericAgent from GitHub"
  if [[ -n "$(find "$GA_DIR" -mindepth 1 -maxdepth 1 ! -name .portable -print -quit)" ]]; then
    [[ "$FORCE" == "1" ]] || die "Install dir contains files. Re-run with FORCE=1 to replace source while preserving portable tools."
    remove_source_files
  fi
  TMP_CLONE="$CACHE/ga-clone"
  rm -rf "$TMP_CLONE"
  "$GIT_EXE" clone --depth 1 "$REPO_URL" "$TMP_CLONE"
  copy_contents "$TMP_CLONE" "$GA_DIR"
  rm -rf "$TMP_CLONE"
else
  say "Downloading GenericAgent package from VPS"
  download "$GA_ZIP_URL" "$GA_ZIP"
  extract_zip_clean "$GA_ZIP" "$GA_EXTRACT"
  SRC_DIR="$GA_EXTRACT/GenericAgent"
  [[ -d "$SRC_DIR" ]] || SRC_DIR="$GA_EXTRACT"
  remove_source_files
  copy_contents "$SRC_DIR" "$GA_DIR"
fi
ok "GenericAgent source ready: $GA_DIR"

# Install basic dependencies and project in editable mode into portable Python.
say "Installing GenericAgent dependencies via uv pip"
install_args=(pip install --python "$PYTHON_EXE" --break-system-packages)
if [[ "$GLOBAL" != "1" ]]; then install_args+=(--index-url "$MAINLAND_INDEX"); fi
install_args+=("${DEPS[@]}")
"$UV_EXE" "${install_args[@]}"

if [[ -f "$GA_DIR/pyproject.toml" ]]; then
  project_args=(pip install --python "$PYTHON_EXE" --break-system-packages)
  if [[ "$GLOBAL" != "1" ]]; then project_args+=(--index-url "$MAINLAND_INDEX"); fi
  project_args+=(-e "$GA_DIR")
  "$UV_EXE" "${project_args[@]}"
fi

# Try-install pywebview (optional UI). Failure is non-fatal.
say "Attempting to install pywebview (optional, failure is OK)"
webview_args=(pip install --python "$PYTHON_EXE" --break-system-packages)
if [[ "$GLOBAL" != "1" ]]; then webview_args+=(--index-url "$MAINLAND_INDEX"); fi
webview_args+=("pywebview>=4.0")
if "$UV_EXE" "${webview_args[@]}" 2>/dev/null; then
  ok "pywebview installed successfully"
else
  printf '\033[33m[warn]\033[0m pywebview install failed. This is optional.\n'
  printf '       On Linux, pywebview requires system GTK/WebKit libraries.\n'
  printf '       Install them first, e.g.:\n'
  printf '         Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1 libgirepository1.0-dev\n'
  printf '         Fedora:        sudo dnf install python3-gobject webkit2gtk4.1\n'
  printf '         macOS:         usually works out of the box (uses PyObjC)\n'
  printf '       Then retry: uv pip install pywebview\n'
fi

# Activation script: portable paths are intentionally before system PATH.
if [[ "$GLOBAL" == "1" ]]; then
  cat > "$ENV_SH" <<EOF
export PORTABLE_DEV_ROOT="$PORTABLE_ROOT"
export GENERICAGENT_HOME="$GA_DIR"
export UV_PYTHON_INSTALL_DIR="$PORTABLE_ROOT/uv-python"
export UV_CACHE_DIR="$PORTABLE_ROOT/uv-cache"
export PATH="$BIN:$PYTHON_DIR:\$PATH"
echo "Activated GenericAgent portable env: \$GENERICAGENT_HOME"
EOF
else
  cat > "$ENV_SH" <<EOF
export PORTABLE_DEV_ROOT="$PORTABLE_ROOT"
export GENERICAGENT_HOME="$GA_DIR"
export UV_PYTHON_INSTALL_DIR="$PORTABLE_ROOT/uv-python"
export UV_CACHE_DIR="$PORTABLE_ROOT/uv-cache"
export UV_DEFAULT_INDEX="$MAINLAND_INDEX"
export PIP_INDEX_URL="$MAINLAND_INDEX"
export PATH="$BIN:$PYTHON_DIR:\$PATH"
echo "Activated GenericAgent portable env: \$GENERICAGENT_HOME"
EOF
fi

ok "Verification:"
"$UV_EXE" --version
"$PYTHON_EXE" --version
if [[ -n "$GIT_EXE" ]]; then "$GIT_EXE" --version; fi
"$PYTHON_EXE" -c "import requests, bs4, bottle; print('deps ok')"

# Copy mykey template if mykey.py does not exist (GLOBAL mode only)
MYKEY_DST="$GA_DIR/mykey.py"
if [[ "$GLOBAL" == "1" && ! -f "$MYKEY_DST" ]]; then
  MYKEY_TPL="$GA_DIR/mykey_template_en.py"
  if [[ -f "$MYKEY_TPL" ]]; then
    cp "$MYKEY_TPL" "$MYKEY_DST"
    ok "Copied mykey_template_en.py -> mykey.py"
  fi
fi

# Final banner
echo ""
if [[ "$GLOBAL" == "1" ]]; then
  cat <<EOF
╔═══════════════════════════════════════════════╗
║  ✅ GenericAgent installed successfully!       ║
╠═══════════════════════════════════════════════╣
║  📁 Location: $GA_DIR
║  🔑 Config: edit mykey.py (copied from template)
║  🚀 Launch: ga tui / ga launch / ga hub
╚═══════════════════════════════════════════════╝
EOF
else
  cat <<EOF
╔═══════════════════════════════════════════════╗
║  ✅ GenericAgent 安装完成！                    ║
╠═══════════════════════════════════════════════╣
║  📁 安装目录: $GA_DIR
║  🔑 配置密钥: ga configure
║  🚀 启动: ga tui / ga launch / ga hub
╚═══════════════════════════════════════════════╝
EOF
fi
echo ""
ok "Activate env: source \"$ENV_SH\""
