import datetime
import re

from collections import defaultdict

from atproto import models

from server import config
from server.logger import logger
from server.database import db, Post


# Compiled regex pattern to verify TV show context when #from is the only matched hashtag
TV_CONTEXT_PATTERN = re.compile(
    r'\b(season|episode|episodes|boyd|jade|victor|tabitha|talisman|talismans|colony\s+house|anghkooey)\b',
    re.IGNORECASE
)


def is_archive_post(record: 'models.AppBskyFeedPost.Record') -> bool:
    # Sometimes users will import old posts from Twitter/X which con flood a feed with
    # old posts. Unfortunately, the only way to test for this is to look an old
    # created_at date. However, there are other reasons why a post might have an old
    # date, such as firehose or firehose consumer outages. It is up to you, the feed
    # creator to weigh the pros and cons, amd and optionally include this function in
    # your filter conditions, and adjust the threshold to your liking.
    #
    # See https://github.com/MarshalX/bluesky-feed-generator/pull/21

    archived_threshold = datetime.timedelta(days=1)
    created_at = datetime.datetime.fromisoformat(record.created_at)
    now = datetime.datetime.now(datetime.UTC)

    return now - created_at > archived_threshold


def should_ignore_post(created_post: dict) -> bool:
    record = created_post['record']
    uri = created_post['uri']

    if config.IGNORE_ARCHIVED_POSTS and is_archive_post(record):
        logger.debug(f'Ignoring archived post: {uri}')
        return True

    if config.IGNORE_REPLY_POSTS and record.reply:
        logger.debug(f'Ignoring reply post: {uri}')
        return True

    return False


def operations_callback(ops: defaultdict) -> None:
    # Here we can filter, process, run ML classification, etc.
    # After our feed alg we can save posts into our DB
    # Also, we should process deleted posts to remove them from our DB and keep it in sync

    # for example, let's create our custom feed that will contain all posts that contains 'python' related text

    posts_to_create = []
    for created_post in ops[models.ids.AppBskyFeedPost]['created']:
        author = created_post['author']
        record = created_post['record']

        post_with_images = isinstance(record.embed, models.AppBskyEmbedImages.Main)
        post_with_video = isinstance(record.embed, models.AppBskyEmbedVideo.Main)
        inlined_text = record.text.replace('\n', ' ')

        # print all texts just as demo that data stream works
        logger.debug(
            f'NEW POST '
            f'[CREATED_AT={record.created_at}]'
            f'[AUTHOR={author}]'
            f'[WITH_IMAGE={post_with_images}]'
            f'[WITH_VIDEO={post_with_video}]'
            f': {inlined_text}'
        )

        if should_ignore_post(created_post):
            continue

        # only posts containing hashtags #from, #fromville, #fromseries, #fromily, and #frommgm
        post_hashtags = set()
        if record.text:
            for match in re.findall(r'#\w+', record.text):
                post_hashtags.add(match.lower())

        if record.facets:
            for facet in record.facets:
                if facet.features:
                    for feature in facet.features:
                        if hasattr(feature, 'tag') and feature.tag:
                            tag_val = feature.tag.lower()
                            if tag_val.startswith('#'):
                                post_hashtags.add(tag_val)
                            else:
                                post_hashtags.add(f'#{tag_val}')

        allowed_tags = {'#from', '#fromville', '#fromseries', '#fromily', '#frommgm'}
        matched_tags = post_hashtags.intersection(allowed_tags)
        
        if matched_tags:
            # If #from is the only matched hashtag, require specific TV show context keywords in the text
            if matched_tags == {'#from'}:
                if not (record.text and TV_CONTEXT_PATTERN.search(record.text)):
                    continue

            reply_root = reply_parent = None
            if record.reply:
                reply_root = record.reply.root.uri
                reply_parent = record.reply.parent.uri

            post_dict = {
                'uri': created_post['uri'],
                'cid': created_post['cid'],
                'reply_parent': reply_parent,
                'reply_root': reply_root,
            }
            posts_to_create.append(post_dict)

    posts_to_delete = ops[models.ids.AppBskyFeedPost]['deleted']

    if posts_to_delete or posts_to_create:
        try:
            with db.atomic():
                if posts_to_delete:
                    post_uris_to_delete = [post['uri'] for post in posts_to_delete]
                    Post.delete().where(Post.uri.in_(post_uris_to_delete)).execute()
                    logger.debug(f'Deleted from feed: {len(post_uris_to_delete)}')

                if posts_to_create:
                    for post_dict in posts_to_create:
                        Post.create(**post_dict)
                    logger.debug(f'Added to feed: {len(posts_to_create)}')
        except Exception as e:
            logger.error(f"Database transaction error: {e}")

    if posts_to_create and config.MAX_POSTS_COUNT:
        try:
            total_posts = Post.select().count()
            if total_posts > config.MAX_POSTS_COUNT:
                excess = total_posts - config.MAX_POSTS_COUNT
                oldest_posts = (Post
                                .select(Post.id)
                                .order_by(Post.indexed_at.asc(), Post.id.asc())
                                .limit(excess))
                ids_to_delete = [p.id for p in oldest_posts]
                if ids_to_delete:
                    Post.delete().where(Post.id.in_(ids_to_delete)).execute()
                    logger.info(f"Pruned {len(ids_to_delete)} oldest posts to maintain MAX_POSTS_COUNT limit of {config.MAX_POSTS_COUNT}")
        except Exception as e:
            logger.error(f"Failed to prune old posts: {e}")


