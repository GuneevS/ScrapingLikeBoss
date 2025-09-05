"""
Quality assurance checks for processed images
"""
import os
import logging
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict
import hashlib
from PIL import Image

logger = logging.getLogger(__name__)


class QAReport:
    """Container for QA check results"""
    
    def __init__(self):
        self.total_files = 0
        self.valid_files = 0
        self.issues = defaultdict(list)
        self.file_hashes = {}
        self.duplicates = defaultdict(list)
        
    def add_issue(self, category: str, message: str):
        """Add an issue to the report"""
        self.issues[category].append(message)
        
    def add_duplicate(self, hash_value: str, file_path: str):
        """Add a duplicate file"""
        self.duplicates[hash_value].append(file_path)
        
    def has_issues(self) -> bool:
        """Check if there are any issues"""
        return len(self.issues) > 0 or len([d for d in self.duplicates.values() if len(d) > 1]) > 0
        
    def print_summary(self):
        """Print QA report summary"""
        print(f"\n{'='*60}")
        print(f"QA REPORT SUMMARY")
        print(f"{'='*60}")
        print(f"Total files processed: {self.total_files}")
        print(f"Valid files: {self.valid_files}")
        print(f"Files with issues: {self.total_files - self.valid_files}")
        
        if self.issues:
            print(f"\nISSUES FOUND:")
            for category, messages in self.issues.items():
                print(f"\n{category.upper()} ({len(messages)} files):")
                for msg in messages[:10]:  # Show first 10
                    print(f"  - {msg}")
                if len(messages) > 10:
                    print(f"  ... and {len(messages) - 10} more")
        
        # Check for duplicates
        duplicate_groups = [files for files in self.duplicates.values() if len(files) > 1]
        if duplicate_groups:
            print(f"\nDUPLICATE FILES ({len(duplicate_groups)} groups):")
            for i, files in enumerate(duplicate_groups[:5]):  # Show first 5 groups
                print(f"  Group {i+1}:")
                for file in files:
                    print(f"    - {file}")
            if len(duplicate_groups) > 5:
                print(f"  ... and {len(duplicate_groups) - 5} more groups")
        
        if not self.has_issues():
            print(f"\n✅ All files passed QA checks!")
        else:
            print(f"\n❌ Issues found - see details above")


def check_image_resolution(file_path: Path, min_resolution: int = 1000) -> tuple[bool, str]:
    """
    Check if image meets minimum resolution requirement.
    
    Args:
        file_path: Path to image file
        min_resolution: Minimum width/height in pixels
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            min_dimension = min(width, height)
            
            if min_dimension < min_resolution:
                return False, f"Resolution too low: {width}x{height} (min: {min_resolution}px)"
            
            return True, ""
            
    except Exception as e:
        return False, f"Cannot read image: {str(e)}"


def check_file_size(file_path: Path, max_kb: int = 200) -> tuple[bool, str]:
    """
    Check if file size is within limit.
    
    Args:
        file_path: Path to file
        max_kb: Maximum file size in KB
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        size_bytes = file_path.stat().st_size
        size_kb = size_bytes / 1024
        
        if size_kb > max_kb:
            return False, f"File too large: {size_kb:.1f}KB (max: {max_kb}KB)"
        
        if size_kb < 1:
            return False, f"File too small: {size_kb:.1f}KB"
        
        return True, ""
        
    except Exception as e:
        return False, f"Cannot check file size: {str(e)}"


