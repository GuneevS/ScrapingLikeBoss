"""
Tests for image processing utilities
"""
import pytest
import io
from PIL import Image
from src.img_utils import optimise, get_image_info, calculate_sha1, is_valid_image, resize_and_crop


def create_test_image(width: int, height: int, color: str = 'red') -> bytes:
    """Create a test image with specified dimensions"""
    img = Image.new('RGB', (width, height), color)
    output = io.BytesIO()
    img.save(output, format='JPEG')
    return output.getvalue()


def test_optimise_basic():
    """Test basic image optimization"""
    # Create a large test image
    test_image = create_test_image(2000, 1500)
    
    # Optimize to 1000px
    result = optimise(test_image, size=1000, fmt='JPEG', max_kb=200)
    
    assert result is not None
    assert len(result) < len(test_image)  # Should be smaller
    
    # Check resulting image
    with Image.open(io.BytesIO(result)) as img:
        assert img.size == (1000, 1000)  # Should be square
        assert img.format == 'JPEG'


def test_optimise_square_crop():
    """Test that images are properly square-cropped"""
    # Create rectangular image
    test_image = create_test_image(1200, 800)
    
    result = optimise(test_image, size=500)
    
    assert result is not None
    
    with Image.open(io.BytesIO(result)) as img:
        assert img.size == (500, 500)


def test_get_image_info():
    """Test image info extraction"""
    test_image = create_test_image(800, 600)
    
    info = get_image_info(test_image)
    
    assert info is not None
    assert info['width'] == 800
    assert info['height'] == 600
    assert info['format'] == 'JPEG'
    assert info['size_bytes'] == len(test_image)


def test_calculate_sha1():
    """Test SHA-1 hash calculation"""
    data = b"test data"
    hash1 = calculate_sha1(data)
    hash2 = calculate_sha1(data)
    
    assert hash1 == hash2  # Same data should produce same hash
    assert len(hash1) == 40  # SHA-1 is 40 hex characters
    
    # Different data should produce different hash
    hash3 = calculate_sha1(b"different data")
    assert hash1 != hash3


def test_is_valid_image():
    """Test image validation"""
    # Valid image
    valid_image = create_test_image(500, 500)
    assert is_valid_image(valid_image, min_size=100)
    
    # Too small image
    small_image = create_test_image(50, 50)
    assert not is_valid_image(small_image, min_size=100)
    
    # Invalid data
    assert not is_valid_image(b"not an image")


def test_resize_and_crop():
    """Test resize and crop functionality"""
    test_image = create_test_image(1000, 800)
    
    result = resize_and_crop(test_image, (400, 300))
    
    assert result is not None
    
    with Image.open(io.BytesIO(result)) as img:
        assert img.size == (400, 300)
