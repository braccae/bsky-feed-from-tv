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

## Container Deployment

This project includes configuration for automated container builds and rootless deployment using Podman Quadlets.

### 1. GitHub Actions (CI/CD)

The GitHub workflow `.github/workflows/build-image.yml` builds and pushes the container image to the GitHub Container Registry (GHCR) at `ghcr.io/<username>/bluesky-feed-generator:latest`.

- **Triggers**: It runs automatically on push to the `main` branch, when a new tag `v*` is pushed, and on any pull requests targeting `main`.
- **Registry Permissions**: Ensure your workflow has permissions to write packages in your repository settings.

### 2. Rootless Podman & Quadlet Deployment

Quadlet is the modern, recommended way to run rootless Podman containers managed by systemd.

#### Prerequisites

1. Enable lingering for your user so that the systemd services can start on system boot without you logging in:
   ```shell
   loginctl enable-linger $USER
   ```
2. Create the configuration and data persistence directories:
   ```shell
   mkdir -p ~/.config/bluesky-feed-generator
   mkdir -p ~/.local/share/bluesky-feed-generator/data
   ```
3. Copy your `.env` configuration file to `~/.config/bluesky-feed-generator/env`:
   ```shell
   cp .env ~/.config/bluesky-feed-generator/env
   ```
   *Make sure you set `LIBSQL_URL=/app/data/feed_database.db` inside this environment file so that the SQLite/LibSQL database is stored on the persistent host mount.*

#### Installation

1. Copy the Quadlet container file to your user's systemd directory:
   ```shell
   mkdir -p ~/.config/containers/systemd
   cp podman/bluesky-feed-generator.container ~/.config/containers/systemd/
   ```
   *Update the `Image=` option inside the copied file to point to your specific GHCR repository if needed.*

2. Reload the systemd daemon to generate the transient service files:
   ```shell
   systemctl --user daemon-reload
   ```

3. Start and enable the service:
   ```shell
   systemctl --user enable --now bluesky-feed-generator.service
   ```

4. Check the service status and logs:
   ```shell
   systemctl --user status bluesky-feed-generator.service
   journalctl --user -xeu bluesky-feed-generator.service
   ```

#### Automatic Updates

Because `AutoUpdate=registry` is set in the container file, you can configure Podman to check for newer images on GHCR and automatically restart the service:
```shell
systemctl --user enable --now podman-auto-update.timer
```

## License

MIT

