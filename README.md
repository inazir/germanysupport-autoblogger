# 🚀 GermanySupport.de Autoblogger System

Fully automated AI-powered article publishing + SEO optimization system for WordPress.

Designed for:
- Expats in Germany content
- Affiliate monetization (/go links only)
- Hands-off automation via cron
- Mobile control via GitHub

---

# 📦 Project Structure

germanysupport-autoblogger/

├── publish_article.py  
├── optimize_articles.py  
├── translate_articles.py  
├── update_links.py  
├── config.py  
├── run_publish.sh  
├── run_optimize.sh  
├── run_translate.sh  
├── run_update_links.sh  
├── run_git_sync.sh  
├── manual_topics.csv  
├── .env (NOT in git)  
├── logs/ (auto-created)  
├── cache/ (auto-created)  
└── .github/  

---

# 🔐 `.env` Setup (MANDATORY)

⚠️ The system WILL FAIL if `.env` is missing.

## Location
germanysupport-autoblogger/.env

## Example

WP_URL=https://germanysupport.de  
WP_USER=your_wp_username  
WP_APP_PASS=your_wp_application_password  

ANTHROPIC_KEY=your_claude_api_key  
PEXELS_KEY=your_pexels_api_key  

SMTP_HOST=smtp.hostinger.com  
SMTP_PORT=587  
SMTP_USER=info@germanysupport.de  
SMTP_PASS=your_email_password  
ALERT_TO=your@email.com  

---

# ⚙️ System Architecture

## Publishing Flow

run_publish.sh  
→ pre-sync  
→ publish_article.py  
→ generate → links → publish → translate → SEO → email  
→ post-sync  

## Optimization Flow

run_optimize.sh  
→ optimize_articles.py  
→ improve SEO  

---

# 📜 run_publish.sh

## Features

- Loads `.env` (mandatory)  
- Creates logs/ and cache/ automatically  
- Git sync before and after publish  
- Logs execution  
- Returns correct exit codes  

## Usage

bash run_publish.sh  
bash run_publish.sh --topic "Best car insurance in Germany"  
bash run_publish.sh --skip-translate  

---

# 📜 run_git_sync.sh

- Syncs ONLY manual_topics.csv  
- Pulls latest changes  
- Commits local CSV changes  
- Pushes back to GitHub  

---

# 📄 manual_topics.csv

topic,products,language,status  

pending → publish  
done → skip  
skipped → needs fix  

Processes ONE topic per run.

---

# 🔗 Referral Links

Always uses:

https://germanysupport.de/go/{slug}

---

# 📧 Email Alerts

- Success email after publish  
- Failure email on crash  

---

# ⏰ Cron

bash run_publish.sh  
bash run_optimize.sh --days 1  

---

# 🧪 Debug

tail -f logs/cron.log  
tail -f logs/git_sync.log  

---

# ⚡ Summary

- Fully automated  
- SEO optimized  
- Email monitored  
- GitHub controlled  
- Safe sync (CSV only)  
