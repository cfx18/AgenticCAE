"""Merge immutable public discovery probes without fetching or promoting assets."""

import argparse
import base64
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("probes", nargs="+", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError("Use a fresh catalog path")
    index, inspected, sources = {}, {}, []
    for probe in args.probes:
        probe = probe.resolve()
        index.update({row["url"]: row for row in json.loads((probe / "index.json").read_text(encoding="utf-8"))})
        catalog = json.loads((probe / "catalog.json").read_text(encoding="utf-8"))
        inspected.update({row["url"]: row for row in catalog["articles"]})
        sources.append({"probe": probe.relative_to(ROOT).as_posix(), "index_sha256": sha256_file(probe / "index.json"),
                        "catalog_sha256": sha256_file(probe / "catalog.json")})
    public_downloads = []
    for article in inspected.values():
        if article["source_file_access"] not in {"public_link_unverified", "mixed_public_links_and_gated_sections"}:
            continue
        row = {"title": article["title"], "article_url": article["url"], "links": article["download_links"],
               "ground_truth_status": article["ground_truth_status"], "rights": article["rights"]}
        for link in row["links"]:
            encoded = parse_qs(urlsplit(link["url"]).query).get("hk_url", [])
            if encoded:
                try:
                    target = base64.b64decode(encoded[0], validate=True).decode("utf-8")
                    parsed = urlsplit(target)
                    if (parsed.scheme == "https" and parsed.hostname in {"pan.quark.cn", "pan.baidu.com"}
                            and not parsed.username and not parsed.password and parsed.port in (None, 443)):
                        link["public_link_target"] = target
                        link["target_provenance"] = "Decoded visible public link parameter, not a hidden/VIP endpoint."
                except (ValueError, UnicodeError):
                    pass
        public_downloads.append(row)
    write_json_atomic(output, {"indexed_articles": len(index), "inspected_articles": len(inspected),
                              "public_download_candidates": public_downloads,
                              "verified_gt_pairs": 0, "sources": sources,
                              "index": list(index.values()), "articles": list(inspected.values())})
    print(json.dumps({"indexed_articles": len(index), "inspected_articles": len(inspected),
                      "public_download_candidates": len(public_downloads), "verified_gt_pairs": 0}))


if __name__ == "__main__":
    main()
