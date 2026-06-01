import os
import logging

from dotenv import load_dotenv

from server.logger import logger

load_dotenv()

SERVICE_DID = os.environ.get('SERVICE_DID')
HOSTNAME = os.environ.get('HOSTNAME')
FLASK_RUN_FROM_CLI = os.environ.get('FLASK_RUN_FROM_CLI')

if FLASK_RUN_FROM_CLI:
    logger.setLevel(logging.DEBUG)

if not HOSTNAME:
    raise RuntimeError('You should set "HOSTNAME" environment variable first.')

if not SERVICE_DID:
    SERVICE_DID = f'did:web:{HOSTNAME}'


FEED_URI = os.environ.get('FEED_URI')
if not FEED_URI:
    raise RuntimeError('Publish your feed first (run publish_feed.py) to obtain Feed URI. '
                       'Set this URI to "FEED_URI" environment variable.')


def _get_bool_env_var(value: str) -> bool:
    if value is None:
        return False

    normalized_value = value.strip().lower()
    if normalized_value in {'1', 'true', 't', 'yes', 'y'}:
        return True

    return False


IGNORE_ARCHIVED_POSTS = _get_bool_env_var(os.environ.get('IGNORE_ARCHIVED_POSTS'))
IGNORE_REPLY_POSTS = _get_bool_env_var(os.environ.get('IGNORE_REPLY_POSTS'))

JETSTREAM_URL = os.environ.get('JETSTREAM_URL', 'wss://jetstream1.us-east.bsky.network/subscribe')

MAX_POSTS_COUNT = os.environ.get('MAX_POSTS_COUNT')
if MAX_POSTS_COUNT:
    try:
        MAX_POSTS_COUNT = int(MAX_POSTS_COUNT)
    except ValueError:
        logger.warning(f"Invalid MAX_POSTS_COUNT value: {MAX_POSTS_COUNT}. Using no limit.")
        MAX_POSTS_COUNT = None


