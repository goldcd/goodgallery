# GoodGallery

A standalone, zero-dependency image gallery application with AI-powered tagging using LLaVA.

**✨ Key Feature**: No installation required! Download, add photos, double-click launcher - done!

## Features

- 📁 Browse large image collections (tested with 100k+ images)
- 🔍 Powerful search with tag filters and boolean operators
- 🏷️ **AI Auto-tagging** using LLaVA vision model
- 🖼️ Automatic thumbnail generation
- ⚡ Fast caching system
- 🎨 Clean web interface with infinite scroll
- 💾 SQLite database (zero configuration)
- 🚀 **Zero Dependencies** - downloads its own Python runtime!

## Quick Start

### 1. Download

```bash
git clone <your-repo-url>
cd GoodGallery
```

### 2. Add Photos

Drop your photos into the `photos/` directory:

```bash
# Windows
copy C:\MyPhotos\*.jpg photos\

# Unix/Mac
cp ~/Pictures/*.jpg photos/
```

### 3. Launch

**Windows:**
```bash
launcher.bat
```

**Unix/Mac:**
```bash
chmod +x launcher.sh
./launcher.sh
```

### 4. Browse!

The launcher will automatically:
- ✓ Download portable Python (~30MB, one-time)
- ✓ Create virtual environment
- ✓ Install dependencies
- ✓ Download LLaVA AI model (~4GB, one-time)
- ✓ Start tagging your photos
- ✓ Launch web server at http://localhost:5000

On subsequent runs, everything starts instantly!

## What Makes This Different?

**Zero Dependencies**: Unlike other galleries, GoodGallery doesn't require you to have Python installed. The launcher downloads its own portable Python runtime on first run. The entire application is self-contained in one folder.

**Truly Portable**: Copy the entire `GoodGallery` folder anywhere - different computer, USB drive, network share - it just works!

**AI-Powered**: Uses Meta's LLaVA vision model to automatically understand and tag your photos with descriptive keywords.

## AI Tagging

GoodGallery uses **LLaVA 1.5** to automatically tag your images with descriptive keywords.

### Requirements

- **GPU recommended**: NVIDIA GPU with 6GB+ VRAM for fast tagging
- **CPU works**: Slower but functional (expect 10-30s per image)

### How It Works

Auto-tagging is enabled by default in `config.yaml`. When you start the app:

1. Server starts at http://localhost:5000
2. AI scanner finds untagged images in `photos/`
3. LLaVA analyzes each image and generates tags
4. Tags are saved to the database
5. Search your photos by tags!

### Example Tags

```
"beach photo" → beach, ocean, sunset, sand, summer, vacation
"family dinner" → people, dining, food, indoor, evening, gathering
"mountain landscape" → mountains, landscape, nature, trees, hiking, scenic
```

## Folder Structure

After first run, your folder will look like this:

```
GoodGallery/
├── launcher.bat              # Windows: run this
├── launcher.sh               # Unix/Mac: run this
├── photos/                   # Put your photos here
│   └── README.txt
├── runtime/                  # Downloaded Python (one-time)
│   └── python-3.11.9/        # ~30MB
├── venv/                     # Python packages (~500MB)
├── models/                   # AI models (one-time)
│   └── llava/                # ~4GB
├── data/                     # Generated data
│   ├── gallery.db           # SQLite database
│   ├── thumbnails/          # Thumbnail cache
│   └── cache/               # Performance cache
├── bootstrap/               # Bootstrap scripts
├── app/                     # Application code
├── static/                  # Web assets
├── config.yaml              # Your settings (auto-created)
└── README.md               # This file
```

**Total size after first run**: ~5.5GB (mostly AI model)  
**Git tracks**: Only ~1MB of code (everything else is gitignored)

## Configuration

Edit `config.yaml` to customize:

```yaml
gallery:
  photo_directory: "./photos"     # Where your photos are
  port: 5000                       # Web server port
  thumbnail_size: 200              # Thumbnail dimensions
  images_per_page: 100             # Pagination

ai:
  model: "llava-hf/llava-1.5-7b-hf"  # AI model
  auto_tag: true                      # Tag on startup
  batch_size: 15                       # Images per batch
  use_quantization: true              # Reduce GPU memory
```

## Troubleshooting

### First Run Takes Forever

- **Normal!** First run downloads ~4.5GB (Python + LLaVA model)
- Subsequent runs start in seconds
- Check internet connection and disk space

### "CUDA out of memory"

- Reduce `batch_size` in config.yaml
- Ensure `use_quantization: true` is enabled
- Close other GPU applications
- CPU mode works too (just slower)

### "No photos showing"

- Verify photos are in `photos/` directory
- Check supported formats: JPG, PNG, GIF, WebP
- Look for errors in console output

### Windows Antivirus Blocking

- Allow `launcher.bat` and `runtime/python-3.11.9/python.exe`
- Some antivirus software flags downloaded Python as suspicious

### Unix/Mac Permission Denied

```bash
chmod +x launcher.sh
./launcher.sh
```

## Advanced Usage

### Use Your Own Photo Directory

Edit `config.yaml`:

```yaml
gallery:
  photo_directory: "/absolute/path/to/photos"
```

### Disable Auto-Tagging

Edit `config.yaml`:

```yaml
ai:
  auto_tag: false
```

Then tag manually from web UI.

### Run on Different Port

Edit `config.yaml`:

```yaml
gallery:
  port: 8080
```

## Credits

- Built on [LLaVA 1.5](https://github.com/haotian-liu/LLaVA)
- Uses Flask, Pillow, and PyTorch
- Portable Python from [python-build-standalone](https://github.com/indygreg/python-build-standalone)

## License

MIT License - Feel free to use and modify!
