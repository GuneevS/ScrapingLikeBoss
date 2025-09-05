"""
Storage utilities for organizing output files in hierarchical structure
"""
import os
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_output_path(sku: str, base_dir: str = "output") -> Path:
    """
    Generate hierarchical output path for a SKU.
    Structure: output/<Tier1>/<Tier2>/<Tier3>/<SKU>.jpg
    
    Args:
        sku: Product SKU/barcode
        base_dir: Base output directory
        
    Returns:
        Path object for the output file
    """
    # Clean SKU for filesystem compatibility
    clean_sku = clean_filename(sku)
    
    # Create 3-tier hierarchy based on SKU characters
    if len(clean_sku) >= 3:
        tier1 = clean_sku[0]
        tier2 = clean_sku[1]
        tier3 = clean_sku[2]
    elif len(clean_sku) == 2:
        tier1 = clean_sku[0]
        tier2 = clean_sku[1]
        tier3 = "0"
    elif len(clean_sku) == 1:
        tier1 = clean_sku[0]
        tier2 = "0"
        tier3 = "0"
    else:
        tier1 = tier2 = tier3 = "0"
    
    # Build path
    output_path = Path(base_dir) / tier1 / tier2 / tier3 / f"{clean_sku}.jpg"
    return output_path


def ensure_directory(path: Path) -> bool:
    """
    Ensure directory exists, creating it if necessary.
    
    Args:
        path: Path to directory or file (will create parent directories)
        
    Returns:
        True if directory exists or was created successfully
    """
    try:
        if path.is_file():
            directory = path.parent
        else:
            directory = path
        
        directory.mkdir(parents=True, exist_ok=True)
        return True
        
    except Exception as e:
        logger.error(f"Error creating directory {path}: {str(e)}")
        return False


def clean_filename(filename: str) -> str:
    """
    Clean filename for filesystem compatibility.
    
    Args:
        filename: Original filename
        
    Returns:
        Cleaned filename safe for filesystem use
    """
    # Remove or replace problematic characters
    invalid_chars = '<>:"/\\|?*'
    cleaned = filename
    
    for char in invalid_chars:
        cleaned = cleaned.replace(char, '_')
    
    # Remove leading/trailing whitespace and dots
    cleaned = cleaned.strip(' .')
    
    # Ensure not empty
    if not cleaned:
        cleaned = "unknown"
    
    return cleaned


def save_image(image_bytes: bytes, output_path: Path) -> bool:
    """
    Save image bytes to specified path.
    
    Args:
        image_bytes: Image data to save
        output_path: Path where to save the image
        
    Returns:
        True if saved successfully
    """
    try:
        # Ensure parent directory exists
        if not ensure_directory(output_path.parent):
            return False
        
        # Write image bytes
        with open(output_path, 'wb') as f:
            f.write(image_bytes)
        
        logger.info(f"Saved image: {output_path} ({len(image_bytes)} bytes)")
        return True
        
    except Exception as e:
        logger.error(f"Error saving image to {output_path}: {str(e)}")
        return False


def file_exists(path: Path) -> bool:
    """
    Check if file exists and is not empty.
    
    Args:
        path: Path to check
        
    Returns:
        True if file exists and has content
    """
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def get_file_size(path: Path) -> Optional[int]:
    """
    Get file size in bytes.
    
    Args:
        path: Path to file
        
    Returns:
        File size in bytes or None if error
    """
    try:
        if path.exists() and path.is_file():
            return path.stat().st_size
        return None
    except Exception:
        return None


def list_output_files(base_dir: str = "output") -> list[Path]:
    """
    List all output image files in the directory structure.
    
    Args:
        base_dir: Base output directory
        
    Returns:
        List of Path objects for all image files found
    """
    try:
        base_path = Path(base_dir)
        if not base_path.exists():
            return []
        
        # Find all .jpg files recursively
        image_files = list(base_path.rglob("*.jpg"))
        image_files.extend(base_path.rglob("*.jpeg"))
        image_files.extend(base_path.rglob("*.png"))
        
        return sorted(image_files)
        
    except Exception as e:
        logger.error(f"Error listing output files: {str(e)}")
        return []


def create_resume_file(processed_skus: set[str], resume_file: str = "processed_skus.txt") -> bool:
    """
    Create a resume file with processed SKUs for resuming interrupted runs.
    
    Args:
        processed_skus: Set of SKUs that have been processed
        resume_file: Path to resume file
        
    Returns:
        True if resume file created successfully
    """
    try:
        with open(resume_file, 'w') as f:
            for sku in sorted(processed_skus):
                f.write(f"{sku}\n")
        
        logger.info(f"Created resume file: {resume_file} with {len(processed_skus)} SKUs")
        return True
        
    except Exception as e:
        logger.error(f"Error creating resume file: {str(e)}")
        return False


def load_resume_file(resume_file: str = "processed_skus.txt") -> set[str]:
    """
    Load processed SKUs from resume file.
    
    Args:
        resume_file: Path to resume file
        
    Returns:
        Set of SKUs that have been processed
    """
    try:
        if not os.path.exists(resume_file):
            return set()
        
        processed_skus = set()
        with open(resume_file, 'r') as f:
            for line in f:
                sku = line.strip()
                if sku:
                    processed_skus.add(sku)
        
        logger.info(f"Loaded {len(processed_skus)} processed SKUs from resume file")
        return processed_skus
        
    except Exception as e:
        logger.error(f"Error loading resume file: {str(e)}")
        return set()
