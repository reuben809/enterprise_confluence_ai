import os, re, time, html, logging
from datetime import datetime
from collections import deque
from bs4 import BeautifulSoup
from pymongo import MongoClient, UpdateOne
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


# ---------- Helper Functions ----------

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
            logging.warning(f"Error {e}, retry {i+1}")
            time.sleep(backoff * (i + 1))
    logging.error(f"❌ Failed to fetch {url}")
    return None


def html_to_text(h):
    soup = BeautifulSoup(h or "", "html.parser")
    for tag in soup(["style", "script"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return html.unescape(re.sub(r"\n{2,}", "\n", text.strip()))


def extract_links(html_str):
    """Find internal Confluence page links"""
    soup = BeautifulSoup(html_str or "", "html.parser")
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


def crawl():
    """Main robust Confluence crawler with MongoDB upsert"""
    start_time = datetime.utcnow()
    home_id = get_homepage_id()
    queue = deque([home_id])
    seen = set()
    ops = []

    logging.info(f"🌐 Starting crawl from homepage {home_id} in space {SPACE}")

    while queue:
        pid = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)

        page_url = f"{BASE}/rest/api/content/{pid}?expand=body.storage,version"
        r = safe_request(page_url)
        if not r or not r.ok:
            continue

        j = r.json()
        title = j.get("title", f"Untitled-{pid}")
        body_html = j.get("body", {}).get("storage", {}).get("value", "")
        content_text = html_to_text(body_html)
        version = j.get("version", {}).get("number", 1)
        last_updated = j.get("version", {}).get("when")

        page_doc = {
            "page_id": pid,
            "space_key": SPACE,
            "title": title,
            "status": "current",
            "url": f"{BASE}/spaces/{SPACE}/pages/{pid}/{title.replace(' ', '+')}",
            "last_updated": last_updated,
            "version": version,
            "content_html": body_html,
            "content_text": content_text,
            "synced_at": datetime.utcnow().isoformat()
        }

        # Upsert: if newer version or missing
        col.update_one(
            {"page_id": pid},
            {"$set": page_doc},
            upsert=True
        )
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

        time.sleep(0.25)

    logging.info(f"🧭 Crawl complete. {len(seen)} pages processed.")
    logging.info(f"🕒 Started: {start_time} | Finished: {datetime.utcnow()}")


if __name__ == "__main__":
    crawl()
