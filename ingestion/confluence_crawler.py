"""
Confluence Crawler with Checkpoint/Resume and Incremental Sync

Features:
- Checkpoint/Resume: Saves progress to file, can resume after crash
- Incremental Sync: Skips pages that haven't changed (based on version)
- Configurable: All parameters from settings.py
"""

import os
import re
import time
import json
import logging
from datetime import datetime
from collections import deque
from pathlib import Path
from bs4 import BeautifulSoup
from pymongo import MongoClient
import requests

from config.settings import settings

# Configuration from settings
BASE = (settings.base_url or "").rstrip("/")
SPACE = settings.space_key
PAT = settings.pat
MONGO_URI = settings.mongo_uri
MONGO_DB = settings.mongo_db

# Validate required settings
if not BASE or not SPACE:
    raise RuntimeError("BASE_URL and SPACE_KEY must be configured in the environment or .env file.")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# PAT is optional - if empty or "anonymous", will use public access
if not PAT:
    logger.warning("⚠️ PAT not provided - using anonymous access (only works for public Confluence)")

# MongoDB connection
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col = db["pages"]
col.create_index("page_id", unique=True)

# HTTP session - supports both authenticated and anonymous access
session = requests.Session()
if PAT and PAT.lower() != "anonymous":
    session.headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {PAT}"
    })
else:
    session.headers.update({"Accept": "application/json"})


# ---------- Checkpoint Management ----------

CHECKPOINT_FILE = Path(__file__).parent / ".crawl_checkpoint.json"


def save_checkpoint(seen: set, queue: list, page_counter: int):
    """Save crawl progress to checkpoint file."""
    checkpoint = {
        "seen": list(seen),
        "queue": list(queue),
        "page_counter": page_counter,
        "timestamp": datetime.utcnow().isoformat(),
        "space_key": SPACE
    }
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f)
    logger.debug(f"Checkpoint saved: {page_counter} pages processed")


def load_checkpoint() -> tuple[set, deque, int] | None:
    """Load checkpoint if exists and matches current space."""
    if not CHECKPOINT_FILE.exists():
        return None
    
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            checkpoint = json.load(f)
        
        # Only use checkpoint if same space
        if checkpoint.get("space_key") != SPACE:
            logger.info("Checkpoint is for different space, starting fresh")
            return None
        
        seen = set(checkpoint.get("seen", []))
        queue = deque(checkpoint.get("queue", []))
        page_counter = checkpoint.get("page_counter", 0)
        
        logger.info(f"📂 Resuming from checkpoint: {page_counter} pages already processed, {len(queue)} in queue")
        return seen, queue, page_counter
        
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Invalid checkpoint file, starting fresh: {e}")
        return None


