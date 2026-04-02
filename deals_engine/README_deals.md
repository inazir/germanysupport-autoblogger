# Deals Engine v1

This package is designed to live inside your repo as:

```text
germanysupport-autoblogger/
└── deals_engine/
```

Run it from the repo root with:

```bash
bash deals_engine/scripts/run_deals.sh
```

Or directly:

```bash
python -m deals_engine.deals.runner
```

## Required `.env` values in repo root

```env
WP_URL="https://germanysupport.de"
WP_USER="your-wordpress-username"
WP_APP_PASS="your-wordpress-application-password"

DEALS_CATEGORY_SLUG="best-deals"
DEALS_DEFAULT_STATUS="draft"
DEALS_LANGUAGE_MODE="both"
DEALS_INTERNAL_LINK_SOURCE="csv_internal_url"
DEALS_SOURCE="csv"
DEALS_CSV_PATH="deals_engine/feeds/sample_deals.csv"
DEALS_MAX_PER_RUN="20"
DEALS_MIN_SCORE="10"
```

## Allowed values

- `DEALS_LANGUAGE_MODE`: `en`, `de`, `both`
- `DEALS_INTERNAL_LINK_SOURCE`: `csv_internal_url`

## CSV columns

Required columns:
- `id`
- `merchant`
- `title`
- `category`
- `internal_url`

Recommended columns:
- `old_price`
- `new_price`
- `promo_text`
- `currency`
- `product_url`

## Important behavior

- v1 publishes **drafts**
- v1 reads the final internal link from the CSV `internal_url` column
- v1 creates **two separate posts** when `DEALS_LANGUAGE_MODE="both"`
- state is stored in:

```text
deals_engine/data/deals.sqlite
```

## Next step

After CSV mode is working, replace or extend the CSV source with a real Awin feed adapter.
