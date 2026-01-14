"""
Query Processor for RAG System

This module preprocesses user queries to improve retrieval quality.
It handles common issues like typos, ambiguity, and query expansion.

Key Terminology:
- Query Cleaning: Removing noise, normalizing whitespace
- Spell Correction: Fixing common typos (e.g., "confleunce" -> "confluence")
- Query Expansion: Adding synonyms/related terms for better recall
- Intent Detection: Classifying query type (how-to, definition, comparison, etc.)

Usage:
    from utils.query_processor import QueryProcessor
    
    processor = QueryProcessor()
    result = processor.process("how to setup conflunce api?")
    # result.processed = "how to setup confluence api"
    # result.expanded = "how to setup confluence api REST"
    # result.intent = "procedural"
"""

import re
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Common technical term corrections for a Confluence/documentation context
# Format: misspelling -> correct spelling
SPELL_CORRECTIONS = {
    # Confluence-specific
    "confleunce": "confluence",
    "conflunce": "confluence",
    "confleuence": "confluence",
    "confuence": "confluence",
    "confulence": "confluence",
    
    # Common tech terms
    "authentification": "authentication",
    "authetication": "authentication",
    "athentication": "authentication",
    "authnetication": "authentication",
    "authorisation": "authorization",
    "authorazation": "authorization",
    "configration": "configuration",
    "configuraiton": "configuration",
    "configuraion": "configuration",
    "documnetation": "documentation",
    "documenation": "documentation",
    "documentaion": "documentation",
    "enviroment": "environment",
    "enviornment": "environment",
    "enviorment": "environment",
    "intergration": "integration",
    "integartion": "integration",
    "implmentation": "implementation",
    "implementaiton": "implementation",
    "respository": "repository",
    "repositroy": "repository",
    "repostitory": "repository",
    "permisson": "permission",
    "permisions": "permissions",
    "paramter": "parameter",
    "paramaters": "parameters",
    "databse": "database",
    "datbase": "database",
    "endpint": "endpoint",
    "endpoitn": "endpoint",
    "sever": "server",
    "servre": "server",
    "mangement": "management",
    "managment": "management",
    "deployement": "deployment",
    "deploment": "deployment",
    "instllation": "installation",
    "instalation": "installation",
    "accses": "access",
    "acess": "access",
    "acces": "access",
    "requst": "request",
    "requets": "request",
    "respone": "response",
    "reponse": "response",
    "serach": "search",
    "seach": "search",
    "qurey": "query",
    "qeury": "query",
    "scirpt": "script",
    "scrpt": "script",
}

# Synonym expansions for query enhancement
# Format: term -> list of related terms (will be added to query)
QUERY_EXPANSIONS = {
    "api": ["REST", "endpoint"],
    "auth": ["authentication", "login", "SSO"],
    "setup": ["configure", "install"],
    "install": ["setup", "configure"],
    "error": ["issue", "problem", "fix"],
    "fix": ["resolve", "solution"],
    "how to": ["guide", "steps"],
    "permission": ["access", "role"],
    "deploy": ["release", "publish"],
    "connect": ["integrate", "link"],
    "create": ["add", "new"],
    "delete": ["remove"],
    "update": ["edit", "modify"],
    "get": ["retrieve", "fetch"],
    "list": ["show", "display"],
}


@dataclass
class ProcessedQuery:
    """
    Result of query processing.
    
    Attributes:
        original: The original user query
        cleaned: Query after basic cleaning
        processed: Query after spell correction
        expanded: Query with added expansion terms
        intent: Detected query intent type
        corrections_made: List of spelling corrections applied
        expansions_added: List of expansion terms added
    """
    original: str
    cleaned: str
    processed: str
    expanded: str
    intent: str
    corrections_made: List[str] = field(default_factory=list)
    expansions_added: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "original": self.original,
            "cleaned": self.cleaned,
            "processed": self.processed,
            "expanded": self.expanded,
            "intent": self.intent,
            "corrections_made": self.corrections_made,
            "expansions_added": self.expansions_added
        }


