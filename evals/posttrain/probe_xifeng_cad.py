"""Inspect public CAD resource claims and anonymous Quark file listings.

No account login, share saving, archive extraction, or training import.
"""

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cad_evoloop.ledger.ledger import write_json_atomic
from cad_evoloop.posttrain.web_discovery import BASE, Fetcher, parse_article

POSTS = ["2300", "2301", "2302", "2304", "2305", "2306", "2312",
         "2315", "2316", "2318", "2292", "2574"]
API = "https://drive-h.quark.cn/1/clouddrive/share/sharepage/"
PARAMS = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}


def public_target(url):
    try:
        encoded = parse_qs(urlsplit(url).query).get("hk_url")
        if encoded:
            url = base64.b64decode(encoded[0], validate=True).decode("utf-8")
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname in {"pan.baidu.com", "pan.quark.cn"}
                and parts.port in (None, 443) and not parts.username and not parts.password):
            return url
    except (ValueError, UnicodeError):
        pass
    return None


def advertised_claims(html):
    entry = BeautifulSoup(html, "html.parser").select_one("article.single-post div.entry")
    paragraphs = [p.get_text(" ", strip=True) for p in entry.select("p, h2, h3, h4")]
    # Keep source evidence, not a claim that downloaded content has been validated.
    evidence = [p[:1000] for p in paragraphs if re.search(
        r"STEP|STP|模型答案|答案模型|模型源文件|提供件|提取码", p, re.I)]
    text = entry.get_text(" ", strip=True)
    codes = re.findall(r"提取码\s*[:：]?\s*([A-Za-z0-9]{4})(?![A-Za-z0-9])", text)
    return {"evidence": evidence[:20], "public_passcodes": list(dict.fromkeys(codes)),
            "format_mentions": sorted(set(m.upper() for m in re.findall(r"STEP|STP", text, re.I))),
            "claims_verified_against_file_bytes": False}


def list_quark(session, url, passcodes):
    match = re.fullmatch(r"/s/([A-Za-z0-9]+)", urlsplit(url).path)
    if not match:
        return {"status": "unsupported_public_url"}
    pwd_id = match[1]
    code = parse_qs(urlsplit(url).query).get("pwd", [""])[0]
    if not code and len(passcodes) == 1:
        code = passcodes[0]
    time.sleep(1)
    response = session.post(API + "token", params=PARAMS,
                            json={"pwd_id": pwd_id, "passcode": code}, timeout=(15, 30))
    result = response.json()
    token = result.get("data", {}).get("stoken")
    if not token:
        return {"status": "unavailable_or_passcode_required", "http_status": response.status_code,
                "api_code": result.get("code"),
                "message": str(result.get("message", ""))[:300]}
    response.raise_for_status()
    files, queue, visited, truncated = [], [("0", "", 0, 1)], 0, False
    while queue and visited < 8:
        fid, prefix, depth, page = queue.pop(0)
        time.sleep(1)
        response = session.get(API + "detail", params={**PARAMS, "ver": 2, "pwd_id": pwd_id,
            "stoken": token, "pdir_fid": fid, "force": 0, "_page": page, "_size": 50,
            "_fetch_banner": int(fid == "0"), "_fetch_share": int(fid == "0"),
            "_fetch_total": 1, "_sort": "file_type:asc,file_name:asc"}, timeout=(15, 30))
        result = response.json()
        if result.get("code") != 0:
            return {"status": "partial_listing_error", "files": files, "api_code": result.get("code"),
                    "http_status": response.status_code, "message": str(result.get("message", ""))[:300]}
        response.raise_for_status()
        rows = result.get("data", {}).get("list", [])
        for row in rows:
            name = row["file_name"]
            files.append({"path": prefix + name, "bytes": row.get("size"),
                          "is_directory": bool(row.get("dir")), "mime": row.get("format_type")})
            if row.get("dir"):
                if depth < 2:
                    queue.append((row["fid"], prefix + name + "/", depth + 1, 1))
                else:
                    truncated = True
        if len(rows) == 50:
            queue.append((fid, prefix, depth, page + 1))
        visited += 1
    return {"status": "anonymous_listing_verified", "files": files,
            "listing_truncated": bool(queue) or truncated,
            "download_status": "not_downloaded", "archive_contents_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--posts", nargs="+", default=POSTS)
    args = parser.parse_args()
    if len(args.posts) > 20 or not all(re.fullmatch(r"\d+", p) for p in args.posts):
        parser.error("At most 20 numeric post IDs")
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    fetcher, session = Fetcher(), requests.Session()
    session.headers["User-Agent"] = "EvoCAD-Research-Discovery/0.1"
    catalog = {"created_at": datetime.now(timezone.utc).isoformat(), "articles": [], "failures": [],
               "policy": "Public metadata only. No login, gated retrieval, or training import.",
               "cloud_protocol_provenance": "Public Quark share page's own anonymous token/detail requests, observed in browser.",
               "downloaded_cad_files": 0, "verified_gt_pairs": 0}
    for post_id in args.posts:
        url = f"{BASE}/post/{post_id}.html"
        try:
            body = fetcher.fetch(url)
            row = parse_article(body, url)
            row["advertised"] = advertised_claims(body)
            row["public_targets"] = list(dict.fromkeys(
                target for link in row["download_links"] if (target := public_target(link["url"]))))
            row["cloud_inspections"] = []
            for target in row["public_targets"]:
                if urlsplit(target).hostname == "pan.quark.cn":
                    try:
                        inspection = list_quark(session, target, row["advertised"]["public_passcodes"])
                    except (requests.RequestException, ValueError) as error:
                        # Do not persist request URLs containing ephemeral share tokens.
                        response = getattr(error, "response", None)
                        inspection = {"status": "request_failed", "error_type": type(error).__name__,
                                      "http_status": response.status_code if response is not None else None}
                    row["cloud_inspections"].append({"share_url": target, **inspection})
            catalog["articles"].append(row)
            print(json.dumps({"post_id": post_id, "title": row["title"], "claims": row["advertised"],
                              "targets": row["public_targets"], "cloud": row["cloud_inspections"]},
                             ensure_ascii=False), flush=True)
        except (requests.RequestException, ValueError) as error:
            catalog["failures"].append({"url": url, "error": str(error)})
        write_json_atomic(output / "catalog.json", catalog)
        write_json_atomic(output / "fetch-audit.json", fetcher.audit)


if __name__ == "__main__":
    main()
