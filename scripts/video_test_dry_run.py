# scripts/video_test_dry_run.py
from __future__ import annotations

import sys
from pathlib import Path

# ✅ Fix Python path (must come AFTER __future__)
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

# Optional but recommended (for .env loading)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from social.models import SocialPost
from social.video_generator import generate_short_video


post = SocialPost(
    external_id="dry-run-video-test",
    content_type="article",
    title="Best Bank Accounts in Germany for New Arrivals",
    link="https://germanysupport.de/example-article/",
    summary=(
        "Learn what documents you need, which banks are beginner-friendly, "
        "how fees differ, and what to check before opening your first account."
    ),
    language="en",
    category_label="Banking",
)

video_path = generate_short_video(post)

print(f"Generated video: {video_path}")
print(f"File size: {Path(video_path).stat().st_size} bytes")