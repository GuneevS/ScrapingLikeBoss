"""
Image search functionality using SerpAPI
"""
import asyncio
import logging
from typing import List, Optional
import aiohttp
import os
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


async def image_urls(session: aiohttp.ClientSession, barcode: str, config: dict) -> List[str]:
    """
    Search for product images using SerpAPI and return candidate URLs.
    
    Args:
        session: aiohttp session for making requests
        barcode: Product barcode/SKU to search for
        config: Configuration dictionary containing search settings
        
    Returns:
        List of image URLs found for the barcode
    """
    try:
        api_key = config['search']['serp_api_key']
        max_results = config['search']['max_results']
        query_template = config['search']['query_template']
        
        # Format the search query
        query = query_template.format(barcode=barcode)
        
        # SerpAPI parameters for Google Images search
        params = {
            'engine': 'google_images',
            'q': query,
            'api_key': api_key,
            'num': max_results,
            'ijn': 0,  # Page number
            'safe': 'active',
            'tbm': 'isch'  # Image search
        }
        
        url = f"https://serpapi.com/search?{urlencode(params)}"
        
        logger.info(f"Searching for images: {query}")
        
        async with session.get(url, timeout=config['network']['timeout']) as response:
            if response.status == 200:
                data = await response.json()
                
                # Extract image URLs from the response
                image_urls = []
                if 'images_results' in data:
                    for result in data['images_results'][:max_results]:
                        if 'original' in result:
                            image_urls.append(result['original'])
                        elif 'link' in result:
                            image_urls.append(result['link'])
                
                logger.info(f"Found {len(image_urls)} images for barcode {barcode}")
                return image_urls
            else:
                logger.error(f"SerpAPI request failed with status {response.status} for barcode {barcode}")
                return []
                
    except asyncio.TimeoutError:
        logger.error(f"Timeout searching for images for barcode {barcode}")
        return []
    except Exception as e:
        logger.error(f"Error searching for images for barcode {barcode}: {str(e)}")
        return []


async def search_batch(barcodes: List[str], config: dict) -> dict:
    """
    Search for images for multiple barcodes concurrently.
    
    Args:
        barcodes: List of barcodes to search for
        config: Configuration dictionary
        
    Returns:
        Dictionary mapping barcode to list of image URLs
    """
    connector = aiohttp.TCPConnector(limit=config['network']['concurrency'])
    timeout = aiohttp.ClientTimeout(total=config['network']['timeout'])
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        for barcode in barcodes:
            task = image_urls(session, barcode, config)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build result dictionary
        barcode_to_urls = {}
        for barcode, result in zip(barcodes, results):
            if isinstance(result, Exception):
                logger.error(f"Exception for barcode {barcode}: {result}")
                barcode_to_urls[barcode] = []
            else:
                barcode_to_urls[barcode] = result
        
        return barcode_to_urls
