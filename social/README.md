# Social Module v2

This module supports:
- config-driven multi-target publishing
- content type routing (`article`, `deal`, `guide`, `news`)
- Facebook first-comment link posting
- branded square image generation
- per-target UTM tagging
- target allow-lists for future main/deals pages

## Folder structure

```text
social/
  __init__.py
  cli.py
  config.py
  env_loader.py
  formatter.py
  image_builder.py
  models.py
  publisher.py
  store.py
  platforms/
    __init__.py
    base.py
    facebook.py
    instagram.py
```

## Notes

- Generated image files are written to `social/cache/generated_images/`.
- Facebook can upload local generated images directly.
- Instagram cannot use a local file path through this implementation. It needs a **public image URL**.
- To use generated images for Instagram, expose the generated image directory through your website and set:

```bash
SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL=https://your-domain/social-images
```

That URL should map to the same generated files.

## Quick manual tests

### Facebook article post with generated image

```bash
python -m social.cli \
  --external-id "article:test:001" \
  --content-type article \
  --title "How to save money on internet in Germany" \
  --summary "A short article summary for social posting." \
  --link "https://germanysupport.de/sample-article/" \
  --generate-image \
  --targets "gs_fb_main"
```

### Instagram deal post with existing public image URL

```bash
python -m social.cli \
  --external-id "deal:test:001" \
  --content-type deal \
  --title "Telekom 100 Mbit/s for €19.49/month" \
  --promo-text "Limited time discount for new customers." \
  --merchant "Telekom" \
  --new-price "19.49 €/Monat" \
  --link "https://germanysupport.de/sample-deal/" \
  --image-url "https://germanysupport.de/path/to/image.jpg" \
  --targets "gs_ig_main"
```
