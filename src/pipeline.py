"""
Main pipeline orchestration for UMS Product Image Enrichment
"""
import asyncio
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Set
import yaml
import pandas as pd
from dotenv import load_dotenv

from . import scrape, downloader, img_utils, storage, qa

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """
    Load configuration from YAML file with environment variable substitution.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Configuration dictionary
    """
    try:
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Replace environment variables
        config_content = os.path.expandvars(config_content)
        
        config = yaml.safe_load(config_content)
        return config
        
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {str(e)}")
        raise


def load_skus_from_excel(excel_files: List[str]) -> Set[str]:
    """
    Load SKUs from Excel files.
    
    Args:
        excel_files: List of paths to Excel files
        
    Returns:
        Set of unique SKUs/barcodes
    """
    all_skus = set()
    
    for excel_file in excel_files:
        try:
            logger.info(f"Loading SKUs from: {excel_file}")
            
            # Try to read Excel file
            df = pd.read_excel(excel_file)
            
            # Look for barcode/SKU columns (common names)
            barcode_columns = ['barcode', 'sku', 'product_code', 'code', 'item_code']
            barcode_col = None
            
            for col in df.columns:
                if col.lower() in barcode_columns:
                    barcode_col = col
                    break
            
            if barcode_col is None:
                # If no obvious column found, use first column
                barcode_col = df.columns[0]
                logger.warning(f"No barcode column found, using first column: {barcode_col}")
            
            # Extract SKUs
            skus = df[barcode_col].dropna().astype(str).unique()
            all_skus.update(skus)
            
            logger.info(f"Loaded {len(skus)} SKUs from {excel_file}")
            
        except Exception as e:
            logger.error(f"Error loading SKUs from {excel_file}: {str(e)}")
            continue
    
    logger.info(f"Total unique SKUs loaded: {len(all_skus)}")
    return all_skus


async def process_sku_batch(skus: List[str], config: dict, resume_skus: Set[str] = None) -> Dict[str, bool]:
    """
    Process a batch of SKUs: search -> download -> optimize -> save.
    
    Args:
        skus: List of SKUs to process
        config: Configuration dictionary
        resume_skus: Set of SKUs to skip (already processed)
        
    Returns:
        Dictionary mapping SKU to success status
    """
    if resume_skus is None:
        resume_skus = set()
    
    # Filter out already processed SKUs
    skus_to_process = [sku for sku in skus if sku not in resume_skus]
    
    if not skus_to_process:
        logger.info("All SKUs in batch already processed")
        return {}
    
    logger.info(f"Processing batch of {len(skus_to_process)} SKUs")
    
    # Step 1: Search for images
    logger.info("Step 1: Searching for images...")
    sku_to_urls = await scrape.search_batch(skus_to_process, config)
    
    # Step 2: Download images
    logger.info("Step 2: Downloading images...")
    download_tasks = []
    sku_url_pairs = []
    
    for sku, urls in sku_to_urls.items():
        if urls:
            # Take first URL for now (could be enhanced to try multiple)
            url = urls[0]
            sku_url_pairs.append((sku, url))
    
    if sku_url_pairs:
        urls_to_download = [url for _, url in sku_url_pairs]
        url_to_bytes = await downloader.download_batch(urls_to_download, config)
    else:
        url_to_bytes = {}
    
    # Step 3: Process and save images
    logger.info("Step 3: Processing and saving images...")
    results = {}
    
    for sku, url in sku_url_pairs:
        try:
            image_bytes = url_to_bytes.get(url)
            
            if image_bytes is None:
                logger.warning(f"No image downloaded for SKU {sku}")
                results[sku] = False
                continue
            
            # Validate image
            if not img_utils.is_valid_image(image_bytes):
                logger.warning(f"Invalid image for SKU {sku}")
                results[sku] = False
                continue
            
            # Optimize image
            optimized_bytes = img_utils.optimise(
                image_bytes,
                size=config['image']['size'],
                fmt=config['image']['format'].upper(),
                max_kb=config['image']['max_kb']
            )
            
            if optimized_bytes is None:
                logger.warning(f"Failed to optimize image for SKU {sku}")
                results[sku] = False
                continue
            
            # Save image
            output_path = storage.get_output_path(sku, config['output']['base_dir'])
            
            if storage.save_image(optimized_bytes, output_path):
                logger.info(f"Successfully processed SKU {sku}")
                results[sku] = True
            else:
                logger.error(f"Failed to save image for SKU {sku}")
                results[sku] = False
                
        except Exception as e:
            logger.error(f"Error processing SKU {sku}: {str(e)}")
            results[sku] = False
    
    # Handle SKUs with no images found
    for sku in skus_to_process:
        if sku not in results:
            logger.warning(f"No images found for SKU {sku}")
            results[sku] = False
    
    return results


