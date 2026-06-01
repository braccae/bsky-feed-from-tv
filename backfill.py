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

            # Build post dict with original creation time as indexed_at
            reply_root = reply_parent = None
            record = post_view.record
            if hasattr(record, "reply") and record.reply:
                reply_root = record.reply.root.uri if hasattr(record.reply, "root") else None
                reply_parent = record.reply.parent.uri if hasattr(record.reply, "parent") else None

            # Parse created_at to use as indexed_at
            indexed_at_val = datetime.utcnow()
            if hasattr(record, "created_at") and record.created_at:
                try:
                    dt = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
                    indexed_at_val = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass

            post_dict = {
                "uri": uri,
                "cid": cid,
                "reply_parent": reply_parent,
                "reply_root": reply_root,
                "indexed_at": indexed_at_val,
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
        print("\n✨ No new posts found to backfill.")
    else:
        # Sort grabbed posts chronologically with the newest posts first
        all_posts.sort(key=lambda p: p["indexed_at"], reverse=True)

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
    print(f"\n✅ Backfill completed!")
    if all_posts:
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

    # Retroactively sort all posts in the database
    retroactive_sort(client)


def retroactive_sort(client: Client):
    """
    Fetch actual creation times for all posts currently in the database
    and update their indexed_at values retroactively.
    """
    print("\n🔄 Starting retroactive database sorting pass...")

    # Select all posts in the database
    all_db_posts = list(Post.select())
    if not all_db_posts:
        print("   Database is empty. Nothing to sort.")
        return

    print(f"   Hydrating actual timestamps for {len(all_db_posts)} posts from Bluesky API...")

    # Process in batches of 25 (the API limit for get_posts)
    batch_size = 25
    updated_count = 0

    for i in range(0, len(all_db_posts), batch_size):
        batch = all_db_posts[i : i + batch_size]
        uris = [post.uri for post in batch]

        try:
            response = client.app.bsky.feed.get_posts(params={"uris": uris})
            if response and response.posts:
                # Map URI to its parsed created_at timestamp
                uri_to_timestamp = {}
                for post_view in response.posts:
                    record = post_view.record
                    if hasattr(record, "created_at") and record.created_at:
                        try:
                            dt = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
                            naive_dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                            uri_to_timestamp[post_view.uri] = naive_dt
                        except Exception:
                            pass

                # Update in a transaction
                with db.atomic():
                    for post in batch:
                        if post.uri in uri_to_timestamp:
                            post.indexed_at = uri_to_timestamp[post.uri]
                            post.save()
                            updated_count += 1

        except Exception as e:
            print(f"  ⚠️  Error updating batch starting at index {i}: {e}")

        # Limit console output spam to every 250 posts
        if (i + batch_size) % 250 == 0 or (i + batch_size) >= len(all_db_posts):
            print(f"   Progress: {min(i + batch_size, len(all_db_posts))}/{len(all_db_posts)} posts processed...")
        
        # Polite API delay
        time.sleep(0.1)

    print(f"   ✅ Retroactive sort complete. Updated {updated_count} posts with their original timestamps.")


if __name__ == "__main__":
    main()
