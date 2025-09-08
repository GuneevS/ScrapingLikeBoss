"""
Intelligent Image Processor with Local Search First
Continuously improves through learning from user feedback
"""

import os
import re
import json
import asyncio
import aiohttp
import requests
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from datetime import datetime

from database import ImageDatabase
from learning_system import LearningSystem
from src import img_utils, downloader
from src.clip_service import get_clip_service

logger = logging.getLogger(__name__)

class ImageSearcher:
    """Simple wrapper for search functionality"""
    def __init__(self, config):
        self.config = config
        self.api_key = config.get('search', {}).get('serp_api_key')
        # Persistent HTTP session for lower latency and connection reuse
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'
        })
    
    def search_google_images(self, query: str, num_results: int = 3) -> List[dict]:
        """Search Google Images via SerpAPI"""
        if not self.api_key:
            return []
        
        params = {
            'engine': 'google_images',
            'q': query,
            'api_key': self.api_key,
            'num': num_results,
            'gl': 'za',
            'hl': 'en'
        }
        
        try:
            response = self.session.get('https://serpapi.com/search', params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = []
                for img in data.get('images_results', [])[:num_results]:
                    results.append({
                        'url': img.get('original'),
                        'original': img.get('original'),  # Add for compatibility
                        'link': img.get('link'),  # Add alternate URL
                        'thumbnail': img.get('thumbnail'),  # Add thumbnail as fallback
                        'title': img.get('title', ''),
                        'source': img.get('source', ''),
                        'snippet': img.get('snippet', '')
                    })
                return results
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
        return []

class ImageDownloader:
    """Simple wrapper for download functionality"""
    def __init__(self, config):
        self.config = config
        # No persistent session to avoid cross-event-loop issues
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        # Build a short-lived session tied to the current loop/task
        connector = aiohttp.TCPConnector(limit=self.config.get('network', {}).get('concurrency', 10))
        timeout = aiohttp.ClientTimeout(total=self.config.get('network', {}).get('timeout', 15))
        return aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL with proper headers"""
        if not url or not isinstance(url, str):
            logger.error(f"Invalid URL: {url}")
            return None
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
            
        try:
            # Add referer when available to improve retailer CDN acceptance
            try:
                from urllib.parse import urlparse as _urlparse
                netloc = _urlparse(url).netloc
                if netloc and 'Referer' not in headers:
                    headers['Referer'] = f"https://{netloc}"
            except Exception:
                pass

            session = await self._get_session()
            async with session as s:
                async with s.get(url, headers=headers, ssl=False) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.warning(f"Download failed with status {response.status} for URL: {url}")
        except Exception as e:
            logger.error(f"Download error for URL {url}: {str(e)}")
        return None

class IntelligentImageProcessor:
    def __init__(self, config: dict, db: ImageDatabase):
        self.config = config
        self.db = db
        self.api_key = config.get('search', {}).get('serp_api_key')
        self.searcher = ImageSearcher(config)
        self.downloader = ImageDownloader(config)
        self.learning = LearningSystem()
        self.clip = get_clip_service(config)
        
        # Setup directories
        self.output_dir = Path('output')
        self.approved_dir = self.output_dir / 'approved'
        self.pending_dir = self.output_dir / 'pending'
        self.declined_dir = self.output_dir / 'declined'
        
        for dir in [self.approved_dir, self.pending_dir, self.declined_dir]:
            dir.mkdir(parents=True, exist_ok=True)
        
        # Load confidence adjustments from learning
        self.confidence_adjustments = self._load_confidence_adjustments()
        
        # IMPROVED: Retailer prioritization system
        self.TRUSTED_RETAILERS = {
            'tier1': ['shoprite.co.za', 'checkers.co.za', 'pnp.co.za', 'makro.co.za'],
            'tier2': ['takealot.com', 'game.co.za', 'woolworths.co.za', 'clicks.co.za'],
            'tier3': []  # All others
        }
        
        # Search result cache to reduce API calls
        self.search_cache = {}
        self.cache_hits = 0
        self.total_searches = 0
    
    def check_local_cache(self, product: dict) -> Optional[dict]:
        """Check if product image already exists locally"""
        sku = product.get('Variant_SKU', 'Unknown')
        
        # Check if product already has an image link
        existing_product = self.db.get_product_by_sku(sku)
        if existing_product and existing_product.get('Image_link'):
            image_link = existing_product['Image_link']
            # Check if it's a local file path that exists
            if image_link.startswith('/') or image_link.startswith('./'):
                image_path = Path(image_link)
                if image_path.exists():
                    return {
                        'success': True,
                        'image_path': str(image_path),
                        'source': 'local_cache',
                        'confidence': 100
                    }
        
        return None
    
    def cache_search_result(self, product: dict, result: dict):
        """Cache search result for future use"""
        if result and result.get('success'):
            cache_key = self._get_search_cache_key(
                product.get('Brand', ''),
                product.get('Tier_1', ''),
                product.get('Variant_Title', '')
            )
            self.search_cache[cache_key] = result.copy()
    
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
    
    def sanitize_filename(self, text: str) -> str:
        """Sanitize text for use as filename"""
        # Remove invalid characters
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        # Replace spaces with underscores
        text = text.replace(' ', '_')
        # Limit length
        return text[:100]
    
    def _get_search_cache_key(self, brand: str, category: str, variant: str) -> str:
        """Generate cache key for similar products - more specific to avoid over-caching"""
        brand = (brand or 'unknown').lower()[:20]
        category = (category or 'unknown').lower()[:20] 
        variant_full = (variant or 'none').lower()[:30]  # Use full variant, not just first word
        return f"{brand}_{category}_{variant_full}"
    
    def _adjust_cached_result_for_variant(self, cached_result: dict, product: dict) -> dict:
        """Adjust cached result for specific variant"""
        # Keep the same source but adjust confidence based on variant match
        variant = product.get('Variant_Title', '').lower()
        cached_title = cached_result.get('title', '').lower()
        
        if variant and variant not in cached_title:
            # Reduce confidence if variant doesn't match
            cached_result['confidence'] = max(30, cached_result.get('confidence', 50) - 20)
            cached_result['adjusted_from_cache'] = True
        
        return cached_result
    
    async def search_product_image(self, product: dict, force_web: bool = False) -> Optional[dict]:
        """Search for product image using improved strategies with variant awareness"""
        
        sku = product.get('Variant_SKU', 'Unknown')
        title = product.get('Title', '')
        brand = product.get('Brand', '')
        barcode = product.get('Variant_Barcode', '')
        variant = product.get('Variant_Title', '')
        
        # Try local cache first
        cached = self.check_local_cache(product)
        if cached:
            logger.info(f"✓ Found in local cache: {sku}")
            return cached
        
        # Try DB search cache to avoid API calls (unless forcing web search)
        try_db_cache = False if force_web else self.config.get('search', {}).get('use_db_cache', True)
        if try_db_cache and (barcode or brand):
            cached_entry = self.db.check_search_cache(str(barcode or ''), str(brand or ''))
            if cached_entry and cached_entry.get('image_url'):
                logger.info(f"✓ DB search cache hit for {sku} → {cached_entry.get('image_url')}")
                dl = await self._download_and_save_image(
                    cached_entry['image_url'],
                    product,
                    cached_entry.get('confidence', 50) or 50,
                    cached_entry.get('source', '') or '',
                    '',
                    cached_entry.get('title', '') or '',
                    cached_entry.get('image_url', '')
                )
                if dl.get('success'):
                    return {
                        'success': True,
                        'url': cached_entry['image_url'],
                        'confidence': cached_entry.get('confidence', 50),
                        'source': cached_entry.get('source', ''),
                        'search_query': 'db_cache',
                        'image_source': cached_entry.get('source', '')
                    }
                else:
                    logger.warning(f"DB cache URL failed to download for {sku}, will fall back to search")

        # Check search result cache for similar products (unless forcing web search)
        cache_key = self._get_search_cache_key(brand, product.get('Tier_1', ''), variant)
        if (not force_web) and (cache_key in self.search_cache):
            self.cache_hits += 1
            logger.info(f"✓ Search cache hit for similar product: {sku}")
            cached_result = self.search_cache[cache_key].copy()
            # Adjust for this specific variant
            cached_result['sku'] = sku
            return self._adjust_cached_result_for_variant(cached_result, product)
        
        # Try online search with improved strategy
        self.total_searches += 1
        if force_web:
            logger.info(f"Force web search enabled for SKU {sku}; bypassing caches")
        result = await self.search_online_improved_async(product)
        if result:
            # Download and save the image
            download_result = await self._download_and_save_image(
                result.get('url', ''),
                product,
                result.get('confidence', 50),
                result.get('source', ''),
                result.get('description', ''),
                result.get('search_query', ''),
                result.get('image_source', '')
            )
            
            if download_result.get('success'):
                # Cache the result for similar products only if download succeeded
                if not force_web:
                    self.search_cache[cache_key] = result.copy()
                    self.cache_search_result(product, result)
                # Save to DB search cache for barcode+brand combo
                if self.config.get('search', {}).get('use_db_cache', True):
                    try:
                        self.db.save_search_cache(
                            str(barcode or ''), str(brand or ''), str(title or ''),
                            result.get('url', ''), float(result.get('confidence', 0) or 0),
                            result.get('source', '') or ''
                        )
                        logger.info(f"✓ Saved to DB search cache: {barcode} / {brand} → {result.get('url','')}")
                    except Exception as e:
                        logger.warning(f"Failed to save search cache: {e}")
                
                # Return success with download info
                result.update(download_result)
                logger.info(f"✓ Downloaded and saved image for {sku}")
                return result
            else:
                logger.warning(f"✗ Failed to download image for {sku}")
                return {'success': False, 'error': 'Download failed'}
        
        logger.info(f"Cache efficiency: {self.cache_hits}/{self.total_searches} = {self.cache_hits/max(1,self.total_searches)*100:.1f}%")
        return {'success': False, 'error': 'No suitable image found'}
    
    async def search_online_improved_async(self, product: dict) -> Optional[dict]:
        """IMPROVED: Search online with retailer prioritization and variant awareness"""
        
        sku = product.get('Variant_SKU', 'Unknown')
        strategies = self.learning.get_search_strategies()
        
        # Search by retailer tiers for efficiency
        for tier_name, retailers in self.TRUSTED_RETAILERS.items():
            if tier_name == 'tier3':
                # For tier3, use learning system's retailers not in tier1/2
                all_retailers = self.learning.get_top_retailers()
                tier1_2 = self.TRUSTED_RETAILERS['tier1'] + self.TRUSTED_RETAILERS['tier2']
                retailers = [r for r in all_retailers if r not in tier1_2][:2]
            
            if not retailers:
                continue
            
            for site in retailers:
                # Try enhanced query first (with variant details)
                for use_enhanced in [True, False]:
                    query = self.build_enhanced_search_query(product, site, use_enhanced)
                    
                    if not query:
                        continue
                    
                    try:
                        logger.debug(f"Searching {site} for {sku}: {query}")
                        results = self.searcher.search_google_images(
                            query, 
                            num_results=self.config.get('search', {}).get('results_per_query', 3)
                        )
                        if results:
                            # Re-rank with CLIP on thumbnails (GPU) to improve top-1
                            results = await self._rank_results_with_clip(results, product)
                            # Evaluate with variant awareness
                            best = self.evaluate_results_with_variant_matching(results, product, site)
                            if best:
                                best['search_strategy'] = 'enhanced_variant' if use_enhanced else 'barcode_brand'
                                best['search_query'] = query
                                best['retailer_tier'] = tier_name
                                logger.info(f"✓ Found on {site} ({tier_name}) for {sku}")
                                logger.info(f"  URL: {best.get('url', 'NO URL')}")
                                logger.info(f"  Confidence: {best.get('confidence', 0)}")
                                return best
                    
                    except Exception as e:
                        logger.error(f"Search error for {sku} on {site}: {str(e)}")
                        continue
                
            # If found something in tier1, don't search tier2/3
            if tier_name == 'tier1' and results:
                break
        
        return None
    
    def search_online(self, product: dict) -> Optional[dict]:
        """Fallback to original search if improved search fails"""
        
        strategies = self.learning.get_search_strategies()
        retailers = self.learning.get_top_retailers()
        
        # Add top retailers to search
        search_sites = retailers[:3] if retailers else ['shoprite', 'checkers', 'pnp']
        
        for strategy in strategies:
            for site in search_sites:
                query = self.build_search_query(product, strategy, site)
                
                if not query:
                    continue
                
                try:
                    results = self.searcher.search_google_images(
                        query, 
                        num_results=self.config.get('search', {}).get('results_per_query', 3)
                    )
                    
                    if results:
                        # Evaluate results
                        best = self.evaluate_search_results(results, product)
                        if best:
                            best['search_strategy'] = strategy
                            best['search_query'] = query
                            return best
                            
                except Exception as e:
                    logger.error(f"Search error for {product.get('Title', 'Unknown')}: {str(e)}")
                    continue
        
        return None
    
    def build_enhanced_search_query(self, product: dict, site: str = None, use_enhanced: bool = True) -> str:
        """Build search query using EXACT product title ONLY - NO BARCODE"""
        
        title = product.get('Title', '')
        
        # USE EXACT PRODUCT TITLE ONLY - NO BARCODE
        if not title:
            return None
            
        query = title  # Use the exact product name as-is
        
        # Add site restriction if specified
        if site:
            if '.' not in site:
                site = f'{site}.co.za'
            query = f'{query} site:{site}'
        
        return query
    
    def build_search_query(self, product: dict, strategy: str, site: str = None) -> str:
        """Build search query using EXACT product title ONLY - NO BARCODE"""
        
        title = product.get('Title', '')
        
        # USE EXACT PRODUCT TITLE ONLY - NO BARCODE
        if not title:
            return None
            
        query = title  # Use the exact product name as-is regardless of strategy
        
        # Add site restriction if specified
        if site:
            if '.' not in site:
                site = f'{site}.co.za'
            query = f'{query} site:{site}'
        
        return query
    
    def evaluate_results_with_variant_matching(self, results: List[dict], product: dict, retailer: str) -> Optional[dict]:
        """IMPROVED: Evaluate search results with variant awareness"""
        
        if not results:
            return None
        
        title = product.get('Title', '').lower()
        brand = (product.get('Brand', '') or '').lower()
        sku = product.get('Variant_SKU', '')
        variant = (product.get('Variant_Title', '') or '').lower()
        variant_option = (product.get('Variant_option', '') or '').lower()
        barcode = str(product.get('Variant_Barcode', ''))
        size_tolerance_pct = self.config.get('validation', {}).get('size_tolerance_percent', 5)
        
        best_result = None
        best_score = 0
        
        for result in results:
            score = 0
            result_title = result.get('title', '').lower()
            result_snippet = result.get('snippet', '').lower()
            source = result.get('source', '').lower()
            
            # Exact barcode match is gold standard
            if len(barcode) > 6 and barcode in result_title + result_snippet:
                score += 40
            
            # Brand matching (30% weight)
            if brand:
                if brand in result_title:
                    score += 25
                elif brand in source:
                    score += 15
            
            # CRITICAL: Variant matching (40% weight)
            variant_score = 0
            if variant or variant_option:
                # Check for variant mismatch (penalty)
                critical_variants = ['vetkoek', 'flapjack', 'pancake', 'waffle', 'scone', 'muffin']
                for cv in critical_variants:
                    if cv in variant.lower() or cv in variant_option.lower():
                        if cv in result_title:
                            variant_score += 30  # Correct variant
                        else:
                            # Check if wrong variant present
                            for other_cv in critical_variants:
                                if other_cv != cv and other_cv in result_title:
                                    variant_score -= 40  # Wrong variant - heavy penalty
                                    logger.warning(f"Variant mismatch for {sku}: wanted '{cv}', got '{other_cv}'")
                                    break
                
                # General variant matching
                if variant and variant in result_title:
                    variant_score += 20
                if variant_option and variant_option != variant and variant_option in result_title:
                    variant_score += 10
            
            score += variant_score
            
            # Size matching with tolerance (15% weight)
            product_size = self._extract_size_value(title)
            result_size = self._extract_size_value(result_title)
            if product_size and result_size:
                # Percent difference
                diff_pct = abs(product_size - result_size) / product_size * 100
                if diff_pct <= size_tolerance_pct:
                    score += 15
                else:
                    score -= 10  # Size mismatch penalty
            
            # Retailer trust bonus (15% weight)
            tier_bonuses = {'tier1': 15, 'tier2': 10, 'tier3': 5}
            for tier, retailers in self.TRUSTED_RETAILERS.items():
                if retailer in retailers:
                    score += tier_bonuses.get(tier, 0)
                    break
            
            # Apply learning adjustments
            adjustments = self.confidence_adjustments.get(source, {})
            if 'confidence_modifier' in adjustments:
                score += adjustments['confidence_modifier']
            
            # Track best result
            if score > best_score:
                best_score = score
                # Enhanced description from search result
                search_description = result.get('title', '')
                if result.get('snippet'):
                    search_description += f" | {result.get('snippet', '')}"
                
                best_result = {
                    'url': result.get('original') or result.get('link') or result.get('thumbnail'),  # CRITICAL FIX: Include URL!
                    'title': result.get('title', ''),
                    'source': result.get('source', ''),
                    'snippet': result.get('snippet', ''),
                    'description': search_description,  # ENHANCED: Full product description from search
                    'confidence': min(max(score, 0), 100),
                    'sku': sku,
                    'variant_match_score': variant_score,
                    'image_source': result.get('source', '')
                }
        
        # Reject if variant mismatch is too severe
        if best_result and best_result.get('variant_match_score', 0) < -20:
            logger.warning(f"Rejecting result for {sku} due to variant mismatch")
            return None
        
        return best_result if best_score > 35 else None

    def _extract_size_value(self, text: str) -> Optional[float]:
        """Extract normalized size value in grams or milliliters from text.
        g/kg -> grams, ml/l -> milliliters (treat ml and g similarly for scoring).
        """
        import re
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|l|ml|L)", text)
        if not match:
            return None
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit == 'kg':
            return value * 1000.0
        if unit == 'l':
            return value * 1000.0
        if unit == 'ml':
            return value
        if unit == 'g':
            return value
        return None

    async def _rank_results_with_clip(self, results: List[dict], product: dict) -> List[dict]:
        """Download thumbnails and use CLIP to re-rank candidates (best first)."""
        try:
            # Collect thumbnail URLs
            urls: List[str] = []
            idx_map: List[int] = []
            for i, r in enumerate(results):
                thumb = r.get('thumbnail') or r.get('original') or r.get('link')
                if thumb:
                    urls.append(thumb)
                    idx_map.append(i)
            if not urls:
                return results

            # Download thumbnails concurrently
            url_to_bytes = await downloader.download_batch(urls, {
                'network': {
                    'concurrency': self.config.get('network', {}).get('concurrency', 10),
                    'timeout': self.config.get('network', {}).get('timeout', 15)
                }
            })
            thumbs: List[bytes] = [url_to_bytes.get(u) for u in urls if url_to_bytes.get(u)]
            if not thumbs:
                return results

            # Rank indices by CLIP
            order = self.clip.rank_thumbnails(product, thumbs)
            logger.info(f"CLIP thumbnail re-ranking: ranked {len(order)} candidates on {getattr(self.clip, 'device', 'gpu')} device")
            if not order:
                return results

            # Map back to original results in new order
            ordered_results: List[dict] = []
            for ord_idx in order:
                if 0 <= ord_idx < len(idx_map):
                    ordered_results.append(results[idx_map[ord_idx]])
            # Append any missing (failed downloads)
            if len(ordered_results) < len(results):
                used = set(id(x) for x in ordered_results)
                for r in results:
                    if id(r) not in used:
                        ordered_results.append(r)
            return ordered_results
        except Exception as e:
            logger.warning(f"CLIP re-ranking failed: {e}")
            return results
    
    def evaluate_search_results(self, results: List[dict], product: dict) -> Optional[dict]:
        """Original evaluation for fallback"""
        
        if not results:
            return None
        
        title = product.get('Title', '').lower()
        brand = (product.get('Brand', '') or '').lower()
        sku = product.get('Variant_SKU', '')
        
        best_result = None
        best_score = 0
        
        for result in results:
            score = 0
            result_title = result.get('title', '').lower()
            source = result.get('source', '').lower()
            
            # Brand matching
            if brand and brand in result_title:
                score += 40
            if brand and brand in source:
                score += 10
            
            # Title similarity
            title_words = set(title.split())
            result_words = set(result_title.split())
            common_words = title_words.intersection(result_words)
            if len(title_words) > 0:
                score += (len(common_words) / len(title_words)) * 30
            
            # Source reliability
            trusted_sources = ['shoprite', 'checkers', 'pnp', 'makro', 'takealot', 'game']
            for trusted in trusted_sources:
                if trusted in source:
                    score += 20
                    break
            
            # Apply learning adjustments
            adjustments = self.confidence_adjustments.get(source, {})
            if 'confidence_modifier' in adjustments:
                score += adjustments['confidence_modifier']
            
            # Track best result
            if score > best_score:
                best_score = score
                best_result = result
                best_result['confidence'] = min(score, 100)
                best_result['sku'] = sku
        
        return best_result if best_score > 30 else None
    
    async def _search_broad(self, session: aiohttp.ClientSession, product: Dict) -> Optional[Dict]:
        """Broader search as fallback"""
        
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        
        # USE EXACT PRODUCT TITLE ONLY - NO BARCODE
        query = title  # Use the exact product name as-is
        
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
            logger.info(f"Starting download from URL: {url}")
            
            # Download image using the downloader; try async first
            image_bytes = await self.downloader.download_image(url)
            # Fallback: try batch downloader (same headers/session path)
            if not image_bytes:
                try:
                    url_to_bytes = await downloader.download_batch([url], {
                        'network': {
                            'concurrency': self.config.get('network', {}).get('concurrency', 10),
                            'timeout': self.config.get('network', {}).get('timeout', 15)
                        }
                    })
                    image_bytes = url_to_bytes.get(url)
                except Exception as e:
                    logger.warning(f"Batch download fallback failed: {e}")
            # Final fallback: sync request in a thread to avoid loop issues
            if not image_bytes:
                import requests
                from concurrent.futures import ThreadPoolExecutor
                def _sync_fetch(u: str) -> bytes:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
                    }
                    try:
                        from urllib.parse import urlparse as _p
                        netloc = _p(u).netloc
                        if netloc:
                            headers['Referer'] = f"https://{netloc}"
                    except Exception:
                        pass
                    r = requests.get(u, headers=headers, timeout=15)
                    if r.status_code == 200:
                        return r.content
                    return b''
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(_sync_fetch, url)
                    try:
                        image_bytes = fut.result(timeout=20)
                    except Exception:
                        image_bytes = None
                
            if not image_bytes:
                logger.error(f"No image bytes returned from download")
                return {'success': False, 'path': None}
            
            logger.info(f"Downloaded {len(image_bytes)} bytes")
                
            # Validate image using src module
            try:
                from src import img_utils
                if not img_utils.is_valid_image(image_bytes, min_size=150):
                    logger.error(f"Image validation failed")
                    return {'success': False, 'path': None}
                logger.info(f"Image validation passed")
            except ImportError:
                logger.warning("img_utils not available, skipping validation")
                # Continue without validation
                
            # Optimize image
            optimized = img_utils.optimise(
                image_bytes,
                size=self.config['image']['size'],
                fmt='JPEG',
                max_kb=self.config['image']['max_kb']
            )
            
            if not optimized:
                return {'success': False, 'path': None}
            
            # Get product info for folder structure
            brand = product.get('Brand', 'Unknown')
            safe_brand = self.sanitize_filename(brand)
            
            # Determine status based on confidence
            if confidence >= self.confidence_adjustments['confidence_thresholds']['auto_approve']:
                status = 'approved'
                destination_dir = self.approved_dir / safe_brand
            elif confidence >= self.confidence_adjustments['confidence_thresholds']['needs_review']:
                status = 'pending'  # Will be validated by CLIP
                destination_dir = self.pending_dir / safe_brand
            else:
                status = 'declined'
                destination_dir = self.declined_dir / safe_brand
            
            # Save image with UNIQUE filename to prevent collisions  
            title = product.get('Title', 'Unknown')
            sku = product.get('Variant_SKU', 'Unknown')
            
            brand_folder = destination_dir
            brand_folder.mkdir(parents=True, exist_ok=True)
            
            # CRITICAL FIX: Always include SKU in filename to guarantee uniqueness
            safe_title = self.sanitize_filename(title)[:100]  # Limit title length
            safe_sku = self.sanitize_filename(sku)
            # Format: Title_SKU.jpg - SKU guarantees uniqueness even for variants
            filename = f"{safe_title}_{safe_sku}.jpg"
            output_path = brand_folder / filename
            
            with open(output_path, 'wb') as f:
                f.write(optimized)
            
            # Save metadata 
            metadata = {
                    'sku': sku,
                    'title': title,
                    'brand': brand,
                    'source': source,
                    'source_url': image_source if image_source else url,  # Store full URL
                    'confidence': confidence,
                    'description': description,
                    'downloaded_at': datetime.now().isoformat(),
                    'search_query': search_query,
                    'image_url': url  # Original image URL
                }
            
            meta_path = output_path.with_suffix('.json')
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Update database with enhanced metadata
            logger.info(f"Updating database for SKU: {product['Variant_SKU']}")
            logger.info(f"  Path: {str(output_path)}")
            logger.info(f"  Status: {status}")
            
            try:
                self.db.update_product_image(
                    product['Variant_SKU'],
                    str(output_path),
                    confidence,
                    source,
                    status,
                    description,
                    search_query,
                    image_source if image_source else url
                )
                logger.info(f"Database updated successfully for {product['Variant_SKU']}")
            except Exception as db_err:
                logger.error(f"Database update failed for {product['Variant_SKU']}: {str(db_err)}")
                raise
            
            logger.info(f"  Saved to {destination_dir.name}: {filename} ({confidence:.0f}%)")
            
            return {'success': True, 'path': str(output_path)}
                
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return {'success': False, 'path': None}
    
    def process_batch(self, products: List[dict], progress_callback=None) -> dict:
        """Process a batch of products with CLIP validation"""
        
        results = {
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'errors': [],
            'validated': 0
        }
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(
                self._process_batch_async(products, results, progress_callback)
            )
            
            # After processing, run CLIP validation on successful images
            if results['success'] > 0:
                self._run_clip_validation(products, results)
                
        finally:
            loop.close()
        
        return results
    
    async def _process_batch_async(self, products: List[dict], results: dict, progress_callback=None):
        """Async processing of product batch"""
        
        total_products = len(products)
        
        for i, product in enumerate(products):
            try:
                if progress_callback:
                    progress_callback(i + 1, total_products, f"Processing {product.get('Variant_SKU', 'Unknown')}")
                
                # Search for image
                image_result = await self.search_product_image(product)
                
                if image_result and image_result.get('success'):
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    if image_result and image_result.get('error'):
                        results['errors'].append(f"SKU {product.get('Variant_SKU')}: {image_result['error']}")
                    # Avoid burning API repeatedly: mark as not_found for now
                    try:
                        self.db.mark_not_found(product.get('Variant_SKU'))
                    except Exception:
                        pass
                
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"SKU {product.get('Variant_SKU')}: {str(e)}")
                logger.error(f"Error processing product {product.get('Variant_SKU')}: {str(e)}")
                try:
                    self.db.mark_not_found(product.get('Variant_SKU'))
                except Exception:
                    pass
    
    def _run_clip_validation(self, products: List[dict], results: dict):
        """Run CLIP validation on processed images"""
        try:
            # Import CLIP validator (lazy load)
            from clip_validator import CLIPValidator
            
            # Get products that were successfully processed
            products_to_validate = []
            for product in products:
                sku = product.get('Variant_SKU')
                # Check if image was downloaded
                cursor = self.db.conn.cursor()
                cursor.execute(
                    "SELECT downloaded_image_path FROM products WHERE Variant_SKU = ? AND downloaded_image_path IS NOT NULL",
                    (sku,)
                )
                row = cursor.fetchone()
                cursor.close()
                
                if row and row[0]:
                    product['downloaded_image_path'] = row[0]
                    products_to_validate.append(product)
            
            if products_to_validate:
                logger.info(f"Running CLIP validation on {len(products_to_validate)} images")
                clip_cfg = self.config.get('clip', {}).copy()
                clip_cfg.update({'update_database': True})
                # Provide device preference as flat keys for validator
                if 'device_preference' in self.config.get('clip', {}):
                    clip_cfg['device_preference'] = self.config['clip']['device_preference']
                validator = CLIPValidator(config=clip_cfg)
                validation_results = validator.validate_batch(products_to_validate)
                results['validated'] = validation_results['validated']
                logger.info(f"CLIP validation complete: {validation_results['auto_approved']} approved, {validation_results['needs_review']} need review")
                
        except ImportError:
            logger.warning("CLIP validator not available - skipping validation")
        except Exception as e:
            logger.error(f"CLIP validation error: {str(e)}")
    
    def move_to_approved(self, sku: str) -> bool:
        """Move INDIVIDUAL image from pending to approved - FIXED to prevent corruption"""
        
        logger.info(f"Moving single image to approved for SKU: {sku}")
        
        # Get the SPECIFIC product - use thread-safe method
        product = self.db.get_product_by_sku(sku)
        if not product or not product['downloaded_image_path']:
            logger.warning(f"No product or image path found for SKU: {sku} - attempting path repair")
            # Attempt path repair by searching known folders
            repaired = self._repair_missing_path(sku, product)
            if not repaired:
                return False
            # Refresh product with repaired path
            product = self.db.get_product_by_sku(sku)
        
        current_path = Path(product['downloaded_image_path'])
        
        # CRITICAL: Ensure we're dealing with a FILE, not a directory
        if not current_path.exists():
            logger.warning(f"Image file does not exist: {current_path} - attempting path repair")
            # Attempt repair again in case DB had stale path
            if not self._repair_missing_path(sku, product):
                return False
            product = self.db.get_product_by_sku(sku)
            current_path = Path(product['downloaded_image_path'])
            if not current_path.exists():
                return False
        
        if current_path.is_dir():
            logger.error(f"CRITICAL ERROR: Path is a directory, not a file: {current_path}")
            return False
        
        try:
            # Move to approved folder
            brand = product.get('Brand', 'Unknown')
            brand_folder = self.approved_dir / self.sanitize_filename(brand)
            brand_folder.mkdir(exist_ok=True)
            
            # Ensure filename includes SKU for new location
            safe_sku = self.sanitize_filename(sku)
            if safe_sku in current_path.name:
                # Already has SKU, keep the name
                new_filename = current_path.name
            else:
                # Add SKU to filename for safety
                title = product.get('Title', 'Unknown')
                safe_title = self.sanitize_filename(title)[:100]
                new_filename = f"{safe_title}_{safe_sku}.jpg"
            
            new_path = brand_folder / new_filename
            
            # Handle existing file
            if new_path.exists() and new_path != current_path:
                new_path.unlink()  # Remove existing approved file
            
            # Move file only if destination differs
            if new_path != current_path:
                current_path.rename(new_path)
                logger.info(f"✓ Moved to approved: {current_path} → {new_path}")
            else:
                logger.info(f"✓ Already in approved: {new_path}")
            
            # Move metadata if exists
            current_meta = current_path.with_suffix('.json')
            if current_meta.exists() and current_meta.is_file():
                new_meta = new_path.with_suffix('.json')
                if new_meta != current_meta:
                    if new_meta.exists():
                        new_meta.unlink()
                    current_meta.rename(new_meta)
            
            # Update database for ONLY this SKU
            cursor = self.db.conn.cursor()
            try:
                cursor.execute('''
                    UPDATE products SET 
                        downloaded_image_path = ?,
                        image_status = 'approved'
                    WHERE Variant_SKU = ?
                ''', (str(new_path), sku))
                
                # Verify only one row was updated
                if cursor.rowcount != 1:
                    logger.error(f"WARNING: Updated {cursor.rowcount} rows for SKU {sku}")
                    if cursor.rowcount > 1:
                        # Rollback if multiple rows affected
                        self.db.conn.rollback()
                        return False
                
                self.db.conn.commit()
                logger.info(f"✓ Database updated for SKU: {sku}")
            finally:
                cursor.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Error moving image for SKU {sku}: {str(e)}")
            self.db.conn.rollback()
            return False
    
    def move_to_pending(self, sku: str) -> bool:
        """Move image from approved back to pending"""
        
        logger.info(f"Moving image to pending for SKU: {sku}")
        
        # Get specific product
        product = self.db.get_product_by_sku(sku)
        if not product or not product['downloaded_image_path']:
            logger.warning(f"No product or image path for SKU: {sku} - attempting path repair")
            if not self._repair_missing_path(sku, product):
                return False
            product = self.db.get_product_by_sku(sku)
        
        current_path = Path(product['downloaded_image_path'])
        
        # Verify it's a file
        if not current_path.exists():
            logger.warning(f"Image file does not exist: {current_path} - attempting path repair")
            if not self._repair_missing_path(sku, product):
                return False
            product = self.db.get_product_by_sku(sku)
            current_path = Path(product['downloaded_image_path'])
            if not current_path.exists():
                return False
        
        if current_path.is_dir():
            logger.error(f"Path is directory: {current_path}")
            return False
        
        try:
            # Move to pending folder
            brand = product.get('Brand', 'Unknown')
            brand_folder = self.pending_dir / self.sanitize_filename(brand)
            brand_folder.mkdir(exist_ok=True)
            
            # Ensure filename has SKU
            safe_sku = self.sanitize_filename(sku)
            if safe_sku in current_path.name:
                new_filename = current_path.name
            else:
                title = product.get('Title', 'Unknown')
                safe_title = self.sanitize_filename(title)[:100]
                new_filename = f"{safe_title}_{safe_sku}.jpg"
            
            new_path = brand_folder / new_filename
            
            # Handle existing file
            if new_path.exists() and new_path != current_path:
                new_path.unlink()
            
            # Move file only if destination differs
            if new_path != current_path:
                current_path.rename(new_path)
                logger.info(f"✓ Moved to pending: {current_path} → {new_path}")
            else:
                logger.info(f"✓ Already in pending: {new_path}")
            
            # Move metadata if exists
            current_meta = current_path.with_suffix('.json')
            if current_meta.exists() and current_meta.is_file():
                new_meta = new_path.with_suffix('.json')
                if new_meta != current_meta:
                    if new_meta.exists():
                        new_meta.unlink()
                    current_meta.rename(new_meta)
            
            # Update database
            cursor = self.db.conn.cursor()
            try:
                cursor.execute('''
                    UPDATE products SET 
                        downloaded_image_path = ?,
                        image_status = 'pending'
                    WHERE Variant_SKU = ?
                ''', (str(new_path), sku))
                
                self.db.conn.commit()
                logger.info(f"✓ Database updated for SKU: {sku}")
            finally:
                cursor.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Error moving image to pending for SKU {sku}: {str(e)}")
            self.db.conn.rollback()
            return False
    
    def move_to_declined(self, sku: str) -> bool:
        """Move image to declined - FIXED to prevent affecting other products"""
        
        logger.info(f"Moving image to declined for SKU: {sku}")
        
        # Get specific product - thread-safe
        product = self.db.get_product_by_sku(sku)
        if not product or not product['downloaded_image_path']:
            logger.warning(f"No product or image path for SKU: {sku} - attempting path repair")
            if not self._repair_missing_path(sku, product):
                return False
            product = self.db.get_product_by_sku(sku)
        
        current_path = Path(product['downloaded_image_path'])
        
        # Verify it's a file
        if not current_path.exists():
            logger.warning(f"Image file does not exist: {current_path} - attempting path repair")
            if not self._repair_missing_path(sku, product):
                # Still update database to declined status
                self.db.decline_image(sku)
                return True
            product = self.db.get_product_by_sku(sku)
            current_path = Path(product['downloaded_image_path'])
        
        if current_path.is_dir():
            logger.error(f"CRITICAL ERROR: Path is directory: {current_path}")
            return False
        
        try:
            # Move to declined folder
            brand = product.get('Brand', 'Unknown')
            brand_folder = self.declined_dir / self.sanitize_filename(brand)
            brand_folder.mkdir(exist_ok=True)
            
            # Ensure filename has SKU
            safe_sku = self.sanitize_filename(sku)
            if safe_sku in current_path.name:
                new_filename = current_path.name
            else:
                title = product.get('Title', 'Unknown')
                safe_title = self.sanitize_filename(title)[:100]
                new_filename = f"{safe_title}_{safe_sku}.jpg"
            
            new_path = brand_folder / new_filename
            
            # Handle existing file
            if new_path.exists() and new_path != current_path:
                new_path.unlink()  # Remove old declined file
            
            # Move file only if destination differs
            if new_path != current_path:
                current_path.rename(new_path)
                logger.info(f"✓ Moved to declined: {current_path} → {new_path}")
            else:
                logger.info(f"✓ Already in declined: {new_path}")
            
            # Move metadata if exists
            current_meta = current_path.with_suffix('.json')
            if current_meta.exists() and current_meta.is_file():
                new_meta = new_path.with_suffix('.json')
                if new_meta != current_meta:
                    if new_meta.exists():
                        new_meta.unlink()
                    current_meta.rename(new_meta)
            
            # Update database for ONLY this SKU
            cursor = self.db.conn.cursor()
            try:
                cursor.execute('''
                    UPDATE products SET 
                        downloaded_image_path = ?,
                        image_status = 'declined'
                    WHERE Variant_SKU = ?
                ''', (str(new_path), sku))
                
                if cursor.rowcount != 1:
                    logger.error(f"WARNING: Updated {cursor.rowcount} rows for SKU {sku}")
                
                self.db.conn.commit()
            finally:
                cursor.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Error declining image for SKU {sku}: {str(e)}")
            self.db.conn.rollback()
            return False

    def _repair_missing_path(self, sku: str, product: Optional[dict]) -> bool:
        """Attempt to find an image file for SKU across approved/pending/declined and update DB."""
        try:
            brand = (product.get('Brand') if product else None) or 'Unknown'
            safe_brand = self.sanitize_filename(brand)
            safe_sku = self.sanitize_filename(sku)
            candidates = [
                self.approved_dir / safe_brand,
                self.pending_dir / safe_brand,
                self.declined_dir / safe_brand,
                self.approved_dir,
                self.pending_dir,
                self.declined_dir,
            ]
            found_path: Optional[Path] = None
            for base in candidates:
                if base.exists():
                    for file in base.glob(f"**/*{safe_sku}*.jpg"):
                        if file.is_file():
                            found_path = file
                            break
                    if found_path:
                        break
            if found_path:
                cursor = self.db.conn.cursor()
                try:
                    cursor.execute(
                        'UPDATE products SET downloaded_image_path = ? WHERE Variant_SKU = ?',
                        (str(found_path), sku)
                    )
                    self.db.conn.commit()
                    logger.info(f"✓ Repaired path for {sku}: {found_path}")
                    return True
                finally:
                    cursor.close()
            logger.warning(f"Path repair failed for {sku}")
            return False
        except Exception as e:
            logger.error(f"Path repair error for {sku}: {e}")
            return False