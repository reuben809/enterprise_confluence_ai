import os, re, time, html, logging
from datetime import datetime
from collections import deque
from bs4 import BeautifulSoup
from pymongo import MongoClient
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BASE = os.getenv("BASE_URL").rstrip("/")
SPACE = os.getenv("SPACE_KEY")
PAT = os.getenv("PAT")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

# MongoDB connection
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col = db["pages"]
col.create_index("page_id", unique=True)

# HTTP session
session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "Authorization": f"Bearer {PAT}"
})


# ---------- Helpers: robust request ----------

def safe_request(url, tries=4, backoff=1.5):
    """Resilient HTTP GET with retry/backoff"""
    for i in range(tries):
        try:
            r = session.get(url, timeout=40)
            if r.status_code in (429, 502, 503, 504):
                wait = backoff * (i + 1)
                logging.warning(f"{r.status_code} on {url}, retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            if r.ok:
                return r
        except requests.RequestException as e:
            logging.warning(f"Error {e}, retry {i + 1}")
            time.sleep(backoff * (i + 1))
    logging.error(f"❌ Failed to fetch {url}")
    return None


# ---------- NEW: Table-preserving extraction ----------

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
    - Preserves tables structurally (list of rows)
    - Uses lxml parser for speed
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
    """
    Convert blocks to readable text for embeddings.
    Tables become pipe-separated rows.
    """
    lines = []
    append = lines.append
    for b in blocks or []:
        typ = b.get("type")
        if typ in ("text", "header"):
            append(b.get("data", ""))
        elif typ == "table":
            append("\n".join(" | ".join(row) for row in b.get("data", [])))
    return "\n".join(lines).strip()


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


def crawl(max_pages: int = 2000):
    """Crawl Confluence → store table-aware blocks + clean text"""
    start_time = datetime.utcnow()
    home_id = get_homepage_id()
    queue = deque([home_id])
    seen = set()
    page_counter = 0

    logging.info(f"🌐 Starting crawl from homepage {home_id} in space {SPACE}")

    # while queue:
    #     pid = queue.popleft()
    #     if pid in seen:
    #         continue
    #     seen.add(pid)

    while queue and page_counter < max_pages:
        pid = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)
        page_counter += 1

        page_url = f"{BASE}/rest/api/content/{pid}?expand=body.storage,version"
        r = safe_request(page_url)
        if not r or not r.ok:
            continue

        j = r.json()
        title = j.get("title", f"Untitled-{pid}")
        body_html = j.get("body", {}).get("storage", {}).get("value", "")
        version = j.get("version", {}).get("number", 1)
        last_updated = j.get("version", {}).get("when")

        # NEW: table-aware blocks + clean text
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
            "content_html": body_html,
            "content_blocks": content_blocks,  # <— structured (tables preserved)
            "content_text": content_text,  # <— used for embeddings
            "synced_at": datetime.utcnow().isoformat()
        }

        col.update_one({"page_id": pid}, {"$set": page_doc}, upsert=True)
        logging.info(f"✅ Synced: {title}")

        # Enqueue children
        try:
            for ch in get_children(pid):
                if ch["id"] not in seen:
                    queue.append(ch["id"])
        except Exception as e:
            logging.warning(f"Child fetch failed for {pid}: {e}")

        # Follow hyperlinks inside body
        for l in extract_links(body_html):
            cid = url_to_id(l)
            if cid and cid not in seen:
                queue.append(cid)

        time.sleep(0.1)

    logging.info(f"🧭 Crawl complete. {len(seen)} pages processed.")
    logging.info(f"🕒 Started: {start_time} | Finished: {datetime.utcnow()}")


if __name__ == "__main__":
    crawl()