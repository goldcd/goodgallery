# GoodGallery

## v0.2.0 Beta

A standalone, fully self-contained image gallery application featuring advanced AI-powered photo tagging with support for state-of-the-art Vision-Language models like **Qwen VL** and **LLaVA**.

**✨ Key Feature**: Zero installation or local Python configuration required! Simply download the repository, drop your photos into the `photos/` directory, run the launcher, and start browsing.

---

## Features

- 📁 **Browse Large Image Collections**: Engineered to handle index structures and search lists for 100k+ images.
- 🔍 **Powerful Search**: Filter by tags using a dynamic input field with support for positive matching and negative (exclude) filters.
- 🏷️ **AI Auto-Tagging**: Powered by **Qwen3-VL** (default) or **LLaVA** models using the Hugging Face Transformers pipeline.
- ⚡ **Asynchronous Background Processing**: Automatic tagging is run in a separate thread/subprocess so your web interface never blocks.
- 💾 **SQLite Storage & Caching**: Fast local tag database and aggressive thumbnail caching for stutter-free scrolling.
- 🔄 **Real-Time Directory Monitoring**: Watches the `photos/` directory to instantly detect file additions, modifications, and deletions.
- 🎨 **Modern Web Interface**: Intuitive UI with infinite scroll, tag filters, tag-cloud visualization, and a dark/responsive layout.
- 📈 **Tag Analytics & Cloud**: Visualize metadata distributions and view a tag-cloud page (`/cloud`).
- 📥 **CSV Metadata Export**: Export all or filtered images and their corresponding tags directly to CSV.
- 🚀 **Zero Dependencies**: Portable runtime scripts automatically download a standalone Python environment and configure platform-specific PyTorch (including CUDA 12.1 for NVIDIA GPUs and MPS for Apple Silicon).

---

## Quick Start

### 1. Download
Clone the repository to your local machine:
```bash
git clone <your-repo-url>
cd GoodGallery
```

### 2. Add Photos
Place your images (JPEG, PNG, GIF, WebP) into the `photos/` directory:
```bash
# Windows
copy C:\MyPhotos\*.jpg photos\

# macOS/Linux
cp ~/Pictures/*.jpg photos/
```

### 3. Launch
The launcher scripts automatically manage environment setup, dependencies, and model downloading.

**On Windows:**
Double-click or run `launcher.bat` in your terminal:
```cmd
launcher.bat
```

**On macOS / Linux:**
Provide executable permissions and run `launcher.sh`:
```bash
chmod +x launcher.sh
./launcher.sh
```

### 4. Browse & Auto-Tag
On the first run, the launcher will:
- ✓ Download a sandboxed Python 3.11.9 runtime (~30MB)
- ✓ Initialize a local Python environment and configure site-packages
- ✓ Detect your operating system and install platform-specific PyTorch (with CUDA 12.1 on Windows or native MPS/CPU builds on macOS/Linux)
- ✓ Install remaining dependencies (`transformers`, `Pillow`, `qwen-vl-utils`, etc.)
- ✓ Download the configured AI vision model (default: ~4.5GB Qwen3-VL model)
- ✓ Start scanning and tagging images in the background while launching the web server at http://localhost:5000

On subsequent launches, the application starts up instantly!

---

## What Makes This Different?

### Portable Sandboxed Runtime
GoodGallery packages itself with zero local environment requirements. By leveraging `python-build-standalone` on macOS/Linux and native embedded Python on Windows, the application keeps itself entirely isolated within its folder. You can copy the entire `GoodGallery` folder onto an external drive or a network share, and it remains functional.

### State-of-the-Art Vision AI
Unlike legacy galleries that rely on simple object detection, GoodGallery supports **Qwen3-VL** and **Qwen2.5-VL** models alongside **LLaVA 1.5**. These models understand complex contexts, actions, facial expressions, styles, and activities.

### GPU Memory-Safe Design
To prevent "CUDA Out of Memory" (OOM) errors common in vision language models:
- **Resolution Limiting**: Qwen-VL processes high-resolution (e.g. 4K) images into thousands of visual tokens, causing massive VRAM spikes. GoodGallery automatically downsizes images to a maximum dimension of `1024px` before sending them to the AI, maintaining tagging precision while reducing VRAM usage under 8-9GB.
- **Aggressive VRAM Cleanup**: Once tagging operations complete, the system fully unloads the model weights and calls PyTorch's garbage collector (`torch.cuda.empty_cache()` and `torch.cuda.ipc_collect()`) to return GPU VRAM back to your system.

---

## Folder Structure

