import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Scraper settings
SCRAPE_BASE_URL = "https://www.amway.ua"
SCRAPE_SECTIONS = [
    "/uk/",
    "/uk/expert-advice",
    "/uk/Health/c/10003",
    "/uk/Artistry/c/10002",
    "/uk/Home/c/10001",
]
MAX_ARTICLES_PER_RUN = 1  # goal: one published post per run/day
CANDIDATE_POOL_SIZE = 8  # how many fresh candidates we try before giving up the run
ATTEMPTED_COOLDOWN_DAYS = 7  # skip previously-failed articles for this many days
SCRAPE_DELAY_SECONDS = 10  # robots.txt: 1 request per 10 seconds
# DataDome anti-bot: only a REAL headful browser (channel="chrome"/"msedge")
# passes. Persistent profile stores the DataDome cookie between runs.
CHROME_PROFILE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".chrome-profile"
)
CHROME_CHANNELS = ["chrome", "msedge", None]
SCRAPE_WAIT_TIMEOUT_MS = 25000  # how long to wait for DataDome challenge to resolve

# LLM settings
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "groq")
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODELS = ["gemini-3.6-flash"]
LLM_TEMPERATURE = 0.7
LLM_MAX_TOKENS = 2048
LLM_MAX_RETRIES = 3

# Content settings
POST_LANGUAGE = "ru"
POST_MAX_LENGTH = 4096
CTA_PROBABILITY = 1.0  # every post gets a CTA
BOOK_ENRICHMENT_PROBABILITY = 0.3  # 30% of posts reference a book

# Telegram settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # legacy: publish target
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or ""  # preview to executor
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID") or TELEGRAM_ADMIN_CHAT_ID or TELEGRAM_CHAT_ID  # publish target

# API keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PUBLISHED_JSON = os.path.join(DATA_DIR, "published.json")
ATTEMPTED_JSON = os.path.join(DATA_DIR, "attempted.json")
PREPARED_POSTS_JSON = os.path.join(DATA_DIR, "prepared_posts.json")
BOOKS_BUNDLE_JSON = os.path.join(DATA_DIR, "books_bundle.json")
