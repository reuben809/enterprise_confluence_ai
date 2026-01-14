"""
Text Cleaner and Chunker for RAG System

This module provides intelligent text chunking that:
- Preserves semantic boundaries (sentences, paragraphs)
- Keeps tables intact as unified chunks
- Validates chunk quality
- Supports hierarchical parent/child chunking

Key Terminology:
- Semantic Chunking: Splitting at natural language boundaries (sentences, paragraphs)
- Hierarchical Chunking: Parent chunks for context, child chunks for retrieval
- Table Preservation: Detecting and keeping structured data intact
- Chunk Quality: Measuring completeness, coherence, and usefulness

Usage:
    from ingestion.text_cleaner import hierarchical_chunks, validate_chunk_quality
    
    for chunk in hierarchical_chunks(text):
        print(chunk["child_text"])
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Iterator, List, Tuple
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


# Patterns for detecting special content
TABLE_PATTERN = re.compile(r'(\|[^\n]+\|\n?)+', re.MULTILINE)
HEADER_PATTERN = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
CODE_BLOCK_PATTERN = re.compile(r'```[\s\S]*?```', re.MULTILINE)
SENTENCE_END_PATTERN = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')


@dataclass
class ChunkQualityScore:
    """
    Quality metrics for a text chunk.
    
    Attributes:
        is_complete: True if chunk ends at a sentence boundary
        has_context: True if chunk has enough words to be meaningful
        is_coherent: True if chunk doesn't split a table or code block
        word_count: Number of words in the chunk
        score: Overall quality score (0-100)
    """
    is_complete: bool
    has_context: bool
    is_coherent: bool
    word_count: int
    score: int
    issues: List[str]


def detect_tables(text: str) -> List[Tuple[int, int, str]]:
    """
    Detect table regions in text.
    
    Returns:
        List of (start_pos, end_pos, table_content) tuples
    """
    tables = []
    for match in TABLE_PATTERN.finditer(text):
        tables.append((match.start(), match.end(), match.group()))
    return tables


def detect_code_blocks(text: str) -> List[Tuple[int, int, str]]:
    """
    Detect code block regions in text.
    
    Returns:
        List of (start_pos, end_pos, code_content) tuples
    """
    blocks = []
    for match in CODE_BLOCK_PATTERN.finditer(text):
        blocks.append((match.start(), match.end(), match.group()))
    return blocks


def is_position_in_special_region(
    pos: int, 
    special_regions: List[Tuple[int, int, str]]
) -> bool:
    """Check if a position falls within any special region."""
    for start, end, _ in special_regions:
        if start <= pos <= end:
            return True
    return False


def extract_special_content(text: str) -> Tuple[str, List[Dict]]:
    """
    Extract tables and code blocks, replacing with placeholders.
    
    Returns:
        Tuple of (text_with_placeholders, list_of_extracted_content)
    """
    extracted = []
    result_text = text
    
    # Extract tables
    for i, (start, end, content) in enumerate(detect_tables(text)):
        placeholder = f"__TABLE_{i}__"
        extracted.append({
            "type": "table",
            "placeholder": placeholder,
            "content": content,
            "original_start": start
        })
    
    # Replace in reverse order to preserve positions
    for item in reversed(extracted):
        result_text = result_text.replace(item["content"], item["placeholder"], 1)
    
    return result_text, extracted


def restore_special_content(text: str, extracted: List[Dict]) -> str:
    """Restore extracted special content from placeholders."""
    result = text
    for item in extracted:
        result = result.replace(item["placeholder"], item["content"])
    return result


def validate_chunk_quality(chunk: str, min_words: int = 5) -> ChunkQualityScore:
    """
    Validate the quality of a text chunk.
    
    Args:
        chunk: The text chunk to validate
        min_words: Minimum words for the chunk to be considered meaningful
    
    Returns:
        ChunkQualityScore with detailed metrics
    """
    issues = []
    
    # Check word count
    words = chunk.split()
    word_count = len(words)
    has_context = word_count >= min_words
    if not has_context:
        issues.append(f"Too short ({word_count} words, min {min_words})")
    
    # Check sentence completeness
    stripped = chunk.strip()
    is_complete = (
        len(stripped) == 0 or  # Empty is "complete"
        stripped[-1] in '.!?:' or  # Ends with punctuation
        stripped.endswith('```') or  # Code block
        '|' in stripped  # Table (ends with pipe)
    )
    if not is_complete:
        issues.append("Ends mid-sentence")
    
    # Check for broken tables (odd number of pipes per line suggests split)
    is_coherent = True
    lines = chunk.split('\n')
    for line in lines:
        pipe_count = line.count('|')
        if pipe_count > 0 and pipe_count < 2:
            is_coherent = False
            issues.append("Contains broken table row")
            break
    
    # Check for broken code blocks
    if chunk.count('```') % 2 != 0:
        is_coherent = False
        issues.append("Contains incomplete code block")
    
    # Calculate overall score
    score = 100
    if not is_complete:
        score -= 30
    if not has_context:
        score -= 40
    if not is_coherent:
        score -= 30
    score = max(0, score)
    
    return ChunkQualityScore(
        is_complete=is_complete,
        has_context=has_context,
        is_coherent=is_coherent,
        word_count=word_count,
        score=score,
        issues=issues
    )


def smart_sentence_split(text: str, max_chunk_size: int = 500) -> List[str]:
    """
    Split text at sentence boundaries.
    
    This creates chunks that are complete sentences, never splitting mid-sentence.
    
    Args:
        text: Text to split
        max_chunk_size: Maximum chunk size in characters
    
    Returns:
        List of chunks, each ending at a sentence boundary
    """
    # Split into sentences
    sentences = SENTENCE_END_PATTERN.split(text)
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        sentence_size = len(sentence)
        
        # If single sentence is too big, use character splitting
        if sentence_size > max_chunk_size:
            if current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = []
                current_size = 0
            # Split long sentence at word boundaries
            words = sentence.split()
            word_chunk = []
            word_size = 0
            for word in words:
                if word_size + len(word) + 1 > max_chunk_size and word_chunk:
                    chunks.append(' '.join(word_chunk))
                    word_chunk = [word]
                    word_size = len(word)
                else:
                    word_chunk.append(word)
                    word_size += len(word) + 1
            if word_chunk:
                chunks.append(' '.join(word_chunk))
            continue
        
        # Check if adding this sentence exceeds limit
        if current_size + sentence_size + 1 > max_chunk_size and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [sentence]
            current_size = sentence_size
        else:
            current_chunk.append(sentence)
            current_size += sentence_size + 1
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks


def hierarchical_chunks(
    text: str,
    parent_chunk_size: int = 1400,
    child_chunk_size: int = 400,
    parent_overlap: int = 200,
    child_overlap: int = 80,
    preserve_tables: bool = True,
    validate_quality: bool = True,
) -> Iterator[Dict[str, str | int]]:
    """
    Yield parent/child chunks that preserve semantic boundaries.

    IMPROVED VERSION:
    - Preserves tables as intact chunks
    - Splits at sentence boundaries when possible
    - Includes quality validation metadata
    
    Parent chunks retain larger spans for context while children are optimized for retrieval.
    
    Args:
        text: The text to chunk
        parent_chunk_size: Maximum parent chunk size
        child_chunk_size: Maximum child chunk size
        parent_overlap: Overlap between parent chunks
        child_overlap: Overlap between child chunks
        preserve_tables: If True, keep tables intact
        validate_quality: If True, include quality scores in output
    
    Yields:
        Dict with parent_index, child_index, parent_text, child_text, and optionally quality_score
    """
    if not text or not text.strip():
        return
    
    # Step 1: Extract tables if preservation is enabled
    text_to_split = text
    extracted_content = []
    
    if preserve_tables:
        text_to_split, extracted_content = extract_special_content(text)
    
    # Step 2: Set up splitters with sentence-aware separators
    # Order matters: try paragraph first, then newline, then sentence, then space
    separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]
    
    parent_splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=parent_chunk_size,
        chunk_overlap=parent_overlap,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=child_chunk_size,
        chunk_overlap=child_overlap,
    )

    # Step 3: Split into parent chunks
    parents = parent_splitter.split_text(text_to_split)
    
    for parent_idx, parent_text in enumerate(parents):
        # Restore any extracted content in parent
        if extracted_content:
            parent_text = restore_special_content(parent_text, extracted_content)
        
        # Check if parent contains a table/code block that shouldn't be split
        parent_tables = detect_tables(parent_text)
        parent_code = detect_code_blocks(parent_text)
        
        # If parent IS a table or mostly a table, yield as single child
        if parent_tables and sum(len(t[2]) for t in parent_tables) > len(parent_text) * 0.5:
            chunk_data = {
                "parent_index": parent_idx,
                "child_index": 0,
                "parent_text": parent_text.strip(),
                "child_text": parent_text.strip(),
                "content_type": "table",
            }
            if validate_quality:
                quality = validate_chunk_quality(parent_text.strip())
                chunk_data["quality_score"] = quality.score
                chunk_data["quality_issues"] = quality.issues
            yield chunk_data
            continue
        
        # Step 4: Split parent into children
        children = child_splitter.split_text(parent_text)
        
        for child_idx, child_text in enumerate(children):
            child_text = child_text.strip()
            
            chunk_data = {
                "parent_index": parent_idx,
                "child_index": child_idx,
                "parent_text": parent_text.strip(),
                "child_text": child_text,
                "content_type": "text",
            }
            
            # Add quality validation if enabled
            if validate_quality:
                quality = validate_chunk_quality(child_text)
                chunk_data["quality_score"] = quality.score
                chunk_data["quality_issues"] = quality.issues
            
            yield chunk_data


# Keep original function signature for backward compatibility
def hierarchical_chunks_simple(
    text: str,
    parent_chunk_size: int = 1400,
    child_chunk_size: int = 400,
    parent_overlap: int = 200,
    child_overlap: int = 80,
) -> Iterator[Dict[str, str | int]]:
    """
    Original simple hierarchical chunking (for backward compatibility).
    
    Use hierarchical_chunks() for improved chunking with table preservation.
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=parent_chunk_size,
        chunk_overlap=parent_overlap,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=child_chunk_size,
        chunk_overlap=child_overlap,
    )

    parents = parent_splitter.split_text(text or "")
    for parent_idx, parent_text in enumerate(parents):
        children = child_splitter.split_text(parent_text)
        for child_idx, child_text in enumerate(children):
            yield {
                "parent_index": parent_idx,
                "child_index": child_idx,
                "parent_text": parent_text.strip(),
                "child_text": child_text.strip(),
            }
