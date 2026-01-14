"""
Citation Validator for RAG Responses

This module verifies that citations in LLM-generated answers actually correspond
to the source documents that were provided as context.

Key Terminology:
- Citation: A reference to a source document in the answer (e.g., [Title](URL))
- Hallucinated Citation: A citation that doesn't match any provided source
- Citation Accuracy: Percentage of citations that are valid

Usage:
    from utils.citation_validator import CitationValidator
    
    validator = CitationValidator()
    result = validator.verify(answer_text, sources_list)
"""

import re
import logging
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CitationVerificationResult:
    """
    Result of citation verification.
    
    Attributes:
        valid_citations: List of citations that match provided sources
        invalid_citations: List of citations that don't match (hallucinated)
        total_citations: Total number of citations found in the answer
        citation_accuracy: Ratio of valid to total citations (0.0 to 1.0)
        sources_used: Set of source titles that were actually cited
        sources_not_cited: Set of source titles that were provided but not cited
    """
    valid_citations: List[str]
    invalid_citations: List[str]
    total_citations: int
    citation_accuracy: float
    sources_used: Set[str]
    sources_not_cited: Set[str]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "valid_citations": self.valid_citations,
            "invalid_citations": self.invalid_citations,
            "total_citations": self.total_citations,
            "citation_accuracy": round(self.citation_accuracy, 3),
            "sources_used": list(self.sources_used),
            "sources_not_cited": list(self.sources_not_cited),
            "has_hallucinations": len(self.invalid_citations) > 0
        }


class CitationValidator:
    """
    Validates that citations in LLM responses match the provided sources.
    
    This helps detect hallucinated citations where the LLM invents or 
    misattributes sources that weren't actually in the context.
    """
    
    # Pattern to match markdown links: [Title](URL)
    MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    
    # Pattern to match plain URL references
    URL_PATTERN = re.compile(r'https?://[^\s\)]+')
    
    # Pattern to match bracket references like [Title] without URL
    BRACKET_REF_PATTERN = re.compile(r'\[([^\]]+)\](?!\()')
    
    def __init__(self, fuzzy_threshold: float = 0.8):
        """
        Initialize the citation validator.
        
        Args:
            fuzzy_threshold: Similarity threshold for fuzzy title matching (0-1)
        """
        self.fuzzy_threshold = fuzzy_threshold
    
    def _normalize_title(self, title: str) -> str:
        """Normalize a title for comparison (lowercase, strip whitespace)."""
        return title.lower().strip()
    
    def _normalize_url(self, url: str) -> str:
        """Normalize a URL for comparison (remove trailing slashes, lowercase)."""
        url = url.lower().strip()
        # Remove trailing slashes
        while url.endswith('/'):
            url = url[:-1]
        # Remove query parameters for comparison
        if '?' in url:
            url = url.split('?')[0]
        return url
    
    def _extract_citations(self, text: str) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
        """
        Extract all citations from the text.
        
        Returns:
            Tuple of (markdown_links, plain_urls, bracket_refs)
            - markdown_links: List of (title, url) tuples
            - plain_urls: List of standalone URLs
            - bracket_refs: List of [Title] references without URLs
        """
        # Find markdown links [Title](URL)
        markdown_links = self.MARKDOWN_LINK_PATTERN.findall(text)
        
        # Find plain URLs (excluding those already in markdown links)
        all_urls = self.URL_PATTERN.findall(text)
        markdown_urls = {url for _, url in markdown_links}
        plain_urls = [url for url in all_urls if url not in markdown_urls]
        
        # Find bracket references [Title] without URLs
        bracket_refs = self.BRACKET_REF_PATTERN.findall(text)
        # Filter out bracket refs that are part of markdown links
        markdown_titles = {title for title, _ in markdown_links}
        bracket_refs = [ref for ref in bracket_refs if ref not in markdown_titles]
        
        return markdown_links, plain_urls, bracket_refs
    
    def _build_source_index(self, sources: List[dict]) -> Tuple[Dict[str, str], Set[str]]:
        """
        Build lookup indexes from source documents.
        
        Returns:
            Tuple of (url_to_title, normalized_titles)
        """
        url_to_title = {}
        normalized_titles = set()
        
        for source in sources:
            title = source.get("title", "")
            url = source.get("url", "")
            
            if title:
                normalized_titles.add(self._normalize_title(title))
            if url:
                url_to_title[self._normalize_url(url)] = title
        
        return url_to_title, normalized_titles
    
    def verify(self, answer: str, sources: List[dict]) -> CitationVerificationResult:
        """
        Verify all citations in an answer against provided sources.
        
        Args:
            answer: The LLM-generated answer text
            sources: List of source documents with 'title' and 'url' keys
        
        Returns:
            CitationVerificationResult with validation details
        """
        # Extract citations from the answer
        markdown_links, plain_urls, bracket_refs = self._extract_citations(answer)
        
        # Build source indexes
        url_to_title, normalized_titles = self._build_source_index(sources)
        
        valid_citations = []
        invalid_citations = []
        sources_used = set()
        
        # Validate markdown links [Title](URL)
        for title, url in markdown_links:
            norm_url = self._normalize_url(url)
            norm_title = self._normalize_title(title)
            
            citation_str = f"[{title}]({url})"
            
            # Check if URL matches a source
            if norm_url in url_to_title:
                valid_citations.append(citation_str)
                sources_used.add(url_to_title[norm_url])
            # Check if title matches a source
            elif norm_title in normalized_titles:
                valid_citations.append(citation_str)
                sources_used.add(title)
            else:
                invalid_citations.append(citation_str)
                logger.warning(f"Hallucinated citation detected: {citation_str}")
        
        # Validate plain URLs
        for url in plain_urls:
            norm_url = self._normalize_url(url)
            if norm_url in url_to_title:
                valid_citations.append(url)
                sources_used.add(url_to_title[norm_url])
            else:
                invalid_citations.append(url)
                logger.warning(f"Hallucinated URL detected: {url}")
        
        # Validate bracket references [Title]
        for ref in bracket_refs:
            norm_ref = self._normalize_title(ref)
            if norm_ref in normalized_titles:
                valid_citations.append(f"[{ref}]")
                sources_used.add(ref)
            # Don't mark as invalid - could be formatting, not a citation
        
        # Calculate metrics
        total_citations = len(valid_citations) + len(invalid_citations)
        citation_accuracy = len(valid_citations) / total_citations if total_citations > 0 else 1.0
        
        # Find sources that weren't cited
        all_source_titles = {s.get("title", "") for s in sources}
        sources_not_cited = all_source_titles - sources_used
        
        return CitationVerificationResult(
            valid_citations=valid_citations,
            invalid_citations=invalid_citations,
            total_citations=total_citations,
            citation_accuracy=citation_accuracy,
            sources_used=sources_used,
            sources_not_cited=sources_not_cited
        )
    
    def filter_hallucinations(self, answer: str, sources: List[dict]) -> str:
        """
        Remove or flag hallucinated citations from an answer.
        
        Args:
            answer: The LLM-generated answer text
            sources: List of source documents
        
        Returns:
            Answer with hallucinated citations marked with ⚠️
        """
        result = self.verify(answer, sources)
        
        filtered_answer = answer
        for invalid in result.invalid_citations:
            # Mark invalid citations with a warning
            filtered_answer = filtered_answer.replace(
                invalid, 
                f"{invalid} ⚠️"
            )
        
        return filtered_answer


# Singleton instance for convenience
citation_validator = CitationValidator()
