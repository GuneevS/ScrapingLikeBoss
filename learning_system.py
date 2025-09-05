"""
Continuous Learning System for NWK Image Management

This module tracks user feedback and improves search accuracy over time.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class LearningSystem:
    """Continuous learning system that improves based on user feedback"""
    
    def __init__(self, db_path: str = "nwk_products.db"):
        self.db_path = db_path
        self.patterns_file = Path("learning_patterns.json")
        self.load_patterns()
        
    def load_patterns(self):
        """Load learned patterns from file"""
        if self.patterns_file.exists():
            with open(self.patterns_file, 'r') as f:
                self.patterns = json.load(f)
        else:
            self.patterns = {
                'successful_retailers': {},  # Retailer -> success count
                'brand_keywords': {},        # Brand -> effective keywords
                'rejected_sources': {},      # Sources that often get rejected
                'confidence_thresholds': {
                    'auto_approve': 80,
                    'auto_reject': 30
                },
                'search_strategies': {
                    'barcode_first': {'success': 0, 'total': 0},
                    'brand_title': {'success': 0, 'total': 0},
                    'retailer_specific': {'success': 0, 'total': 0}
                }
            }
    
    def save_patterns(self):
        """Save learned patterns to file"""
        with open(self.patterns_file, 'w') as f:
            json.dump(self.patterns, f, indent=2)
    
    def record_approval(self, product: dict):
        """Record when a product image is approved"""
        
        # Track successful retailer
        source = product.get('image_source', '').lower()
        if source:
            for retailer in ['checkers', 'shoprite', 'pnp', 'makro', 'woolworths', 'dischem']:
                if retailer in source:
                    self.patterns['successful_retailers'][retailer] = \
                        self.patterns['successful_retailers'].get(retailer, 0) + 1
                    break
        
        # Track successful search strategy
        query = product.get('search_query', '')
        if query:
            if product.get('Variant_Barcode') and product['Variant_Barcode'] in query:
                strategy = 'barcode_first'
            elif 'site:' in query:
                strategy = 'retailer_specific'
            else:
                strategy = 'brand_title'
            
            self.patterns['search_strategies'][strategy]['success'] += 1
            self.patterns['search_strategies'][strategy]['total'] += 1
        
        # Track effective brand keywords
        brand = product.get('Brand', '').strip()
        if brand and product.get('confidence', 0) > 80:
            if brand not in self.patterns['brand_keywords']:
                self.patterns['brand_keywords'][brand] = []
            
            # Extract keywords from successful search
            keywords = query.lower().split()
            for keyword in keywords:
                if keyword not in ['site:', 'or', 'and', '"'] and \
                   keyword not in self.patterns['brand_keywords'][brand]:
                    self.patterns['brand_keywords'][brand].append(keyword)
        
        self.save_patterns()
        logger.info(f"Recorded approval for {product.get('Variant_SKU')}")
    
    def record_rejection(self, product: dict):
        """Record when a product image is rejected"""
        
        # Track problematic sources
        source = product.get('image_source', '').lower()
        if source:
            self.patterns['rejected_sources'][source] = \
                self.patterns['rejected_sources'].get(source, 0) + 1
        
        # Update strategy metrics
        query = product.get('search_query', '')
        if query:
            if product.get('Variant_Barcode') and product['Variant_Barcode'] in query:
                strategy = 'barcode_first'
            elif 'site:' in query:
                strategy = 'retailer_specific'
            else:
                strategy = 'brand_title'
            
            self.patterns['search_strategies'][strategy]['total'] += 1
        
        self.save_patterns()
        logger.info(f"Recorded rejection for {product.get('Variant_SKU')}")
    
    def get_best_retailers(self, limit: int = 5) -> List[str]:
        """Get the most successful retailers for searches"""
        
        retailers = self.patterns['successful_retailers']
        sorted_retailers = sorted(retailers.items(), key=lambda x: x[1], reverse=True)
        
        # Always include the top SA retailers
        best = ['checkers', 'shoprite', 'pnp', 'makro']
        
        # Add learned successful retailers
        for retailer, _ in sorted_retailers[:limit]:
            if retailer not in best:
                best.append(retailer)
        
        return best[:limit]
    
    def get_brand_keywords(self, brand: str) -> List[str]:
        """Get effective keywords for a specific brand"""
        
        brand_key = brand.strip()
        return self.patterns['brand_keywords'].get(brand_key, [])
    
    def should_auto_approve(self, confidence: float) -> bool:
        """Check if confidence is high enough for auto-approval"""
        
        # Adjust threshold based on learning
        success_rate = self.get_overall_success_rate()
        
        if success_rate > 0.8:  # High success rate, be more lenient
            threshold = self.patterns['confidence_thresholds']['auto_approve'] - 5
        elif success_rate < 0.5:  # Low success rate, be stricter
            threshold = self.patterns['confidence_thresholds']['auto_approve'] + 5
        else:
            threshold = self.patterns['confidence_thresholds']['auto_approve']
        
        return confidence >= threshold
    
    def should_auto_reject(self, confidence: float, source: str = None) -> bool:
        """Check if confidence is too low or source is problematic"""
        
        # Check if source is frequently rejected
        if source and source in self.patterns['rejected_sources']:
            rejection_count = self.patterns['rejected_sources'][source]
            if rejection_count > 5:  # Frequently rejected source
                return confidence < 60  # Higher threshold for problematic sources
        
        return confidence < self.patterns['confidence_thresholds']['auto_reject']
    
    def get_best_search_strategy(self) -> str:
        """Get the most successful search strategy"""
        
        strategies = self.patterns['search_strategies']
        best_strategy = 'barcode_first'  # Default
        best_rate = 0
        
        for strategy, stats in strategies.items():
            if stats['total'] > 0:
                success_rate = stats['success'] / stats['total']
                if success_rate > best_rate:
                    best_rate = success_rate
                    best_strategy = strategy
        
        logger.info(f"Best strategy: {best_strategy} (success rate: {best_rate:.2%})")
        return best_strategy
    
    def get_overall_success_rate(self) -> float:
        """Calculate overall system success rate"""
        
        total_success = sum(s['success'] for s in self.patterns['search_strategies'].values())
        total_attempts = sum(s['total'] for s in self.patterns['search_strategies'].values())
        
        if total_attempts == 0:
            return 0.5  # Default to 50% if no data
        
        return total_success / total_attempts
    
    def suggest_improvements(self) -> Dict[str, any]:
        """Suggest system improvements based on learning"""
        
        suggestions = {
            'best_retailers': self.get_best_retailers(),
            'best_strategy': self.get_best_search_strategy(),
            'success_rate': self.get_overall_success_rate(),
            'confidence_adjustments': {},
            'problematic_sources': []
        }
        
        # Suggest confidence threshold adjustments
        success_rate = self.get_overall_success_rate()
        if success_rate > 0.8:
            suggestions['confidence_adjustments']['auto_approve'] = \
                self.patterns['confidence_thresholds']['auto_approve'] - 5
            suggestions['confidence_adjustments']['message'] = \
                "High success rate - consider lowering auto-approve threshold"
        elif success_rate < 0.5:
            suggestions['confidence_adjustments']['auto_approve'] = \
                self.patterns['confidence_thresholds']['auto_approve'] + 5
            suggestions['confidence_adjustments']['message'] = \
                "Low success rate - consider raising auto-approve threshold"
        
        # Identify problematic sources
        for source, count in self.patterns['rejected_sources'].items():
            if count > 10:
                suggestions['problematic_sources'].append({
                    'source': source,
                    'rejections': count
                })
        
        return suggestions
    
    def update_confidence_model(self, features: dict) -> float:
        """
        Adjust confidence based on learned patterns
        
        Features should include:
        - base_confidence: Initial confidence score
        - retailer: Source retailer
        - has_barcode: Whether barcode was used in search
        - brand_match: Whether brand was matched
        """
        
        confidence = features.get('base_confidence', 50)
        
        # Boost for successful retailers
        retailer = features.get('retailer', '').lower()
        if retailer in self.patterns['successful_retailers']:
            success_count = self.patterns['successful_retailers'][retailer]
            if success_count > 10:
                confidence += 10
            elif success_count > 5:
                confidence += 5
        
        # Penalty for problematic sources
        source = features.get('source', '').lower()
        if source in self.patterns['rejected_sources']:
            rejection_count = self.patterns['rejected_sources'][source]
            if rejection_count > 10:
                confidence -= 15
            elif rejection_count > 5:
                confidence -= 10
        
        # Boost for successful search strategies
        if features.get('has_barcode'):
            barcode_success = self.patterns['search_strategies']['barcode_first']
            if barcode_success['total'] > 0:
                rate = barcode_success['success'] / barcode_success['total']
                if rate > 0.8:
                    confidence += 10
        
        # Ensure confidence stays in valid range
        return max(0, min(100, confidence))
    
    def export_insights(self) -> dict:
        """Export learning insights for reporting"""
        
        insights = {
            'learning_date': datetime.now().isoformat(),
            'total_patterns': len(self.patterns),
            'top_retailers': self.get_best_retailers(3),
            'overall_success_rate': f"{self.get_overall_success_rate():.1%}",
            'best_strategy': self.get_best_search_strategy(),
            'total_approvals': sum(s['success'] for s in self.patterns['search_strategies'].values()),
            'total_rejections': sum(self.patterns['rejected_sources'].values()),
            'brand_keywords_learned': len(self.patterns['brand_keywords']),
            'suggestions': self.suggest_improvements()
        }
        
        return insights
    
    def reset_learning(self):
        """Reset all learned patterns (use with caution)"""
        
        self.patterns = {
            'successful_retailers': {},
            'brand_keywords': {},
            'rejected_sources': {},
            'confidence_thresholds': {
                'auto_approve': 80,
                'auto_reject': 30
            },
            'search_strategies': {
                'barcode_first': {'success': 0, 'total': 0},
                'brand_title': {'success': 0, 'total': 0},
                'retailer_specific': {'success': 0, 'total': 0}
            }
        }
        self.save_patterns()
        logger.warning("Learning system has been reset")


class AdaptiveSearchOptimizer:
    """Optimizes search queries based on learning"""
    
    def __init__(self, learning_system: LearningSystem):
        self.learning = learning_system
    
    def optimize_query(self, product: dict, base_query: str) -> str:
        """Optimize search query based on learned patterns"""
        
        brand = product.get('Brand', '').strip()
        
        # Get brand-specific keywords
        brand_keywords = self.learning.get_brand_keywords(brand)
        
        # Get best retailers
        best_retailers = self.learning.get_best_retailers()
        
        # Build optimized query
        optimized = base_query
        
        # Add learned brand keywords
        if brand_keywords:
            keyword_str = ' '.join(brand_keywords[:3])  # Use top 3 keywords
            optimized = f"{optimized} {keyword_str}"
        
        # Focus on successful retailers
        if best_retailers and 'site:' not in base_query:
            sites = ' OR '.join([f"site:{r}.co.za" for r in best_retailers[:3]])
            optimized = f"{optimized} ({sites})"
        
        return optimized
    
    def score_result(self, result: dict, product: dict) -> float:
        """Score a search result based on learned patterns"""
        
        score = 50  # Base score
        
        # Check retailer
        source = result.get('source', '').lower()
        for retailer in self.learning.get_best_retailers():
            if retailer in source:
                score += 20
                break
        
        # Check for rejected sources
        if source in self.learning.patterns['rejected_sources']:
            rejection_count = self.learning.patterns['rejected_sources'][source]
            score -= min(30, rejection_count * 3)
        
        # Brand match
        brand = product.get('Brand', '').lower()
        if brand and brand in result.get('title', '').lower():
            score += 15
        
        # Title similarity
        product_title = product.get('Title', '').lower()
        result_title = result.get('title', '').lower()
        
        # Simple word overlap
        product_words = set(product_title.split())
        result_words = set(result_title.split())
        overlap = len(product_words & result_words)
        score += min(20, overlap * 5)
        
        return max(0, min(100, score))