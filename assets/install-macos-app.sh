#!/bin/bash

# GenericAgent macOS Desktop App Installation Script
#
# Usage:
#   bash assets/install-macos-app.sh [--auto]
#
# This installer creates a small .app bundle that opens Terminal and runs
# `python3 launch.pyw` from the current GenericAgent checkout.

if [ -z "${BASH_VERSION}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash -- "${0}" "$@"
    else
        echo "Error: This script requires bash."
        exit 1
    fi
fi

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

AUTO_MODE=false
for arg in "$@"; do
    case "$arg" in
        --auto) AUTO_MODE=true ;;
    esac
done

APP_NAME="GenericAgent"
PRIMARY_INSTALL_DIR="/Applications"
FALLBACK_INSTALL_DIR="${HOME}/Applications"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ICON_PATH="${PROJECT_ROOT}/assets/images/logo.jpg"
LAUNCH_SCRIPT="${PROJECT_ROOT}/launch.pyw"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   GenericAgent — macOS Desktop App Installer             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [[ "$(uname)" != "Darwin" ]]; then
    log_error "This script only supports macOS."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    log_error "python3 is not installed."
    exit 1
fi

if [ ! -f "${LAUNCH_SCRIPT}" ]; then
    log_error "launch.pyw not found at ${LAUNCH_SCRIPT}"
    exit 1
fi

project_path_for_applescript="${PROJECT_ROOT}/"
project_path_for_applescript="${project_path_for_applescript//\\/\\\\}"
project_path_for_applescript="${project_path_for_applescript//\"/\\\"}"

detect_existing_app() {
    if [ -d "${PRIMARY_INSTALL_DIR}/${APP_NAME}.app" ]; then
        echo "${PRIMARY_INSTALL_DIR}/${APP_NAME}.app"
        return
    fi
    if [ -d "${FALLBACK_INSTALL_DIR}/${APP_NAME}.app" ]; then
        echo "${FALLBACK_INSTALL_DIR}/${APP_NAME}.app"
        return
    fi
}

existing_app_path="$(detect_existing_app || true)"
if [ -n "${existing_app_path}" ]; then
    log_warning "${APP_NAME}.app already exists at ${existing_app_path}"
fi

if [ "${AUTO_MODE}" = false ]; then
    echo ""
    echo "This will install a desktop app that launches GenericAgent"
    echo "from Spotlight, Launchpad, or the Applications folder."
    echo ""
    if [ -n "${existing_app_path}" ]; then
        read -p "Reinstall ${APP_NAME}.app? (y/N) " -n 1 -r
    else
        read -p "Continue? (Y/n) " -n 1 -r
    fi
    echo
    if [ -n "${existing_app_path}" ]; then
        [[ ! ${REPLY:-} =~ ^[Yy]$ ]] && { echo "Aborted."; exit 0; }
    else
        [[ ${REPLY:-} =~ ^[Nn]$ ]] && { echo "Aborted."; exit 0; }
    fi
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

log_info "Building ${APP_NAME}.app..."

cat > "${TMP_DIR}/${APP_NAME}.applescript" <<APPLESCRIPT
on run
    set projectPathStr to "${project_path_for_applescript}"
    tell application "Terminal"
        activate
        do script "cd " & quoted form of projectPathStr & " && python3 launch.pyw"
    end tell
end run
APPLESCRIPT

osacompile -o "${TMP_DIR}/${APP_NAME}.app" "${TMP_DIR}/${APP_NAME}.applescript"

log_info "Applying GenericAgent icon..."
if [ -f "${ICON_PATH}" ]; then
    ICONSET_DIR="${TMP_DIR}/ga-icon.iconset"
    mkdir -p "${ICONSET_DIR}"

    sips -z 16 16   "${ICON_PATH}" --out "${ICONSET_DIR}/icon_16x16.png"       >/dev/null 2>&1
    sips -z 32 32   "${ICON_PATH}" --out "${ICONSET_DIR}/icon_16x16@2x.png"    >/dev/null 2>&1
    sips -z 32 32   "${ICON_PATH}" --out "${ICONSET_DIR}/icon_32x32.png"       >/dev/null 2>&1
    sips -z 64 64   "${ICON_PATH}" --out "${ICONSET_DIR}/icon_32x32@2x.png"    >/dev/null 2>&1
    sips -z 128 128 "${ICON_PATH}" --out "${ICONSET_DIR}/icon_128x128.png"     >/dev/null 2>&1
    sips -z 256 256 "${ICON_PATH}" --out "${ICONSET_DIR}/icon_128x128@2x.png"  >/dev/null 2>&1
    sips -z 256 256 "${ICON_PATH}" --out "${ICONSET_DIR}/icon_256x256.png"     >/dev/null 2>&1
    sips -z 512 512 "${ICON_PATH}" --out "${ICONSET_DIR}/icon_256x256@2x.png"  >/dev/null 2>&1
    sips -z 512 512 "${ICON_PATH}" --out "${ICONSET_DIR}/icon_512x512.png"     >/dev/null 2>&1
    cp "${ICON_PATH}" "${ICONSET_DIR}/icon_512x512@2x.png"

    iconutil -c icns "${ICONSET_DIR}" -o "${TMP_DIR}/ga-icon.icns"
    cp "${TMP_DIR}/ga-icon.icns" "${TMP_DIR}/${APP_NAME}.app/Contents/Resources/applet.icns"
    log_success "Icon applied from assets/images/logo.jpg"
else
    log_warning "Logo not found at ${ICON_PATH}, using default icon."
fi

install_bundle() {
    local install_dir="$1"
    local destination="${install_dir}/${APP_NAME}.app"
    mkdir -p "${install_dir}"
    rm -rf "${destination}"
    cp -R "${TMP_DIR}/${APP_NAME}.app" "${destination}"
}

install_path=""
if install_bundle "${PRIMARY_INSTALL_DIR}" 2>/dev/null; then
    install_path="${PRIMARY_INSTALL_DIR}/${APP_NAME}.app"
else
    log_warning "Could not write to ${PRIMARY_INSTALL_DIR}; falling back to ${FALLBACK_INSTALL_DIR}"
    install_bundle "${FALLBACK_INSTALL_DIR}"
    install_path="${FALLBACK_INSTALL_DIR}/${APP_NAME}.app"
fi

log_success "Installed to: ${install_path}"

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ✨  ${APP_NAME} Desktop App installed successfully!          ${CYAN}║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Launch methods:${NC}"
echo "  • Spotlight:  Cmd + Space → type '${APP_NAME}' → Enter"
echo "  • Launchpad:  Find the '${APP_NAME}' icon"
echo "  • Finder:     Open ${install_path}"
echo ""
echo -e "${BLUE}Runtime behavior:${NC}"
echo "  The app uses the current checkout path embedded at install time:"
echo "  ${PROJECT_ROOT}"
echo "  If you move the repo later, re-run this installer."
echo ""
echo -e "${BLUE}Uninstall:${NC}"
echo "  rm -rf '${install_path}'"
echo ""
