# 🚀 GermanySupport.de Autoblogger System

Fully automated AI-based article publishing + SEO optimization system for WordPress.

---

# 📦 Project Structure

germanysupport-autoblogger/

├── publish_article.py  
├── optimize_articles.py  
├── config.py  
├── run_publish.sh  
├── run_optimize.sh  
├── manual_topics.csv  
├── .env  
├── logs/  
├── cache/  
└── .github/workflows/  

---

# 🔐 `.env` Setup (MANDATORY)

## Location
Place `.env` in repo root:

germanysupport-autoblogger/.env

## Example

WP_URL=https://germanysupport.de  
WP_USER=your_wp_username  
WP_APP_PASS=your_wp_application_password  

ANTHROPIC_KEY=your_claude_api_key  
PEXELS_KEY=your_pexels_api_key  

---

# ⚙️ System Architecture

Publishing Flow:
run_publish.sh → publish_article.py → generate → enforce links → publish → translate → SEO

Optimization Flow:
run_optimize.sh → optimize_articles.py → improve SEO → update WP

---

# 📜 run_publish.sh

bash run_publish.sh  
bash run_publish.sh --topic "Best car insurance in Germany"  
bash run_publish.sh --topic "..." --skip-translate  

source run_publish.sh → loads env only

---

# 📜 run_optimize.sh

bash run_optimize.sh  
bash run_optimize.sh --days 1  
bash run_optimize.sh --limit 5  

---

# 📄 manual_topics.csv

topic,products,language,status  

pending → publish  
done → skip  

Processes ONE topic per run.

---

# 🔗 Referral Links

Always uses:

https://germanysupport.de/go/{slug}

Never raw affiliate links.

---

# ⏰ Cron Setup

Git pull:
cd repo && git pull

Publish:
bash run_publish.sh

Optimize:
bash run_optimize.sh --days 1

---

# 📱 Mobile Workflow

Edit manual_topics.csv in GitHub → commit → cron publishes

---

# 💻 Manual Run

set -a  
source .env  
set +a  

python3 publish_article.py --topic "..."  
python3 optimize_articles.py --days 1  

---

# 🔄 Git Sync

manual_topics.csv auto-committed + pushed after publish

---

# 🧪 Debug

tail -f logs/cron.log  

grep -R "py.pl" .  
grep -R "referral-link" .  

---

# ⚡ Summary

- Fully automated publishing  
- SEO optimized  
- Mobile controllable  
- Uses internal /go links only  
