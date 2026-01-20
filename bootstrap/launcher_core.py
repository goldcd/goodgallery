"""
GoodGallery Bootstrap Core
Intelligent setup and launcher that handles:
- Creating venv
- Downloading LLaVA model
- Installing dependencies
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
        self.venv_dir = self.root_dir / "venv"
        self.models_dir = self.root_dir / "models"
        self.runtime_dir = self.root_dir / "runtime"
        self.photos_dir = self.root_dir / "photos"
        self.config_file = self.root_dir / "config.yaml"
        
        # Determine venv python executable
        if sys.platform == "win32":
            self.venv_python = self.venv_dir / "Scripts" / "python.exe"
            self.venv_pip = self.venv_dir / "Scripts" / "pip.exe"
        else:
            self.venv_python = self.venv_dir / "bin" / "python"
            self.venv_pip = self.venv_dir / "bin" / "pip"
    
    def print_banner(self):
        """Print welcome banner"""
        print("\n" + "="*60)
        print("   🎨 GoodGallery - AI-Powered Photo Gallery")
        print("="*60 + "\n")
    
    def check_setup_complete(self):
        """Check if initial setup is complete"""
        checks = {
            "Virtual environment": self.venv_python.exists(),
            "Configuration file": self.config_file.exists(),
            "Models directory": (self.models_dir / "llava").exists(),
        }
        
        all_complete = all(checks.values())
        
        if all_complete:
            print("✓ Setup complete - launching application...\n")
            return True
        else:
            print("⚙️  First-time setup required\n")
            for name, status in checks.items():
                icon = "✓" if status else "⏳"
                print(f"  {icon} {name}")
            print()
            return False
    
    def create_venv(self):
        """Create virtual environment"""
        if self.venv_dir.exists():
            print("✓ Virtual environment already exists\n")
            return
        
        print("📦 Creating virtual environment...")
        print(f"   Location: {self.venv_dir}")
        
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(self.venv_dir)])
            print("✓ Virtual environment created\n")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to create virtual environment: {e}")
            sys.exit(1)
    
    def install_dependencies(self):
        """Install Python dependencies into venv"""
        requirements_file = self.root_dir / "requirements.txt"
        
        if not requirements_file.exists():
            print("❌ requirements.txt not found!")
            sys.exit(1)
        
        print("📚 Installing Python packages...")
        print("   This may take 5-10 minutes on first run...")
        print(f"   Installing from: {requirements_file}\n")
        
        try:
            # Upgrade pip first
            subprocess.check_call(
                [str(self.venv_python), "-m", "pip", "install", "--upgrade", "pip"],
                stdout=subprocess.DEVNULL
            )
            
            # Install requirements with progress
            subprocess.check_call([
                str(self.venv_python), "-m", "pip", "install", 
                "-r", str(requirements_file)
            ])
            
            print("\n✓ Python packages installed\n")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Failed to install dependencies: {e}")
            print("   Try running manually: venv/Scripts/pip install -r requirements.txt")
            sys.exit(1)
    
    def download_llava_model(self):
        """Download LLaVA model using HuggingFace Hub"""
        llava_dir = self.models_dir / "llava"
        
        if llava_dir.exists() and any(llava_dir.iterdir()):
            print("✓ LLaVA model already downloaded\n")
            return
        
        print("🤖 Downloading LLaVA AI model...")
        print("   Model: llava-hf/llava-1.5-7b-hf")
        print("   Size: ~4GB (this will take several minutes)")
        print("   Location: models/llava/\n")
        
        llava_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Use the venv python to ensure transformers is available
            download_script = f"""
import sys
from transformers import AutoProcessor, LlavaForConditionalGeneration
import torch

print("   Downloading model files...")
model_name = "llava-hf/llava-1.5-7b-hf"
cache_dir = r"{llava_dir}"

# Download processor
processor = AutoProcessor.from_pretrained(
    model_name,
    cache_dir=cache_dir
)

# Download model (quantized to save space)
model = LlavaForConditionalGeneration.from_pretrained(
    model_name,
    cache_dir=cache_dir,
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)

print("\\n   Model downloaded successfully!")
"""
            
            result = subprocess.run(
                [str(self.venv_python), "-c", download_script],
                check=True,
                capture_output=False
            )
            
            print("\n✓ LLaVA model downloaded\n")
            
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Failed to download LLaVA model: {e}")
            print("   The app will attempt to download on first use")
            print("   You can continue, but AI tagging may be delayed\n")
            # Don't exit - let the app try to download later
    
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
        
        # Launch using venv python
        try:
            # Set PYTHONPATH to include app directory
            env = os.environ.copy()
            env['PYTHONPATH'] = str(self.root_dir)
            
            subprocess.run(
                [str(self.venv_python), str(app_main)],
                env=env,
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
        self.create_venv()
        self.install_dependencies()
        self.download_llava_model()
        
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
