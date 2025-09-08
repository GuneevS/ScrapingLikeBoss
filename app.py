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
from dotenv import load_dotenv
import sqlite3
import pandas as pd

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

# Initialize database - use correct path
db = ImageDatabase('data/products.db')

# Initialize learning system
learning = LearningSystem()

# Load environment and configuration
load_dotenv()
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

# Processing state with enhanced tracking
processing_state = {
    'active': False,
    'is_running': False,
    'stop_requested': False,  # Add flag for stop requests
    'current_batch': None,
    'progress': 0,
    'message': 'Ready',
    'results': {},
    'current_product': None,
    'current_sku': None,
    'products_processed': 0,
    'products_total': 0,
    'current_action': 'idle',
    'images_found': 0,
    'images_downloaded': 0,
    'images_skipped': 0,
    'serpapi_calls': 0,
    'last_update': None
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
    # Recompute remaining including not_found
    cursor = db.conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE (image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found') AND (downloaded_image_path IS NULL OR downloaded_image_path = '')"
        )
        remaining = cursor.fetchone()[0]
    finally:
        cursor.close()
    stats['not_processed'] = remaining
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
    
    # Check if already processing
    global processing_state
    if processing_state['active']:
        return jsonify({'error': 'Already processing'}), 400
    
    # Get batch size from request
    data = request.json or {}
    batch_size = data.get('batch_size', 10)
    batch_size = min(max(1, int(batch_size)), 100)  # Limit between 1-100
    from_bottom = bool(data.get('from_bottom', False))
    force_web = bool(data.get('force_web', False))
    
    logger.info(f"Starting processing with batch_size: {batch_size}")
    
    processing_state['active'] = True
    processing_state['is_running'] = True
    processing_state['progress'] = 0
    processing_state['message'] = f'Starting processing {batch_size} products...'
    
    # Start processing in background thread
    def process_batch():
        try:
            logger.info(f"Thread started for processing {batch_size} products")
            
            # Get unprocessed products
            products = db.get_unprocessed_products_from_bottom(limit=batch_size) if from_bottom else db.get_unprocessed_products(limit=batch_size)
            logger.info(f"Found {len(products) if products else 0} unprocessed products")
            
            if not products:
                processing_state['message'] = 'No products to process'
                processing_state['progress'] = 100
                logger.warning("No unprocessed products found")
                return
            
            # Log product SKUs being processed
            skus = [p.get('Variant_SKU', 'Unknown') for p in products]
            logger.info(f"Processing SKUs: {skus}")
            
            # Process the batch
            def progress_callback(current, total, message):
                processing_state['progress'] = int((current / total) * 100)
                processing_state['message'] = message
                processing_state['products_processed'] = current
                processing_state['products_total'] = total
                processing_state['last_update'] = datetime.now().isoformat()
                # Extract SKU from message if present
                if 'Processing' in message:
                    parts = message.split(' ')
                    if len(parts) > 1:
                        processing_state['current_sku'] = parts[-1]
                        # Get product details
                        prod = db.get_product_by_sku(parts[-1])
                        if prod:
                            processing_state['current_product'] = f"{prod.get('Brand', '')} {prod.get('Title', '')}"
                processing_state['current_action'] = 'searching' if 'Searching' in message else 'processing'
                logger.info(f"Progress: {current}/{total} - {message}")
            
            # Wrap processor to pass force_web flag into async search
            def _process_with_force(products_list, cb):
                # monkey-patch: run each product with force_web
                async def _runner():
                    res = {
                        'success': 0, 'failed': 0, 'skipped': 0, 'errors': [], 'validated': 0
                    }
                    for idx, prod in enumerate(products_list):
                        try:
                            if cb:
                                cb(idx + 1, len(products_list), f"Processing {prod.get('Variant_SKU','Unknown')}")
                            r = await processor.search_product_image(prod, force_web=force_web)
                            if r and r.get('success'):
                                res['success'] += 1
                            else:
                                res['failed'] += 1
                        except Exception as e:
                            res['failed'] += 1
                            res['errors'].append(str(e))
                    return res
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(_runner())
                finally:
                    loop.close()

            results = _process_with_force(products, progress_callback) if force_web else processor.process_batch(products, progress_callback)
            
            logger.info(f"Processing complete: {results}")
            processing_state['message'] = f"Completed: {results['success']} successful, {results['failed']} failed"
            processing_state['progress'] = 100
            
        except Exception as e:
            logger.error(f"Processing error: {str(e)}", exc_info=True)
            processing_state['message'] = f"Error: {str(e)}"
        finally:
            processing_state['active'] = False
            processing_state['is_running'] = False
            logger.info("Processing thread finished")
    
    thread = threading.Thread(target=process_batch)
    thread.daemon = True  # Make thread daemon so it doesn't block shutdown
    thread.start()
    
    return jsonify({'success': True, 'message': f'Processing {batch_size} products', 'processed': batch_size})

@app.route('/api/process-all', methods=['POST'])
def process_all_images():
    """Process ALL remaining unprocessed images"""
    
    # Check if already processing
    global processing_state
    if processing_state.get('active') or processing_state.get('is_running'):
        logger.warning("Process-all called while already processing")
        return jsonify({'error': 'Already processing, please wait for current batch to complete'}), 400
    
    # Reset state completely before starting
    processing_state = {
        'active': True,
        'is_running': True,
        'stop_requested': False,  # Reset stop flag
        'current_batch': None,
        'progress': 0,
        'message': 'Starting to process all remaining products...',
        'results': {},
        'current_product': None,
        'current_sku': None,
        'products_processed': 0,
        'products_total': 0,
        'current_action': 'initializing',
        'images_found': 0,
        'images_downloaded': 0,
        'images_skipped': 0,
        'serpapi_calls': 0,
        'last_update': datetime.now().isoformat()
    }
    
    data = request.get_json(silent=True) or {}
    from_bottom = bool(data.get('from_bottom', False))
    force_web = bool(data.get('force_web', False))
    
    # Start processing in background thread
    def process_all():
        try:
            logger.info(f"Starting process_all with from_bottom={from_bottom}, force_web={force_web}")
            # Get ALL unprocessed products AT THE START - snapshot to avoid infinite loop
            cursor = db.conn.cursor()
            cursor.execute(
                """
                SELECT Variant_SKU FROM products 
                WHERE (image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found')
                   AND (downloaded_image_path IS NULL OR downloaded_image_path = '')
                """
            )
            all_skus_to_process = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            total_remaining = len(all_skus_to_process)
            
            if total_remaining == 0:
                processing_state['message'] = 'No products to process'
                processing_state['progress'] = 100
                return
            
            processing_state['message'] = f'Processing {total_remaining} products...'
            processing_state['products_total'] = total_remaining
            
            # Process in batches of 50 to avoid memory issues
            batch_size = 50
            processed_total = 0
            skus_processed = set()  # Track what we've already tried
            
            while processed_total < total_remaining:
                # Check if stop was requested
                if processing_state.get('stop_requested', False):
                    processing_state['message'] = f'Processing stopped at {processed_total}/{total_remaining} products'
                    logger.info(f"Processing stopped by user at {processed_total}/{total_remaining}")
                    break
                
                # Get next batch of SKUs we haven't tried yet
                remaining_skus = [sku for sku in all_skus_to_process if sku not in skus_processed]
                if not remaining_skus:
                    break
                    
                batch_skus = remaining_skus[:batch_size]
                
                # Get the actual product data for this batch
                cursor = db.conn.cursor()
                placeholders = ','.join(['?' for _ in batch_skus])
                cursor.execute(f"SELECT * FROM products WHERE Variant_SKU IN ({placeholders})", batch_skus)
                products = [dict(row) for row in cursor.fetchall()]
                cursor.close()
                
                if not products:
                    break
                
                # Mark these SKUs as processed
                for product in products:
                    skus_processed.add(product.get('Variant_SKU'))
                
                # Process this batch
                def progress_callback(current, total, message):
                    overall_progress = min(100, int(((processed_total + current) / total_remaining) * 100))
                    processing_state['progress'] = overall_progress
                    processing_state['message'] = f"Processing {processed_total + current}/{total_remaining}: {message}"
                    processing_state['products_processed'] = processed_total + current
                
                # Use force web mode optionally
                if force_web:
                    def _process_with_force(products_list, cb):
                        async def _runner():
                            res = {'success': 0, 'failed': 0, 'skipped': 0, 'errors': [], 'validated': 0}
                            for idx, prod in enumerate(products_list):
                                try:
                                    if cb:
                                        cb(idx + 1, len(products_list), f"Processing {prod.get('Variant_SKU','Unknown')}")
                                    r = await processor.search_product_image(prod, force_web=True)
                                    if r and r.get('success'):
                                        res['success'] += 1
                                    else:
                                        res['failed'] += 1
                                except Exception as e:
                                    res['failed'] += 1
                                    res['errors'].append(str(e))
                            return res
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(_runner())
                        finally:
                            loop.close()
                    results = _process_with_force(products, progress_callback)
                else:
                    results = processor.process_batch(products, progress_callback)
                processed_total += len(products)  # Count all attempted, not just success/failed
                
                # Update overall progress - cap at 100%
                processing_state['progress'] = min(100, int((processed_total / total_remaining) * 100))
                processing_state['products_processed'] = processed_total
                
                # Stop if we've processed all the SKUs we originally intended to
                if processed_total >= total_remaining:
                    break
            
            processing_state['message'] = f"Completed processing {processed_total} products"
            processing_state['progress'] = 100
            logger.info(f"Process-all completed: processed {processed_total} products")
            
        except Exception as e:
            logger.error(f"Processing error in process_all: {str(e)}", exc_info=True)
            processing_state['message'] = f"Error: {str(e)}"
        finally:
            # Ensure state is properly reset
            processing_state['active'] = False
            processing_state['is_running'] = False
            processing_state['current_action'] = 'idle'
            logger.info("Process-all thread finished, state reset")
    
    thread = threading.Thread(target=process_all)
    thread.daemon = True  # Make thread daemon so it doesn't block shutdown
    thread.start()
    
    return jsonify({'success': True, 'message': 'Processing all remaining products', 'processed': 'all'})

@app.route('/api/stop-processing', methods=['POST'])
def stop_processing():
    """Stop the current processing"""
    global processing_state
    
    if not processing_state['active']:
        return jsonify({'error': 'No processing is currently active'}), 400
    
    processing_state['stop_requested'] = True
    processing_state['message'] = 'Stopping processing...'
    
    # Wait a bit for the processing to actually stop
    import time
    for _ in range(10):  # Wait up to 2 seconds
        if not processing_state['active']:
            break
        time.sleep(0.2)
    
    # Force stop if still running
    if processing_state['active']:
        processing_state['active'] = False
        processing_state['is_running'] = False
        processing_state['message'] = 'Processing stopped (forced)'
    
    return jsonify({
        'success': True, 
        'message': 'Processing stopped',
        'processed': processing_state.get('products_processed', 0)
    })

@app.route('/api/progress')
def get_progress():
    """Get enhanced processing progress with detailed tracking"""
    # Add real-time stats if processing
    if processing_state['is_running']:
        cursor = db.conn.cursor()
        try:
            # Get counts of processed images today
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN image_status = 'approved' THEN 1 END) as approved,
                    COUNT(CASE WHEN image_status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN image_status = 'declined' THEN 1 END) as declined,
                    COUNT(CASE WHEN image_status = 'not_found' THEN 1 END) as not_found
                FROM products 
                WHERE processed_date >= date('now', 'start of day')
            """)
            row = cursor.fetchone()
            if row:
                processing_state['today_stats'] = {
                    'approved': row[0],
                    'pending': row[1],
                    'declined': row[2],
                    'not_found': row[3]
                }
        except:
            pass
        finally:
            cursor.close()
    
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

@app.route('/api/approve/<sku>', methods=['POST'])
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

@app.route('/api/decline/<sku>', methods=['POST'])
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

@app.route('/api/unapprove/<sku>', methods=['POST'])
def unapprove_product(sku):
    """Unapprove a previously approved product image"""
    
    # Get product details
    product = db.get_product_by_sku(sku)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    
    # Move from approved to pending
    success = processor.move_to_pending(sku)
    
    if success:
        # Update database status
        cursor = db.conn.cursor()
        try:
            cursor.execute('''
                UPDATE products SET 
                    image_status = 'pending'
                WHERE Variant_SKU = ?
            ''', (sku,))
            db.conn.commit()
            
            return jsonify({'success': True, 'message': 'Image moved to pending'})
        except Exception as e:
            db.conn.rollback()
            logger.error(f"Error unapproving {sku}: {str(e)}")
            return jsonify({'error': str(e)}), 500
        finally:
            cursor.close()
    else:
        return jsonify({'error': 'Failed to unapprove image'}), 500

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
    """Serve product image with comprehensive error handling and path repair"""
    
    try:
        product = db.get_product_by_sku(sku)
        
        if not product:
            logger.warning(f"Product not found for SKU: {sku}")
            return '', 404
        
        image_path = product['downloaded_image_path']
        if not image_path:
            logger.warning(f"No image path for SKU: {sku}")
            return '', 404
        
        # Check if file exists at recorded path
        if os.path.exists(image_path):
            logger.debug(f"Serving image: {image_path} for SKU: {sku}")
            return send_file(image_path)
        
        # If file doesn't exist, try to repair path by searching for it
        logger.warning(f"Image file not found at {image_path}, attempting repair for SKU: {sku}")
        
        # Search for image in all possible locations
        safe_sku = processor.sanitize_filename(sku)
        brand = product.get('Brand', 'Unknown')
        safe_brand = processor.sanitize_filename(brand) if brand else 'Unknown'
        
        search_dirs = [
            f"output/approved/{safe_brand}",
            f"output/pending/{safe_brand}", 
            f"output/declined/{safe_brand}",
            "output/approved",
            "output/pending",
            "output/declined"
        ]
        
        for search_dir in search_dirs:
            if os.path.exists(search_dir):
                for file in os.listdir(search_dir):
                    if safe_sku in file and file.lower().endswith(('.jpg', '.jpeg', '.png')):
                        found_path = os.path.join(search_dir, file)
                        logger.info(f"Found image at repaired path: {found_path} for SKU: {sku}")
                        
                        # Update database with correct path
                        cursor = db.conn.cursor()
                        try:
                            cursor.execute(
                                'UPDATE products SET downloaded_image_path = ? WHERE Variant_SKU = ?',
                                (found_path, sku)
                            )
                            db.conn.commit()
                            logger.info(f"Updated image path in database for SKU: {sku}")
                        finally:
                            cursor.close()
                        
                        return send_file(found_path)
        
        # If still not found, log comprehensive debugging info
        logger.error(f"Image completely missing for SKU: {sku}")
        logger.error(f"  - Expected path: {image_path}")
        logger.error(f"  - Product status: {product.get('image_status')}")
        logger.error(f"  - Brand: {brand}")
        logger.error(f"  - Safe SKU: {safe_sku}")
        
        return '', 404
        
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
    """Export to Excel - FIXED with proper filtering"""
    
    data = request.json
    batch_ids = data.get('batch_ids', [])
    status_filter = data.get('status_filter', 'all')
    
    # Generate filename with status indicator
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    status_suffix = f"_{status_filter}" if status_filter != 'all' else ''
    output_file = f"exports/NWK_Export_{timestamp}{status_suffix}.xlsx"
    os.makedirs('exports', exist_ok=True)
    
    # Export with new parameters - pass empty list as None for batch_ids
    success = db.export_to_excel(
        output_file, 
        None if not batch_ids else batch_ids,  # Fixed: pass None instead of empty list
        status_filter=status_filter
    )
    
    if success:
        # Get file size for UI
        file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
        
        return jsonify({
            'success': True,
            'file': output_file,
            'download_url': f'/download/{os.path.basename(output_file)}',
            'file_size': file_size
        })
    else:
        return jsonify({'error': 'Export failed - no data found or error occurred'}), 500

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
    """Get current statistics with optimized remaining count"""
    
    stats = db.get_statistics()
    
    # Use optimized query for remaining count (same as dashboard)
    cursor = db.conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE (image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found') AND (downloaded_image_path IS NULL OR downloaded_image_path = '')"
        )
        remaining = cursor.fetchone()[0]
    finally:
        cursor.close()
    stats['not_processed'] = remaining
    
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

@app.route('/products')
def products_page():
    """Visual product dashboard page"""
    return render_template('products.html')

@app.route('/api/products/all')
def get_all_products():
    """Get all products with filtering support"""
    
    # Use thread-safe cursor
    cursor = db.conn.cursor()
    cursor.row_factory = sqlite3.Row
    try:
        query = '''SELECT * FROM products ORDER BY Sorting, Variant_SKU'''
        results = cursor.execute(query).fetchall()
        products = [dict(row) for row in results]
        
        return jsonify({
            'success': True,
            'products': products,
            'total': len(products)
        })
    except Exception as e:
        logger.error(f"Error fetching products: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@app.route('/api/products/filters')
def get_product_filters():
    """Get unique values for filter dropdowns"""
    
    cursor = db.conn.cursor()
    try:
        brands = cursor.execute('SELECT DISTINCT Brand FROM products WHERE Brand IS NOT NULL ORDER BY Brand').fetchall()
        tier1s = cursor.execute('SELECT DISTINCT Tier_1 FROM products WHERE Tier_1 IS NOT NULL ORDER BY Tier_1').fetchall()
        
        return jsonify({
            'brands': [row[0] for row in brands],
            'tier1s': [row[0] for row in tier1s]
        })
    finally:
        cursor.close()

@app.route('/api/export/selected', methods=['POST'])
def export_selected():
    """Export selected products to Excel"""
    
    data = request.json
    skus = data.get('skus', [])
    
    if not skus:
        return jsonify({'error': 'No products selected'}), 400
    
    # Generate filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"exports/NWK_Selected_{len(skus)}_products_{timestamp}.xlsx"
    os.makedirs('exports', exist_ok=True)
    
    # Export selected products
    cursor = db.conn.cursor()
    try:
        placeholders = ','.join(['?' for _ in skus])
        query = f'SELECT * FROM products WHERE Variant_SKU IN ({placeholders})'
        df = pd.read_sql_query(query, db.conn, params=skus)
        
        if not df.empty:
            df.to_excel(output_file, index=False)
            return jsonify({
                'success': True,
                'download_url': f'/download/{os.path.basename(output_file)}'
            })
        else:
            return jsonify({'error': 'No data to export'}), 404
    except Exception as e:
        logger.error(f"Export error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@app.route('/api/reprocess/<sku>', methods=['POST'])
def reprocess_product(sku):
    """Reprocess a single product"""
    
    # Get the product
    product = db.get_product_by_sku(sku)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    
    # Clear existing image data
    cursor = db.conn.cursor()
    try:
        cursor.execute('''
            UPDATE products SET 
                downloaded_image_path = NULL,
                image_status = 'not_processed',
                confidence = NULL,
                source_retailer = NULL,
                search_query = NULL,
                image_source = NULL
            WHERE Variant_SKU = ?
        ''', (sku,))
        db.conn.commit()
        
        # Process the product
        results = processor.process_batch([dict(product)], progress_callback=None)
        
        if results['success'] > 0:
            # Get updated product
            updated = db.get_product_by_sku(sku)
            return jsonify({
                'success': True,
                'message': f'Product {sku} reprocessed successfully',
                'status': updated['image_status'] if updated else 'unknown'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to find image for product'
            })
            
    except Exception as e:
        db.conn.rollback()
        logger.error(f"Error reprocessing {sku}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@app.route('/api/validate-images', methods=['POST'])
def validate_images():
    """Run CLIP validation on products"""
    
    data = request.get_json() or {}
    validate_all = data.get('validate_all', False)
    skus = data.get('skus', [])
    
    try:
        # Import CLIP validator (lazy load)
        from clip_validator import CLIPValidator
        
        if validate_all:
            # Get all products with images but no CLIP scores
            products = db.get_products_for_validation()
        else:
            # Get specific products
            products = []
            for sku in skus:
                product = db.get_product_by_sku(sku)
                if product and product.get('downloaded_image_path'):
                    products.append(product)
        
        if not products:
            return jsonify({
                'success': False,
                'message': 'No products found for validation'
            })
        
        logger.info(f"Running CLIP validation on {len(products)} products")
        
        # Initialize validator with clip config
        clip_cfg = config.get('clip', {}).copy()
        clip_cfg.update({'update_database': True})
        validator = CLIPValidator(clip_cfg)
        
        # Run validation
        results = validator.validate_batch(products)
        
        return jsonify({
            'success': True,
            'message': f'Validated {len(products)} products',
            'results': results
        })
        
    except ImportError:
        return jsonify({
            'success': False,
            'error': 'CLIP validator not available'
        }), 500
    except Exception as e:
        logger.error(f"CLIP validation error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/clip-actions', methods=['POST'])
def clip_actions():
    """Perform actions based on CLIP scores"""
    
    data = request.get_json() or {}
    action = data.get('action')
    threshold = data.get('threshold', 0.6)
    
    try:
        if action == 'auto_approve_high':
            # Auto-approve products with high CLIP scores
            cursor = db.conn.cursor()
            cursor.execute(
                'SELECT Variant_SKU FROM products WHERE clip_confidence > ? AND image_status = "pending"',
                (threshold,)
            )
            skus = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            approved_count = 0
            for sku in skus:
                if processor.move_to_approved(sku):
                    approved_count += 1
            
            return jsonify({
                'success': True,
                'message': f'Auto-approved {approved_count} products with CLIP score > {threshold*100}%',
                'count': approved_count
            })
            
        elif action == 'auto_decline_low':
            # Auto-decline products with very low CLIP scores
            low_threshold = data.get('low_threshold', 0.3)
            cursor = db.conn.cursor()
            cursor.execute(
                'SELECT Variant_SKU FROM products WHERE clip_confidence < ? AND image_status = "pending"',
                (low_threshold,)
            )
            skus = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            declined_count = 0
            for sku in skus:
                if processor.move_to_declined(sku):
                    declined_count += 1
            
            return jsonify({
                'success': True,
                'message': f'Auto-declined {declined_count} products with CLIP score < {low_threshold*100}%',
                'count': declined_count
            })
            
        elif action == 'get_review_candidates':
            # Get products that need manual review (medium CLIP scores)
            cursor = db.conn.cursor()
            cursor.execute(
                'SELECT Variant_SKU, Brand, Title, clip_confidence, clip_action FROM products WHERE clip_confidence BETWEEN ? AND ? AND image_status = "pending" ORDER BY clip_confidence DESC LIMIT 50',
                (0.4, 0.7)
            )
            products = [{
                'sku': row[0],
                'brand': row[1], 
                'title': row[2],
                'confidence': row[3],
                'action': row[4]
            } for row in cursor.fetchall()]
            cursor.close()
            
            return jsonify({
                'success': True,
                'products': products,
                'count': len(products)
            })
            
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid action specified'
            }), 400
            
    except Exception as e:
        logger.error(f"CLIP action error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/validation-summary')
def get_validation_summary():
    """Get summary of CLIP validations"""
    
    try:
        cursor = db.conn.cursor()
        
        # Check if validation columns exist
        cursor.execute(
            "SELECT COUNT(*) FROM pragma_table_info('products') WHERE name='clip_confidence'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.close()
            return jsonify({
                'message': 'No validations performed yet',
                'total': 0
            })
        
        # Get validation statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(clip_confidence) as validated,
                AVG(clip_confidence) as avg_confidence,
                SUM(CASE WHEN clip_action = 'auto_approve' THEN 1 ELSE 0 END) as auto_approved,
                SUM(CASE WHEN clip_action = 'manual_review' THEN 1 ELSE 0 END) as needs_review,
                SUM(CASE WHEN clip_action = 'auto_reject' THEN 1 ELSE 0 END) as auto_rejected
            FROM products WHERE downloaded_image_path IS NOT NULL
        """)
        
        row = cursor.fetchone()
        stats = {
            'total': row[0],
            'validated': row[1],
            'avg_confidence': row[2],
            'auto_approved': row[3],
            'needs_review': row[4],
            'auto_rejected': row[5]
        }
        
        # Get recent validations
        cursor.execute("""
            SELECT Variant_SKU, Title, Brand, clip_confidence, clip_action, clip_validation
            FROM products 
            WHERE clip_confidence IS NOT NULL
            ORDER BY rowid DESC
            LIMIT 10
        """)
        
        recent = []
        for row in cursor.fetchall():
            recent.append({
                'sku': row[0],
                'title': row[1],
                'brand': row[2],
                'confidence': row[3],
                'action': row[4],
                'reason': row[5]
            })
        
        cursor.close()
        
        return jsonify({
            'stats': stats,
            'recent': recent
        })
        
    except Exception as e:
        logger.error(f"Error getting validation summary: {str(e)}")
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/validate-paths')
def validate_image_paths():
    """Validate all image paths in database exist on disk"""
    
    cursor = db.conn.cursor()
    try:
        products = cursor.execute(
            'SELECT Variant_SKU, downloaded_image_path FROM products WHERE downloaded_image_path IS NOT NULL'
        ).fetchall()
        
        results = {
            'total': len(products),
            'valid': 0,
            'missing': [],
            'invalid': 0
        }
        
        for sku, path in products:
            if path and os.path.exists(path):
                results['valid'] += 1
            else:
                results['missing'].append({'sku': sku, 'path': path})
                results['invalid'] += 1
        
        return jsonify(results)
    finally:
        cursor.close()

