"""Bounded public resource discovery, not a training-data/license approval step."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from PIL import Image
import requests

from cad_evoloop.ledger.ledger import write_json_atomic

BASE = "https://xifengboke.com"
HOSTS = {"xifengboke.com", "image.xifengboke.com"}
USER_AGENT = "EvoCAD-Research-Discovery/0.1"
NOTICE = "Site states: learning/testing only, no commercial use, delete in 24 hours, original authors retain copyright. Not an open training-data license."


def allowed_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in HOSTS and
            parsed.port in (None, 443) and parsed.username is None and parsed.password is None)


def parse_index(html: bytes, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = {}
    for anchor in soup.select("h2 a[href], h3 a[href]"):
        href = urljoin(url, anchor["href"])
        match = re.fullmatch(r"/post/(\d+)\.html", urlsplit(href).path)
        if match and allowed_url(href):
            rows[match[1]] = {"post_id": match[1], "url": href,
                             "title": anchor.get_text(" ", strip=True), "index_url": url}
    return list(rows.values())


def section_role(heading: str) -> str:
    if any(term in heading for term in ("步骤", "教程", "过程")):
        return "solution_step_candidate"
    if any(term in heading for term in ("图纸", "尺寸")):
        return "input_drawing_candidate"
    if "效果" in heading:
        return "target_render_candidate"
    return "unclassified"


def parse_article(html: bytes, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.single-post")
    entry = article.select_one("div.entry") if article else None
    if not article or not entry or not article.find("h1"):
        raise ValueError("Article structure not recognized; manual review required")
    images, links, heading = [], [], ""
    for element in entry.find_all(["h2", "h3", "h4", "img", "a"]):
        if element.name.startswith("h"):
            heading = element.get_text(" ", strip=True)
        elif element.name == "img":
            source = element.get("data-src") or element.get("src", "")
            source = urljoin(url, source)
            if ("/zb_users/upload/" not in source or not allowed_url(source) or
                    Path(urlsplit(source).path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
                continue
            if source not in {row["url"] for row in images}:
                images.append({"url": source, "section": heading,
                               "role_hint": section_role(heading), "role_verified": False})
        elif element.name == "a" and element.get("href"):
            href = urljoin(url, element["href"])
            if urlsplit(href).scheme not in {"http", "https"}:
                continue
            label = element.get_text(" ", strip=True)
            if ("下载" in label or "hk_url=" in href or
                    urlsplit(href).hostname in {"pan.baidu.com", "pan.quark.cn", "www.123pan.com"}):
                links.append({"url": href, "label": label, "status": "not_followed"})
    text = entry.get_text(" ", strip=True)
    gated = "VIP用户" in text and "隐藏内容" in text
    return {"url": url, "post_id": re.search(r"/post/(\d+)\.html", url).group(1),
            "title": article.find("h1").get_text(" ", strip=True),
            "page_sha256": hashlib.sha256(html).hexdigest(),
            "images": images, "download_links": links,
            "has_gated_sections": gated,
            "source_file_access": ("mixed_public_links_and_gated_sections" if gated and links else
                                   "vip_or_login_required" if gated else
                                   "public_link_unverified" if links else "not_found"),
            "ground_truth_status": "no_cad_file_acquired_or_verified",
            "rights": {"status": "permission_required", "notice": NOTICE,
                       "training_eligible": False, "redistribution_eligible": False},
            "source_date_warning": "Index dates may be refreshed; not proof of original publication date."}


class Fetcher:
    def __init__(self, *, interval: float = 2.0, budget: int = 32 * 1024 * 1024):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.interval, self.budget = max(interval, 1.0), budget
        self.bytes = 0
        self.last_request = 0.0
        self.robots: dict[str, RobotFileParser] = {}
        self.audit: list[dict] = []

    def _get(self, url: str, max_bytes: int) -> tuple[int, bytes, str]:
        original_host = urlsplit(url).netloc
        for _ in range(4):
            if not allowed_url(url):
                raise ValueError("URL outside allowed public site hosts")
            host = urlsplit(url).netloc
            if host != original_host:
                raise ValueError("Cross-host redirect requires a separate robots-checked request")
            if host in self.robots and not self.robots[host].can_fetch(USER_AGENT, url):
                raise ValueError("robots.txt disallows this URL")
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            with self.session.get(url, timeout=(15, 30), stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    self.audit.append({"url": url, "status": response.status_code, "redirect": response.headers["Location"]})
                    url = urljoin(url, response.headers["Location"])
                    continue
                content = bytearray()
                for chunk in response.iter_content(65536):
                    self.bytes += len(chunk)
                    content.extend(chunk)
                    if len(content) > max_bytes or self.bytes > self.budget:
                        raise ValueError("Download byte budget exceeded")
                self.audit.append({"url": url, "status": response.status_code, "bytes": len(content),
                                   "sha256": hashlib.sha256(content).hexdigest()})
                return response.status_code, bytes(content), response.headers.get("Content-Type", "")
        raise ValueError("Redirect limit exceeded")

    def fetch(self, url: str, *, image: bool = False) -> bytes:
        if not allowed_url(url):
            raise ValueError("URL outside allowed public site hosts")
        host = urlsplit(url).netloc
        if host not in self.robots:
            status, body, _ = self._get(f"https://{host}/robots.txt", 1024 * 1024)
            parser = RobotFileParser()
            if status in (404, 410):
                parser.parse(["User-agent: *", "Disallow:"])
            elif status == 200:
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            else:
                raise ValueError(f"robots.txt unavailable ({status}); stopping")
            self.robots[host] = parser
            delay = parser.crawl_delay(USER_AGENT)
            if delay:
                self.interval = max(self.interval, delay)
        if not self.robots[host].can_fetch(USER_AGENT, url):
            raise ValueError("robots.txt disallows this URL")
        status, body, content_type = self._get(url, 8 * 1024 * 1024 if image else 2 * 1024 * 1024)
        if status != 200:
            raise ValueError(f"HTTP {status}; not retried")
        expected = "image/" if image else "text/html"
        if image and content_type.lower().split(";")[0] == "application/octet-stream":
            with Image.open(io.BytesIO(body)) as preview:
                preview.verify()
        elif not content_type.lower().startswith(expected):
            raise ValueError(f"Unexpected content type: {content_type}")
        return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages", type=int, nargs="+", default=[2, 3])
    parser.add_argument("--details", type=int, default=8)
    parser.add_argument("--extra-posts", nargs="*", default=["1936", "2679"])
    parser.add_argument("--sample-posts", nargs="+", default=[])
    parser.add_argument("--images-per-post", type=int, default=1)
    args = parser.parse_args()
    if not (1 <= len(args.pages) <= 5 and all(1 <= n <= 59 for n in args.pages)
            and 0 <= args.details <= 30 and 0 <= args.images_per_post <= 2
            and len(args.sample_posts) <= 5 and len(args.extra_posts) <= 10
            and all(re.fullmatch(r"\d+", n) for n in args.extra_posts + args.sample_posts)):
        parser.error("Discovery limits exceeded")
    output = args.output.resolve()
    output.relative_to(Path(__file__).resolve().parents[3])
    output.mkdir(parents=True, exist_ok=False)
    fetcher, index, articles, failures = Fetcher(), {}, [], []
    now = datetime.now(timezone.utc)
    for number in args.pages:
        url = f"{BASE}/category-8{'_' + str(number) if number > 1 else ''}.html"
        for row in parse_index(fetcher.fetch(url), url):
            index.setdefault(row["post_id"], row)
    detail_ids = list(dict.fromkeys(list(index)[:args.details] + args.extra_posts))
    write_json_atomic(output / "index.json", list(index.values()))
    def save_progress():
        write_json_atomic(output / "catalog.json", {"created_at": now.isoformat(), "articles": articles,
                          "failures": failures, "bytes_received": fetcher.bytes,
                          "policy": "Metadata discovery and small private inspection samples only; no gated retrieval or training import."})
        write_json_atomic(output / "fetch-audit.json", fetcher.audit)

    save_progress()
    for post_id in detail_ids:
        url = f"{BASE}/post/{post_id}.html"
        try:
            row = parse_article(fetcher.fetch(url), url)
            for item in row["images"][:args.images_per_post] if post_id in args.sample_posts else []:
                try:
                    body = fetcher.fetch(item["url"], image=True)
                    with Image.open(io.BytesIO(body)) as preview:
                        preview.verify()
                    with Image.open(io.BytesIO(body)) as preview:
                        dimensions, fmt = list(preview.size), preview.format
                    digest = hashlib.sha256(body).hexdigest()
                    suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(fmt)
                    if not suffix:
                        raise ValueError("Unsupported preview image format")
                    destination = output / "inspection-only" / (digest + suffix)
                    destination.parent.mkdir(exist_ok=True)
                    destination.write_bytes(body)
                    item.update({"local_preview": destination.relative_to(output).as_posix(), "sha256": digest,
                                 "dimensions": dimensions, "bytes": len(body),
                                 "inspection_expires_at": (now + timedelta(hours=24)).isoformat(),
                                 "retention_note": "Do not retain for training without permission; expiry is recorded, not automatically enforced."})
                except (ValueError, requests.RequestException, OSError) as error:
                    item["preview_error"] = str(error)
            articles.append(row)
        except (ValueError, requests.RequestException) as error:
            failures.append({"url": url, "error": str(error)})
        save_progress()
    print(json.dumps({"index_count": len(index), "articles_inspected": len(articles),
                      "failures": len(failures), "bytes_received": fetcher.bytes,
                      "downloaded_previews": sum("local_preview" in i for a in articles for i in a["images"]),
                      "verified_cad_ground_truths": 0, "output": str(output)}))


if __name__ == "__main__":
    main()
