#!/usr/bin/env bash
# GoodGallery Launcher for Unix/macOS
# Bootstraps portable Python if needed, then launches the app

set -e

echo ""
echo "============================================================"
echo "   GoodGallery Launcher (Unix/macOS)"
echo "============================================================"
echo ""

# Define paths
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/runtime"
PYTHON_DIR="$RUNTIME_DIR/python-3.11.9"
BOOTSTRAP_SCRIPT="$ROOT_DIR/bootstrap/launcher_core.py"

# Detect OS and architecture
detect_platform() {
    local os="$(uname -s)"
    local arch="$(uname -m)"
    
    case "$os" in
        Darwin)
            PLATFORM="apple-darwin"
            PYTHON_EXE="$PYTHON_DIR/bin/python3"
            
            if [ "$arch" = "arm64" ]; then
                PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.9+20240107-aarch64-apple-darwin-install_only.tar.gz"
            else
                PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.9+20240107-x86_64-apple-darwin-install_only.tar.gz"
            fi
            ;;
        Linux)
            PLATFORM="unknown-linux-gnu"
            PYTHON_EXE="$PYTHON_DIR/bin/python3"
            PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.9+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz"
            ;;
        *)
            echo "[ERROR] Unsupported OS: $os"
            exit 1
            ;;
    esac
}

# Check if portable Python exists
if [ -f "$PYTHON_EXE" ]; then
    echo "[*] Using portable Python: $PYTHON_DIR"
    echo ""
else
    # Download portable Python
    echo "[*] Portable Python not found - downloading..."
    echo "    This is a one-time setup (~35MB download)"
    echo ""
    
    detect_platform
    
    # Create runtime directory
    mkdir -p "$RUNTIME_DIR"
    
    # Download
    echo "[*] Downloading Python 3.11.9 ($PLATFORM)..."
    PYTHON_ARCHIVE="$RUNTIME_DIR/python.tar.gz"
    
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$PYTHON_ARCHIVE" "$PYTHON_URL"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$PYTHON_ARCHIVE" "$PYTHON_URL"
    else
        echo "[ERROR] Neither curl nor wget found. Please install one of them."
        exit 1
    fi
    
    if [ ! -f "$PYTHON_ARCHIVE" ]; then
        echo ""
        echo "[ERROR] Failed to download Python"
        echo "Please check your internet connection and try again"
        exit 1
    fi
    
    echo "[*] Download complete"
    echo ""
    
    # Extract
    echo "[*] Extracting Python..."
    tar -xzf "$PYTHON_ARCHIVE" -C "$RUNTIME_DIR"
    
    # Rename extracted directory
    for dir in "$RUNTIME_DIR"/python*; do
        if [ -d "$dir" ] && [ "$dir" != "$PYTHON_DIR" ]; then
            mv "$dir" "$PYTHON_DIR" 2>/dev/null || true
        fi
    done
    
    # Clean up
    rm -f "$PYTHON_ARCHIVE"
    
    # Make executable
    chmod +x "$PYTHON_EXE" 2>/dev/null || true
    
    if [ -f "$PYTHON_EXE" ]; then
        echo "[*] Python extracted successfully"
        echo ""
    else
        echo "[ERROR] Python extraction failed"
        echo "Expected: $PYTHON_EXE"
        exit 1
    fi
fi

# Launch bootstrap script
echo "[*] Starting GoodGallery bootstrap..."
echo ""

"$PYTHON_EXE" "$BOOTSTRAP_SCRIPT"
