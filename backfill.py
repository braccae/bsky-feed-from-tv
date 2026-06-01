#!/usr/bin/env python3
"""
Backfill script for the FROMily Bluesky feed generator.

Queries the Bluesky app.bsky.feed.searchPosts API for posts matching the
feed's hashtags and inserts them into the database. This script applies the
same filtering logic as the live Jetstream consumer (TV context verification
for lone #from, reply skipping, etc.).

Usage:
    # Inside the container:
    podman exec <container> uv run python backfill.py

    # Or locally with the venv:
    uv run python backfill.py

Environment variables (from .env):
    HANDLE   - Your Bluesky handle (e.g. user.bsky.social)
    PASSWORD - Your Bluesky app password
"""

import os
import re
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from atproto import Client

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HANDLE = os.environ.get("HANDLE")
PASSWORD = os.environ.get("PASSWORD")

# The hashtags the feed tracks (without the '#' prefix, as the API expects)
SEARCH_TAGS = ["fromville", "fromseries", "fromily", "frommgm", "from"]

# Maximum number of pages to fetch per tag (each page = up to 100 posts)
MAX_PAGES_PER_TAG = 50

# Compiled regex pattern for TV show context verification (same as data_filter.py)
TV_CONTEXT_PATTERN = re.compile(
    r"\b(season|episode|episodes|boyd|jade|victor|tabitha|talisman|talismans|colony\s+house|anghkooey)\b",
    re.IGNORECASE,
)

# Whether to skip reply posts (mirrors IGNORE_REPLY_POSTS from .env)
IGNORE_REPLY_POSTS = os.environ.get("IGNORE_REPLY_POSTS", "true").strip().strip("'\"").lower() in {
    "1", "true", "t", "yes", "y"
}


# ---------------------------------------------------------------------------
# Database setup (import after load_dotenv so env vars are available)
# ---------------------------------------------------------------------------

from server.database import db, Post  # noqa: E402


def get_existing_uris() -> set[str]:
    """Return all URIs currently in the database for deduplication."""
    return {post.uri for post in Post.select(Post.uri)}


def extract_hashtags_from_post(post_view) -> set[str]:
    """Extract lowercase hashtags from a post view (both text regex and facets)."""
    tags: set[str] = set()
    record = post_view.record

    # From post text via regex
    if hasattr(record, "text") and record.text:
        for match in re.findall(r"#\w+", record.text):
            tags.add(match.lower())

    # From rich-text facets
    if hasattr(record, "facets") and record.facets:
        for facet in record.facets:
            if facet.features:
                for feature in facet.features:
                    if hasattr(feature, "tag") and feature.tag:
                        tag_val = feature.tag.lower()
                        if tag_val.startswith("#"):
                            tags.add(tag_val)
                        else:
                            tags.add(f"#{tag_val}")

    return tags


def should_include_post(post_view, post_hashtags: set[str]) -> bool:
    """
    Apply the same filtering logic as data_filter.py:
    - Skip replies if IGNORE_REPLY_POSTS is set
    - If #from is the only matched allowed tag, require TV show context keywords
    """
    record = post_view.record

    # Skip replies
    if IGNORE_REPLY_POSTS and hasattr(record, "reply") and record.reply:
        return False

    allowed_tags = {"#from", "#fromville", "#fromseries", "#fromily", "#frommgm"}
    matched_tags = post_hashtags.intersection(allowed_tags)

    if not matched_tags:
        return False

    # If #from is the only matched tag, require TV context
    if matched_tags == {"#from"}:
        text = getattr(record, "text", None)
        if not text or not TV_CONTEXT_PATTERN.search(text):
            return False

    return True