After the first setup run, your folder hierarchy will look like this:

```
GoodGallery/
├── launcher.bat              # Windows: Launcher script
├── launcher.sh               # Unix/macOS: Launcher script
├── photos/                   # Put your photos here (monitored in real-time)
│   └── README.txt
├── runtime/                  # Self-contained portable Python (~30MB)
│   └── python-3.11.9/
├── models/                   # AI weights folder (local, gitignored)
│   └── prithivMLmods_Qwen3-VL-8B-Instruct-abliterated-v2/  # (~4.5GB)
├── data/                     # Local data storage
│   ├── gallery.db           # SQLite database for image index & tags
│   ├── thumbnails/          # Generated image thumbnail cache
│   └── cache/               # Directory index cache
├── bootstrap/                # Startup logic scripts
│   └── launcher_core.py     # Setup, dependency solver, and model downloader
├── app/                      # Application backend source code
│   ├── ai_tagger.py         # AI Vision integration pipeline
│   ├── file_monitor.py      # Watchdog real-time file scanner
│   ├── server.py            # Flask Web API routes
│   └── ...
├── static/                   # Web interface CSS/JS assets
├── config.yaml               # User configuration (automatically generated on start)
├── config.yaml.example       # Default configuration template
└── README.md                 # This documentation file
```

---

## Configuration

Settings can be customized by editing the `config.yaml` file:

```yaml
gallery:
  # Path to your photo directory
  photo_directory: "./photos"
  
  # Gallery Title shown in the header
  title: "Good Gallery"
  
  # Web server port
  port: 5000
  
  # Monitor photos directory for changes in real-time
  watch_for_changes: true
  
  # Thumbnail settings
  thumbnail_size: 200
  images_per_page: 300
  
  # Allowed image extensions
  allowed_extensions:
    - jpg
    - jpeg
    - png
    - gif
    - webp

  # Tag UI limits
  tag_limits:
    dropdown: 1000      # Max tags to load in search autocomplete dropdown
    browse: 100         # Max tags to show in the browse filter bar
    min_count: 1        # Minimum occurrences of a tag to display in filters

ai:
  # Model selection (Options: Qwen3-VL-8B, Qwen2.5-VL-7B, LLaVA-1.5-7b)
  model: "prithivMLmods/Qwen3-VL-8B-Instruct-abliterated-v2"
  
  # Auto-tag images on startup
  auto_tag: true
  
  # Keep the model loaded in GPU memory (faster start, uses VRAM until app closed)
  try_keep_loaded: false
  
  # Enable 4-bit quantization (Fits model in ~6GB VRAM, ~9GB with overhead)
  use_quantization: true
  
  # Batch size for tagging
  # NOTE: 1 is recommended for stability with Qwen VL to avoid VRAM overhead
  batch_size: 1
  
  # Max image dimension (in pixels) for AI analysis to prevent VRAM spikes
  max_image_size: 1024

  # High-precision prompt engineering template
  tagging_prompt: |
    USER: <image>
    SYSTEM:
    You are a high-precision image annotation assistant.
    Generate a comma-separated list of relevant tags based ONLY on what is clearly visible.
    Rules: Tags must be 1-2 words each, no duplicates, describe image classification and elements.
    ASSISTANT:
```

---

## Troubleshooting

### "CUDA out of memory" (GPU crashes)
- **Lower batch size**: Set `batch_size: 1` in `config.yaml`.
- **Verify quantization**: Ensure `use_quantization: true` is enabled in `config.yaml` to run in 4-bit.
- **Decrease maximum resolution**: Lower the `max_image_size` parameter in `config.yaml` to `512` or `768`.
- **Free background VRAM**: Close other GPU-intensive applications (games, video editors, other LLM local runtimes).

### "First run is taking a very long time"
This is normal behavior! On the initial launch, the system downloads:
1. Portable Python runtime zip package (~30MB)
2. Operating system-tailored Python environment and site packages (~500MB)
3. Model weights and configuration config files (~4.5GB)
Depending on your network speed, this setup might take 10-20 minutes. Subsequent starts will be nearly instantaneous.

### "Newly added photos are not appearing in the gallery"
- Ensure `watch_for_changes: true` is configured in `config.yaml`.
- Verify the photos are in one of the allowed formats (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`).
- If you're using an external drive, double-check that the absolute path in `photo_directory` is correct and accessible.

### Unix/macOS "Permission Denied"
If you get a shell error when running the launcher script, make it executable:
```bash
chmod +x launcher.sh
./launcher.sh
```

---

## License

This project is licensed under the MIT License. Feel free to use, modify, and distribute it!
