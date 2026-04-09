# Social Module v3

Automated social publishing engine for germanysupport.de

Supports:
- multi-platform publishing (Facebook, Instagram)
- config-driven targets
- content-type routing (`article`, `deal`, `guide`, `news`)
- automatic branded image generation
- smart background image fetching (Pexels)
- local font rendering (Roboto)
- Facebook first-comment link posting
- per-target UTM tagging (ready)
- scalable architecture for future channels

---

## 📁 Folder Structure

social/
  assets/
    fonts/
      Roboto-Regular.ttf
      Roboto-Bold.ttf
    germanysupport_logo.png

  platforms/
    __init__.py
    base.py
    facebook.py
    instagram.py

  __init__.py
  cli.py
  config.py
  env_loader.py
  formatter.py
  image_builder.py
  models.py
  pexels_client.py
  publisher.py
  share_existing_articles.py
  store.py

  cache/                  # (ignored in git)
    generated_images/

---

## 🚀 Features

### Automated Publishing
- CLI-based publishing
- multi-target support
- per-target behavior

### Smart Image Generation
- 1080x1080 branded images
- Pexels backgrounds + fallback
- overlays for readability
- logo + badge + styling

### Typography
- Roboto (local fonts)
- no system dependency

### Content Types
- article
- deal
- guide
- news

---

## ⚙️ Environment Variables

### Core
WP_URL=...
WP_USER=...
WP_APP_PASS=...

### Social
GS_FB_MAIN_PAGE_ID=...
GS_FB_MAIN_ACCESS_TOKEN=...

GS_IG_MAIN_PAGE_ID=...
GS_IG_MAIN_ACCESS_TOKEN=...

### Images
SOCIAL_LOGO_PATH=...
SOCIAL_FONT_REGULAR_PATH=...
SOCIAL_FONT_BOLD_PATH=...
PEXELS_API_KEY=...

### Optional (Instagram)
SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL=https://germanysupport.de/social-images

---

## 🧪 CLI Usage

### Facebook

python -m social.cli \
  --external-id "article:test:001" \
  --content-type article \
  --title "Save Money on Electricity in Germany" \
  --summary "Reduce your electricity costs." \
  --link "https://germanysupport.de/" \
  --generate-image \
  --targets "gs_fb_main"

---

### Instagram

python -m social.cli \
  --external-id "deal:test:001" \
  --content-type deal \
  --title "Telekom Deal" \
  --promo-text "Limited offer" \
  --link "https://germanysupport.de/" \
  --image-url "https://example.com/image.jpg" \
  --targets "gs_ig_main"

---

## 📦 Git Guidelines

### Commit
- source code
- fonts
- logo

### Do NOT commit
- .env
- tokens
- cache/
- logs
- generated images

---

## Notes

- dark image → Pexels failed
- bad text → font not loaded
- IG requires public image URL

---

## Status

- Facebook: working
- Image generation: working
- Fonts: fixed
- Instagram: requires public URL
