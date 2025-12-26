from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "perplexity-2api"
    APP_VERSION: str = "2.2.0"
    API_MASTER_KEY: str = "1"
    NGINX_PORT: int = 8092
    
    FLARESOLVERR_URL: str = "http://localhost:8191/v1"
    TARGET_URL: str = "https://www.perplexity.ai"
    API_URL: str = "https://www.perplexity.ai/rest/sse/perplexity_ask"

    # Read from .env
    PPLX_COOKIE: str = ""
    PPLX_USER_AGENT: str = ""

    MODELS: List[str] = [
        "gemini30pro", 
        "gpt-4o",
        "claude-3-opus",
        "sonar-reasoning-pro",
        "sonar-pro"
    ]
    DEFAULT_MODEL: str = "gemini30pro"

    def get_initial_cookies_dict(self) -> List[Dict[str, str]]:
        """Parse Cookie string"""
        cookies = []
        raw_cookie = self.PPLX_COOKIE
        
        if not raw_cookie:
            return cookies
        
        # Clean: remove possible leading/trailing quotes (if .env parser didn't handle it)
        if raw_cookie.startswith('"') and raw_cookie.endswith('"'):
            raw_cookie = raw_cookie[1:-1]
        
        for item in raw_cookie.split(';'):
            if '=' in item:
                name, value = item.strip().split('=', 1)
                if name and value:
                    cookies.append({
                        "name": name,
                        "value": value,
                        "url": self.TARGET_URL
                    })
        return cookies

settings = Settings()