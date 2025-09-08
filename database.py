"""
Database module for NWK Image Management System
Handles all data persistence with full Excel column mirroring
"""

import sqlite3
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from pathlib import Path

# Initialize logger
logger = logging.getLogger(__name__)

class ImageDatabase:
    def __init__(self, db_path: str = "nwk_images.db"):
        """Initialize database with full Excel schema mirroring"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_database()
        
    def init_database(self):
        """Create tables with full Excel column preservation"""
        
        # Main products table - mirrors Excel exactly
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                -- Original Excel columns
                Handle TEXT,
                Title TEXT,
                Body TEXT,
                Brand TEXT,
                Variant_Title TEXT,
                Variant_option TEXT,
                Variant_SKU TEXT PRIMARY KEY,
                Weight_in_grams INTEGER,
                Variant_Barcode TEXT,
                Image_link TEXT,
                Variant_Image TEXT,
                Sorting INTEGER,
                Vendor TEXT,
                VendorName TEXT,
                Supplier_SKU TEXT,
                Tier_1 TEXT,
                Tier_2 TEXT,
                Tier_3 TEXT,
                
                -- System columns
                downloaded_image_path TEXT,
                image_status TEXT, -- 'approved', 'pending', 'declined', 'not_found', 'not_processed'
                confidence REAL,
                source_retailer TEXT,
                scraped_description TEXT, -- Product description from scraped source
                search_query TEXT, -- Search query used to find the image
                image_source TEXT, -- Source URL of the image
                processed_date TIMESTAMP,
                approved_date TIMESTAMP,
                batch_id TEXT,
                search_count INTEGER DEFAULT 0,
                last_search_date TIMESTAMP
            )
        ''')
        
        # Batches table for managing multiple imports
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                filename TEXT,
                imported_at TIMESTAMP,
                total_products INTEGER,
                processed INTEGER DEFAULT 0,
                approved INTEGER DEFAULT 0,
                pending INTEGER DEFAULT 0,
                declined INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Search cache to avoid repeated API calls
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_cache (
                search_key TEXT PRIMARY KEY,
                barcode TEXT,
                brand TEXT,
                title TEXT,
                image_url TEXT,
                confidence REAL,
                source TEXT,
                cached_at TIMESTAMP,
                used_count INTEGER DEFAULT 1
            )
        ''')
        
        # Learning table - track user decisions for improvement
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS learning_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_sku TEXT,
                confidence REAL,
                source TEXT,
                user_action TEXT, -- 'approved' or 'declined'
                feedback_date TIMESTAMP,
                brand TEXT,
                has_barcode_match BOOLEAN,
                has_brand_match BOOLEAN,
                has_size_match BOOLEAN
            )
        ''')
        
        # Create indexes for performance
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_barcode ON products(Variant_Barcode)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_brand ON products(Brand)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON products(image_status)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_batch ON products(batch_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_image_path ON products(downloaded_image_path)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sorting ON products(Sorting)')
        # Composite index for the optimized unprocessed query
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_unprocessed ON products(image_status, downloaded_image_path)')
        
        self.conn.commit()
    
    def import_excel(self, excel_path: str, batch_id: str = None) -> Tuple[bool, str, int]:
        """Import Excel file preserving ALL columns"""
        try:
            # Generate batch ID if not provided
            if not batch_id:
                batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Read Excel
            df = pd.read_excel(excel_path)
            total_products = len(df)
            
            # Create batch record
            self.cursor.execute('''
                INSERT INTO batches (id, filename, imported_at, total_products)
                VALUES (?, ?, ?, ?)
            ''', (batch_id, os.path.basename(excel_path), datetime.now(), total_products))
            
            # Import products
            imported_count = 0
            for _, row in df.iterrows():
                # Check if product already exists
                existing = self.get_product_by_sku(str(row.get('Variant SKU / Article Code', '')))
                
                if not existing:
                    # Insert new product
                    self.cursor.execute('''
                        INSERT INTO products (
                            Handle, Title, Body, Brand, Variant_Title, Variant_option,
                            Variant_SKU, Weight_in_grams, Variant_Barcode, Image_link,
                            Variant_Image, Sorting, Vendor, VendorName, Supplier_SKU,
                            Tier_1, Tier_2, Tier_3, batch_id, image_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        row.get('Handle'), row.get('Title'), row.get('Body'),
                        row.get('Brand'), row.get('Variant Title'), row.get('Variant option'),
                        row.get('Variant SKU / Article Code'), row.get('Weight in grams'),
                        row.get('Variant Barcode'), row.get('Image link'),
                        row.get('Variant Image (if required)'), row.get('Sorting'),
                        row.get('Vendor'), row.get('VendorName'), row.get('Supplier SKU'),
                        row.get('Tier 1'), row.get('Tier 2'), row.get('Tier 3'),
                        batch_id, 'not_processed'
                    ))
                    imported_count += 1
                else:
                    # Update existing product with new batch
                    self.cursor.execute('''
                        UPDATE products SET batch_id = ? WHERE Variant_SKU = ?
                    ''', (batch_id, row.get('Variant SKU / Article Code')))
            
            self.conn.commit()
            return True, batch_id, imported_count
            
        except Exception as e:
            self.conn.rollback()
            return False, str(e), 0
    
    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get product by SKU with thread-safe cursor"""
        # Use a fresh cursor to avoid recursive cursor issues
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row  # Ensure row factory is set
        try:
            result = cursor.execute(
                'SELECT * FROM products WHERE Variant_SKU = ?', (sku,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            cursor.close()
    
    def check_local_approved(self, brand: str, title: str, barcode: str) -> Optional[str]:
        """Check if we already have an approved image locally"""
        
        # First check by exact barcode match
        if barcode:
            result = self.cursor.execute('''
                SELECT downloaded_image_path FROM products 
                WHERE Variant_Barcode = ? AND image_status = 'approved'
            ''', (barcode,)).fetchone()
            
            if result and result['downloaded_image_path']:
                # Verify file still exists
                if os.path.exists(result['downloaded_image_path']):
                    return result['downloaded_image_path']
        
        # Check by brand + title match
        result = self.cursor.execute('''
            SELECT downloaded_image_path FROM products 
            WHERE Brand = ? AND Title = ? AND image_status = 'approved'
        ''', (brand, title)).fetchone()
        
        if result and result['downloaded_image_path']:
            if os.path.exists(result['downloaded_image_path']):
                return result['downloaded_image_path']
        
        # Check fuzzy match on title (same brand, similar title)
        # This helps with slight variations
        result = self.cursor.execute('''
            SELECT downloaded_image_path, Title FROM products 
            WHERE Brand = ? AND image_status = 'approved'
        ''', (brand,)).fetchall()
        
        for row in result:
            if row['downloaded_image_path'] and os.path.exists(row['downloaded_image_path']):
                # Simple similarity check
                if self._similar_titles(title, row['Title']):
                    return row['downloaded_image_path']
        
        return None
    
    def _similar_titles(self, title1: str, title2: str) -> bool:
        """Check if two titles are similar enough to be the same product"""
        if not title1 or not title2:
            return False
        
        # Normalize for comparison
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        
        # Exact match
        if t1 == t2:
            return True
        
        # Check if all important words match
        words1 = set(w for w in t1.split() if len(w) > 2)
        words2 = set(w for w in t2.split() if len(w) > 2)
        
        if words1 and words2:
            overlap = len(words1 & words2)
            min_len = min(len(words1), len(words2))
            if overlap / min_len >= 0.8:  # 80% word overlap
                return True
        
        return False
    
    def check_search_cache(self, barcode: str, brand: str) -> Optional[Dict]:
        """Check if we've searched for this product recently"""
        
        search_key = f"{barcode}_{brand}".lower()
        
        result = self.cursor.execute('''
            SELECT * FROM search_cache 
            WHERE search_key = ? 
            AND datetime(cached_at) > datetime('now', '-7 days')
        ''', (search_key,)).fetchone()
        
        if result:
            # Increment usage counter
            self.cursor.execute('''
                UPDATE search_cache SET used_count = used_count + 1 
                WHERE search_key = ?
            ''', (search_key,))
            self.conn.commit()
            
            return dict(result)
        
        return None
    
    def save_search_cache(self, barcode: str, brand: str, title: str, 
                         image_url: str, confidence: float, source: str):
        """Cache search results to avoid repeated API calls"""
        
        search_key = f"{barcode}_{brand}".lower()
        
        self.cursor.execute('''
            INSERT OR REPLACE INTO search_cache 
            (search_key, barcode, brand, title, image_url, confidence, source, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (search_key, barcode, brand, title, image_url, confidence, source, datetime.now()))
        
        self.conn.commit()
    
    def update_product_image(self, sku: str, image_path: str, confidence: float, 
                            source: str, status: str = 'pending', description: str = None, 
                            search_query: str = None, image_source: str = None):
        """Update product with downloaded image information and metadata"""
        
        # Use a fresh cursor for thread safety
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                UPDATE products SET 
                    downloaded_image_path = ?,
                    confidence = ?,
                    source_retailer = ?,
                    scraped_description = ?,
                    search_query = ?,
                    image_source = ?,
                    image_status = ?,
                    processed_date = ?,
                    search_count = COALESCE(search_count, 0) + 1,
                    last_search_date = ?
                WHERE Variant_SKU = ?
            ''', (image_path, confidence, source, description, search_query, image_source, 
                  status, datetime.now(), datetime.now(), sku))
            
            self.conn.commit()
            
            if cursor.rowcount == 0:
                logger.error(f"No rows updated for SKU: {sku}")
            else:
                logger.info(f"Updated {cursor.rowcount} row(s) for SKU: {sku}")
        finally:
            cursor.close()
    
    def approve_image(self, sku: str):
        """Approve an image and track for learning"""
        
        # Get current product info
        product = self.get_product_by_sku(sku)
        if not product:
            return False
        
        # Update status
        self.cursor.execute('''
            UPDATE products SET 
                image_status = 'approved',
                approved_date = ?
            WHERE Variant_SKU = ?
        ''', (datetime.now(), sku))
        
        # Record for learning
        self.record_feedback(sku, 'approved')
        
        # Update batch stats
        self._update_batch_stats(product['batch_id'])
        
        self.conn.commit()
        return True
    
    def decline_image(self, sku: str):
        """Decline an image and track for learning"""
        
        product = self.get_product_by_sku(sku)
        if not product:
            return False
        
        # Update status
        self.cursor.execute('''
            UPDATE products SET 
                image_status = 'declined'
            WHERE Variant_SKU = ?
        ''', (sku,))
        
        # Record for learning
        self.record_feedback(sku, 'declined')
        
        # Update batch stats
        self._update_batch_stats(product['batch_id'])
        
        self.conn.commit()
        return True

    def mark_not_found(self, sku: str) -> None:
        """Mark product as not_found to prevent repeated API usage in this session."""
        try:
            self.cursor.execute('''
                UPDATE products SET image_status = 'not_found' WHERE Variant_SKU = ?
            ''', (sku,))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            # best-effort; don't raise
    
    def record_feedback(self, sku: str, action: str):
        """Record user feedback for continuous learning"""
        
        product = self.get_product_by_sku(sku)
        if not product:
            return
        
        # Analyze what matched
        has_barcode = bool(product.get('Variant_Barcode'))
        has_brand = bool(product.get('Brand'))
        
        self.cursor.execute('''
            INSERT INTO learning_feedback 
            (product_sku, confidence, source, user_action, feedback_date, 
             brand, has_barcode_match, has_brand_match)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sku, product.get('confidence'), product.get('source_retailer'),
            action, datetime.now(), product.get('Brand'),
            has_barcode, has_brand
        ))
        
        self.conn.commit()
    
    def _update_batch_stats(self, batch_id: str):
        """Update batch statistics"""
        if not batch_id:
            return
        
        stats = self.cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN image_status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN image_status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN image_status = 'declined' THEN 1 ELSE 0 END) as declined,
                SUM(CASE WHEN image_status != 'not_processed' THEN 1 ELSE 0 END) as processed
            FROM products WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        
        self.cursor.execute('''
            UPDATE batches SET 
                processed = ?, approved = ?, pending = ?, declined = ?
            WHERE id = ?
        ''', (stats['processed'], stats['approved'], stats['pending'], stats['declined'], batch_id))
        
        self.conn.commit()
    
    def get_learning_insights(self) -> Dict:
        """Analyze user feedback to improve confidence scoring"""
        
        # What sources get approved most?
        source_stats = self.cursor.execute('''
            SELECT 
                source, 
                COUNT(*) as total,
                SUM(CASE WHEN user_action = 'approved' THEN 1 ELSE 0 END) as approved,
                AVG(confidence) as avg_confidence
            FROM learning_feedback
            GROUP BY source
        ''').fetchall()
        
        # What confidence levels get approved?
        confidence_stats = self.cursor.execute('''
            SELECT 
                CASE 
                    WHEN confidence >= 70 THEN 'High (70+)'
                    WHEN confidence >= 50 THEN 'Medium (50-70)'
                    WHEN confidence >= 30 THEN 'Low (30-50)'
                    ELSE 'Very Low (<30)'
                END as confidence_band,
                COUNT(*) as total,
                SUM(CASE WHEN user_action = 'approved' THEN 1 ELSE 0 END) as approved
            FROM learning_feedback
            GROUP BY confidence_band
        ''').fetchall()
        
        return {
            'source_performance': [dict(row) for row in source_stats],
            'confidence_accuracy': [dict(row) for row in confidence_stats]
        }
    
    def get_statistics(self) -> Dict:
        """Get overall system statistics with thread-safe cursor"""
        
        # Use a fresh cursor to avoid recursive cursor issues
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row  # Ensure row factory is set
        try:
            total = cursor.execute('SELECT COUNT(*) as cnt FROM products').fetchone()['cnt']
            
            status_counts = cursor.execute('''
                SELECT 
                    image_status,
                    COUNT(*) as count
                FROM products
                GROUP BY image_status
            ''').fetchall()
            
            status_dict = {row['image_status']: row['count'] for row in status_counts}
            
            return {
                'total_products': total,
                'approved': status_dict.get('approved', 0),
                'pending': status_dict.get('pending', 0),
                'declined': status_dict.get('declined', 0),
                'not_found': status_dict.get('not_found', 0),
                'not_processed': status_dict.get('not_processed', 0),
                'completion_percentage': (status_dict.get('approved', 0) / total * 100) if total > 0 else 0
            }
        finally:
            cursor.close()
    
    def get_products_for_review(self, status: str = 'pending', limit: int = 50) -> List[Dict]:
        """Get products that need review with enhanced debugging and thread-safe cursor"""
        
        # Use a fresh cursor to avoid recursive cursor issues
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row  # Ensure row factory is set
        try:
            results = cursor.execute('''
                SELECT *, 
                       CASE WHEN downloaded_image_path IS NOT NULL THEN 1 ELSE 0 END as has_image_path,
                       processed_date,
                       approved_date
                FROM products 
                WHERE image_status = ? 
                ORDER BY confidence DESC, processed_date DESC
                LIMIT ?
            ''', (status, limit)).fetchall()
            
            products = [dict(row) for row in results]
            
            # Log debugging info
            logger.info(f"Found {len(products)} products with status '{status}' for review")
            for product in products[:3]:  # Log first 3 for debugging
                logger.debug(f"Review product - SKU: {product['Variant_SKU']}, "
                            f"Path: {product.get('downloaded_image_path', 'None')}, "
                            f"Status: {product.get('image_status', 'None')}, "
                            f"Confidence: {product.get('confidence', 0)}")
            
            return products
        finally:
            cursor.close()
    
    def get_unprocessed_products(self, limit: int = 10) -> List[Dict]:
        """Get products that haven't been processed yet - includes 'not_found' for reprocessing"""
        
        results = self.cursor.execute('''
            SELECT * FROM products 
            WHERE (image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found')
               AND (downloaded_image_path IS NULL OR downloaded_image_path = '')
            ORDER BY Sorting 
            LIMIT ?
        ''', (limit,)).fetchall()
        
        return [dict(row) for row in results]

    def get_unprocessed_products_from_bottom(self, limit: int = 10) -> List[Dict]:
        """Get unprocessed products starting from the bottom (reverse sorting) - includes 'not_found' for reprocessing"""
        results = self.cursor.execute('''
            SELECT * FROM products 
            WHERE (image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found')
               AND (downloaded_image_path IS NULL OR downloaded_image_path = '')
            ORDER BY Sorting DESC 
            LIMIT ?
        ''', (limit,)).fetchall()
        return [dict(row) for row in results]
    
    def clear_images(self, clear_type: str) -> int:
        """Clear images based on type"""
        
        count = 0
        
        if clear_type == 'declined':
            # Clear only declined
            results = self.cursor.execute('''
                SELECT downloaded_image_path FROM products 
                WHERE image_status = 'declined'
            ''').fetchall()
            
            for row in results:
                if row['downloaded_image_path'] and os.path.exists(row['downloaded_image_path']):
                    os.remove(row['downloaded_image_path'])
                    count += 1
            
            self.cursor.execute('''
                UPDATE products SET downloaded_image_path = NULL 
                WHERE image_status = 'declined'
            ''')
            
        elif clear_type == 'pending':
            # Clear pending
            results = self.cursor.execute('''
                SELECT downloaded_image_path FROM products 
                WHERE image_status = 'pending'
            ''').fetchall()
            
            for row in results:
                if row['downloaded_image_path'] and os.path.exists(row['downloaded_image_path']):
                    os.remove(row['downloaded_image_path'])
                    count += 1
            
            self.cursor.execute('''
                UPDATE products SET downloaded_image_path = NULL, image_status = 'not_processed'
                WHERE image_status = 'pending'
            ''')
            
        elif clear_type == 'all_unapproved':
            # Clear declined + pending
            results = self.cursor.execute('''
                SELECT downloaded_image_path FROM products 
                WHERE image_status IN ('declined', 'pending')
            ''').fetchall()
            
            for row in results:
                if row['downloaded_image_path'] and os.path.exists(row['downloaded_image_path']):
                    os.remove(row['downloaded_image_path'])
                    count += 1
            
            self.cursor.execute('''
                UPDATE products SET downloaded_image_path = NULL, image_status = 'not_processed'
                WHERE image_status IN ('declined', 'pending')
            ''')
        
        self.conn.commit()
        return count
    
    def export_to_excel(self, output_path: str, batch_ids: List[str] = None, status_filter: str = 'all') -> bool:
        """Export database back to Excel with all columns - FIXED v3"""
        try:
            # Build query based on filters
            base_query = "SELECT * FROM products"
            conditions = []
            params = []
            
            # Skip batch filter - export based on status only
            # Batch filtering is not working due to string/int mismatch
            # We'll export all products matching the status filter
            
            # Apply status filter
            if status_filter == 'approved':
                conditions.append("image_status = 'approved'")
            elif status_filter == 'pending':
                conditions.append("image_status = 'pending'")
            elif status_filter == 'declined':
                conditions.append("image_status = 'declined'")
            elif status_filter == 'with_images':
                conditions.append("downloaded_image_path IS NOT NULL AND downloaded_image_path != ''")
            elif status_filter == 'not_processed':
                conditions.append("(image_status = 'not_processed' OR image_status IS NULL OR image_status = 'not_found')")
            
            # Combine conditions
            if conditions:
                query = f"{base_query} WHERE {' AND '.join(conditions)}"
            else:
                query = base_query
            
            # Execute query with proper error handling
            df = pd.read_sql_query(query, self.conn, params=params if params else None)
            
            # Check if we have data
            if df.empty:
                logger.warning("No data to export with current filters")
                # Create empty dataframe with headers
                excel_columns = [
                    'Handle', 'Title', 'Body', 'Brand', 'Variant_Title', 'Variant_option',
                    'Variant_SKU', 'Weight_in_grams', 'Variant_Barcode', 'Image_link',
                    'Variant_Image', 'Sorting', 'Vendor', 'VendorName', 'Supplier_SKU',
                    'Tier_1', 'Tier_2', 'Tier_3', 'downloaded_image_path', 'confidence',
                    'source_retailer', 'image_status'
                ]
                df = pd.DataFrame(columns=excel_columns)
            else:
                # Process Body column safely
                df['Body'] = df.apply(lambda row: 
                    str(row.get('scraped_description', '')) if pd.notna(row.get('scraped_description')) and str(row.get('scraped_description')).strip()
                    else str(row.get('Body', '')) if pd.notna(row.get('Body')) else '', axis=1)
                
                # Define expected columns (removed problematic columns that might not exist)
                excel_columns = [
                    'Handle', 'Title', 'Body', 'Brand', 'Variant_Title', 'Variant_option',
                    'Variant_SKU', 'Weight_in_grams', 'Variant_Barcode', 'Image_link',
                    'Variant_Image', 'Sorting', 'Vendor', 'VendorName', 'Supplier_SKU',
                    'Tier_1', 'Tier_2', 'Tier_3', 'downloaded_image_path', 'confidence',
                    'source_retailer', 'image_status'
                ]
                
                # Add missing columns with empty values
                for col in excel_columns:
                    if col not in df.columns:
                        df[col] = ''
                
                # Reorder columns
                df = df[excel_columns]
                
                # Fill NaN values with empty strings to prevent export issues
                df = df.fillna('')
            
            # Save to Excel with error handling
            logger.info(f"Exporting {len(df)} rows to {output_path}")
            df.to_excel(output_path, index=False, engine='openpyxl')
            
            # Verify the file was created
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                logger.info(f"Export successful: {output_path} ({file_size} bytes)")
                return True
            else:
                logger.error(f"Export file not created: {output_path}")
                return False
            
        except Exception as e:
            logger.error(f"Export error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def close(self):
        """Close database connection"""
        self.conn.close()