# NWK Image Management System - Complete Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Key Features](#key-features)
4. [Installation & Setup](#installation--setup)
5. [API Endpoints](#api-endpoints)
6. [Database Schema](#database-schema)
7. [Image Processing Pipeline](#image-processing-pipeline)
8. [CLIP Validation System](#clip-validation-system)
9. [Frontend Components](#frontend-components)
10. [Troubleshooting](#troubleshooting)

---

## System Overview

The NWK Image Management System is an AI-powered web application for automated product image discovery, validation, and management. It uses advanced computer vision (CLIP) and OCR technologies to ensure product images match their metadata.

### Core Technologies
- **Backend**: Flask (Python 3.11)
- **Database**: SQLite
- **AI/ML**: OpenAI CLIP, EasyOCR
- **Image Search**: SerpAPI (Google Images)
- **Frontend**: Vanilla JavaScript with custom UI components
- **Image Processing**: Pillow, scikit-image

---

## Architecture

```
WebScrape/
├── app.py                  # Main Flask application
├── database.py             # Database operations
├── image_processor.py      # Image search & processing
├── clip_validator.py       # CLIP validation & OCR
├── learning_system.py      # ML feedback loop
├── START.sh               # Startup script
├── requirements.txt       # Python dependencies
├── config.yaml           # Configuration
├── .env                  # API keys & settings
│
├── static/
│   ├── css/              # Stylesheets
│   └── js/               # JavaScript modules
│
├── templates/            # HTML templates
│   ├── base.html        # Base template
│   ├── dashboard.html   # Main dashboard
│   ├── products.html    # Product management
│   └── ...
│
├── output/              # Processed images
│   ├── approved/        # Approved images
│   ├── pending/         # Awaiting review
│   └── declined/        # Rejected images
│
└── data/               # Database & cache
    └── products.db     # SQLite database
```

---

## Key Features

### 1. Intelligent Image Discovery
- **Multi-retailer search**: Shoprite, Pick n Pay, Checkers, and more
- **Smart caching**: Reduces duplicate API calls for similar products
- **Variant-aware matching**: Handles different flavors/sizes correctly
- **Confidence scoring**: Rates image-product match quality

### 2. CLIP Validation with OCR
- **Visual similarity**: Uses CLIP model to match images with product descriptions
- **Text extraction**: OCR reads text from images for verification
- **Brand detection**: Confirms brand presence in image
- **Adjustable thresholds**: 
  - Auto-approve: ≥65% confidence
  - Manual review: 35-65% confidence
  - Auto-reject: <35% confidence

### 3. Learning System
- **Feedback loop**: Learns from user approvals/rejections
- **Retailer ranking**: Prioritizes successful sources
- **Search optimization**: Improves queries over time

### 4. Batch Processing
- **Configurable batch sizes**: 1-100 products at a time
- **Progress tracking**: Real-time updates
- **Resume capability**: Continues from interruptions
- **Parallel processing**: Multiple workers for speed

---

## Installation & Setup

### Prerequisites
- Python 3.11+
- 4GB+ RAM (8GB recommended for CLIP)
- SerpAPI account with API key

### Quick Start
```bash
# Clone repository
cd WebScrape

# Run startup script
chmod +x START.sh
./START.sh

# Script will:
# 1. Create virtual environment
# 2. Install all dependencies
# 3. Initialize database
# 4. Create directory structure
# 5. Start web server on port 8847
```

### Manual Setup
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your SERPAPI_KEY

# Initialize database
python -c "from database import ProductDatabase; db = ProductDatabase('data/products.db')"

# Start server
python app.py
```

---

## API Endpoints

### Processing Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process` | Start batch processing |
| GET | `/api/progress` | Get processing status |
| POST | `/api/stop` | Stop current processing |

### Product Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products/all` | Get all products |
| POST | `/api/approve/<sku>` | Approve product image |
| POST | `/api/decline/<sku>` | Decline product image |
| POST | `/api/unapprove/<sku>` | Unapprove product |
| POST | `/api/reprocess/<sku>` | Reprocess single product |

### CLIP Validation
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/validate-images` | Run CLIP validation |
| POST | `/api/clip-actions` | Execute CLIP-based actions |
| GET | `/api/validation-summary` | Get validation statistics |

### Import/Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/import` | Import Excel file |
| POST | `/api/export` | Export to Excel |
| GET | `/download/<filename>` | Download exported file |

### Image Serving
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/image/<sku>` | Serve product image |

---

## Database Schema

### Products Table
```sql
CREATE TABLE products (
    Variant_SKU TEXT PRIMARY KEY,
    Title TEXT,
    Brand TEXT,
    Variant_Title TEXT,
    Variant_option TEXT,
    Tier_1 TEXT,
    Tier_2 TEXT,
    Tier_3 TEXT,
    downloaded_image_path TEXT,
    image_status TEXT,  -- 'not_processed', 'pending', 'approved', 'declined'
    confidence REAL,
    source_retailer TEXT,
    image_source TEXT,  -- Full URL where image was found
    clip_confidence REAL,
    clip_action TEXT,
    clip_validation TEXT,
    detected_text TEXT,
    ocr_match BOOLEAN,
    updated_at TIMESTAMP
)
```

### Search Cache Table
```sql
CREATE TABLE search_cache (
    query TEXT PRIMARY KEY,
    title TEXT,
    image_url TEXT,
    confidence REAL,
    source TEXT,
    cached_at TIMESTAMP,
    used_count INTEGER DEFAULT 1
)
```

---

## Image Processing Pipeline

### 1. Search Strategy
```python
# Priority order for retailers
TRUSTED_RETAILERS = {
    'tier1': ['shoprite.co.za', 'pnp.co.za', 'checkers.co.za'],
    'tier2': ['makro.co.za', 'game.co.za', 'woolworths.co.za'],
    'tier3': [dynamic based on learning]
}
```

### 2. Image Download & Optimization
- Downloads images via async HTTP
- Optimizes to <200KB JPEG
- Square crops for consistency
- Saves with SKU in filename for uniqueness

### 3. Metadata Storage
Each image has accompanying `.json` file:
```json
{
    "sku": "716001049019408",
    "title": "Product Name",
    "brand": "Brand Name",
    "source": "shoprite.co.za",
    "source_url": "https://www.shoprite.co.za/product/...",
    "confidence": 85,
    "search_query": "site:shoprite.co.za Brand Product 500ml",
    "downloaded_at": "2024-01-15T10:30:00"
}
```

---

## CLIP Validation System

### How It Works
1. **Image Encoding**: Converts image to feature vector
2. **Text Encoding**: Creates descriptions from product metadata
3. **Similarity Calculation**: Measures image-text alignment
4. **OCR Enhancement**: Extracts and matches text from image
5. **Confidence Adjustment**: Applies OCR boost if text matches

### Validation Results
```python
{
    'valid': True/False,
    'confidence': 0.75,  # 0-1 score
    'action': 'auto_approve'/'manual_review'/'auto_reject',
    'detected_text': 'brand product 500ml...',
    'ocr_match': True,
    'quality_score': 0.8,
    'issues': []
}
```

---

## Frontend Components

### Dashboard (`/`)
- System overview with statistics
- Process buttons (custom batch, all)
- Real-time progress tracking
- CLIP validation summary
- System health status

### Products Page (`/products`)
- Simplified table view:
  - Image thumbnail
  - SKU
  - Product Name (Title + Variant)
  - Brand
  - Category (Tier 1)
  - Status badge
  - CLIP Analysis (score + details)
  - Source (with clickable link)
  - Action buttons
- Filters and search
- Bulk operations
- Pagination

### Key UI Features
- **Custom confirmation modals** instead of native dialogs
- **Persistent alert messages** with icons
- **Loading states** on buttons during operations
- **Responsive design** with proper mobile support

---

## Troubleshooting

### Common Issues

#### 1. 404 Errors for Images
**Cause**: Image not yet processed or path incorrect
**Solution**: 
- Check if product has been processed
- Verify image exists in output directory
- Run repair endpoint: `/api/repair-paths`

#### 2. Low CLIP Scores for Valid Images
**Cause**: Generic product descriptions, poor OCR
**Solution**:
- Ensure good lighting in product images
- Check if brand text is visible
- Adjust thresholds in config

#### 3. Processing Hangs
**Cause**: API rate limits, network issues
**Solution**:
- Check SerpAPI quota
- Verify internet connection
- Restart with smaller batch size

#### 4. Database Lock Errors
**Cause**: Multiple processes accessing database
**Solution**:
```bash
# Clear lock files
rm data/*.db-journal
rm data/*.db-wal
# Restart application
```

### Performance Optimization

1. **Enable Caching**: Reduces API calls by 70%+
2. **Adjust Workers**: Set MAX_WORKERS based on CPU cores
3. **Batch Size**: Start with 10-20 for testing
4. **CLIP Device**: Use CUDA if available for 10x speed

### API Rate Limits
- SerpAPI: 100 searches/month (free tier)
- Recommended: Process in batches of 10-20
- Monitor usage at: https://serpapi.com/dashboard

---

## Configuration

### config.yaml
```yaml
api:
  serpapi_key: ${SERPAPI_KEY}
  
search:
  results_per_query: 3
  timeout: 30
  
processing:
  batch_size: 10
  max_workers: 5
  
image:
  max_size_kb: 200
  quality: 85
  format: JPEG
```

### Environment Variables (.env)
```bash
# Required
SERPAPI_KEY=your_key_here

# Optional - defaults shown
CLIP_MODEL=ViT-B/32
CLIP_CONFIDENCE_THRESHOLD=0.65
BATCH_SIZE=10
MAX_WORKERS=5
ENABLE_OCR=true
```

---

## Development

### Adding New Retailers
Edit `image_processor.py`:
```python
TRUSTED_RETAILERS = {
    'tier1': [..., 'newretailer.com'],
    ...
}
```

### Adjusting CLIP Thresholds
Edit `clip_validator.py`:
```python
if max_score >= 0.65:  # Auto-approve threshold
    action = 'auto_approve'
elif max_score >= 0.35:  # Manual review threshold
    action = 'manual_review'
```

### Custom Processing Logic
Override in `image_processor.py`:
```python
def evaluate_results_with_variant_matching(self, results, product, site):
    # Add custom scoring logic
    pass
```

---

## Support & Maintenance

### Logs
- Application logs: `logs/app.log`
- Processing logs: Terminal output
- CLIP validation log: In-memory (export via API)

### Database Maintenance
```bash
# Backup database
cp data/products.db data/products_backup.db

# Vacuum database (reduce size)
sqlite3 data/products.db "VACUUM;"

# Check integrity
sqlite3 data/products.db "PRAGMA integrity_check;"
```

### Updates
```bash
# Update dependencies
pip install --upgrade -r requirements.txt

# Update CLIP model
pip install --upgrade git+https://github.com/openai/CLIP.git
```

---

## License & Credits

**NWK Image Management System**
- Developed for NWK product catalog enrichment
- Uses OpenAI CLIP for image validation
- Powered by SerpAPI for image search

For support, please refer to this documentation or check the logs for detailed error messages.
