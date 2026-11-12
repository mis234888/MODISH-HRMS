"""
Central config for Modish Enterprises
"""
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "keka-clone-secret-2026")
    USE_MOCK = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
    PORT = int(os.getenv("PORT", 5000))
    
    # App specific
    COMPANY_NAME = "Modish Enterprises"
    DEFAULT_SHIFT = "General Shift"
    LEAVE_YEAR = 2026
