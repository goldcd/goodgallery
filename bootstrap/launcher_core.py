"""
GoodGallery Bootstrap Core
Intelligent setup and launcher that handles:
- Installing dependencies into embedded Python
- Downloading LLaVA model
- Launching the application
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


class BootstrapManager:
    def __init__(self):
        self.root_dir = Path(__file__).parent.parent.absolute()
        self.models_dir = self.root_dir / "models"
        self.runtime_dir = self.root_dir / "runtime"
        self.photos_dir = self.root_dir / "photos"
        self.config_file = self.root_dir / "config.yaml"
    
    def print_banner(self):
        """Print welcome banner"""
        print("\n" + "="*60)
        print("   🎨 GoodGallery - AI-Powered Photo Gallery")
        print("="*60 + "\n")
    
    def check_setup_complete(self):
        """Check if initial setup is complete"""
        # Check if dependencies are installed
        try:
            import flask
            import PIL
            import yaml
            # Check for qwen-vl-utils (required for Qwen models)
            try:
                import qwen_vl_utils
            except ImportError:
                # Only strictly required if using Qwen, but good to have consistency
                if config.get('ai', {}).get('model', '').startswith('prithivMLmods/'):
                    try:
                        import pyxet
                    except ImportError:
                        try:
                             # Newer versions might expose it differently, or just rely on the installed package
                             # failing that, we check for the package presence logic in pip later, but checking import is better
                             import hf_xet
                        except ImportError:
                             print("⚠️  Xet storage support missing (required for Qwen)")
                             raise ImportError("hf_xet missing")
                    
                    if 'qwen_vl_utils' not in sys.modules:
                         import qwen_vl_utils
            
            deps_installed = True
        except ImportError:
            deps_installed = False
        
        # Check model directory based on config
        model_exists = False
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f)
                model_id = config.get('ai', {}).get('model', 'llava-hf/llava-1.5-7b-hf')
                model_dirname = model_id.replace('/', '_')
                model_path = self.models_dir / model_dirname
                # Check if directory exists and has files
                model_exists = model_path.exists() and any(model_path.iterdir())
        except:
            pass
            
        checks = {
            "Dependencies installed": deps_installed,
            "Configuration file": self.config_file.exists(),
            "AI Model downloaded": model_exists,
        }
        
        all_complete = all(checks.values())
        
        if all_complete:
            print("✓ Setup complete - launching application...\n")
            return True
        else:
            print("⚙️  Setup check failed, running setup...\n")
            for name, status in checks.items():
                icon = "✓" if status else "⏳"
                print(f"  {icon} {name}")
            print()
            return False
    
    def install_dependencies(self):
        """Install Python dependencies directly into embedded Python"""
        requirements_file = self.root_dir / "requirements.txt"
        
        if not requirements_file.exists():
            print("❌ requirements.txt not found!")
            sys.exit(1)
        
        print("📚 Installing Python packages...")
        print("   This may take 5-10 minutes on first run...")
        print(f"   Installing from: {requirements_file}\n")
        
        try:
            # 1. Install PyTorch (Platform specific)
            if sys.platform == 'win32':
                # Windows: Install with CUDA 12.1 support
                print("   [Windows] Installing PyTorch with CUDA support...")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", 
                    "torch==2.5.1", "torchvision==0.20.1", "torchaudio==2.5.1",
                    "--index-url", "https://download.pytorch.org/whl/cu121",
                    "--no-warn-script-location"
                ])
            else:
                # Mac/Linux: Install standard PyTorch (includes MPS for Mac)
                print(f"   [{sys.platform}] Installing standard PyTorch...")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", 
                    "torch==2.5.1", "torchvision==0.20.1", "torchaudio==2.5.1",
                    "--no-warn-script-location"
                ])



            # 2. Install remaining requirements
            print("   Installing other dependencies...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "--no-warn-script-location",
                "-r", str(requirements_file)
            ])
            
            print("\n✓ Python packages installed\n")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Failed to install dependencies: {e}")
            print(f"   Try running manually: {sys.executable} -m pip install -r requirements.txt")
            sys.exit(1)
    
    def download_ai_model(self):
        """Download configured AI model using HuggingFace Hub"""
        try:
            import yaml
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
            model_id = config.get('ai', {}).get('model', 'llava-hf/llava-1.5-7b-hf')
        except Exception as e:
            print(f"⚠️  Could not read config for model selection ({e}). Defaulting to LLaVA.")
            model_id = "llava-hf/llava-1.5-7b-hf"

        # Determine safe directory name from model ID (replace / with _)
        model_dirname = model_id.replace('/', '_')
        model_dir = self.models_dir / model_dirname
        
        if model_dir.exists() and any(model_dir.iterdir()):
            print(f"✓ AI Model ({model_id}) already downloaded\n")
            return
        
        print(f"🤖 Downloading AI model: {model_id}")
        print("   Size: ~4GB++ (this will take several minutes)")
        print(f"   Location: models/{model_dirname}/\n")
        
        model_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Dynamic download script
            download_script = f"""
