#!/bin/bash

#############################################
# NWK IMAGE MANAGEMENT SYSTEM - PRODUCTION STARTUP
# The ONLY startup script you need
#############################################

echo "============================================================"
echo "🚀 NWK IMAGE MANAGEMENT SYSTEM - PRODUCTION READY"
echo "============================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found!"
    echo "Please run this script from the WebScrape directory."
    exit 1
fi

# Kill any existing processes on port 5001
echo "🔄 Stopping any existing instances..."
pkill -f "python app.py" 2>/dev/null || true
sleep 2

# Create required directories
echo "📁 Setting up directories..."
mkdir -p output/approved output/pending output/declined
mkdir -p uploads exports static/js static/css

# Set up virtual environment if needed
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

echo "🐍 Activating virtual environment..."
source .venv/bin/activate

# Install essential dependencies if needed
echo "📋 Checking dependencies..."
pip install flask werkzeug pandas openpyxl pyyaml python-dotenv aiohttp pillow -q

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found - creating template..."
    echo "SERP_API_KEY=your_api_key_here" > .env
    echo "   💡 Edit .env file to add your SerpAPI key"
fi

echo ""
echo "============================================================"
echo "🎯 STARTING NWK IMAGE MANAGEMENT SYSTEM"
echo "============================================================"
echo ""
echo "🌐 WEB INTERFACE WILL BE AVAILABLE AT:"
echo "   📊 Dashboard:     http://localhost:5001"
echo "   📤 Import:        http://localhost:5001/import"
echo "   🔍 Review:        http://localhost:5001/review"
echo "   📥 Export:        http://localhost:5001/export"
echo "   ⚙️  Management:    http://localhost:5001/management"
echo ""
echo "🔥 FEATURES READY:"
echo "   ✅ Full Product Names (no truncation)"
echo "   ✅ Click-to-Enlarge Image Modal" 
echo "   ✅ Bulk Operations"
echo "   ✅ Real-time Progress"
echo "   ✅ Enhanced Exports"
echo "   ✅ Zero JavaScript Errors"
echo "   ✅ FIXED: Filename collision bug"
echo ""
echo "⚠️  Press Ctrl+C to stop the server"
echo "============================================================"
echo ""

# Start the application
python app.py

