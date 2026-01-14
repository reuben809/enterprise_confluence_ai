"""
Simple Query Preprocessing for POC
Handles basic query improvements without heavy dependencies
"""

import re
from typing import List, Dict


class QueryProcessor:
    """Lightweight query preprocessing for POC."""
    
    def __init__(self):
        # Common acronyms in your domain (customize these)
        self.acronyms = {
            "vpn": "virtual private network",
            "api": "application programming interface",
            "db": "database",
            "prod": "production",
            "dev": "development",
            "qa": "quality assurance",
            "ci": "continuous integration",
            "cd": "continuous deployment",
            "k8s": "kubernetes",
            "aws": "amazon web services",
        }
        
        # Common synonyms
        self.synonyms = {
            "deploy": ["deployment", "release", "push"],
            "setup": ["configure", "install", "initialize"],
            "error": ["issue", "problem", "bug"],
            "guide": ["documentation", "tutorial", "how-to"],
        }
    
    def process(self, query: str) -> Dict[str, str]:
        """
        Process query with basic improvements.
        
        Returns:
            {
                "original": original query,
                "processed": improved query,
                "expanded": query with synonyms
            }
        """
        # 1. Clean query
        cleaned = self._clean_query(query)
        
        # 2. Expand acronyms
        expanded_acronyms = self._expand_acronyms(cleaned)
        
        # 3. Add synonyms for better retrieval
        with_synonyms = self._add_synonyms(expanded_acronyms)
        
        return {
            "original": query,
            "processed": expanded_acronyms,
            "expanded": with_synonyms
        }
    
    def _clean_query(self, query: str) -> str:
        """Basic cleaning: lowercase, remove extra spaces."""
        query = query.lower().strip()
        query = re.sub(r'\s+', ' ', query)  # Remove extra spaces
        return query
    
    def _expand_acronyms(self, query: str) -> str:
        """Expand known acronyms."""
        words = query.split()
        expanded = []
        
        for word in words:
            # Remove punctuation for matching
            clean_word = re.sub(r'[^\w\s]', '', word)
            
            if clean_word in self.acronyms:
                # Add both acronym and expansion
                expanded.append(f"{word} ({self.acronyms[clean_word]})")
            else:
                expanded.append(word)
        
        return ' '.join(expanded)
    
    def _add_synonyms(self, query: str) -> str:
        """Add synonyms to improve retrieval."""
        words = query.split()
        expanded = [query]  # Start with original
        
        for word in words:
            clean_word = re.sub(r'[^\w\s]', '', word)
            if clean_word in self.synonyms:
                # Add synonym variants
                for syn in self.synonyms[clean_word][:2]:  # Limit to 2 synonyms
                    expanded.append(syn)
        
        return ' '.join(expanded)
    
    def extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords (simple version)."""
        # Remove common stop words
        stop_words = {'how', 'what', 'where', 'when', 'why', 'is', 'are', 'the', 'a', 'an', 'to', 'do', 'i'}
        
        words = query.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        return keywords


# Example usage
if __name__ == "__main__":
    processor = QueryProcessor()
    
    test_queries = [
        "How do I setup VPN?",
        "What's the prod deployment process?",
        "API authentication guide",
        "Fix DB connection error"
    ]
    
    for q in test_queries:
        result = processor.process(q)
        print(f"\nOriginal: {result['original']}")
        print(f"Processed: {result['processed']}")
        print(f"Expanded: {result['expanded']}")
