"""Publish learning videos as a GitHub Release.

Encodes a directory of source MP4s locally with ffmpeg and publishes
them — plus a manifest.json — as release assets on this repo.
Customer environments fetch the manifest via VIDD_LEARNING_MANIFEST_URL
(pointed at GitHub's /releases/latest/download/manifest.json
redirector) and download each video directly from its versioned
release-asset URL.

Source files must be named <lesson_id>.mp4, matching a video lesson
in narrati's learning_curriculum.json.

Usage:

    python publish.py \\
        --source-dir ~/Videos/learning-raw \\
        --tag v2026-06-01

Pre-requisites (all on PATH):
- ffmpeg, ffprobe
- gh CLI, authenticated with write access to this repo
"""

import argparse
import datetime
import hashlib
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("publish")

DEFAULT_REPO = "narratidev/vidd-learning-content"


def _ffmpeg_encode(input_path: Path, output_path: Path) -> None:
    # H.264/AAC, faststart, 1080p cap, CRF 22.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-vf", "scale='min(1920,iw)':'-2'",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def _ffprobe_duration_sec(path: Path) -> int:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    return int(round(float(json.loads(out)["format"]["duration"])))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


@dataclass
class EncodedVideo:
    lesson_id: str
    path: Path
    duration_sec: int
    content_hash: str


def _release_asset_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def _build_manifest(
    videos: List[EncodedVideo], repo: str, tag: str
) -> dict:
    entries: List[dict] = [
        {
            "lesson_id": v.lesson_id,
            "source_url": _release_asset_url(repo, tag, f"{v.lesson_id}.mp4"),
            "duration_sec": v.duration_sec,
            "content_hash": v.content_hash,
        }
        for v in sorted(videos, key=lambda v: v.lesson_id)
    ]
    return {
        "version": "1.0",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "videos": entries,
    }


def _gh_release_create(
    repo: str, tag: str, files: List[Path], draft: bool
) -> None:
    cmd = [
        "gh", "release", "create", tag,
        *[str(f) for f in files],
        "--repo", repo,
        "--title", tag,
        "--notes", f"Learning library publish for {tag}.",
    ]
    if draft:
        cmd.append("--draft")
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True,
        help="Directory containing <lesson_id>.mp4 source files.")
    parser.add_argument("--repo", default=DEFAULT_REPO,
        help=f"GitHub repo in <owner>/<name> form. Default: {DEFAULT_REPO}.")
    parser.add_argument("--tag", required=True,
        help="Release tag (e.g. v2026-06-01). Must not already exist.")
    parser.add_argument("--work-dir", default=None,
        help="Directory for intermediate encoded files. "
             "Defaults to <source-dir>/encoded.")
    parser.add_argument("--draft", action="store_true",
        help="Create a draft release (won't flip /latest/ until published). "
             "Use to stage a publish for review.")
    args = parser.parse_args()

    for tool in ("ffmpeg", "ffprobe", "gh"):
        if shutil.which(tool) is None:
            logger.error("%s not on PATH — install it and retry.", tool)
            return 2

    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        logger.error("Source dir does not exist: %s", source_dir)
        return 2

    inputs = sorted(source_dir.glob("*.mp4"))
    if not inputs:
        logger.error("No .mp4 files found in %s", source_dir)
        return 2

    work_dir = Path(args.work_dir) if args.work_dir else source_dir / "encoded"
    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Encoding %d source video(s) → %s", len(inputs), work_dir)

    encoded: List[EncodedVideo] = []

    for input_path in inputs:
        lesson_id = input_path.stem
        output_path = work_dir / f"{lesson_id}.mp4"
        logger.info("[%s] encoding %s", lesson_id, input_path.name)
        _ffmpeg_encode(input_path, output_path)

        duration_sec = _ffprobe_duration_sec(output_path)
        content_hash = _sha256(output_path)
        logger.info("[%s] duration: %ds, size: %d bytes, %s",
                    lesson_id, duration_sec,
                    output_path.stat().st_size, content_hash)
        encoded.append(EncodedVideo(
            lesson_id=lesson_id,
            path=output_path,
            duration_sec=duration_sec,
            content_hash=content_hash,
        ))

    manifest = _build_manifest(encoded, args.repo, args.tag)
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Wrote manifest with %d entries → %s",
                len(manifest["videos"]), manifest_path)

    logger.info("Creating GitHub release %s on %s%s",
                args.tag, args.repo, " (draft)" if args.draft else "")
    _gh_release_create(args.repo, args.tag,
                       [manifest_path, *(v.path for v in encoded)],
                       args.draft)

    manifest_url = (
        f"https://github.com/{args.repo}"
        f"/releases/latest/download/manifest.json"
    )
    logger.info("Done.")
    logger.info("Stable manifest URL "
                "(set as VIDD_LEARNING_MANIFEST_URL in each env):")
    logger.info("  %s", manifest_url)
    if args.draft:
        logger.info("Release is a DRAFT — /latest/ will not flip until you "
                    "publish it (`gh release edit %s --draft=false`).",
                    args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
