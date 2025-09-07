#!/bin/bash

#############################################
# NWK IMAGE MANAGEMENT SYSTEM - AI-POWERED STARTUP
# Complete pipeline with CLIP validation & learning system
#############################################

echo "============================================================"
echo "🚀 NWK AI-POWERED IMAGE MANAGEMENT SYSTEM"
echo "============================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found!"
    echo "Please run this script from the WebScrape directory."
    exit 1
fi

# Kill any existing processes
echo "🔄 Stopping any existing instances..."
pkill -f "python app.py" 2>/dev/null || true
pkill -f "flask" 2>/dev/null || true
sleep 2

# Create output directories with full structure
echo "Creating output directories..."
mkdir -p output/{approved,pending,declined}
mkdir -p exports
mkdir -p logs
mkdir -p data

# Ensure proper permissions
chmod -R 755 output/
chmod -R 755 exports/
chmod -R 755 logs/
mkdir -p static/js static/css
mkdir -p data src tests
mkdir -p output/tier1 output/tier2 output/tier3

# Set up virtual environment if needed
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

echo "🐍 Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip first
echo "⬆️  Upgrading pip..."
pip install --upgrade pip -q

# Install ALL dependencies from requirements.txt
echo "📋 Installing complete dependency stack..."
if [ -f "requirements.txt" ]; then
    # Install base requirements first
    pip install -r requirements.txt -q
    echo "   ✅ Complete requirements.txt installed"
else
    echo "⚠️  Installing essential dependencies..."
    pip install flask werkzeug pandas openpyxl pyyaml python-dotenv aiohttp pillow -q
    pip install requests beautifulsoup4 selenium tqdm imagehash scikit-image numpy -q
    pip install flask-cors -q
fi

# Install CLIP and its dependencies
echo "🤖 Installing CLIP model and dependencies..."
echo "   This may take a few minutes on first install (~2GB)..."

# Check if PyTorch is installed, if not install it
python3 -c "import torch" 2>/dev/null || {
    echo "   📦 Installing PyTorch..."
    pip install torch torchvision torchaudio -q
}

# Install CLIP dependencies
echo "   📦 Installing CLIP dependencies..."
pip install ftfy regex tqdm -q

# Install CLIP from GitHub
echo "   📦 Installing CLIP model..."
pip install git+https://github.com/openai/CLIP.git -q

# Install EasyOCR for text extraction
echo "   📦 Installing EasyOCR for text extraction..."
pip install easyocr opencv-python -q

echo "   ✅ CLIP and dependencies installed"

# Initialize database with correct path
echo "💾 Initializing database..."
python3 << 'EOF'
from database import ImageDatabase
import os

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Initialize with correct path
db = ImageDatabase('data/products.db')
print("   ✅ Database initialized at data/products.db")

# Quick verification
cursor = db.conn.cursor()
cursor.execute("SELECT COUNT(*) FROM products")
count = cursor.fetchone()[0]
print(f"   📊 Database contains {count} products")
cursor.close()
EOF

