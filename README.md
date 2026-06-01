# vidd-learning-content

Distribution channel for Vidd's learning portal videos.

The repo itself is small — just `publish.py` and this README. The
actual content lives in **GitHub Releases** on this repo: each
release tag contains the encoded `<lesson_id>.mp4` files plus a
`manifest.json` describing them.

Customer environments pull from a stable URL that always resolves to
the latest release:

```
https://github.com/narratidev/vidd-learning-content/releases/latest/download/manifest.json
```

The `narrati` backend has a `SyncLearningVideosWorkflow` that fetches
the manifest, diffs against the local environment's object store,
and downloads any missing videos directly from their release-asset
URLs.

## Publishing a new release

You'll need:

- `ffmpeg` and `ffprobe` on PATH
- `gh` CLI authenticated with write access to this repo
- A directory of raw source MP4s named `<lesson_id>.mp4`, where each
  `lesson_id` matches a `type: "video"` lesson in
  [`learning_curriculum.json`](https://github.com/narratidev/narrati/blob/main/narrati/narrati/api_server/data/learning_curriculum.json)

Then:

```bash
python publish.py \
    --source-dir ~/Videos/vidd-learning-raw \
    --tag v2026-06-01
```

The script:

1. Encodes each MP4 with the canonical profile (H.264/AAC, faststart,
   1080p cap, CRF 22). Encoded outputs land in `<source-dir>/encoded/`.
2. Probes duration with `ffprobe` and computes a SHA-256 of each
   encoded file.
3. Writes `manifest.json` listing each lesson with its versioned
   release-asset URL, duration, and content hash.
4. Runs `gh release create <tag> ./encoded/*.mp4 ./manifest.json` to
   publish.

After the script exits, the `/latest/download/manifest.json`
redirector flips to the new release. Customer environments pick up
the change on their next `SyncLearningVideosWorkflow` run (manual
trigger via `python -m narrati.api_server.scripts.sync_learning_videos`
or by pushing the event from the Hatchet dashboard).

### Staging a release for review

Add `--draft` to create a draft release. Draft releases don't flip
the `/latest/` redirector, so customer envs keep pulling the previous
release until you publish it manually:

```bash
gh release edit v2026-06-01 --draft=false
```

### One-time customer-env setup

In each environment's `vidd-config`:

```
VIDD_LEARNING_MANIFEST_URL=https://github.com/narratidev/vidd-learning-content/releases/latest/download/manifest.json
```

Once set, this never needs to change — only the contents of the
manifest at that URL evolve when new releases are published.

## Why GitHub Releases

- Public, stable, CDN-backed URLs. No signed URLs to refresh.
- 2 GB per asset cap — well above a 1080p lesson.
- Atomic publish: manifest and videos go up in the same release, so
  customer envs can never see a half-updated catalog.
- Built-in versioning. Roll back by deleting the bad release;
  `/latest/` resolves to the previous one automatically.
- Zero new infrastructure.

If the security posture later requires gated access, the publisher
swaps to an S3/R2 bucket; the customer-env env var changes once and
the sync workflow is untouched.
