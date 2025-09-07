"""
CLIP-based Image Validation System
Modular component for validating product images against their descriptions
Uses OpenAI's CLIP model for semantic matching
"""

import torch
import clip
from PIL import Image
import numpy as np
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
from datetime import datetime
import sqlite3
import easyocr
import cv2

logger = logging.getLogger(__name__)

class CLIPValidator:
    """Semantic image validation using CLIP model"""
    
    def __init__(self, config: dict = None, db_path: str = "nwk_images.db"):
        """
        Initialize CLIP validator with OCR and quality assessment
        
        Args:
            config: Configuration dictionary
            db_path: Path to database
        """
        self.config = config or {}
        self.db_path = db_path
        
        # Device selection - use MPS (Metal) for M4 Max GPU acceleration
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
            logger.info("Using Apple Silicon GPU (MPS) for CLIP")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
            logger.info("Using CUDA GPU for CLIP")
        else:
            self.device = torch.device("cpu")
            logger.info("Using CPU for CLIP")
        
        # Load CLIP model (ViT-B/32 is a good balance of speed and accuracy)
        try:
            self.model, self.preprocess = clip.load("ViT-B/32", device=self.device)
            logger.info("CLIP model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load CLIP model: {str(e)}")
            raise
        
        # Initialize OCR reader (English language)
        try:
            self.ocr_reader = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
            logger.info("OCR reader initialized")
        except Exception as e:
            logger.warning(f"OCR initialization failed: {str(e)}")
            self.ocr_reader = None
        
        # Validation thresholds (more lenient to reduce false rejections)
        self.thresholds = {
            'auto_approve': 0.60,    # High confidence match (reduced from 0.70)
            'needs_review': 0.30,    # Low confidence, manual review needed (reduced from 0.40)
            'auto_reject': 0.15,     # Very poor match, likely wrong product (reduced from 0.25)
            'variant_penalty': 0.10  # Penalty for variant mismatch (reduced from 0.15)
        }
        
        # Cache for processed embeddings
        self.embedding_cache = {}
        self.validation_log = []
    
    def validate_image(self, image_path: str, product: Dict) -> Dict:
        """
        Validate a single image against product description with OCR and quality checks
        
        Args:
            image_path: Path to image file
            product: Product dictionary with metadata
            
        Returns:
            Validation result dictionary
        """
        try:
            # Load and preprocess image
            image = Image.open(image_path)
            image_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
            
            # Create text descriptions for the product
            text_descriptions = self._create_product_descriptions(product)
            
            # Tokenize text
            text_tokens = clip.tokenize(text_descriptions, truncate=True).to(self.device)
            
            # Calculate features
            with torch.no_grad():
                image_features = self.model.encode_image(image_tensor)
                text_features = self.model.encode_text(text_tokens)
                
                # Normalize features
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                
                # Calculate similarities
                similarities = (100.0 * image_features @ text_features.T).softmax(dim=-1)
                
            # Get scores
            scores = similarities[0].cpu().numpy()
            
            # Analyze results
            result = self._analyze_scores(scores, product, text_descriptions)
            
            # Add OCR text detection with confidence boost
            ocr_result = self._detect_text(image_path, product)
            result['ocr_match'] = ocr_result['match']
            result['detected_text'] = ocr_result['text']
            result['text_issues'] = ocr_result['issues']
            
            # Apply OCR confidence boost
            if ocr_result['match']:
                result['confidence'] = min(1.0, result['confidence'] + ocr_result.get('confidence_boost', 0))
                result['ocr_boost_applied'] = ocr_result.get('confidence_boost', 0)
            
            # Add image quality assessment
            quality_result = self._assess_image_quality(image_path)
            result['quality_score'] = quality_result['score']
            result['quality_issues'] = quality_result['issues']
            result['is_professional'] = quality_result['is_professional']
            
            # Adjust final action based on all factors
            result = self._adjust_final_decision(result)
            
            # Log validation
            self.validation_log.append({
                'timestamp': datetime.now().isoformat(),
                'sku': product.get('Variant_SKU'),
                'image_path': image_path,
                'result': result
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Validation error for {image_path}: {str(e)}")
            return {
                'valid': False,
                'confidence': 0.0,
                'reason': f"Validation error: {str(e)}",
                'action': 'manual_review'
            }
    
    def _create_product_descriptions(self, product: Dict) -> List[str]:
        """Create multiple text descriptions for better matching"""
        
        descriptions = []
        
        # Basic product description
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        variant = product.get('Variant_Title', '')
        variant_option = product.get('Variant_option', '')
        
        # Primary description
        descriptions.append(f"A product photo of {brand} {title}")
        
        # Brand and variant specific
        if brand and variant:
            descriptions.append(f"A package of {brand} {variant}")
        
        # Variant option specific (critical for flavors)
        if variant_option:
            descriptions.append(f"A {variant_option} product from {brand}")
        
        # Category based
        tier1 = product.get('Tier_1', '')
        if tier1:
            descriptions.append(f"A {tier1} product: {title}")
        
        # Size specific
        import re
        size_match = re.search(r'(\d+(?:\.\d+)?)\s*(g|kg|ml|l|L)', title)
        if size_match:
            size = size_match.group(0)
            descriptions.append(f"A {size} package of {brand} {variant or title}")
        
        return descriptions
    
    def _analyze_scores(self, scores: np.ndarray, product: Dict, descriptions: List[str]) -> Dict:
        """Analyze similarity scores and determine validation result"""
        
        max_score = float(scores.max())
        avg_score = float(scores.mean())
        best_match_idx = scores.argmax()
        
        # Check for variant mismatch
        variant_penalty = 0
        variant = product.get('Variant_Title', '').lower()
        variant_option = product.get('Variant_option', '').lower()
        
        if variant or variant_option:
            # Check if this is a critical variant (flavor, type)
            critical_variants = ['vetkoek', 'flapjack', 'pancake', 'waffle', 'chocolate', 'vanilla', 'strawberry']
            for cv in critical_variants:
                if cv in variant or cv in variant_option:
                    # This product has a critical variant
                    if best_match_idx > 1:  # Not matching primary descriptions
                        variant_penalty = self.thresholds['variant_penalty']
                    break
        
        # Adjust score for variant
        final_score = max_score - variant_penalty
        
        # Adjust thresholds based on real-world product matching
        # More lenient for legitimate product images
        if max_score >= 0.65:  # Lowered from 0.8
            action = 'auto_approve'
            valid = True
            reason = 'High confidence match'
        elif max_score >= 0.35:  # Lowered from 0.4
            action = 'manual_review'
            valid = True
            reason = 'Medium confidence - review recommended'
        else:
            action = 'auto_reject'
            valid = False
            reason = 'Low confidence match'
        
        return {
            'valid': valid,
            'confidence': final_score,
            'raw_scores': scores.tolist(),
            'best_match': descriptions[best_match_idx],
            'reason': reason,
            'action': action,
            'variant_penalty': variant_penalty
        }
    
    def validate_batch(self, products: List[Dict], progress_callback=None) -> Dict:
        """
        Validate a batch of products
        
        Args:
            products: List of product dictionaries
            progress_callback: Optional callback for progress updates
            
        Returns:
            Batch validation results
        """
        results = {
            'total': len(products),
            'validated': 0,
            'auto_approved': 0,
            'needs_review': 0,
            'auto_rejected': 0,
            'errors': 0,
            'details': []
        }
        
        for i, product in enumerate(products):
            if progress_callback:
                progress_callback(i, len(products), f"Validating {product.get('Variant_SKU')}")
            
            image_path = product.get('downloaded_image_path')
            if not image_path or not Path(image_path).exists():
                results['errors'] += 1
                results['details'].append({
                    'sku': product.get('Variant_SKU'),
                    'error': 'Image not found'
                })
                continue
            
            # Validate image
            validation = self.validate_image(image_path, product)
            
            # Update counts
            results['validated'] += 1
            if validation['action'] == 'auto_approve':
                results['auto_approved'] += 1
            elif validation['action'] == 'manual_review':
                results['needs_review'] += 1
            elif validation['action'] == 'auto_reject':
                results['auto_rejected'] += 1
            
            # Store detailed result
            results['details'].append({
                'sku': product.get('Variant_SKU'),
                'validation': validation
            })
            
            # Update database if configured
            if self.config.get('update_database', False):
                self._update_database(product.get('Variant_SKU'), validation)
        
        return results
    
    def _update_database(self, sku: str, validation: Dict):
        """Update database with validation results"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Add validation columns if they don't exist
            cursor.execute("""
                SELECT COUNT(*) FROM pragma_table_info('products') 
                WHERE name='clip_confidence'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE products ADD COLUMN clip_confidence REAL
                """)
                cursor.execute("""
                    ALTER TABLE products ADD COLUMN clip_validation TEXT
                """)
                cursor.execute("""
                    ALTER TABLE products ADD COLUMN clip_action TEXT
                """)
            
            # Update product
            cursor.execute("""
                UPDATE products 
                SET clip_confidence = ?, 
                    clip_validation = ?,
                    clip_action = ?
                WHERE Variant_SKU = ?
            """, (
                validation['confidence'],
                validation['reason'],
                validation['action'],
                sku
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Database update error: {str(e)}")
    
    def _detect_text(self, image_path: str, product: Dict) -> Dict:
        """Detect text in image using OCR with improved matching"""
        
        try:
            if not self.ocr_reader:
                return {'match': False, 'text': '', 'issues': [], 'confidence_boost': 0}
            
            # Read text from image
            result = self.ocr_reader.readtext(image_path)
            detected_text = ' '.join([text[1] for text in result]).lower()
            
            brand = product.get('Brand', '').lower()
            title = product.get('Title', '').lower()
            variant = product.get('Variant_option', '').lower()
            variant_title = product.get('Variant_Title', '').lower()
            
            issues = []
            match = False
            confidence_boost = 0
            
            # Check for brand match (high value)
            if brand and brand in detected_text:
                match = True
                confidence_boost += 0.15  # Boost confidence if brand is found
            elif brand:
                issues.append(f"Brand '{brand}' not found in text")
            
            # Check for variant match (critical for accuracy)
            if variant and variant in detected_text:
                match = True
                confidence_boost += 0.1
            
            if variant_title and variant_title in detected_text:
                match = True
                confidence_boost += 0.1
            
            # Check for key product terms
            title_words = [w for w in title.split() if len(w) > 3]
            matching_words = sum(1 for word in title_words if word in detected_text)
            
            if matching_words >= 2:
                match = True
                confidence_boost += 0.05 * min(matching_words, 3)  # Up to 0.15 boost
            
            return {
                'match': match,
                'text': detected_text[:500],  # Limit text length
                'issues': issues,
                'confidence_boost': min(confidence_boost, 0.3)  # Cap total boost
            }
            
        except Exception as e:
            logger.error(f"OCR error: {str(e)}")
            return {'match': None, 'text': [], 'issues': [f"OCR error: {str(e)}"]}
    
    def _assess_image_quality(self, image_path: str) -> Dict:
        """
        Assess image quality and whether it looks professional
        """
        try:
            # Read image with OpenCV
            img = cv2.imread(image_path)
            if img is None:
                return {'score': 0, 'issues': ['Cannot read image'], 'is_professional': False}
            
            issues = []
            score = 100
            
            # Check resolution
            height, width = img.shape[:2]
            if width < 300 or height < 300:
                issues.append(f"Low resolution: {width}x{height}")
                score -= 30
            
            # Check blur using Laplacian variance
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if laplacian_var < 100:
                issues.append("Image appears blurry")
                score -= 20
            
            # Check brightness
            mean_brightness = gray.mean()
            if mean_brightness < 50:
                issues.append("Image too dark")
                score -= 15
            elif mean_brightness > 200:
                issues.append("Image overexposed")
                score -= 15
            
            # Check for uniform background (professional indicator)
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = edges.sum() / (width * height * 255)
            
            # Professional images typically have clean backgrounds
            is_professional = True
            if edge_ratio > 0.15:  # Too many edges suggest cluttered background
                issues.append("Cluttered background (possibly user-taken)")
                is_professional = False
                score -= 25
            
            # Check color distribution (professional images have better color balance)
            hist = cv2.calcHist([img], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist = hist.flatten()
            hist = hist / hist.sum()
            entropy = -np.sum(hist * np.log2(hist + 1e-10))
            
            if entropy < 3.5:  # Low entropy suggests poor color distribution
                issues.append("Poor color distribution")
                score -= 10
            
            # Check aspect ratio (professional product images are usually square or 4:3)
            aspect_ratio = width / height
            if aspect_ratio < 0.7 or aspect_ratio > 1.5:
                issues.append(f"Unusual aspect ratio: {aspect_ratio:.2f}")
                is_professional = False
            
            return {
                'score': max(0, score),
                'issues': issues,
                'is_professional': is_professional and score >= 70
            }
            
        except Exception as e:
            logger.error(f"Quality assessment error: {str(e)}")
            return {'score': 50, 'issues': [f"Assessment error: {str(e)}"], 'is_professional': None}
    
    def _adjust_final_decision(self, result: Dict) -> Dict:
        """
        Adjust final decision based on all validation factors
        """
        # Start with CLIP-based decision
        confidence = result['confidence']
        
        # Apply penalties for OCR mismatches
        if result.get('text_issues'):
            confidence -= 0.1 * len(result['text_issues'])
            result['reason'] += f" | Text issues: {len(result['text_issues'])}"
        
        # Apply penalty for poor quality
        if result.get('quality_score', 100) < 50:
            confidence -= 0.15
            result['reason'] += " | Poor image quality"
        
        # Apply penalty if not professional
        if result.get('is_professional') == False:
            confidence -= 0.1
            result['reason'] += " | Appears user-taken"
        
        # Re-evaluate action based on adjusted confidence
        if confidence >= self.thresholds['auto_approve']:
            result['action'] = 'auto_approve'
        elif confidence >= self.thresholds['needs_review']:
            result['action'] = 'manual_review'
        else:
            result['action'] = 'auto_reject'
        
        result['final_confidence'] = confidence
        
        return result
    
    def get_validation_summary(self) -> Dict:
        """Get summary of all validations performed"""
        if not self.validation_log:
            return {'message': 'No validations performed yet'}
        
        summary = {
            'total_validations': len(self.validation_log),
            'avg_confidence': np.mean([v['result']['confidence'] for v in self.validation_log]),
            'action_breakdown': {},
            'recent_validations': self.validation_log[-10:]
        }
        
        # Count actions
        for validation in self.validation_log:
            action = validation['result']['action']
            summary['action_breakdown'][action] = summary['action_breakdown'].get(action, 0) + 1
        
        return summary
    
    def save_validation_log(self, filepath: str = "validation_log.json"):
        """Save validation log to file"""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.validation_log, f, indent=2)
            logger.info(f"Validation log saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save validation log: {str(e)}")


# Standalone validation function for easy integration
def validate_product_image(image_path: str, product: Dict, config: Dict = None) -> Dict:
    """
    Standalone function to validate a single product image
    
    Args:
        image_path: Path to image
        product: Product metadata
        config: Optional configuration
        
    Returns:
        Validation result
    """
    validator = CLIPValidator(config)
    return validator.validate_image(image_path, product)


if __name__ == "__main__":
    # Test the validator
    import sys
    
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
        test_product = {
            'Variant_SKU': 'TEST123',
            'Brand': 'Test Brand',
            'Title': 'Test Product 500g',
            'Variant_Title': 'Original',
            'Variant_option': 'Classic'
        }
        
        validator = CLIPValidator()
        result = validator.validate_image(test_image, test_product)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python clip_validator.py <image_path>")
