# Read your first five rows

You will read five demo products in three requests. On the last request, the API tells you that you have reached the end.

You need a browser, the service URL from your operator, and a Snowflake user who can open the service and read the demo. Ask your operator for the address ending in `.snowflake.app`. The following paths go after that address in the same browser tab.

## Read the first page

In the address bar, keep the scheme and hostname of your service and replace any existing path, including `/openapi.json`, with `/v1/tables/demo?limit=2`. Complete Snowflake sign-in if prompted. Your browser displays JSON with two products. The first product is Notebook, with ID 1. The second is Pencil, with ID 2. If you see 403 or the demo path is missing, use the [request troubleshooting guide](../how-to/troubleshoot.md).

Look at the two top-level fields. `items` contains the rows. `next_cursor` contains a string that marks the last row you received. Copy the string inside the quotes. Keep your own value for the next step.

## Move to the next page

Keep the same address and append `&cursor=` followed by the string you copied. Press Enter. Your path now has this shape, with your actual cursor in place of `YOUR_CURSOR`.

```text
/v1/tables/demo?limit=2&cursor=YOUR_CURSOR
```

This time you see Folder (ID 3) and Ruler (ID 4). Copy the **new** value of `next_cursor`. Replace the previous cursor in the address and press Enter once more.

## Recognize the last page

The last response contains one row.

```json
{
  "items": [{"ID": 5, "ITEM": "Eraser", "PRICE": "0.65"}],
  "next_cursor": null
}
```

You have read all five products. A client stops when it receives `null`. To repeat the exercise, open the original address without a cursor.

Next, [make the same requests with Python](../how-to/client.md) or [look up the HTTP contract](../reference/http.md).
