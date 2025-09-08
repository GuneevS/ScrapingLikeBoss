"""
Async image downloading with retry logic
"""
import asyncio
import logging
from typing import Optional
import aiohttp
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


async def fetch_image(session: aiohttp.ClientSession, url: str, max_retries: int = 3) -> Optional[bytes]:
    """
    Download image from URL and return bytes or None if failed.
    
    Args:
        session: aiohttp session for making requests
        url: Image URL to download
        max_retries: Maximum number of retry attempts
        
    Returns:
        Image bytes if successful, None if failed
    """
    if not url or not url.startswith(('http://', 'https://')):
        logger.warning(f"Invalid URL: {url}")
        return None
    
    for attempt in range(max_retries + 1):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive'
            }
            # Add Referer from URL to improve CDN acceptance
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    headers['Referer'] = f"https://{parsed.netloc}"
            except Exception:
                pass
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if not content_type.startswith('image/'):
                        logger.warning(f"URL does not return an image: {url} (content-type: {content_type})")
                        return None
                    
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB limit
                        logger.warning(f"Image too large: {url} ({content_length} bytes)")
                        return None
                    
                    image_bytes = await response.read()
                    
                    # Additional size check after download
                    if len(image_bytes) > 10 * 1024 * 1024:  # 10MB limit
                        logger.warning(f"Downloaded image too large: {url} ({len(image_bytes)} bytes)")
                        return None
                    
                    if len(image_bytes) < 1024:  # Minimum 1KB
                        logger.warning(f"Downloaded image too small: {url} ({len(image_bytes)} bytes)")
                        return None
                    
                    logger.info(f"Successfully downloaded image: {url} ({len(image_bytes)} bytes)")
                    return image_bytes
                    
                elif response.status == 404:
                    logger.warning(f"Image not found (404): {url}")
                    return None
                elif response.status == 403:
                    logger.warning(f"Access forbidden (403): {url}")
                    return None
                else:
                    logger.warning(f"HTTP {response.status} for URL: {url}")
                    if attempt < max_retries:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning(f"Timeout downloading image (attempt {attempt + 1}): {url}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
                continue
            return None
        except Exception as e:
            logger.error(f"Error downloading image (attempt {attempt + 1}): {url} - {str(e)}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
                continue
            return None
    
    return None


async def download_batch(urls: list[str], config: dict) -> dict[str, Optional[bytes]]:
    """
    Download multiple images concurrently.
    
    Args:
        urls: List of image URLs to download
        config: Configuration dictionary
        
    Returns:
        Dictionary mapping URL to image bytes (or None if failed)
    """
    connector = aiohttp.TCPConnector(limit=config['network']['concurrency'])
    timeout = aiohttp.ClientTimeout(total=config['network']['timeout'])
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        for url in urls:
            task = fetch_image(session, url)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build result dictionary
        url_to_bytes = {}
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error(f"Exception downloading {url}: {result}")
                url_to_bytes[url] = None
            else:
                url_to_bytes[url] = result
        
        return url_to_bytes


def is_valid_image_url(url: str) -> bool:
    """
    Basic validation of image URL.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL appears to be a valid image URL
    """
    if not url or not url.startswith(('http://', 'https://')):
        return False
    
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return False
        
        # Check for common image extensions
        path = parsed.path.lower()
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        
        # Either has image extension or no extension (could be dynamic URL)
        return path.endswith(image_extensions) or '.' not in path.split('/')[-1]
        
    except Exception:
        return False
