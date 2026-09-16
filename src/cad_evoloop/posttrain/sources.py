"""Bounded, provenance-preserving sampling of the official Fusion archive."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

import requests

from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic


FUSION_URL = (
    "https://fusion-360-gallery-dataset.s3.us-west-2.amazonaws.com/"
    "reconstruction/r1.0.1/r1.0.1.zip"
)
FUSION_LICENSE = (
    "https://raw.githubusercontent.com/AutodeskAILab/Fusion360GalleryDataset/"
    "1084b881f3bb710267801d812d6e9286b8667059/LICENSE.md"
)
MAX_MEMBER = 16 * 1024 * 1024


class RangeArchive(io.RawIOBase):
    """Seekable HTTPS reader; reject ignored ranges and changing archives."""

    def __init__(self, url: str, *, direct: bool = False, budget: int = 128 << 20):
        if not url.startswith("https://"):
            raise ValueError("Archive URL must use HTTPS")
        self.url = url
        self.session = requests.Session()
        self.session.trust_env = not direct
        self.position = 0
        self.transferred = 0
        self.budget = budget
        self.etag = None
        self.length = None
        self.cache: list[tuple[int, bytes]] = []
        self._fetch(0, 0)

    def _fetch(self, start: int, end: int) -> bytes:
        if end < start or self.transferred + end - start + 1 > self.budget:
            raise ValueError("Range download exceeds transfer budget")
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        if self.etag:
            headers["If-Match"] = self.etag
        with self.session.get(self.url, headers=headers, timeout=(15, 60), stream=True) as response:
            response.raise_for_status()
            expected = end - start + 1
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if response.status_code != 206 or not match:
                raise ValueError("Server must honor byte ranges")
            first, last, length = map(int, match.groups())
            if (first, last) != (start, end) or length <= end:
                raise ValueError("Unexpected Content-Range")
            etag = response.headers.get("ETag")
            if not etag or (self.etag and self.etag != etag) or self.length not in (None, length):
                raise ValueError("Archive identity changed or is unavailable")
            self.etag, self.length = etag, length
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > expected:
                    raise ValueError("Response exceeds requested range")
            if len(content) != expected:
                raise ValueError("Truncated range response")
            self.transferred += len(content)
            return bytes(content)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence not in (0, 1, 2):
            raise ValueError("Invalid seek origin")
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.length)
        if position < 0:
            raise ValueError("Negative seek")
        self.position = position
        return position

    def read(self, size: int = -1) -> bytes:
        if self.position >= self.length or size == 0:
            return b""
        count = self.length - self.position if size < 0 else min(size, self.length - self.position)
        start, end = self.position, self.position + count
        for cached_start, cached in self.cache:
            if cached_start <= start and end <= cached_start + len(cached):
                self.position = end
                return cached[start - cached_start:end - cached_start]
        # Cache ZIP metadata and nearby member headers to avoid dozens of tiny requests.
        fetch_end = min(self.length, max(end, start + 65536))
        data = self._fetch(start, fetch_end - 1)
        self.cache.append((start, data))
        self.position = end
        return data[:count]

    def close(self) -> None:
        if getattr(self, "session", None) is not None:
            self.session.close()
        super().close()


def safe_member(archive: zipfile.ZipFile, name: str) -> bytes:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe archive member")
    info = archive.getinfo(name)
    mode = info.external_attr >> 16
    if mode & 0o170000 == 0o120000 or info.is_dir():
        raise ValueError("Archive member must be a regular file")
    if info.file_size > MAX_MEMBER:
        raise ValueError("Archive member too large")
    return archive.read(info)


def acquire_fusion(output: Path, *, count: int = 32, direct: bool = False) -> dict:
    if not 1 <= count <= 100:
        raise ValueError("Probe count must be between 1 and 100")
    workspace = Path(__file__).resolve().parents[3]
    output = output.resolve()
    if not output.is_relative_to(workspace) or output == workspace:
        raise ValueError("Acquisition output must stay in this workspace")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("Use a fresh acquisition directory")
    manifest = {
        "schema_version": "1.0", "source": "Fusion360Gallery/reconstruction/r1.0.1",
        "url": FUSION_URL, "license_url": FUSION_LICENSE,
        "license_scope": "upstream-custom-noncommercial; no blanket relicensing",
        "status": "downloaded_not_accepted", "acquired_at": utc_now(), "parts": [],
    }
    with RangeArchive(FUSION_URL, direct=direct) as remote:
        with zipfile.ZipFile(remote) as archive:
            names = set(archive.namelist())
            split_name = next(name for name in sorted(names) if name.endswith("/train_test.json"))
            split = json.loads(safe_member(archive, split_name))
            write_json_atomic(output / "upstream-train-test.json", split)
            candidates = sorted(name for name in names if re.search(r"/\d+_[0-9a-f]+_\d{4}\.json$", name))
            # Keep upstream test identities out of the future training candidate pool.
            train = {Path(str(item)).stem for item in split["train"]}
            candidates = [name for name in candidates if PurePosixPath(name).stem in train and name[:-5] + ".step" in names]
            manifest["eligible_train_parts"] = len(candidates)
            for name in candidates[:count]:
                stem = PurePosixPath(name).stem
                part = {"part_id": stem, "ancestry": "fusion360:" + stem, "upstream_split": "train", "files": []}
                for extension in ("json", "step", "png"):
                    member = str(PurePosixPath(name).with_suffix("." + extension))
                    if member not in names:
                        continue
                    payload = safe_member(archive, member)
                    path = output / f"{stem}.{extension}"
                    path.write_bytes(payload)
                    part["files"].append({"member": member, "path": path.name, "bytes": len(payload), "sha256": sha256_file(path)})
                manifest["parts"].append(part)
                print(f"downloaded {stem} ({len(manifest['parts'])}/{count})", flush=True)
                write_json_atomic(output / "source-manifest.json", manifest)
        manifest.update({"archive_etag": remote.etag, "archive_bytes": remote.length, "downloaded_bytes": remote.transferred})
        with remote.session.get(FUSION_LICENSE, timeout=30) as response:
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("Unexpected license size")
            (output / "LICENSE.upstream.md").write_bytes(response.content)
    manifest["license_sha256"] = sha256_file(output / "LICENSE.upstream.md")
    write_json_atomic(output / "source-manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--direct", action="store_true", help="Use direct HTTPS, bypassing environment proxy settings")
    args = parser.parse_args()
    result = acquire_fusion(args.output, count=args.count, direct=args.direct)
    print(json.dumps({"parts": len(result["parts"]), "bytes": result["downloaded_bytes"]}))