class QueryProcessor:
    """
    Preprocesses user queries to improve retrieval quality.
    
    Features:
    - Basic cleaning (normalize whitespace, lowercase)
    - Spell correction using domain-specific dictionary
    - Query expansion with synonyms
    - Intent detection for specialized handling
    """
    
    def __init__(
        self,
        spell_corrections: Optional[Dict[str, str]] = None,
        query_expansions: Optional[Dict[str, List[str]]] = None,
        max_expansion_terms: int = 3
    ):
        """
        Initialize the query processor.
        
        Args:
            spell_corrections: Custom spelling corrections dictionary
            query_expansions: Custom query expansion dictionary
            max_expansion_terms: Maximum terms to add during expansion
        """
        self.spell_corrections = spell_corrections or SPELL_CORRECTIONS
        self.query_expansions = query_expansions or QUERY_EXPANSIONS
        self.max_expansion_terms = max_expansion_terms
        
        # Pre-compile patterns for efficiency
        self._whitespace_pattern = re.compile(r'\s+')
        self._special_chars_pattern = re.compile(r'[^\w\s\-\?\.\'"]', re.UNICODE)
    
    def _clean(self, query: str) -> str:
        """
        Basic query cleaning.
        
        - Strip leading/trailing whitespace
        - Normalize multiple spaces to single space
        - Convert to lowercase
        - Remove problematic special characters (keep ?, ., ', ")
        """
        cleaned = query.strip()
        cleaned = self._whitespace_pattern.sub(' ', cleaned)
        cleaned = cleaned.lower()
        # Remove special chars except common punctuation
        cleaned = self._special_chars_pattern.sub('', cleaned)
        return cleaned
    
    def _spell_correct(self, query: str) -> tuple[str, List[str]]:
        """
        Apply spelling corrections.
        
        Returns:
            Tuple of (corrected_query, list_of_corrections_made)
        """
        words = query.split()
        corrections = []
        corrected_words = []
        
        for word in words:
            word_lower = word.lower()
            if word_lower in self.spell_corrections:
                correction = self.spell_corrections[word_lower]
                corrected_words.append(correction)
                corrections.append(f"{word} -> {correction}")
                logger.info(f"Spell correction: '{word}' -> '{correction}'")
            else:
                corrected_words.append(word)
        
        return ' '.join(corrected_words), corrections
    
    def _expand_query(self, query: str) -> tuple[str, List[str]]:
        """
        Expand query with related terms.
        
        Returns:
            Tuple of (expanded_query, list_of_expansions_added)
        """
        words = set(query.lower().split())
        expansions_to_add: Set[str] = set()
        
        # Check for matching expansion triggers
        for trigger, expansions in self.query_expansions.items():
            trigger_words = set(trigger.lower().split())
            # If trigger is in query, add expansions
            if trigger_words.issubset(words):
                for exp in expansions:
                    # Don't add if already in query
                    if exp.lower() not in query.lower():
                        expansions_to_add.add(exp)
                        if len(expansions_to_add) >= self.max_expansion_terms:
                            break
        
        # Limit total expansions
        expansions_list = list(expansions_to_add)[:self.max_expansion_terms]
        
        if expansions_list:
            expanded = f"{query} {' '.join(expansions_list)}"
            logger.info(f"Query expanded with: {expansions_list}")
            return expanded, expansions_list
        
        return query, []
    
    def _detect_intent(self, query: str) -> str:
        """
        Detect the intent/type of the query.
        
        Intent types:
        - procedural: How-to questions
        - definitional: What is X?
        - explanatory: Why questions
        - comparison: X vs Y
        - troubleshooting: Error/fix related
        - navigational: Looking for specific page/resource
        - general: Default
        """
        query_lower = query.lower()
        
        # Check patterns in order of specificity
        if any(query_lower.startswith(p) for p in ["how to", "how do i", "how can i", "steps to"]):
            return "procedural"
        
        if any(query_lower.startswith(p) for p in ["what is", "what are", "define", "explain"]):
            return "definitional"
        
        if query_lower.startswith("why"):
            return "explanatory"
        
        if " vs " in query_lower or " versus " in query_lower or "compare" in query_lower:
            return "comparison"
        
        if any(word in query_lower for word in ["error", "issue", "problem", "fix", "bug", "failed", "not working"]):
            return "troubleshooting"
        
        if any(query_lower.startswith(p) for p in ["where is", "find", "locate", "link to"]):
            return "navigational"
        
        return "general"
    
    def process(self, query: str) -> ProcessedQuery:
        """
        Process a raw user query through the full pipeline.
        
        Pipeline:
        1. Clean (normalize)
        2. Spell correct
        3. Detect intent
        4. Expand with related terms
        
        Args:
            query: Raw user query string
        
        Returns:
            ProcessedQuery with all transformations
        """
        # Step 1: Clean
        cleaned = self._clean(query)
        
        # Step 2: Spell correct
        corrected, corrections = self._spell_correct(cleaned)
        
        # Step 3: Detect intent
        intent = self._detect_intent(corrected)
        
        # Step 4: Expand
        expanded, expansions = self._expand_query(corrected)
        
        result = ProcessedQuery(
            original=query,
            cleaned=cleaned,
            processed=corrected,
            expanded=expanded,
            intent=intent,
            corrections_made=corrections,
            expansions_added=expansions
        )
        
        logger.info(f"Query processed: '{query}' -> '{corrected}' (intent: {intent})")
        
        return result


# Singleton instance for convenience
query_processor = QueryProcessor()
