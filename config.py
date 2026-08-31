import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"
OPENROUTER_HAIKU_MODEL = "anthropic/claude-haiku-4.5"

EDITOR = os.getenv("EDITOR", "nano")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRANDS_DIR = os.path.join(BASE_DIR, "brands")
POSTS_DIR = os.path.join(BASE_DIR, "posts")
DB_PATH = os.path.join(BASE_DIR, "content.db")
