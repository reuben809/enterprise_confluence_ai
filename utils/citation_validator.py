"""
Citation Verification Utility
Validates that LLM-generated citations actually exist in source documents
"""

import re
from typing import List, Dict, Tuple


class CitationValidator:
    """Validates citations in generated answers against source documents."""
    
    def __init__(self):
        self.citation_pattern = re.compile(r'\[([^\]]+)\]\(([^\)]+)\)')
    
    def verify(self, answer: str, sources: List[Dict]) -> Dict:
        """
        Verify all citations in answer exist in sources.
        
        Args:
            answer: Generated answer with markdown citations
            sources: List of source documents with 'title' and 'url'
        
        Returns:
            {
                "valid_citations": int,
                "invalid_citations": int,
                "hallucinated": list of invalid citations,
                "citation_accuracy": float (0-1),
                "verified_answer": str (answer with warnings on invalid citations)
            }
        """
        # Extract citations from answer
        citations = self.citation_pattern.findall(answer)
        
        # Build source lookup
        source_urls = {s["url"].rstrip('/') for s in sources}
        source_titles = {s["title"].lower().strip() for s in sources}
        
        valid = []
        invalid = []
        
        for title, url in citations:
            url_normalized = url.rstrip('/')
            title_normalized = title.lower().strip()
            
            # Check if URL exists in sources
            if url_normalized in source_urls:
                valid.append((title, url))
            # Check if title matches (case-insensitive)
            elif title_normalized in source_titles:
                valid.append((title, url))
            else:
                invalid.append((title, url))
        
        # Calculate accuracy
        total_citations = len(citations)
        accuracy = len(valid) / total_citations if total_citations > 0 else 1.0
        
        # Mark invalid citations in answer
        verified_answer = self._mark_invalid_citations(answer, invalid)
        
        return {
            "valid_citations": len(valid),
            "invalid_citations": len(invalid),
            "hallucinated": [{"title": t, "url": u} for t, u in invalid],
            "citation_accuracy": accuracy,
            "verified_answer": verified_answer,
            "needs_regeneration": accuracy < 0.8  # Flag if < 80% accurate
        }
    
    def _mark_invalid_citations(self, answer: str, invalid: List[Tuple[str, str]]) -> str:
        """Add warning markers to invalid citations."""
        verified = answer
        for title, url in invalid:
            # Replace invalid citation with warning
            pattern = re.escape(f"[{title}]({url})")
            replacement = f"[{title}]({url}) ⚠️ *[Citation not verified]*"
            verified = re.sub(pattern, replacement, verified)
        return verified
    
    def extract_cited_sources(self, answer: str, sources: List[Dict]) -> List[Dict]:
        """
        Extract only the sources that were actually cited in the answer.
        Useful for showing "Sources Used" vs "Sources Retrieved"
        """
        citations = self.citation_pattern.findall(answer)
        cited_urls = {url.rstrip('/') for _, url in citations}
        
        cited_sources = [
            s for s in sources 
            if s["url"].rstrip('/') in cited_urls
        ]
        
        return cited_sources
    
    def suggest_missing_citations(self, answer: str, sources: List[Dict]) -> List[str]:
        """
        Identify sentences in answer that lack citations.
        Returns list of sentences that should probably have citations.
        """
        # Split answer into sentences
        sentences = re.split(r'(?<=[.!?])\s+', answer)
        
        missing_citations = []
        for sentence in sentences:
            # Skip if sentence already has citation
            if self.citation_pattern.search(sentence):
                continue
            
            # Skip if it's a meta-statement (intro, conclusion, etc.)
            if any(phrase in sentence.lower() for phrase in [
                "based on", "according to", "in summary", "to answer",
                "here's", "let me", "i found", "the sources"
            ]):
                continue
            
            # If sentence makes a factual claim, it should have citation
            if len(sentence.split()) > 5:  # Substantial sentence
                missing_citations.append(sentence.strip())
        
        return missing_citations


# Example usage
if __name__ == "__main__":
    validator = CitationValidator()
    
    # Test case
    answer = """
    The deployment process requires VPN access [DevOps Guide](https://wiki.company.com/devops).
    You should also check the security policy [Security Docs](https://wiki.company.com/security).
    The database credentials are stored in Vault [Vault Guide](https://fake.url/vault).
    """
    
    sources = [
        {"title": "DevOps Guide", "url": "https://wiki.company.com/devops"},
        {"title": "Security Docs", "url": "https://wiki.company.com/security"}
    ]
    
    result = validator.verify(answer, sources)
    
    print("Verification Results:")
    print(f"  Valid: {result['valid_citations']}")
    print(f"  Invalid: {result['invalid_citations']}")
    print(f"  Accuracy: {result['citation_accuracy']:.1%}")
    print(f"  Hallucinated: {result['hallucinated']}")
    print(f"\nVerified Answer:\n{result['verified_answer']}")
