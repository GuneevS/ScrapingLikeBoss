"""
Image processing utilities for optimization and quality control
"""
import io
import logging
import hashlib
from typing import Optional, Tuple
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


def optimise(img_bytes: bytes, size: int, fmt: str = "JPEG", max_kb: int = 200) -> Optional[bytes]:
    """
    Square-crop, resize & compress image; return optimized bytes.
    
    Args:
        img_bytes: Original image bytes
        size: Target size (width and height in pixels)
        fmt: Output format (JPEG, PNG, etc.)
        max_kb: Maximum file size in KB
        
    Returns:
        Optimized image bytes or None if processing failed
    """
    try:
        # Open image from bytes
        with Image.open(io.BytesIO(img_bytes)) as img:
            # Convert to RGB if necessary (for JPEG compatibility)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparent images
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Square crop (center crop to smallest dimension)
            width, height = img.size
            min_dimension = min(width, height)
            
            left = (width - min_dimension) // 2
            top = (height - min_dimension) // 2
            right = left + min_dimension
            bottom = top + min_dimension
            
            img_cropped = img.crop((left, top, right, bottom))
            
            # Resize to target size
            img_resized = img_cropped.resize((size, size), Image.Resampling.LANCZOS)
            
            # Save with compression, trying different quality levels
            for quality in [95, 85, 75, 65, 55, 45]:
                output = io.BytesIO()
                save_kwargs = {'format': fmt}
                
                if fmt.upper() == 'JPEG':
                    save_kwargs.update({
                        'quality': quality,
                        'optimize': True,
                        'progressive': True
                    })
                elif fmt.upper() == 'PNG':
                    save_kwargs.update({
                        'optimize': True,
                        'compress_level': 9
                    })
                
                img_resized.save(output, **save_kwargs)
                output_bytes = output.getvalue()
                
                # Check if file size is within limit
                if len(output_bytes) <= max_kb * 1024:
                    logger.info(f"Optimized image: {len(img_bytes)} -> {len(output_bytes)} bytes (quality: {quality})")
                    return output_bytes
            
            # If we couldn't get under the size limit, return the smallest version
            logger.warning(f"Could not optimize image under {max_kb}KB, returning best effort")
            return output_bytes
            
    except Exception as e:
        logger.error(f"Error optimizing image: {str(e)}")
        return None


def get_image_info(img_bytes: bytes) -> Optional[dict]:
    """
    Get basic information about an image.
    
    Args:
        img_bytes: Image bytes
        
    Returns:
        Dictionary with image info or None if invalid
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            return {
                'width': img.width,
                'height': img.height,
                'mode': img.mode,
                'format': img.format,
                'size_bytes': len(img_bytes)
            }
    except Exception as e:
        logger.error(f"Error getting image info: {str(e)}")
        return None


def calculate_sha1(data: bytes) -> str:
    """
    Calculate SHA-1 hash of data.
    
    Args:
        data: Bytes to hash
        
    Returns:
        SHA-1 hash as hexadecimal string
    """
    return hashlib.sha1(data).hexdigest()


def is_valid_image(img_bytes: bytes, min_size: int = 100) -> bool:
    """
    Check if image bytes represent a valid image meeting minimum requirements.
    
    Args:
        img_bytes: Image bytes to validate
        min_size: Minimum width/height in pixels
        
    Returns:
        True if image is valid and meets requirements
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            width, height = img.size
            
            # Check minimum dimensions
            if width < min_size or height < min_size:
                logger.warning(f"Image too small: {width}x{height} (minimum: {min_size})")
                return False
            
            # Check if image is corrupted by trying to load it
            img.load()
            
            return True
            
    except Exception as e:
        logger.error(f"Invalid image: {str(e)}")
        return False


def resize_and_crop(img_bytes: bytes, target_size: Tuple[int, int]) -> Optional[bytes]:
    """
    Resize and crop image to exact target dimensions.
    
    Args:
        img_bytes: Original image bytes
        target_size: Target (width, height) in pixels
        
    Returns:
        Processed image bytes or None if failed
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Use ImageOps.fit for smart cropping and resizing
            img_fitted = ImageOps.fit(img, target_size, Image.Resampling.LANCZOS)
            
            # Save to bytes
            output = io.BytesIO()
            img_fitted.save(output, format='JPEG', quality=85, optimize=True)
            
            return output.getvalue()
            
    except Exception as e:
        logger.error(f"Error resizing and cropping image: {str(e)}")
        return None
