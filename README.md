# GoodGallery

A standalone image gallery application with AI-powered tagging using LLaVA.

## Features

- 📁 Browse large image collections (tested with 100k+ images)
- 🔍 Powerful search with tag filters and boolean operators
- 🏷️ **AI Auto-tagging** using LLaVA vision model
- 🖼️ Automatic thumbnail generation
- ⚡ Fast caching system
- 🎨 Clean web interface with infinite scroll
- 💾 SQLite database (zero configuration)

## Quick Start

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd GoodGallery
```

### 2. Configure

Copy the example config and edit it:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` and set your photo directory:

```yaml
gallery:
  photo_directory: "/path/to/your/photos"
```

### 3. Run

```bash
python launcher.py
```

The launcher will:
- ✓ Check Python version (3.10+ required)
- ✓ Install dependencies automatically
- ✓ Download LLaVA model on first run (~7GB, one-time)
- ✓ Create database and scan your photos
- ✓ Start web server on http://localhost:5000
- ✓ Open your browser

## AI Tagging

GoodGallery uses **LLaVA 1.5** to automatically tag your images with descriptive keywords.

### Requirements

- **GPU recommended**: NVIDIA GPU with 6GB+ VRAM
- **CPU works**: Slower but functional (expect 10-30s per image)

### How It Works

1. Visit http://localhost:5000 after starting the gallery
2. Click "Start Auto-Tagging" button
3. LLaVA analyzes each image and generates tags
4. Tags are saved to the database
5. Search your photos by tags!

### Example Tags

```
"beach photo" → beach, ocean, sunset, sand, summer, vacation
"family dinner" → people, dining, food, indoor, evening, gathering
"mountain landscape" → mountains, landscape, nature, trees, hiking, scenic
```

## Manual Installation (Advanced)

If you prefer manual setup:

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp config.yaml.example config.yaml
# Edit config.yaml

# 4. Run
python app/server.py
```

## Configuration Options

See `config.yaml.example` for all available options:

- Gallery settings (port, thumbnail size, pagination)
- AI model selection and batch sizes
- Database path

## Architecture

```
GoodGallery/
├── launcher.py          # One-command startup
├── config.yaml          # Your configuration
├── requirements.txt     # Python dependencies
├── app/
│   ├── server.py       # Flask web server
│   ├── database.py     # SQLite operations
│   ├── gallery.py      # Gallery logic
│   ├── thumbnails.py   # Thumbnail generation
│   ├── ai_tagger.py    # LLaVA integration
│   └── templates/      # HTML templates
├── static/             # CSS, JavaScript
└── data/              # Generated on first run
    ├── gallery.db     # Your database
    ├── thumbnails/    # Generated thumbnails
    └── cache/         # Performance cache
```

## Troubleshooting

### "CUDA out of memory"
- Reduce `batch_size` in config.yaml
- Ensure `use_quantization: true` is enabled
- Close other GPU applications

### "Model download failed"
- Check internet connection
- Ensure ~7GB free disk space
- Model downloads automatically on first AI tagging run

### "No photos showing"
- Verify `photo_directory` path in config.yaml
- Check photo extensions match `allowed_extensions`
- Look for errors in console output

## Credits

- Built on [LLaVA 1.5](https://github.com/haotian-liu/LLaVA)
- Uses Flask, Pillow, and PyTorch
- Ported from original PHP gallery

## License

MIT License - Feel free to use and modify!
