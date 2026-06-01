# ATProto Feed Generator powered by [The AT Protocol SDK for Python](https://github.com/MarshalX/atproto)

> Feed Generators are services that provide custom algorithms to users through the AT Protocol.

Official overview (read it first): https://github.com/bluesky-social/feed-generator#overview

## Getting Started

We've set up this server with libSQL to store and query data. This supports local database files as well as remote/embedded replicas using Turso.

Next, you will need to do three things:

1. Implement filtering logic in `server/data_filter.py`.
2. Copy `.env.example` to `.env` and fill in your settings.
3. Optionally implement custom feed generation logic in `server/algos`.

We've taken care of setting this server up with a did:web. However, you're free to switch this out for did:plc if you like - you may want to if you expect this Feed Generator to be long-standing and possibly migrating domains.

## Publishing your feed

To publish your feed, simply run:

```shell
uv run publish
```

To update your feed's display data (name, avatar, description, etc.), just update the relevant variables in `.env` and re-run the script.

After successfully running the script, you should be able to see your feed from within the app, as well as share it by embedding a link in a post (similar to a quote post).

## Running the Server

This project requires Python 3.14+ and is configured to use the `uv` toolchain for dependency management.

### 1. Synchronize Dependencies

Run `uv sync` to setup a virtual environment and install the dependencies:

```shell
uv sync
```

**Note**: To get a value for `FEED_URI`, you need to publish the feed first.

### 2. Start the Development Server

To run the development Flask server:

```shell
uv run dev
```

### 3. Start the Production Server

To run the production-grade Gunicorn WSGI server:

```shell
uv run prod
```

**Warning**: If you want to run the server with many workers, you should run the Data Stream (Firehose) separately.

### Endpoints

- `/.well-known/did.json`
- `/xrpc/app.bsky.feed.describeFeedGenerator`
- `/xrpc/app.bsky.feed.getFeedSkeleton`

## License

MIT
