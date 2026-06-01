import asyncio
import json
import logging
import time
import urllib.parse
from collections import defaultdict

import websockets
from atproto import models

from server import config
from server.database import SubscriptionState
from server.logger import logger

_INTERESTED_RECORDS = {
    models.AppBskyFeedLike: models.ids.AppBskyFeedLike,
    models.AppBskyFeedPost: models.ids.AppBskyFeedPost,
    models.AppBskyGraphFollow: models.ids.AppBskyGraphFollow,
}


async def _run_async(name, operations_callback, stream_stop_event=None):
    state = SubscriptionState.get_or_none(SubscriptionState.service == name)

    # Initial cursor setup (Unix microsecond timestamp)
    current_us = int(time.time() * 1_000_000)
    if not state:
        state = SubscriptionState.create(service=name, cursor=current_us)

    cursor = state.cursor
    # Reset/update if it looks like an old Firehose cursor (Firehose cursors are small sequential integers)
    if cursor < 1700000000000000:
        cursor = current_us
        SubscriptionState.update(cursor=cursor).where(SubscriptionState.service == name).execute()

    _NSID_TO_RECORD_TYPE = {nsid: record_type for record_type, nsid in _INTERESTED_RECORDS.items()}

    # Jetstream URL configuration
    jetstream_url = getattr(config, 'JETSTREAM_URL', 'wss://jetstream1.us-east.bsky.network/subscribe')

    # Build WebSocket URL with query parameters
    parsed_url = urllib.parse.urlparse(jetstream_url)
    query_params = urllib.parse.parse_qsl(parsed_url.query)

    # Filter by the collections we are interested in to reduce bandwidth
    for nsid in _INTERESTED_RECORDS.values():
        query_params.append(('wantedCollections', nsid))

    logger.info(f"Connecting to Jetstream at {jetstream_url} with collections: {list(_INTERESTED_RECORDS.values())}")

    processed_count = 0
    last_save_time = time.time()

    while stream_stop_event is None or not stream_stop_event.is_set():
        params = list(query_params)
        if cursor:
            params.append(('cursor', str(cursor)))

        url_with_params = parsed_url._replace(query=urllib.parse.urlencode(params)).geturl()

        try:
            async with websockets.connect(url_with_params) as websocket:
                logger.info("Connected to Jetstream successfully.")

                while stream_stop_event is None or not stream_stop_event.is_set():
                    try:
                        # Periodically timeout to check stream_stop_event
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue

                    data = json.loads(message)

                    # Keep track of the cursor from the last event
                    if 'time_us' in data:
                        cursor = data['time_us']

                    kind = data.get('kind')
                    if kind != 'commit':
                        continue

                    commit = data.get('commit', {})
                    op_type = commit.get('operation')
                    if op_type not in ('create', 'delete'):
                        continue

                    collection = commit.get('collection')
                    if collection not in _NSID_TO_RECORD_TYPE:
                        continue

                    did = data.get('did')
                    rkey = commit.get('rkey')
                    uri = f"at://{did}/{collection}/{rkey}"

                    ops = defaultdict(lambda: {'created': [], 'deleted': []})

                    if op_type == 'create':
                        cid = commit.get('cid')
                        record_dict = commit.get('record', {})
                        record_cls = _NSID_TO_RECORD_TYPE[collection]

                        try:
                            # Direct Pydantic model parsing
                            record = record_cls.Record(**record_dict)
                            create_info = {
                                'uri': uri,
                                'cid': cid,
                                'author': did,
                                'record': record
                            }
                            ops[collection]['created'].append(create_info)
                        except Exception as e:
                            logger.error(f"Failed to parse record for {uri}: {e}")
                            continue

                    elif op_type == 'delete':
                        ops[collection]['deleted'].append({'uri': uri})

                    # Forward to the operations callback
                    try:
                        operations_callback(ops)
                    except Exception as e:
                        logger.error(f"Error in operations_callback: {e}")

                    processed_count += 1

                    # Persist cursor in DB periodically
                    now = time.time()
                    if processed_count % 1000 == 0 or (now - last_save_time) > 10.0:
                        logger.debug(f"Saving Jetstream cursor: {cursor}")
                        SubscriptionState.update(cursor=cursor).where(SubscriptionState.service == name).execute()
                        last_save_time = now

        except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as e:
            logger.error(f"Jetstream connection error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error in Jetstream client: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

    # Save final cursor before stopping
    if cursor:
        SubscriptionState.update(cursor=cursor).where(SubscriptionState.service == name).execute()


def run(name, operations_callback, stream_stop_event=None):
    try:
        asyncio.run(_run_async(name, operations_callback, stream_stop_event))
    except KeyboardInterrupt:
        logger.info("Jetstream stream stopped.")
