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
    pip install -r requirements.txt -q
    echo "   ✅ Complete requirements.txt installed"
else
    echo "⚠️  Installing essential dependencies..."
    pip install flask werkzeug pandas openpyxl pyyaml python-dotenv aiohttp pillow -q
    pip install requests beautifulsoup4 selenium tqdm imagehash scikit-image numpy -q
    pip install flask-cors torch torchvision ftfy regex easyocr -q
    pip install git+https://github.com/openai/CLIP.git -q
fi

# Initialize database if needed
if [ ! -f data/products.db ]; then
    echo "Initializing database..."
    python -c "from database import ProductDatabase; db = ProductDatabase('data/products.db'); print('Database initialized')" 2>/dev/null || true
fi

# Clear any stale lock files
rm -f data/*.db-journal 2>/dev/null || true
rm -f data/*.db-wal 2>/dev/null || true

# Check CLIP model availability
echo "🤖 Checking CLIP model..."
python3 -c "
import torch
import clip
try:
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model, preprocess = clip.load('ViT-B/32', device=device)
    print(f'   ✅ CLIP model loaded on {device}')
except Exception as e:
    print(f'   ⚠️  CLIP model will download on first use: {e}')
" 2>/dev/null || echo "   ⚠️  CLIP model will be downloaded when needed"

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