def backfill_tag(client: Client, tag: str, existing_uris: set[str]) -> list[dict]:
    """
    Search for posts with a given tag and return a list of post dicts ready for
    database insertion.
    """
    posts_to_insert: list[dict] = []
    cursor = None
    page = 0

    print(f"\n🔍 Searching for #{tag}...")

    while page < MAX_PAGES_PER_TAG:
        page += 1
        try:
            response = client.app.bsky.feed.search_posts(
                params={
                    "q": f"#{tag}",
                    "tag": [tag],
                    "limit": 100,
                    "sort": "latest",
                    **({"cursor": cursor} if cursor else {}),
                }
            )
        except Exception as e:
            print(f"  ⚠️  API error on page {page}: {e}")
            break

        if not response or not response.posts:
            break

        for post_view in response.posts:
            uri = post_view.uri
            cid = post_view.cid

            # Skip duplicates
            if uri in existing_uris:
                continue

            # Extract hashtags and apply filters
            post_hashtags = extract_hashtags_from_post(post_view)
            if not should_include_post(post_view, post_hashtags):
                continue

            # Build post dict
            reply_root = reply_parent = None
            record = post_view.record
            if hasattr(record, "reply") and record.reply:
                reply_root = record.reply.root.uri if hasattr(record.reply, "root") else None
                reply_parent = record.reply.parent.uri if hasattr(record.reply, "parent") else None

            post_dict = {
                "uri": uri,
                "cid": cid,
                "reply_parent": reply_parent,
                "reply_root": reply_root,
            }
            posts_to_insert.append(post_dict)
            existing_uris.add(uri)  # Track for cross-tag dedup

        print(f"  Page {page}: {len(response.posts)} results, {len(posts_to_insert)} matched so far")

        cursor = getattr(response, "cursor", None)
        if not cursor:
            break

        # Be polite to the API
        time.sleep(0.5)

    return posts_to_insert


def main():
    print("=" * 60)
    print("FROMily Feed Backfill Script")
    print("=" * 60)

    # Set up client (authentication is optional for searchPosts if using the public API endpoint)
    client = None
    if HANDLE and PASSWORD:
        try:
            client = Client()
            print(f"\n🔑 Logging in as {HANDLE}...")
            client.login(HANDLE, PASSWORD)
            print("   ✅ Authenticated successfully.")
        except Exception as e:
            print(f"  ⚠️  Login failed: {e}")
            print("     Falling back to unauthenticated public client...")
            client = None

    if not client:
        client = Client(base_url="https://api.bsky.app")
        print("\n🔓 Running unauthenticated using api.bsky.app endpoint.")
        print("   No login required.")

    # Get existing URIs for deduplication
    existing_uris = get_existing_uris()
    print(f"📊 Database currently has {len(existing_uris)} posts.")

    # Search for each tag
    all_posts: list[dict] = []
    for tag in SEARCH_TAGS:
        tag_posts = backfill_tag(client, tag, existing_uris)
        all_posts.extend(tag_posts)

    if not all_posts:
        print("\n✨ No new posts found to backfill. Database is up to date!")
        return

    # Bulk insert into database
    print(f"\n💾 Inserting {len(all_posts)} new posts into the database...")
    inserted = 0
    try:
        with db.atomic():
            # Insert in batches of 100
            for i in range(0, len(all_posts), 100):
                batch = all_posts[i : i + 100]
                for post_dict in batch:
                    Post.create(**post_dict)
                    inserted += 1
    except Exception as e:
        print(f"  ⚠️  Database error after inserting {inserted} posts: {e}")

    total_posts = Post.select().count()
    print(f"\n✅ Backfill complete!")
    print(f"   • Inserted: {inserted} new posts")
    print(f"   • Total posts in database: {total_posts}")

    # Prune if MAX_POSTS_COUNT is set
    max_posts = os.environ.get("MAX_POSTS_COUNT")
    if max_posts:
        try:
            max_posts = int(max_posts.strip().strip("'\""))
        except ValueError:
            max_posts = None

    if max_posts and total_posts > max_posts:
        excess = total_posts - max_posts
        print(f"\n🗑️  Pruning {excess} oldest posts to stay under MAX_POSTS_COUNT={max_posts}...")
        oldest_posts = (
            Post.select(Post.id)
            .order_by(Post.indexed_at.asc(), Post.id.asc())
            .limit(excess)
        )
        ids_to_delete = [p.id for p in oldest_posts]
        if ids_to_delete:
            Post.delete().where(Post.id.in_(ids_to_delete)).execute()
            print(f"   ✅ Pruned {len(ids_to_delete)} posts.")


if __name__ == "__main__":
    main()
