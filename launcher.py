"""
GoodGallery Launcher
Auto-bootstrap and start the gallery application
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path


def check_python_version():
    """Ensure Python 3.10+"""
    if sys.version_info < (3, 10):
        print("❌ Python 3.10+ required")
        print(f"   You have: Python {sys.version_info.major}.{sys.version_info.minor}")
        print("   Download from: https://www.python.org/downloads/")
        sys.exit(1)
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor} detected")


def check_config():
    """Ensure config.yaml exists"""
    if not os.path.exists('config.yaml'):
        if os.path.exists('config.yaml.example'):
            print("\n⚠️  No config.yaml found")
            print("   Creating from config.yaml.example...")
            
            import shutil
            shutil.copy('config.yaml.example', 'config.yaml')
            
            print("\n📝 Please edit config.yaml and set your photo_directory")
            print("   Then run launcher.py again\n")
            
            # Try to open in default editor
            try:
                if sys.platform == 'win32':
                    os.startfile('config.yaml')
                elif sys.platform == 'darwin':
                    subprocess.call(['open', 'config.yaml'])
                else:
                    subprocess.call(['xdg-open', 'config.yaml'])
            except:
                pass
            
            sys.exit(0)
        else:
            print("❌ No config.yaml or config.yaml.example found!")
            sys.exit(1)
    
    # Validate config
    import yaml
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    photo_dir = config['gallery']['photo_directory']
    
    if photo_dir == 'path/to/your/photos':
        print("\n⚠️  Please edit config.yaml and set your photo_directory")
        print(f"   Current value: {photo_dir}\n")
        sys.exit(1)
    
    if not os.path.exists(photo_dir):
        print(f"\n❌ Photo directory not found: {photo_dir}")
        print("   Please check config.yaml\n")
        sys.exit(1)
    
    print(f"✓ Config loaded")
    print(f"  Photo directory: {photo_dir}")
    
    return config


def install_dependencies():
    """Install Python dependencies if needed"""
    print("\n📦 Checking dependencies...")
    
    try:
        import flask
        import PIL
        import yaml
        import torch
        import transformers
        print("✓ All dependencies installed")
        return
    except ImportError:
        pass
    
    print("⏳ Installing dependencies (this may take a few minutes)...")
    
    try:
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'
        ])
        print("✓ Dependencies installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed to install dependencies: {e}")
        print("   Try manually: pip install -r requirements.txt")
        sys.exit(1)


def check_gpu():
    """Check if CUDA/GPU is available"""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            print(f"✓ GPU detected: {gpu_name}")
            return True
        else:
            print("⚠️  No GPU detected - AI tagging will be slow on CPU")
            return False
    except:
        return False


def create_data_dirs():
    """Create data directories"""
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/cache', exist_ok=True)
    os.makedirs('data/thumbnails', exist_ok=True)
    print("✓ Data directories ready")


def start_server(config):
    """Start Flask server"""
    print("\n" + "="*50)
    print("🚀 Starting GoodGallery...")
    print("="*50)
    
    port = config['gallery']['port']
    url = f"http://127.0.0.1:{port}"
    
    # Open browser after short delay
    def open_browser():
        time.sleep(2)
        print(f"\n🌐 Opening browser: {url}")
        webbrowser.open(url)
    
    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Start server
    from app.server import run_server
    run_server(port=port, debug=False)


def main():
    """Main launcher"""
    print("="*50)
    print("   GoodGallery Launcher")
    print("="*50 + "\n")
    
    # Check Python version
    check_python_version()
    
    # Check/create config
    config = check_config()
    
    # Install dependencies
    install_dependencies()
    
    # Check GPU
    has_gpu = check_gpu()
    
    if not has_gpu:
        print("\n💡 Tip: AI tagging works best with an NVIDIA GPU")
        print("   It will still work on CPU, just slower (~10-30s per image)")
    
    # Create directories
    create_data_dirs()
    
    # Start server
    start_server(config)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✋ GoodGallery stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