@app.route('/api/repair-paths', methods=['POST'])
def repair_image_paths():
    """Attempt to repair broken image paths"""
    
    repaired = 0
    failed = []
    
    cursor = db.conn.cursor()
    try:
        # Get all products with paths
        products = cursor.execute(
            'SELECT Variant_SKU, Title, Brand, downloaded_image_path FROM products WHERE downloaded_image_path IS NOT NULL'
        ).fetchall()
        
        for sku, title, brand, old_path in products:
            if old_path and not os.path.exists(old_path):
                # Try to find the image in approved/pending/declined folders
                safe_sku = processor.sanitize_filename(sku)
                safe_brand = processor.sanitize_filename(brand) if brand else 'Unknown'
                
                # Search in all possible locations
                search_paths = [
                    f"output/approved/{safe_brand}",
                    f"output/pending/{safe_brand}",
                    f"output/declined/{safe_brand}"
                ]
                
                found = False
                for search_dir in search_paths:
                    if os.path.exists(search_dir):
                        for file in os.listdir(search_dir):
                            if safe_sku in file and file.endswith('.jpg'):
                                new_path = os.path.join(search_dir, file)
                                # Update database
                                cursor.execute(
                                    'UPDATE products SET downloaded_image_path = ? WHERE Variant_SKU = ?',
                                    (new_path, sku)
                                )
                                repaired += 1
                                found = True
                                break
                    if found:
                        break
                
                if not found:
                    failed.append(sku)
        
        db.conn.commit()
        
        return jsonify({
            'success': True,
            'repaired': repaired,
            'failed': failed,
            'message': f'Repaired {repaired} paths, {len(failed)} could not be found'
        })
        
    except Exception as e:
        db.conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

if __name__ == '__main__':
    # Ensure all directories exist
    for folder in ['output/approved', 'output/pending', 'output/declined', 'uploads', 'exports']:
        os.makedirs(folder, exist_ok=True)
    
    # Start Flask app
    print("\n" + "="*60)
    print("NWK IMAGE MANAGEMENT SYSTEM")
    print("="*60)
    print("Starting web server...")
    print(f"Open browser to: http://localhost:8847")
    print("="*60 + "\n")
    
    # Disable auto-reload in debug mode to prevent crashes during processing
    app.run(debug=True, host='0.0.0.0', port=8847, use_reloader=False)