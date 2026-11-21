---
title: SnowFastAPI documentation
hide:
  - toc
---

<div class="sf-hero" markdown="1">
<div class="sf-intro" markdown="1">

# Publish a Snowflake table as an API

Give readers a URL for your data. They sign in with Snowflake and fetch one page at a time. You choose the table and page limit in a configuration file.

[Read your first five rows](tutorials/read-five-rows.md){ .sf-cta }

</div>
<div class="sf-sample" aria-label="Example dataset configuration">

<p>tables.toml</p>
<pre><code>[tables.demo]
table = "DEMO_PRODUCTS"
max_page_size = 50</code></pre>
</div>
</div>

## Start with what you have

<div class="sf-paths" markdown="1">
<div class="sf-path" markdown="1">

[**I have a service URL**](tutorials/read-five-rows.md)

Read the demo in your browser. You need a Snowflake identity with access to the service and its data.

</div>
<div class="sf-path" markdown="1">

[**I have the implementation checkout**](how-to/deploy.md)

Deploy the demo in your environment. If the service already exists, [publish your own table](how-to/publish.md).

</div>
</div>

The Python client and deployment commands run from the application checkout supplied by your operator. The browser tutorial only needs a deployed service.

## While you work

- [Use the Python client](how-to/client.md) to read several pages from a named Snowflake connection.
- [Look up settings](reference/configuration.md) or [check an HTTP response](reference/http.md).
- [Follow a request through Snowflake](explanation/architecture.md) to see which role controls each step.
- [Troubleshoot a request](how-to/troubleshoot.md) if a call redirects, fails, or returns unexpected rows.
