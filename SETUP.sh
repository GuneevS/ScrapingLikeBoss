#!/bin/bash

#############################################
# NWK IMAGE MANAGEMENT SYSTEM - INITIAL SETUP
# Run this after cloning from GitHub
#############################################

echo "============================================================"
echo "🚀 NWK IMAGE MANAGEMENT SYSTEM - INITIAL SETUP"
echo "============================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found!"
    echo "Please run this script from the project root directory."
    exit 1
fi

# Create essential directories
echo "📁 Creating essential directories..."
mkdir -p data
mkdir -p output/{approved,pending,declined}
mkdir -p output/{tier1,tier2,tier3}
mkdir -p exports
mkdir -p logs
mkdir -p uploads
mkdir -p static/{js,css,images}

# Set proper permissions
chmod -R 755 output/
chmod -R 755 exports/
chmod -R 755 logs/
chmod -R 755 uploads/

echo "   ✅ Directory structure created"

# Create .env file from template if it doesn't exist
if [ ! -f ".env" ]; then
    echo "🔧 Creating .env configuration file..."
    cat > .env << 'EOL'
# NWK Image Management System - Environment Configuration
# Fill in your actual values below

# API Keys (REQUIRED)
SERP_API_KEY=your_serpapi_key_here

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

# Development Settings
FLASK_ENV=development
FLASK_DEBUG=true
EOL
    echo "   ✅ .env file created"
    echo "   ⚠️  IMPORTANT: Edit .env file and add your SerpAPI key!"
else
    echo "   ✅ .env file already exists"
fi

# Create initial database
echo "💾 Initializing database..."
python3 -c "
import os
import sys
sys.path.insert(0, '.')

try:
    from database import ImageDatabase
    
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)
    
    # Initialize database
    db = ImageDatabase('data/products.db')
    print('   ✅ Database initialized successfully')
    
    # Check if it has data
    cursor = db.conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM products')
    count = cursor.fetchone()[0]
    cursor.close()
    
    if count == 0:
        print('   ℹ️  Database is empty - import Excel file to add products')
    else:
        print(f'   📊 Database contains {count} products')
        
except Exception as e:
    print(f'   ❌ Database initialization failed: {e}')
    print('   💡 You may need to install dependencies first with: pip install -r requirements.txt')
"

# Create learning patterns file if it doesn't exist
if [ ! -f "learning_patterns.json" ]; then
    echo "🧠 Creating learning patterns file..."
    cat > learning_patterns.json << 'EOL'
{
    "search_strategies": [
        "barcode_first",
        "brand_product",
        "product_only"
    ],
    "retailer_success": {
        "shoprite.co.za": 0.85,
        "checkers.co.za": 0.80,
        "pnp.co.za": 0.75,
        "makro.co.za": 0.70
    },
    "confidence_adjustments": {
        "confidence_thresholds": {
            "auto_approve": 65,
            "needs_review": 35,
            "auto_reject": 20
        }
    },
    "last_updated": "2024-01-01T00:00:00"
}
EOL
    echo "   ✅ Learning patterns initialized"
fi

# Create no-image placeholder
if [ ! -f "static/images/no-image.png" ]; then
    echo "🖼️  Creating placeholder image..."
    # Create a simple 200x200 gray placeholder
    python3 -c "
try:
    from PIL import Image, ImageDraw, ImageFont
    import os
    
    os.makedirs('static/images', exist_ok=True)
    
    # Create a simple placeholder image
    img = Image.new('RGB', (200, 200), color='#f0f0f0')
    draw = ImageDraw.Draw(img)
    
    # Add text
    try:
        # Try to use default font
        font = ImageFont.load_default()
    except:
        font = None
    
    text = 'No Image'
    if font:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (200 - text_width) // 2
        y = (200 - text_height) // 2
        draw.text((x, y), text, fill='#666666', font=font)
    
    img.save('static/images/no-image.png')
    print('   ✅ Placeholder image created')
    
except ImportError:
    print('   ⚠️  PIL not available - placeholder image not created')
except Exception as e:
    print(f'   ⚠️  Could not create placeholder image: {e}')
"
fi

echo ""
echo "============================================================"
echo "✅ SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "📋 NEXT STEPS:"
echo "1. Edit the .env file and add your SerpAPI key:"
echo "   nano .env"
echo ""
echo "2. Install dependencies and start the application:"
echo "   ./START.sh"
echo ""
echo "3. Open your browser to:"
echo "   http://localhost:8847"
echo ""
echo "📚 IMPORTANT NOTES:"
echo "• You need a SerpAPI key from https://serpapi.com/"
echo "• Import an Excel file with product data to get started"
echo "• The system requires Python 3.8+ and about 2GB for CLIP model"
echo ""
echo "🆘 TROUBLESHOOTING:"
echo "• If you get import errors, run: pip install -r requirements.txt"
echo "• If database errors occur, delete data/products.db and re-run setup"
echo "• For CLIP issues, ensure you have sufficient RAM (4GB+)"
echo ""
echo "============================================================"