def calculate_file_hash(file_path: Path) -> str:
    """
    Calculate SHA-1 hash of file.
    
    Args:
        file_path: Path to file
        
    Returns:
        SHA-1 hash as hexadecimal string
    """
    try:
        with open(file_path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except Exception as e:
        logger.error(f"Error calculating hash for {file_path}: {str(e)}")
        return ""


def check_directory(output_dir: str, config: dict) -> QAReport:
    """
    Perform comprehensive QA checks on output directory.
    
    Args:
        output_dir: Path to output directory
        config: Configuration dictionary
        
    Returns:
        QAReport with results
    """
    report = QAReport()
    output_path = Path(output_dir)
    
    if not output_path.exists():
        report.add_issue("directory", f"Output directory does not exist: {output_dir}")
        return report
    
    # Get image configuration
    min_resolution = config.get('image', {}).get('size', 1000)
    max_kb = config.get('image', {}).get('max_kb', 200)
    
    # Find all image files
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    image_files = []
    
    for file_path in output_path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in image_extensions:
            image_files.append(file_path)
    
    report.total_files = len(image_files)
    logger.info(f"Found {len(image_files)} image files to check")
    
    # Check each file
    for file_path in image_files:
        file_valid = True
        
        # Check resolution
        res_valid, res_error = check_image_resolution(file_path, min_resolution)
        if not res_valid:
            report.add_issue("resolution", f"{file_path.name}: {res_error}")
            file_valid = False
        
        # Check file size
        size_valid, size_error = check_file_size(file_path, max_kb)
        if not size_valid:
            report.add_issue("file_size", f"{file_path.name}: {size_error}")
            file_valid = False
        
        # Calculate hash for duplicate detection
        file_hash = calculate_file_hash(file_path)
        if file_hash:
            report.file_hashes[str(file_path)] = file_hash
            report.add_duplicate(file_hash, str(file_path))
        
        if file_valid:
            report.valid_files += 1
    
    return report


def check_sku_coverage(output_dir: str, expected_skus: Set[str]) -> Dict[str, List[str]]:
    """
    Check coverage of SKUs in output directory.
    
    Args:
        output_dir: Path to output directory
        expected_skus: Set of SKUs that should have images
        
    Returns:
        Dictionary with 'missing' and 'extra' SKU lists
    """
    output_path = Path(output_dir)
    found_skus = set()
    
    if output_path.exists():
        # Extract SKUs from filenames
        for file_path in output_path.rglob('*.jpg'):
            sku = file_path.stem  # Filename without extension
            found_skus.add(sku)
    
    missing_skus = expected_skus - found_skus
    extra_skus = found_skus - expected_skus
    
    return {
        'missing': sorted(list(missing_skus)),
        'extra': sorted(list(extra_skus)),
        'found': sorted(list(found_skus))
    }


def main():
    """Main QA script entry point"""
    import argparse
    import yaml
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Quality assurance checks for processed images')
    parser.add_argument('--dir', required=True, help='Output directory to check')
    parser.add_argument('--config', default='config.yaml', help='Configuration file')
    parser.add_argument('--expected-skus', help='File with expected SKUs (one per line)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load configuration
    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading config: {str(e)}")
        return 1
    
    # Run QA checks
    print(f"Running QA checks on: {args.dir}")
    report = check_directory(args.dir, config)
    
    # Check SKU coverage if expected SKUs provided
    if args.expected_skus:
        try:
            with open(args.expected_skus, 'r') as f:
                expected_skus = {line.strip() for line in f if line.strip()}
            
            coverage = check_sku_coverage(args.dir, expected_skus)
            
            print(f"\nSKU COVERAGE:")
            print(f"Expected: {len(expected_skus)}")
            print(f"Found: {len(coverage['found'])}")
            print(f"Missing: {len(coverage['missing'])}")
            print(f"Extra: {len(coverage['extra'])}")
            
            if coverage['missing']:
                print(f"\nMissing SKUs ({len(coverage['missing'])}):")
                for sku in coverage['missing'][:20]:  # Show first 20
                    print(f"  - {sku}")
                if len(coverage['missing']) > 20:
                    print(f"  ... and {len(coverage['missing']) - 20} more")
            
        except Exception as e:
            logger.error(f"Error checking SKU coverage: {str(e)}")
    
    # Print report
    report.print_summary()
    
    # Return exit code
    return 0 if not report.has_issues() else 1


if __name__ == '__main__':
    exit(main())
