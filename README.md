# SnowFastAPI

Read the [SnowFastAPI manual](docs/site/index.md) to deploy a read-only FastAPI service on Snowflake, publish tables with TOML and follow paginated results with your existing Snowflake identity.

This repository publishes the documentation. The browser tutorial works with a service URL provided by your operator. Deployment commands and the Python client require the implementation checkout.

## Build the documentation

From this directory, use uv with Python 3.11 or later.

```sh
uvx --from zensical==0.1.3 zensical build --clean --strict
python3 scripts/check_site.py
uvx --from zensical==0.1.3 zensical serve
```

Edit the Markdown pages in `docs/site/`. Navigation and the theme are configured in `zensical.toml`. Pull requests build and check the site. Merges to `main` publish it to GitHub Pages.
