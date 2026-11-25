import os
import shutil
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "projects"
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profile"
DB_PATH = BASE_DIR / "taaft_movie_gen.db"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure runtime directories exist
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# TAAFT Video Generator Settings
TAAFT_URL = "https://theresanaiforthat.com/@taaft/video-generator/?ref=header"
DEFAULT_MODEL = "Fast"  # "Fast" or "Quality"
DEFAULT_ORIENTATION = "Landscape"  # "Landscape", "Portrait", "Square"
CLIP_DURATION_SECONDS = 8
MAX_DAILY_VIDEOS = 100

# Generation Timeouts and Intervals (seconds)
GENERATION_TIMEOUT_SECONDS = 3600  # Up to 60 minutes per clip (handles peak TAAFT queue)
POLLING_INTERVAL_SECONDS = 15     # Check every 15 seconds
SCREENSHOT_INTERVAL_SECONDS = 15  # Stream screenshot preview every 15s

# Gemini AI Defaults
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODEL = "gemini-flash-latest"

def get_gemini_api_key():
    """Retrieve Gemini API key from environment variable or database settings."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        try:
            from database import db
            api_key = db.get_setting("gemini_api_key", "")
        except Exception:
            pass
    return api_key or ""

def get_ffmpeg_executable():
    """Locate ffmpeg executable via imageio-ffmpeg or system PATH."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

FFMPEG_PATH = get_ffmpeg_executable()
