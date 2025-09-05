#!/usr/bin/env python3
"""
NWK Image Management System - Web Interface
Streamlined UI for product image processing with approval pipeline
"""

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import threading
import queue
from werkzeug.utils import secure_filename
import yaml

from database import ImageDatabase
from image_processor import IntelligentImageProcessor
from learning_system import LearningSystem

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'nwk-image-system-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# Create upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database
db = ImageDatabase()

# Initialize learning system
learning = LearningSystem()

# Load configuration
def load_config():
    config_path = 'config.yaml'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_content = f.read()
            config_content = os.path.expandvars(config_content)
            return yaml.safe_load(config_content)
    else:
        # Default config
        return {
            'search': {
                'serp_api_key': os.getenv('SERP_API_KEY', ''),
                'max_results': 10,
                'sa_keywords': 'South Africa product packshot retail'
            },
            'network': {
                'concurrency': 5,
                'timeout': 15
            },
            'output': {
                'base_dir': 'output'
            },
            'image': {
                'size': 1000,
                'max_kb': 200,
                'format': 'jpg'
            }
        }

config = load_config()

# Initialize processor
processor = IntelligentImageProcessor(config, db)

# Processing state
processing_state = {
    'is_running': False,
    'current_batch': None,
    'progress': {},
    'results': {}
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    """Main dashboard"""
    stats = db.get_statistics()
    return render_template('dashboard.html', stats=stats)

@app.route('/import')
def import_page():
    """Import Excel page"""
    # Use a thread-safe method to get batches
    cursor = db.conn.cursor()
    cursor.row_factory = db.conn.row_factory
    try:
        batches = cursor.execute('SELECT * FROM batches ORDER BY imported_at DESC').fetchall()
        return render_template('import.html', batches=[dict(b) for b in batches])
    finally:
        cursor.close()

@app.route('/api/import', methods=['POST'])
def import_excel():
    """Handle Excel file import"""
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.xlsx'):
        return jsonify({'error': 'Only .xlsx files are supported'}), 400
    
    # Save uploaded file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    # Import to database
    success, batch_id_or_error, count = db.import_excel(filepath)
    
    if success:
        return jsonify({
            'success': True,
            'batch_id': batch_id_or_error,
            'imported_count': count,
            'message': f'Successfully imported {count} products'
        })
    else:
        return jsonify({
            'success': False,
            'error': batch_id_or_error
        }), 500

@app.route('/api/process', methods=['POST'])
def start_processing():
    """Start processing products"""
    
    if processing_state['is_running']:
        return jsonify({'error': 'Processing already in progress'}), 400
    
    data = request.json
    limit = data.get('limit', 10)
    batch_id = data.get('batch_id')
    
    # Get unprocessed products
    products = db.get_unprocessed_products(limit)
    
    if not products:
        return jsonify({'error': 'No unprocessed products found'}), 404
    
    # Start processing in background
    processing_state['is_running'] = True
    processing_state['current_batch'] = batch_id
    processing_state['progress'] = {
        'current': 0,
        'total': len(products),
        'status': 'starting'
    }
    
    def process_thread():
        try:
            # Create event loop for async processing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            def progress_callback(progress):
                processing_state['progress'].update(progress)
            
            # Process products
            results = loop.run_until_complete(
                processor.process_batch(products, progress_callback)
            )
            
            processing_state['results'] = results
            processing_state['progress']['status'] = 'completed'
            
        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            processing_state['progress']['status'] = 'error'
            processing_state['progress']['error'] = str(e)
        finally:
            processing_state['is_running'] = False
            loop.close()
    
    thread = threading.Thread(target=process_thread)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': f'Started processing {len(products)} products'})

@app.route('/api/progress')
def get_progress():
    """Get processing progress"""
    return jsonify(processing_state)

@app.route('/review')
def review_page():
    """Review pending images"""
    
    # Get products needing review
    pending = db.get_products_for_review('pending', 50)
    
    # Add image URLs for display
    for product in pending:
        if product['downloaded_image_path'] and os.path.exists(product['downloaded_image_path']):
            # Create URL for serving image
            product['image_url'] = f"/image/{product['Variant_SKU']}"
            logger.debug(f"Image URL set for {product['Variant_SKU']}: {product['image_url']}")
        else:
            product['image_url'] = None
            logger.debug(f"No valid image path for {product['Variant_SKU']}: {product.get('downloaded_image_path', 'None')}")
    
    return render_template('review.html', products=pending)

@app.route('/api/approve/<sku>')
def approve_product(sku):
    """Approve a product image"""
    
    # Get product details for learning
    product = db.get_product_by_sku(sku)
    
    # Move to approved
    success = processor.move_to_approved(sku)
    
    if success:
        # Record in database
        db.approve_image(sku)
        
        # Record in learning system
        if product:
            learning.record_approval(dict(product))
        
        return jsonify({'success': True, 'message': 'Image approved'})
    else:
        return jsonify({'error': 'Failed to approve image'}), 500

@app.route('/api/decline/<sku>')
def decline_product(sku):
    """Decline a product image"""
    
    # Get product details for learning
    product = db.get_product_by_sku(sku)
    
    # Move to declined
    success = processor.move_to_declined(sku)
    
    if success:
        # Record in learning system
        if product:
            learning.record_rejection(dict(product))
        
        return jsonify({'success': True, 'message': 'Image declined'})
    else:
        return jsonify({'error': 'Failed to decline image'}), 500

@app.route('/api/bulk-action', methods=['POST'])
def bulk_action():
    """Handle bulk approve/decline actions"""
    
    data = request.json
    action = data.get('action')  # 'approve' or 'decline'
    skus = data.get('skus', [])
    
    if not action or not skus:
        return jsonify({'error': 'Invalid request'}), 400
    
    success_count = 0
    
    for sku in skus:
        if action == 'approve':
            if processor.move_to_approved(sku):
                db.approve_image(sku)
                success_count += 1
        elif action == 'decline':
            if processor.move_to_declined(sku):
                success_count += 1
    
    return jsonify({
        'success': True,
        'message': f'Successfully {action}d {success_count}/{len(skus)} images'
    })

@app.route('/api/clear', methods=['POST'])
def clear_images():
    """Clear images based on type"""
    
    data = request.json
    clear_type = data.get('type')
    
    if clear_type not in ['declined', 'pending', 'all_unapproved', 'full_reset']:
        return jsonify({'error': 'Invalid clear type'}), 400
    
    if clear_type == 'full_reset':
        # Require confirmation
        if not data.get('confirm', False):
            return jsonify({'error': 'Confirmation required for full reset'}), 400
    
    # Clear images
    count = db.clear_images(clear_type)
    
    return jsonify({
        'success': True,
        'message': f'Cleared {count} images',
        'type': clear_type
    })

@app.route('/image/<sku>')
def serve_image(sku):
    """Serve product image with better error handling"""
    
    try:
        product = db.get_product_by_sku(sku)
        
        if not product:
            logger.warning(f"Product not found for SKU: {sku}")
            return '', 404
        
        image_path = product['downloaded_image_path']
        if not image_path:
            logger.warning(f"No image path for SKU: {sku}")
            return '', 404
        
        if not os.path.exists(image_path):
            logger.warning(f"Image file not found: {image_path} for SKU: {sku}")
            return '', 404
        
        logger.debug(f"Serving image: {image_path} for SKU: {sku}")
        return send_file(image_path)
        
    except Exception as e:
        logger.error(f"Error serving image for SKU {sku}: {str(e)}")
        return '', 500

@app.route('/management')
def management_page():
    """System management page"""
    
    stats = db.get_statistics()
    return render_template('management.html', stats=stats)

@app.route('/export')
def export_page():
    """Export page"""
    
    # Use a thread-safe method to get batches
    cursor = db.conn.cursor()
    cursor.row_factory = db.conn.row_factory
    try:
        batches = cursor.execute('SELECT * FROM batches ORDER BY imported_at DESC').fetchall()
        return render_template('export.html', batches=[dict(b) for b in batches])
    finally:
        cursor.close()

@app.route('/api/export', methods=['POST'])
def export_excel():
    """Export to Excel"""
    
    data = request.json
    batch_ids = data.get('batch_ids', [])
    
    # Generate filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"exports/NWK_Export_{timestamp}.xlsx"
    os.makedirs('exports', exist_ok=True)
    
    # Export
    success = db.export_to_excel(output_file, batch_ids if batch_ids else None)
    
    if success:
        return jsonify({
            'success': True,
            'file': output_file,
            'download_url': f'/download/{os.path.basename(output_file)}'
        })
    else:
        return jsonify({'error': 'Export failed'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Download exported file"""
    
    filepath = os.path.join('exports', filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    else:
        return 'File not found', 404

@app.route('/api/stats')
def get_stats():
    """Get current statistics"""
    
    stats = db.get_statistics()
    insights = db.get_learning_insights()
    
    # Add learning system insights
    learning_insights = learning.export_insights()
    
    return jsonify({
        'stats': stats,
        'insights': insights,
        'learning': learning_insights
    })

@app.route('/api/learning/insights')
def get_learning_insights():
    """Get detailed learning system insights"""
    
    insights = learning.export_insights()
    suggestions = learning.suggest_improvements()
    
    return jsonify({
        'insights': insights,
        'suggestions': suggestions,
        'success_rate': learning.get_overall_success_rate(),
        'best_retailers': learning.get_best_retailers(),
        'best_strategy': learning.get_best_search_strategy()
    })

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Get or update configuration"""
    
    global config, processor
    
    if request.method == 'GET':
        return jsonify(config)
    
    elif request.method == 'POST':
        new_config = request.json
        
        # Save config
        with open('config.yaml', 'w') as f:
            yaml.dump(new_config, f)
        
        # Reload
        config = load_config()
        processor = IntelligentImageProcessor(config, db)
        
        return jsonify({'success': True, 'message': 'Configuration updated'})

@app.route('/api/test-connection')
def test_connection():
    """Test database and API connections"""
    
    results = {
        'database': False,
        'api_key': False,
        'folders': False
    }
    
    # Test database
    try:
        db.get_statistics()
        results['database'] = True
    except:
        pass
    
    # Test API key
    if config.get('search', {}).get('serp_api_key'):
        results['api_key'] = True
    
    # Test folders
    folders = ['output/approved', 'output/pending', 'output/declined']
    results['folders'] = all(os.path.exists(f) for f in folders)
    
    return jsonify(results)

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Ensure all directories exist
    for folder in ['output/approved', 'output/pending', 'output/declined', 'uploads', 'exports']:
        os.makedirs(folder, exist_ok=True)
    
    # Start Flask app
    print("\n" + "="*60)
    print("NWK IMAGE MANAGEMENT SYSTEM")
    print("="*60)
    print("Starting web server...")
    print(f"Open browser to: http://localhost:5001")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5001)