async def run_pipeline(excel_files: List[str], config: dict, limit: int = None, resume: bool = False) -> None:
    """
    Main pipeline execution.
    
    Args:
        excel_files: List of Excel files containing SKUs
        config: Configuration dictionary
        limit: Maximum number of SKUs to process (for testing)
        resume: Whether to resume from previous run
    """
    # Load SKUs
    all_skus = load_skus_from_excel(excel_files)
    
    if not all_skus:
        logger.error("No SKUs loaded from Excel files")
        return
    
    # Apply limit if specified
    if limit:
        all_skus = set(list(all_skus)[:limit])
        logger.info(f"Limited to {limit} SKUs for processing")
    
    # Load resume information
    resume_skus = set()
    if resume:
        resume_skus = storage.load_resume_file()
        logger.info(f"Resuming: {len(resume_skus)} SKUs already processed")
    
    # Filter SKUs to process
    skus_to_process = all_skus - resume_skus
    logger.info(f"SKUs to process: {len(skus_to_process)}")
    
    if not skus_to_process:
        logger.info("All SKUs already processed")
        return
    
    # Process in batches
    batch_size = config['network']['concurrency'] * 2  # Process 2x concurrency at a time
    sku_list = list(skus_to_process)
    total_batches = (len(sku_list) + batch_size - 1) // batch_size
    
    processed_skus = resume_skus.copy()
    successful_count = 0
    failed_count = 0
    
    for i in range(0, len(sku_list), batch_size):
        batch_num = i // batch_size + 1
        batch_skus = sku_list[i:i + batch_size]
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_skus)} SKUs)")
        
        try:
            batch_results = await process_sku_batch(batch_skus, config, processed_skus)
            
            # Update counters
            for sku, success in batch_results.items():
                if success:
                    successful_count += 1
                    processed_skus.add(sku)
                else:
                    failed_count += 1
            
            # Save progress
            if resume:
                storage.create_resume_file(processed_skus)
            
            logger.info(f"Batch {batch_num} complete. Success: {successful_count}, Failed: {failed_count}")
            
        except Exception as e:
            logger.error(f"Error processing batch {batch_num}: {str(e)}")
            continue
    
    logger.info(f"Pipeline complete. Total processed: {successful_count}, Failed: {failed_count}")


def run(excel_files: List[str], cfg_path: str, limit: int = None, resume: bool = False) -> None:
    """
    Main entrypoint – orchestrates scrape → download → optimise → save
    
    Args:
        excel_files: List of Excel files containing SKUs
        cfg_path: Path to configuration file
        limit: Maximum number of SKUs to process
        resume: Whether to resume from previous run
    """
    # Load environment variables
    load_dotenv()
    
    # Load configuration
    config = load_config(cfg_path)
    
    # Set up logging
    log_level = getattr(logging, config.get('logging', {}).get('level', 'INFO'))
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Validate configuration
    required_keys = ['search', 'network', 'output', 'image']
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required configuration section: {key}")
    
    # Check for API key
    if not config['search']['serp_api_key'] or config['search']['serp_api_key'] == "${SERP_API_KEY}":
        raise ValueError("SERP_API_KEY not set in environment variables")
    
    # Run pipeline
    try:
        asyncio.run(run_pipeline(excel_files, config, limit, resume))
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        raise


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='UMS Product Image Enrichment Pipeline')
    parser.add_argument('--excel', action='append', required=True,
                       help='Excel file(s) containing SKUs (can be specified multiple times)')
    parser.add_argument('--config', default='config.yaml',
                       help='Configuration file path')
    parser.add_argument('--limit', type=int,
                       help='Limit number of SKUs to process (for testing)')
    parser.add_argument('--resume', action='store_true',
                       help='Resume from previous run')
    parser.add_argument('--tier-to-dir', action='store_true',
                       help='Use tier-based directory structure (default behavior)')
    
    args = parser.parse_args()
    
    try:
        run(args.excel, args.config, args.limit, args.resume)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
