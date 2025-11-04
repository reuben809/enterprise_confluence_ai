import os, time, requests, logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

def safe_request(session, url, tries=3, backoff=1.5):
    for i in range(tries):
        try:
            r = session.get(url, timeout=40)
            if r.status_code in (429,502,503,504):
                time.sleep(backoff*(i+1)); continue
            if r.ok: return r
        except requests.RequestException:
            time.sleep(backoff*(i+1))
    logging.error(f"Failed after {tries} tries: {url}")
    return None
