# JSON and Snowflake types

The API projects named columns and preserves their Snowflake names. JSON strings are used where conversion to a JSON number would lose precision or formatting.

| Source value | Returned JSON | Example |
| --- | --- | --- |
| SQL NULL | Null | `null` |
| Boolean | Boolean | `true` |
| Integer in the JavaScript safe range, inclusive | Number | `42` |
| Integer outside ±9,007,199,254,740,991 | String of digits | `"9007199254740992"` |
| Connector Decimal, including fixed-point amounts | Decimal string | `"4.95"` |
| Finite floating-point value | Number | `1.5` |
| Nonfinite floating-point value | String | `"inf"`, `"-inf"`, `"nan"` |
| Text | String | `"Notebook"` |
| DATE | ISO date string | `"2026-01-31"` |
| TIME or TIMESTAMP | String with nine fractional digits. Zoned timestamps include an offset. | `"12:00:00.123456789"` |
| BINARY | Standard base64 string | `"AQI="` for bytes 1 and 2 |
| VARIANT, OBJECT or ARRAY returned as JSON text | Parsed JSON value. Integers follow the safe-range rule. Fractional JSON numbers are parsed as decimals and returned as strings. | `{"count": 2, "amount": "1.50"}` |
| Snowflake-specific text inside a semi-structured value | Original string when it cannot be parsed as JSON | Sparse array containing a bare `undefined` |

Returned values depend on the Snowflake connector's representation. Day-time intervals returned as Python `timedelta` currently fail page serialization. The tested connection returned numeric-key structured MAP values as text, so the API returned a JSON string containing the map. A connector-native map with non-string keys can fail the response model. Use an explicit projection to omit unsupported columns, or expose a source representation you have tested before publishing it.

[Dataset configuration](configuration.md) controls the projection. [Pagination key types](configuration.md#pagination-keys) are a smaller set because the API must compare and resume from key values exactly.
