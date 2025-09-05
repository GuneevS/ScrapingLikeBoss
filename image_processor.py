"""
Intelligent Image Processor with Local Search First
Continuously improves through learning from user feedback
"""

import os
import re
import json
import asyncio
import aiohttp
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from datetime import datetime

from database import ImageDatabase
from src import img_utils, downloader

logger = logging.getLogger(__name__)

class IntelligentImageProcessor:
    def __init__(self, config: dict, db: ImageDatabase):
        self.config = config
        self.db = db
        self.api_key = config['search']['serp_api_key']
        
        # Folders
        self.approved_dir = Path("output/approved")
        self.pending_dir = Path("output/pending")
        self.declined_dir = Path("output/declined")
        
        # Create folders
        for folder in [self.approved_dir, self.pending_dir, self.declined_dir]:
            folder.mkdir(parents=True, exist_ok=True)
        
        # Learning-based confidence adjustments
        self.confidence_adjustments = self._load_confidence_adjustments()
    
    def _load_confidence_adjustments(self) -> Dict:
        """Load confidence adjustments based on learning"""
        
        insights = self.db.get_learning_insights()
        adjustments = {
            'source_multipliers': {},
            'confidence_thresholds': {
                'auto_approve': 70,
                'needs_review': 30
            }
        }
        
        # Adjust source confidence based on approval rates
        for source_stat in insights.get('source_performance', []):
            if source_stat['total'] > 5:  # Need enough data
                approval_rate = source_stat['approved'] / source_stat['total']
                if approval_rate > 0.8:
                    adjustments['source_multipliers'][source_stat['source']] = 1.2
                elif approval_rate < 0.3:
                    adjustments['source_multipliers'][source_stat['source']] = 0.8
                else:
                    adjustments['source_multipliers'][source_stat['source']] = 1.0
        
        return adjustments
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename preserving brand names like Good 'n Gold"""
        # Keep apostrophes for brand names
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            if char != "'":  # Keep apostrophes
                filename = filename.replace(char, '_')
        
        filename = re.sub(r'\s+', '_', filename)
        filename = re.sub(r'_+', '_', filename)
        filename = filename.strip('_.')
        
        return filename[:200] if filename else "unknown"
    
    async def process_product(self, product: Dict) -> Dict:
        """Process a single product with local search first"""
        
        sku = product['Variant_SKU']
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        barcode = product.get('Variant_Barcode', '')
        
        logger.info(f"Processing: {title} (SKU: {sku})")
        
        # STEP 1: Check local approved folder first
        local_path = self._check_local_approved(brand, title, barcode)
        if local_path:
            logger.info(f"  ✓ Found locally: {local_path}")
            self.db.update_product_image(
                sku, local_path, 100.0, 'local_approved', 'approved',
                'Previously approved local image', 'Local search', local_path
            )
            return {
                'sku': sku,
                'status': 'found_local',
                'path': local_path,
                'confidence': 100.0
            }
        
        # STEP 2: Check search cache
        cached = self.db.check_search_cache(barcode, brand)
        if cached and cached['confidence'] >= 50:
            logger.info(f"  ✓ Found in cache: {cached['source']} ({cached['confidence']}%)")
            
            # Download and save
            result = await self._download_and_save_image(
                cached['image_url'], 
                product, 
                cached['confidence'], 
                cached['source'],
                cached.get('description', ''),
                cached.get('search_query', ''),
                cached['image_url']
            )
            
            if result['success']:
                return {
                    'sku': sku,
                    'status': 'found_cached',
                    'path': result['path'],
                    'confidence': cached['confidence']
                }
        
        # STEP 3: Search online with improved strategy
        search_result = await self._search_online(product)
        
        if search_result:
            return {
                'sku': sku,
                'status': 'found_online',
                'path': search_result['path'],
                'confidence': search_result['confidence']
            }
        
        # Not found
        logger.warning(f"  ✗ No suitable image found for: {title}")
        search_attempts = f'Brand: {brand}, Title: {title}'
        if barcode and barcode != 'nan':
            search_attempts += f', Barcode: {barcode}'
        
        self.db.update_product_image(
            sku, None, 0, None, 'not_found', 
            'No suitable image found', search_attempts, ''
        )
        
        return {
            'sku': sku,
            'status': 'not_found',
            'path': None,
            'confidence': 0
        }
    
    def _check_local_approved(self, brand: str, title: str, barcode: str) -> Optional[str]:
        """Check local approved folder for existing images"""
        
        if not brand or not title:
            return None
        
        # Clean names for filesystem
        brand_folder = self.sanitize_filename(brand)
        
        # Check for files with SKU-based naming (preferred approach)
        # This searches the brand folder for any file that might match this product
        brand_dir = self.approved_dir / brand_folder
        if brand_dir.exists():
            for img_file in brand_dir.glob('*.jpg'):
                if img_file.stem.endswith(f"_{barcode}") or title.lower().replace(' ', '_') in img_file.stem.lower():
                    return str(img_file)
        
        # Check exact match with old naming format for backwards compatibility
        filename_jpg = self.sanitize_filename(title) + '.jpg'
        path_jpg = self.approved_dir / brand_folder / filename_jpg
        if path_jpg.exists():
            return str(path_jpg)
        
        # Check database for approved with same barcode
        if barcode:
            db_result = self.db.check_local_approved(brand, title, barcode)
            if db_result and os.path.exists(db_result):
                return db_result
        
        return None
    
    async def _search_online(self, product: Dict) -> Optional[Dict]:
        """Search online with intelligent strategy"""
        
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        barcode = product.get('Variant_Barcode', '')
        
        # Prioritize retailers based on learning
        retailers_priority = self._get_retailer_priority(brand)
        
        connector = aiohttp.TCPConnector(limit=5)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            
            # Try retailers in priority order
            for retailer in retailers_priority:
                result = await self._search_retailer(session, product, retailer)
                if result and result['confidence'] >= 60:
                    # Good match found
                    downloaded = await self._download_and_save_image(
                        result['url'], 
                        product, 
                        result['confidence'], 
                        result['source'],
                        result.get('description', ''),
                        result.get('search_query', ''),
                        result.get('image_source', result['url'])
                    )
                    
                    if downloaded['success']:
                        # Cache successful search
                        self.db.save_search_cache(
                            barcode, brand, title,
                            result['url'], result['confidence'], result['source']
                        )
                        
                        return {
                            'path': downloaded['path'],
                            'confidence': result['confidence']
                        }
            
            # Broader search if retailers don't have it
            result = await self._search_broad(session, product)
            if result:
                downloaded = await self._download_and_save_image(
                    result['url'], 
                    product, 
                    result['confidence'], 
                    result['source'],
                    result.get('description', ''),
                    result.get('search_query', ''),
                    result.get('image_source', result['url'])
                )
                
                if downloaded['success']:
                    self.db.save_search_cache(
                        barcode, brand, title,
                        result['url'], result['confidence'], result['source']
                    )
                    
                    return {
                        'path': downloaded['path'],
                        'confidence': result['confidence']
                    }
        
        return None
    
    def _get_retailer_priority(self, brand: str) -> List[str]:
        """Get retailer priority based on brand and learning"""
        
        # Default priority
        retailers = [
            'checkers.co.za',
            'shoprite.co.za',
            'pnp.co.za',
            'makro.co.za',
            'woolworths.co.za',
            'takealot.com'
        ]
        
        # TODO: Adjust based on brand-specific success rates from learning
        
        return retailers
    
    async def _search_retailer(self, session: aiohttp.ClientSession, 
                              product: Dict, retailer: str) -> Optional[Dict]:
        """Search specific retailer"""
        
        barcode = product.get('Variant_Barcode', '')
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        
        # Build query focusing on barcode and brand
        if barcode and barcode != 'nan':
            query = f'"{barcode}" "{brand}" site:{retailer}'
        else:
            query = f'"{brand}" "{title}" site:{retailer}'
        
        params = {
            'engine': 'google_images',
            'q': query,
            'api_key': self.api_key,
            'num': 10,
            'gl': 'za',
            'hl': 'en'
        }
        
        try:
            url = f"https://serpapi.com/search?{urlencode(params)}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    for result in data.get('images_results', []):
                        confidence = self._calculate_confidence(result, product, retailer)
                        
                        if confidence >= 50:
                            return {
                                'url': result.get('original') or result.get('link'),
                                'confidence': confidence,
                                'source': retailer,
                                'description': '',  # Description scraping removed to save API credits
                                'search_query': query,
                                'image_source': result.get('source', retailer)
                            }
        except Exception as e:
            logger.error(f"Search error for {retailer}: {str(e)}")
        
        return None
    
    async def _search_broad(self, session: aiohttp.ClientSession, product: Dict) -> Optional[Dict]:
        """Broader search as fallback"""
        
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        
        query = f'"{brand}" "{title}" South Africa product'
        
        params = {
            'engine': 'google_images',
            'q': query,
            'api_key': self.api_key,
            'num': 15,
            'gl': 'za',
            'hl': 'en'
        }
        
        try:
            url = f"https://serpapi.com/search?{urlencode(params)}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    best_match = None
                    best_confidence = 0
                    
                    for result in data.get('images_results', []):
                        confidence = self._calculate_confidence(result, product, 'general')
                        
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_match = {
                                'url': result.get('original') or result.get('link'),
                                'confidence': confidence,
                                'source': result.get('source', 'unknown'),
                                'description': '',  # Description scraping removed to save API credits  
                                'search_query': query,
                                'image_source': result.get('source', 'unknown')
                            }
                    
                    if best_match and best_confidence >= 30:
                        return best_match
                        
        except Exception as e:
            logger.error(f"Broad search error: {str(e)}")
        
        return None
    
    def _calculate_confidence(self, result: dict, product: Dict, retailer: str) -> float:
        """Calculate confidence with learning adjustments"""
        
        confidence = 0.0
        
        # Get product details
        barcode = str(product.get('Variant_Barcode', '')).lower()
        brand = str(product.get('Brand', '')).lower()
        title = str(product.get('Title', '')).lower()
        
        # Get result details
        img_title = result.get('title', '').lower()
        img_snippet = result.get('snippet', '').lower()
        img_url = result.get('link', '').lower()
        
        combined_text = f"{img_title} {img_snippet} {img_url}"
        
        # CRITICAL: Brand match (most important for differentiation)
        if brand:
            # Handle special brand formats
            brand_variants = [
                brand,
                brand.replace(' ', ''),
                brand.replace(' ', '-'),
                brand.replace("'", ""),  # Handle Good 'n Gold
                brand.replace("'n", "n")
            ]
            
            if any(variant in combined_text for variant in brand_variants):
                confidence += 35
                logger.debug(f"    + Brand match: {brand}")
            else:
                # No brand match is a strong negative
                confidence -= 40
                logger.debug(f"    - No brand match")
        
        # Barcode match (very strong signal)
        if barcode and barcode != 'nan' and barcode in combined_text:
            confidence += 40
            logger.debug(f"    + Barcode match: {barcode}")
        
        # Retailer trust
        trusted_retailers = ['checkers', 'shoprite', 'pnp', 'makro', 'woolworths']
        if any(r in retailer for r in trusted_retailers):
            confidence += 15
        
        # Title word matching
        title_words = [w for w in title.split() if len(w) > 2]
        matches = sum(1 for w in title_words if w in combined_text)
        if title_words:
            match_ratio = matches / len(title_words)
            confidence += match_ratio * 20
        
        # Apply learning adjustments
        if retailer in self.confidence_adjustments['source_multipliers']:
            confidence *= self.confidence_adjustments['source_multipliers'][retailer]
        
        return min(100, max(0, confidence))
    
    async def _download_and_save_image(self, url: str, product: Dict, 
                                      confidence: float, source: str, description: str = '', 
                                      search_query: str = '', image_source: str = '') -> Dict:
        """Download and save image to appropriate folder"""
        
        try:
            connector = aiohttp.TCPConnector()
            async with aiohttp.ClientSession(connector=connector) as session:
                image_bytes = await downloader.fetch_image(session, url)
                
                if not image_bytes:
                    return {'success': False, 'path': None}
                
                # Validate image
                if not img_utils.is_valid_image(image_bytes, min_size=150):
                    return {'success': False, 'path': None}
                
                # Optimize image
                optimized = img_utils.optimise(
                    image_bytes,
                    size=self.config['image']['size'],
                    fmt='JPEG',
                    max_kb=self.config['image']['max_kb']
                )
                
                if not optimized:
                    return {'success': False, 'path': None}
                
                # Determine folder based on confidence
                if confidence >= self.confidence_adjustments['confidence_thresholds']['auto_approve']:
                    folder = self.approved_dir
                    status = 'approved'
                elif confidence >= self.confidence_adjustments['confidence_thresholds']['needs_review']:
                    folder = self.pending_dir
                    status = 'pending'
                else:
                    folder = self.declined_dir
                    status = 'declined'
                
                # Save image with UNIQUE filename to prevent collisions
                brand = product.get('Brand', 'Unknown')
                title = product.get('Title', 'Unknown')
                sku = product.get('Variant_SKU', 'Unknown')
                
                brand_folder = folder / self.sanitize_filename(brand)
                brand_folder.mkdir(exist_ok=True)
                
                # Create UNIQUE filename using SKU to prevent overwrites
                safe_title = self.sanitize_filename(title)
                safe_sku = self.sanitize_filename(sku)
                filename = f"{safe_title}_{safe_sku}.jpg"
                output_path = brand_folder / filename
                
                with open(output_path, 'wb') as f:
                    f.write(optimized)
                
                # Save metadata (description field kept empty to save API credits)
                metadata = {
                    'product': title,
                    'brand': brand,
                    'barcode': product.get('Variant_Barcode', ''),
                    'confidence': confidence,
                    'source': source,
                    'url': url,
                    'description': description,  # Usually empty to save credits
                    'search_query': search_query,
                    'image_source': image_source,
                    'downloaded_at': datetime.now().isoformat()
                }
                
                meta_path = output_path.with_suffix('.json')
                with open(meta_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                # Update database with enhanced metadata
                self.db.update_product_image(
                    product['Variant_SKU'],
                    str(output_path),
                    confidence,
                    source,
                    status,
                    description,
                    search_query,
                    image_source
                )
                
                logger.info(f"  ✓ Saved to {folder.name}: {filename} ({confidence:.0f}%)")
                
                return {'success': True, 'path': str(output_path)}
                
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return {'success': False, 'path': None}
    
    async def process_batch(self, products: List[Dict], progress_callback=None) -> Dict:
        """Process a batch of products"""
        
        results = {
            'processed': 0,
            'found_local': 0,
            'found_cached': 0,
            'found_online': 0,
            'not_found': 0,
            'errors': 0
        }
        
        for i, product in enumerate(products):
            try:
                result = await self.process_product(product)
                
                results['processed'] += 1
                results[result['status']] = results.get(result['status'], 0) + 1
                
                if progress_callback:
                    progress_callback({
                        'current': i + 1,
                        'total': len(products),
                        'product': product.get('Title', 'Unknown'),
                        'status': result['status'],
                        'confidence': result.get('confidence', 0)
                    })
                
                # Small delay to be respectful
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error processing {product.get('Title', 'Unknown')}: {str(e)}")
                results['errors'] += 1
        
        # Reload confidence adjustments after batch
        self.confidence_adjustments = self._load_confidence_adjustments()
        
        return results
    
    def move_to_approved(self, sku: str) -> bool:
        """Move INDIVIDUAL image from pending to approved (NOT entire folders)"""
        
        logger.info(f"Moving single image to approved for SKU: {sku}")
        
        # Get the SPECIFIC product
        product = self.db.get_product_by_sku(sku)
        if not product or not product['downloaded_image_path']:
            logger.warning(f"No product or image path found for SKU: {sku}")
            return False
        
        current_path = Path(product['downloaded_image_path'])
        
        # CRITICAL: Ensure we're dealing with a FILE, not a directory
        if not current_path.exists():
            logger.warning(f"Image file does not exist: {current_path}")
            return False
        
        if current_path.is_dir():
            logger.error(f"Path is a directory, not a file. This should not happen: {current_path}")
            return False
        
        # SAFETY CHECK: Ensure the file belongs to this specific SKU
        title = product.get('Title', 'Unknown')
        safe_title = self.sanitize_filename(title)
        safe_sku = self.sanitize_filename(sku)
        expected_filename = f"{safe_title}_{safe_sku}.jpg"
        
        # Also check old format for backwards compatibility
        old_expected_filename = self.sanitize_filename(title) + '.jpg'
        
        if current_path.name != expected_filename and current_path.name != old_expected_filename:
            logger.warning(f"Filename mismatch for SKU {sku}. Expected: {expected_filename}, Got: {current_path.name}")
            logger.info(f"This may be due to filename format update - continuing with move")
        
        # Create new path in approved folder
        brand = product.get('Brand', 'Unknown')
        brand_folder = self.approved_dir / self.sanitize_filename(brand)
        brand_folder.mkdir(exist_ok=True)
        
        new_path = brand_folder / current_path.name
        
        # SAFETY: Check if target already exists
        if new_path.exists():
            logger.warning(f"Target file already exists, will overwrite: {new_path}")
        
        try:
            # Move ONLY the specific image file
            current_path.rename(new_path)
            logger.info(f"✓ Moved image file: {current_path} → {new_path}")
            
            # Move ONLY the corresponding metadata file if exists
            current_meta = current_path.with_suffix('.json')
            if current_meta.exists() and current_meta.is_file():
                new_meta = new_path.with_suffix('.json')
                current_meta.rename(new_meta)
                logger.info(f"✓ Moved metadata file: {current_meta} → {new_meta}")
            
            # Update database for THIS SPECIFIC SKU ONLY
            self.db.cursor.execute('''
                UPDATE products SET 
                    downloaded_image_path = ?,
                    image_status = 'approved',
                    approved_date = ?
                WHERE Variant_SKU = ?
            ''', (str(new_path), datetime.now(), sku))
            self.db.conn.commit()
            
            logger.info(f"✓ Successfully moved single image for SKU: {sku}")
            return True
            
        except Exception as e:
            logger.error(f"Error moving image for SKU {sku}: {str(e)}")
            return False
    
    def move_to_declined(self, sku: str) -> bool:
        """Move image to declined and optionally delete"""
        
        product = self.db.get_product_by_sku(sku)
        if not product or not product['downloaded_image_path']:
            return False
        
        current_path = Path(product['downloaded_image_path'])
        if current_path.exists():
            # Move to declined folder
            brand = product.get('Brand', 'Unknown')
            brand_folder = self.declined_dir / self.sanitize_filename(brand)
            brand_folder.mkdir(exist_ok=True)
            
            new_path = brand_folder / current_path.name
            current_path.rename(new_path)
            
            # Move metadata
            current_meta = current_path.with_suffix('.json')
            if current_meta.exists():
                new_meta = new_path.with_suffix('.json')
                current_meta.rename(new_meta)
        
        # Update database
        self.db.decline_image(sku)
        
        return True