# Clear any stale lock files
rm -f data/*.db-journal 2>/dev/null || true
rm -f data/*.db-wal 2>/dev/null || true

# Initialize and test CLIP model
echo "🤖 Initializing CLIP model..."
python3 << 'EOF'
import sys
try:
    import torch
    import clip
    from PIL import Image
    import numpy as np
    
    # Detect best available device
    if torch.backends.mps.is_available():
        device = torch.device("mps")
        device_name = "Apple Silicon GPU (MPS)"
    elif torch.cuda.is_available():
        device = torch.device("cuda")
        device_name = "NVIDIA GPU (CUDA)"
    else:
        device = torch.device("cpu")
        device_name = "CPU"
    
    print(f"   🔧 Using device: {device_name}")
    
    # Load CLIP model (this downloads it if not cached)
    print("   ⏳ Loading CLIP model (ViT-B/32)...")
    model, preprocess = clip.load("ViT-B/32", device=device)
    print("   ✅ CLIP model loaded and ready")
    
    # Quick test to ensure it works
    test_text = clip.tokenize(["a product image"]).to(device)
    with torch.no_grad():
        text_features = model.encode_text(test_text)
    print("   ✅ CLIP validation test passed")
    
except ImportError as e:
    print(f"   ❌ CLIP dependencies missing: {e}")
    print("   Run: pip install torch torchvision ftfy regex")
    print("   Run: pip install git+https://github.com/openai/CLIP.git")
    sys.exit(1)
except Exception as e:
    print(f"   ⚠️  CLIP initialization warning: {e}")
    print("   CLIP will initialize on first use")
EOF

# Check for .env file with all required settings
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Please update .env with your API keys"
    else
        echo "Creating comprehensive .env file..."
        cat > .env << 'EOL'
# API Keys
SERPAPI_KEY=your_serpapi_key_here

# AI Model Settings
CLIP_MODEL=ViT-B/32
CLIP_CONFIDENCE_THRESHOLD=0.65
CLIP_AUTO_APPROVE_THRESHOLD=0.65
CLIP_MANUAL_REVIEW_THRESHOLD=0.35

# Processing Settings
BATCH_SIZE=10
MAX_WORKERS=5
ENABLE_OCR=true
ENABLE_CLIP_VALIDATION=true

# Image Settings
MAX_IMAGE_SIZE_KB=200
IMAGE_QUALITY=85
IMAGE_FORMAT=JPEG

# Database Settings
DB_PATH=data/products.db
EOL
    fi
else
    echo "   ✅ Using existing .env configuration"
fi

echo ""
echo "============================================================"
echo "🎯 STARTING AI-POWERED NWK IMAGE MANAGEMENT SYSTEM"
echo "============================================================"
echo ""
echo "🌐 WEB INTERFACE AVAILABLE AT:"
echo "   📊 Dashboard:        http://localhost:8847"
echo "   📤 Import Products:  http://localhost:8847/import"
echo "   🔍 Review Queue:     http://localhost:8847/review"
echo "   📥 Export Results:   http://localhost:8847/export"
echo "   ⚙️  Management:       http://localhost:8847/management"
echo ""
echo "🤖 AI-POWERED FEATURES:"
echo "   ✅ CLIP Semantic Image Validation"
echo "   ✅ Continuous Learning System"
echo "   ✅ Intelligent Image Processing"
echo "   ✅ OCR Text Recognition (EasyOCR)"
echo "   ✅ Automated Quality Assessment"
echo "   ✅ Local-First Image Search"
echo "   ✅ SerpAPI Google Images Integration"
echo ""
echo "🔧 TECHNICAL CAPABILITIES:"
echo "   ✅ Async Pipeline Processing"
echo "   ✅ Hierarchical Storage (Tier1/2/3)"
echo "   ✅ Resume Interrupted Operations"
echo "   ✅ Duplicate Detection (ImageHash)"
echo "   ✅ Image Optimization (<200KB)"
echo "   ✅ Bulk Operations & Real-time Progress"
echo "   ✅ Enhanced Export Formats"
echo ""
echo "🗂️  PIPELINE MODULES:"
echo "   ✅ Core Pipeline (src/pipeline.py)"
echo "   ✅ Image Scraping (src/scrape.py)"
echo "   ✅ Async Downloader (src/downloader.py)"
echo "   ✅ Image Utils (src/img_utils.py)"
echo "   ✅ Storage Manager (src/storage.py)"
echo "   ✅ Quality Assurance (src/qa.py)"
echo ""
echo "💾 DATA MANAGEMENT:"
echo "   ✅ SQLite Database (ImageDatabase)"
echo "   ✅ Configuration Management (YAML)"
echo "   ✅ Environment Variables (.env)"
echo "   ✅ Learning Patterns (JSON)"
echo ""
echo "🚀 STARTUP COMPLETE - ALL SYSTEMS OPERATIONAL"
echo "⚠️  Press Ctrl+C to stop the server"
echo "============================================================"
echo ""

# Start the application with proper error handling
echo "🎬 Launching application..."
python3 app.py

