BOT_TOKEN = "8258353048:AAGUC5iygvTHyDXOX7N_1DGCbX_oMFt7pe4"
API_ID = 34227994
API_HASH = "e41d1f3aa94f97f07e5d4e8126cfa35e"
ADMIN_IDS = [1526536345]
ACCOUNTS_PER_PROXY = 2

# Tiger SMS API Key
TIGER_API_KEY = "5lSQtpVENAT4WoIHx8LfVRyPCqKquAx5"

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_DIR = os.path.join(BASE_DIR, "accounts")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

os.makedirs(ACCOUNTS_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)