import sys
import torch
from transformers import AutoProcessor

model_name = "{model_id}"
cache_dir = r"{model_dir}"

print(f"   Target: {{model_name}}")

try:
    # 1. Download Processor (Common for both)
    print("   Downloading processor...")
    processor = AutoProcessor.from_pretrained(
        model_name,
        cache_dir=cache_dir
    )

    # 2. Download Model
    # Use AutoModelForVision2Seq to automatically pick the correct class (Qwen2VL, Qwen2.5VL, LLaVA, etc.)
    print("   Downloading model weights...")
    from transformers import AutoModelForVision2Seq
    
    # We use AutoModelForVision2Seq which covers both LLaVA and Qwen2-VL family
    model_class = AutoModelForVision2Seq
        
    model = model_class.from_pretrained(
        model_name,
        cache_dir=cache_dir,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
        trust_remote_code=True
    )
    print("\\n   Model downloaded successfully!")

except Exception as e:
    print(f"\\n❌ Error downloading: {{e}}")
    sys.exit(1)
"""
            
            result = subprocess.run(
                [sys.executable, "-c", download_script],
                check=True,
                capture_output=False
            )
            
            print("\n✓ AI model downloaded\n")
            
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Failed to download model: {e}")
            print("   The app will attempt to download on first use")
            print("   You can continue, but AI tagging may be delayed\n")
    
    def create_default_config(self):
        """Create default config.yaml from example"""
        if self.config_file.exists():
            print("✓ Configuration file exists\n")
            return
        
        example_config = self.root_dir / "config.yaml.example"
        
        if not example_config.exists():
            print("❌ config.yaml.example not found!")
            sys.exit(1)
        
        print("📝 Creating default configuration...")
        
        # Read example and update paths
        with open(example_config, 'r') as f:
            content = f.read()
        
        # Replace placeholder path with ./photos
        content = content.replace(
            'photo_directory: "path/to/your/photos"',
            'photo_directory: "./photos"'
        )
        
        # Enable auto-tagging by default
        content = content.replace(
            'auto_tag: false',
            'auto_tag: true'
        )
        
        with open(self.config_file, 'w') as f:
            f.write(content)
        
        print(f"   Created: {self.config_file}")
        print("   Photo directory: ./photos")
        print("   Auto-tagging: enabled\n")
    
    def create_photos_directory(self):
        """Create photos directory if it doesn't exist"""
        if not self.photos_dir.exists():
            print("📁 Creating photos directory...")
            self.photos_dir.mkdir(parents=True, exist_ok=True)
            
            # Create a README
            readme = self.photos_dir / "README.txt"
            readme.write_text(
                "GoodGallery Photos\n"
                "==================\n\n"
                "Place your photos in this directory.\n"
                "The AI will automatically tag them when you start the application.\n\n"
                "Supported formats: JPG, PNG, GIF, WebP\n"
            )
            print(f"   Created: {self.photos_dir}")
            print("   Add your photos here!\n")
        else:
            # Count photos
            extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            photo_count = sum(
                1 for f in self.photos_dir.iterdir() 
                if f.suffix.lower() in extensions
            )
            
            if photo_count > 0:
                print(f"✓ Photos directory ready ({photo_count} photos found)\n")
            else:
                print("⚠️  Photos directory is empty")
                print("   Add some photos to ./photos/ to get started!\n")
    
    def launch_app(self):
        """Launch the main application"""
        print("\n" + "="*60)
        print("   🚀 Launching GoodGallery...")
        print("="*60 + "\n")
        
        app_main = self.root_dir / "app" / "server.py"
        
        if not app_main.exists():
            print(f"❌ Application not found: {app_main}")
            sys.exit(1)
        
        print("   Server will start at: http://localhost:5000")
        print("   Press Ctrl+C to stop\n")
        
        # Launch using current Python (embedded)
        try:
            app_main = self.root_dir / "app" / "server.py"
            # Launch browser in a separate thread (similar to launcher.py)
            import threading
            import time
            import webbrowser
            
            def open_browser():
                time.sleep(2)
                url = "http://localhost:5000"
                print(f"\n🌐 Opening browser: {url}")
                webbrowser.open(url)
            
            threading.Thread(target=open_browser, daemon=True).start()

            subprocess.run(
                [sys.executable, str(app_main)],
                cwd=str(self.root_dir)
            )
        except KeyboardInterrupt:
            print("\n\n✋ GoodGallery stopped")
            sys.exit(0)
    
    def run(self):
        """Main bootstrap process"""
        self.print_banner()
        
        # Quick check - if everything is ready, skip setup
        if self.check_setup_complete():
            self.launch_app()
            return
        
        # First-time setup
        print("Starting first-time setup...\n")
        
        self.create_photos_directory()
        self.create_default_config()
        self.install_dependencies()
        self.download_ai_model()
        
        print("\n" + "="*60)
        print("   ✓ Setup Complete!")
        print("="*60 + "\n")
        
        # Launch the app
        self.launch_app()


def main():
    """Entry point"""
    try:
        manager = BootstrapManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n✋ Setup cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