def clear_checkpoint():
    """Remove checkpoint file after successful completion."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleared")


# ---------- Helpers: robust request ----------

def safe_request(url, tries=4, backoff=1.5):
    """Resilient HTTP GET with retry/backoff"""
    for i in range(tries):
        try:
            r = session.get(url, timeout=40)
            if r.status_code in (429, 502, 503, 504):
                wait = backoff * (i + 1)
                logger.warning(f"{r.status_code} on {url}, retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            if r.ok:
                return r
        except requests.RequestException as e:
            logger.warning(f"Error {e}, retry {i + 1}")
            time.sleep(backoff * (i + 1))
    logger.error(f"❌ Failed to fetch {url}")
    return None


# ---------- Table-preserving extraction ----------

def _html_table_to_json_fast(table_tag):
    """Extract table rows with minimal overhead."""
    rows = []
    for tr in table_tag.find_all("tr", recursive=False):
        cols = tr.find_all(["th", "td"], recursive=False)
        if cols:
            rows.append([c.get_text(" ", strip=True) for c in cols])
    return rows


def extract_content_with_tables_fast(html_str: str):
    """
    Returns a list of blocks: {"type": "text"|"header"|"table", "data": ...}
    """
    soup = BeautifulSoup(html_str or "", "lxml")
    for tag in soup(["style", "script"]):
        tag.decompose()

    body = soup.body or soup
    blocks = []

    for tag in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li", "span", "table"], recursive=True):
        name = tag.name
        if name == "table":
            data = _html_table_to_json_fast(tag)
            if data:
                blocks.append({"type": "table", "data": data})
        elif name[0] == "h":  # headers
            t = tag.get_text(" ", strip=True)
            if t:
                blocks.append({"type": "header", "data": t})
        else:
            t = tag.get_text(" ", strip=True)
            if t:
                blocks.append({"type": "text", "data": t})
    return blocks


def blocks_to_plaintext_for_embedding(blocks):
    """Convert blocks to readable text for embeddings with proper markdown tables."""
    lines = []
    for b in blocks or []:
        typ = b.get("type")
        if typ in ("text", "header"):
            lines.append(b.get("data", ""))
        elif typ == "table":
            table_data = b.get("data", [])
            if table_data:
                # Convert to proper markdown table format
                md_rows = []
                for i, row in enumerate(table_data):
                    # Escape pipe characters in cell content
                    escaped_row = [cell.replace("|", "\\|") for cell in row]
                    md_rows.append("| " + " | ".join(escaped_row) + " |")
                    
                    # Add separator after header row (first row)
                    if i == 0:
                        separator = "| " + " | ".join(["---"] * len(row)) + " |"
                        md_rows.append(separator)
                
                lines.append("\n".join(md_rows))
    return "\n\n".join(lines).strip()


# ---------- Links & IDs ----------

def extract_links(html_str):
    """Find internal Confluence page links"""
    soup = BeautifulSoup(html_str or "", "lxml")
    out = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            href = f"{BASE}{href}"
        if href.startswith(BASE) and ("pageId=" in href or "/pages/" in href):
            out.add(href)
    return out


def url_to_id(url):
    m = re.search(r"pageId=(\d+)", url) or re.search(r"/pages/(\d+)", url)
    return m.group(1) if m else None


# ---------- Core Crawl ----------

def get_homepage_id():
    """Find space homepage ID"""
    r = safe_request(f"{BASE}/rest/api/space/{SPACE}?expand=homepage")
    if not r or not r.ok:
        raise RuntimeError("Cannot fetch space homepage")
    return r.json()["homepage"]["id"]


def get_children(pid):
    """Get all child pages for given page ID"""
    nxt = f"{BASE}/rest/api/content/{pid}/child/page?limit=200"
    while nxt:
        r = safe_request(nxt)
        if not r or not r.ok:
            break
        data = r.json()
        for it in data.get("results", []):
            yield it
        nxt_link = data.get("_links", {}).get("next")
        nxt = f"{BASE}{nxt_link}" if nxt_link else None


def should_sync_page(pid: str, remote_version: int) -> bool:
    """
    Check if page needs syncing (incremental sync).
    Returns True if page is new or has been updated.
    """
    if not settings.enable_incremental_sync:
        return True  # Always sync if incremental disabled
    
    existing = col.find_one({"page_id": pid}, {"version": 1})
    if not existing:
        return True  # New page
    
    local_version = existing.get("version", 0)
    return remote_version > local_version


def crawl(max_pages: int = None, resume: bool = True):
    """
    Crawl Confluence → store table-aware blocks + clean text
    
    Args:
        max_pages: Maximum pages to crawl (default from settings)
        resume: Whether to resume from checkpoint if available
    """
    max_pages = max_pages or settings.max_pages_to_crawl
    crawl_delay = settings.crawl_delay_seconds
    
    start_time = datetime.utcnow()
    
    # Try to resume from checkpoint
    checkpoint_data = load_checkpoint() if resume else None
    
    if checkpoint_data:
        seen, queue, page_counter = checkpoint_data
    else:
        home_id = get_homepage_id()
        queue = deque([home_id])
        seen = set()
        page_counter = 0
        logger.info(f"🌐 Starting fresh crawl from homepage {home_id} in space {SPACE}")
    
    synced_count = 0
    skipped_count = 0
    
    try:
        while queue and page_counter < max_pages:
            pid = queue.popleft()
            if pid in seen:
                continue
            seen.add(pid)
            page_counter += 1

            # Enhanced API call with ancestors, labels, and history (for author)
            page_url = f"{BASE}/rest/api/content/{pid}?expand=body.storage,version,ancestors,metadata.labels,history"
            r = safe_request(page_url)
            if not r or not r.ok:
                continue

            j = r.json()
            title = j.get("title", f"Untitled-{pid}")
            version = j.get("version", {}).get("number", 1)
            
            # Incremental sync check
            if not should_sync_page(pid, version):
                skipped_count += 1
                logger.debug(f"⏭️ Skipped (unchanged): {title}")
                # Still need to process children even if page unchanged
                try:
                    for ch in get_children(pid):
                        if ch["id"] not in seen:
                            queue.append(ch["id"])
                except Exception:
                    pass
                continue
            
            body_html = j.get("body", {}).get("storage", {}).get("value", "")
            last_updated = j.get("version", {}).get("when")

            # Extract page hierarchy (ancestors)
            ancestors = j.get("ancestors", [])
            parent_page_id = ancestors[-1]["id"] if ancestors else None
            breadcrumb = [{"id": a["id"], "title": a["title"]} for a in ancestors]
            
            # Extract labels/tags
            labels_data = j.get("metadata", {}).get("labels", {}).get("results", [])
            labels = [lbl["name"] for lbl in labels_data]
            
            # Extract author info
            author = j.get("history", {}).get("createdBy", {}).get("displayName", "Unknown")
            author_email = j.get("history", {}).get("createdBy", {}).get("email")

            # Table-aware blocks + clean text
            content_blocks = extract_content_with_tables_fast(body_html)
            content_text = blocks_to_plaintext_for_embedding(content_blocks)

            page_doc = {
                "page_id": pid,
                "space_key": SPACE,
                "title": title,
                "status": "current",
                "url": f"{BASE}/spaces/{SPACE}/pages/{pid}/{title.replace(' ', '+')}",
                "last_updated": last_updated,
                "version": version,
                # NEW: Page hierarchy
                "parent_page_id": parent_page_id,
                "breadcrumb": breadcrumb,
                # NEW: Labels/tags
                "labels": labels,
                # NEW: Author info
                "author": author,
                "author_email": author_email,
                # Content
                "content_html": body_html,
                "content_blocks": content_blocks,
                "content_text": content_text,
                "synced_at": datetime.utcnow().isoformat()
            }

            col.update_one({"page_id": pid}, {"$set": page_doc}, upsert=True)
            synced_count += 1
            logger.info(f"✅ Synced: {title}")

            # Enqueue children
            try:
                for ch in get_children(pid):
                    if ch["id"] not in seen:
                        queue.append(ch["id"])
            except Exception as e:
                logger.warning(f"Child fetch failed for {pid}: {e}")

            # Follow hyperlinks inside body
            for l in extract_links(body_html):
                cid = url_to_id(l)
                if cid and cid not in seen:
                    queue.append(cid)

            time.sleep(crawl_delay)
            
            # Save checkpoint every 50 pages
            if page_counter % 50 == 0:
                save_checkpoint(seen, list(queue), page_counter)
    
    except KeyboardInterrupt:
        logger.info("\n⚠️ Crawl interrupted by user")
        save_checkpoint(seen, list(queue), page_counter)
        logger.info(f"💾 Progress saved. Resume with: python -m ingestion.confluence_crawler")
        raise
    
    # Clear checkpoint on successful completion
    clear_checkpoint()
    
    logger.info(f"🧭 Crawl complete!")
    logger.info(f"   📄 Pages processed: {page_counter}")
    logger.info(f"   ✅ Synced: {synced_count}")
    logger.info(f"   ⏭️ Skipped (unchanged): {skipped_count}")
    logger.info(f"🕒 Started: {start_time} | Finished: {datetime.utcnow()}")


if __name__ == "__main__":
    crawl()