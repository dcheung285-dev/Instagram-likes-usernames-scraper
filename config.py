# All configuration is centralized here. Edit values directly.

# Instagram credentials and target
INSTAGRAM_USERNAME: str = "jorangeson056"  # e.g. "your_username"
INSTAGRAM_PASSWORD: str = "RippleMax372#"  # e.g. "your_password"
TARGET_ACCOUNT_HANDLE: str = "stake"
TARGET_ACCOUNT_QUERY: str = TARGET_ACCOUNT_HANDLE

# Scrape settings
NUM_POSTS: int = 5
MAX_LIKES_PER_POST: int = 500

# Google Apps Script Web App endpoint
# Deploy the Apps Script as a Web App and paste the URL here.
GAS_WEBAPP_URL: str = "https://script.google.com/a/macros/whiteswandata.com/s/AKfycbzwvH3R5mjh-pv_un2-VSsJb8KK3tXA7HpIbc5x4l2BUpm4S116p5y5CuJZLEMJaiDO/exec"  # e.g. "https://script.google.com/macros/s/AKfycbx.../exec"
WORKSHEET_NAME: str = "Likers"

# Browser/session
PLAYWRIGHT_SLOW_MO_MS: int = 150
AUTH_STORAGE_PATH: str = "auth.json"

# Timeouts
NAVIGATION_TIMEOUT_MS: int = 60_000
SELECTOR_TIMEOUT_MS: int = 25_000


