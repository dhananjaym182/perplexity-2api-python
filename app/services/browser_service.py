import logging
import asyncio
import os
import time
import json
import platform
import subprocess
import signal
import urllib.request
from urllib.error import URLError, HTTPError
from typing import Dict, Any, List
from botasaurus.browser_decorator import browser
from app.core.config import settings

logger = logging.getLogger(__name__)

# Detect if running in WSL
def is_wsl():
    """Check if running in Windows Subsystem for Linux"""
    try:
        with open('/proc/version', 'r') as f:
            return 'microsoft' in f.read().lower()
    except:
        return 'microsoft' in platform.uname().release.lower() or 'wsl' in platform.uname().release.lower()

IS_WSL = is_wsl()

# Detect Chrome path for WSL/Linux
def get_chrome_path():
    """Detect Chrome executable path, supporting WSL"""
    # Try Linux Chrome paths first (preferred in WSL2)
    linux_chrome_paths = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        os.path.expanduser("~/.local/bin/google-chrome"),
    ]
    for path in linux_chrome_paths:
        if os.path.exists(path):
            logger.info(f"🔍 Found Linux Chrome at: {path}")
            return path
    
    if IS_WSL:
        # In WSL, try Windows Chrome as fallback
        windows_chrome_paths = [
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        ]
        for path in windows_chrome_paths:
            if os.path.exists(path):
                logger.info(f"🔍 Found Windows Chrome at: {path}")
                return path
    
    # Return None to let Botasaurus auto-detect
    return None

CHROME_PATH = get_chrome_path()

# Additional Chrome arguments for headless/server environments (especially WSL2)
CHROME_ARGS = [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-software-rasterizer',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-default-apps',
    '--disable-sync',
    '--no-first-run',
    '--disable-setuid-sandbox',
    # '--single-process',  # REMOVED: causes Chrome to crash/become defunct
    '--disable-features=VizDisplayCompositor',  # Helps with headless mode
    '--remote-debugging-port=0',  # Let Chrome pick a random port
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-hang-monitor',
    '--disable-ipc-flooding-protection',
    '--disable-popup-blocking',
    '--disable-prompt-on-repost',
    '--disable-breakpad',  # Disable crash reporter
    '--metrics-recording-only',
    '--no-default-browser-check',
    '--password-store=basic',
    '--use-mock-keychain',
]

# Botasaurus browser configuration
BROWSER_OPTIONS = {
    "headless": True,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36",
    "window_size": (1366, 768),
    "add_arguments": CHROME_ARGS,
}

# Add chrome_executable_path if detected
if CHROME_PATH:
    BROWSER_OPTIONS["chrome_executable_path"] = CHROME_PATH

# Monkey-patch botasaurus_driver to increase Chrome startup timeout for WSL2
def patch_botasaurus_chrome_timeout():
    """Increase Chrome connection timeout for WSL2 environments"""
    try:
        import botasaurus_driver.core.browser as browser_module
        
        original_ensure_chrome_is_alive = browser_module.ensure_chrome_is_alive
        
        def patched_ensure_chrome_is_alive(url):
            """Patched version with longer timeout for WSL2"""
            start_time = time.time()
            timeout = 15  # Increased timeout per request (was 10)
            duration = 90  # Increased total duration (was 45) for slow WSL2 startup
            retry_delay = 1.0  # Increased delay between retries (was 0.5)
            
            logger.info(f"🔄 Waiting for Chrome at {url} (max {duration}s)...")
            
            attempt = 0
            while time.time() - start_time < duration:
                attempt += 1
                try:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        if response.status == 200:
                            data = response.read().decode('utf-8')
                            elapsed = time.time() - start_time
                            logger.info(f"✅ Chrome connected in {elapsed:.1f}s (attempt {attempt})")
                            return json.loads(data)
                except (URLError, HTTPError) as e:
                    elapsed = time.time() - start_time
                    if attempt % 5 == 0:  # Log every 5 attempts
                        logger.info(f"⏳ Still waiting for Chrome... ({elapsed:.1f}s, attempt {attempt})")
                    time.sleep(retry_delay)
                    continue
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.warning(f"⚠️ Unexpected error connecting to Chrome (attempt {attempt}, {elapsed:.1f}s): {e}")
                    time.sleep(retry_delay)
                    continue
            
            elapsed = time.time() - start_time
            raise Exception(f"Failed to connect to Chrome URL: {url} after {elapsed:.1f}s ({attempt} attempts). Chrome may have failed to start.")
        
        # Apply the patch
        browser_module.ensure_chrome_is_alive = patched_ensure_chrome_is_alive
        logger.info("✅ Patched botasaurus Chrome timeout for WSL2 compatibility (90s timeout)")
        
    except Exception as e:
        logger.warning(f"⚠️ Could not patch botasaurus timeout: {e}")

# Apply the patch at module load time
patch_botasaurus_chrome_timeout()

# Check if we have a display available (for non-headless mode)
def has_display():
    """Check if a display is available for GUI applications"""
    display = os.environ.get('DISPLAY')
    wayland = os.environ.get('WAYLAND_DISPLAY')
    # Check for WSLg
    wslg = os.path.exists('/mnt/wslg')
    return bool(display or wayland or wslg)

HAS_DISPLAY = has_display()

# Interactive login configuration (show browser window)
# If no display is available, fall back to headless mode with xvfb or just headless
if HAS_DISPLAY:
    INTERACTIVE_BROWSER_OPTIONS = {
        "headless": False,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36",
        "window_size": (1280, 800),
        "add_arguments": CHROME_ARGS,  # Use same args for stability
    }
else:
    # No display available - use headless mode for interactive login
    # User will need to use Cookie import instead of browser login
    logger.warning("⚠️ No display available - interactive browser login will use headless mode")
    INTERACTIVE_BROWSER_OPTIONS = {
        "headless": True,  # Fall back to headless since no display
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36",
        "window_size": (1280, 800),
        "add_arguments": CHROME_ARGS,
    }

# Add chrome_executable_path if detected
if CHROME_PATH:
    INTERACTIVE_BROWSER_OPTIONS["chrome_executable_path"] = CHROME_PATH

class BrowserService:
    def __init__(self):
        self.cached_cookies: Dict[str, str] = {}
        self.cached_user_agent: str = settings.PPLX_USER_AGENT
        self.last_refresh_time = 0
        self.refresh_interval = 300  # Don't refresh again within 5 minutes

    async def initialize_session(self):
        """Initialize: prioritize scanning local saved Cookie files, then try .env file"""
        logger.info("🚀 Initializing browser service (Botasaurus)...")
        try:
            # 1. First scan local data/cookies/ directory for Cookie files
            local_cookies_found = False
            cookies_dir = os.path.join("data", "cookies")
            
            if os.path.exists(cookies_dir):
                # Find all cookies.json files in subdirectories
                cookie_files = []
                for account_dir in os.listdir(cookies_dir):
                    account_path = os.path.join(cookies_dir, account_dir)
                    if os.path.isdir(account_path):
                        cookie_file = os.path.join(account_path, "cookies.json")
                        if os.path.exists(cookie_file):
                            # Get file modification time for sorting
                            mtime = os.path.getmtime(cookie_file)
                            cookie_files.append((mtime, cookie_file, account_dir))
                
                # Sort by modification time (newest first)
                cookie_files.sort(reverse=True)
                
                if cookie_files:
                    # Load the newest Cookie file
                    mtime, cookie_file, account_dir = cookie_files[0]
                    try:
                        with open(cookie_file, 'r', encoding='utf-8') as f:
                            cookie_data = json.load(f)
                        
                        cookies_dict = cookie_data.get("cookies", {})
                        user_agent = cookie_data.get("user_agent", self.cached_user_agent)
                        
                        if cookies_dict:
                            # Clean Cookie keys and values: remove PowerShell/CMD escape characters
                            cleaned_cookies = {}
                            import re
                            
                            for key, value in cookies_dict.items():
                                # Clean key name: remove various escape characters
                                cleaned_key = key
                                # Remove leading "-b ^\"" or similar prefix
                                cleaned_key = re.sub(r'^-[a-z]\s*\^?"?', '', cleaned_key)
                                # Remove ^" and ^% escapes
                                cleaned_key = cleaned_key.replace('^"', '').replace('^%', '%')
                                # Remove quotes
                                cleaned_key = cleaned_key.replace('"', '').replace("'", '')
                                # Remove leading/trailing whitespace
                                cleaned_key = cleaned_key.strip()
                                
                                # Clean value: remove escape characters
                                cleaned_value = value
                                if isinstance(cleaned_value, str):
                                    cleaned_value = cleaned_value.replace('^"', '').replace('^%', '%')
                                    cleaned_value = cleaned_value.replace('^', '').strip()
                                    # Remove trailing quotes
                                    cleaned_value = cleaned_value.rstrip('"').rstrip("'")
                                
                                # Special handling: ensure key cookie names are standardized
                                if "pplx.visitor-id" in cleaned_key:
                                    cleaned_key = "pplx.visitor-id"
                                elif "__Secure-next-auth.session-token" in cleaned_key:
                                    cleaned_key = "__Secure-next-auth.session-token"
                                elif "cf_clearance" in cleaned_key:
                                    cleaned_key = "cf_clearance"
                                elif "__cf_bm" in cleaned_key:
                                    cleaned_key = "__cf_bm"
                                elif "__cflb" in cleaned_key:
                                    cleaned_key = "__cflb"
                                
                                cleaned_cookies[cleaned_key] = cleaned_value
                                # Debug log: show key names before and after cleaning
                                if key != cleaned_key or value != cleaned_value:
                                    logger.debug(f"Cookie cleaned: '{key}' -> '{cleaned_key}'")
                            
                            self.cached_cookies = cleaned_cookies
                            self.cached_user_agent = user_agent
                            self.last_refresh_time = time.time()  # Set last refresh time to avoid immediate refresh
                            local_cookies_found = True
                            logger.info(f"📦 Loaded {len(self.cached_cookies)} Cookies from local directory (account: {account_dir})")
                            logger.debug(f"Cookie keys: {list(self.cached_cookies.keys())}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to load local Cookie file, skipping: {e}")
            
            # 2. If no local Cookie found, try loading from .env file
            if not local_cookies_found:
                initial_cookies_list = settings.get_initial_cookies_dict()
                if initial_cookies_list:
                    self.cached_cookies = {c["name"]: c["value"] for c in initial_cookies_list}
                    logger.info(f"📦 Loaded {len(self.cached_cookies)} initial Cookies from .env")
                    
                    # Try warm-up (not mandatory, failure doesn't affect startup)
                    try:
                        await self.refresh_context(force=True)
                    except Exception as e:
                        logger.warning(f"⚠️ Initial warm-up failed, but doesn't affect service startup: {e}")
                        logger.info("💡 Please add valid account Cookies via Web UI")
                else:
                    logger.info("ℹ️ No initial Cookies found, service started normally")
                    logger.info("💡 Please add accounts or import Cookies via Web UI to enable API functionality")
                    # Set empty cache, waiting for user to add
                    self.cached_cookies = {}
            else:
                # Local Cookie loaded successfully, log it
                logger.info("✅ Local Cookies loaded successfully, API functionality enabled")
                
        except Exception as e:
            logger.error(f"❌ Unexpected error during initialization: {e}")
            logger.info("💡 Service will continue to start, but please add accounts via Web UI")

    @staticmethod
    @browser(**BROWSER_OPTIONS)
    def _refresh_cookies_with_browser(driver, data) -> Dict[str, str]:
        """
        Botasaurus core function: visit page, handle verification, return latest Cookies
        data parameter: can be initial Cookie dict, or dict containing cookies and user_agent
        """
        # Handle two data formats
        if isinstance(data, dict) and "cookies" in data:
            # New format: dict containing cookies and user_agent
            initial_cookies = data.get("cookies", {})
            user_agent = data.get("user_agent")
        else:
            # Old format: direct cookie dict
            initial_cookies = data
            user_agent = None
        
        # User-Agent already set in browser options, skip runtime setting
        
        # If there are initial Cookies, set them first (add necessary fields)
        if initial_cookies:
            logger.info(f"Attempting to set {len(initial_cookies)} initial Cookies")
            # Create complete Cookie objects with all fields Botasaurus needs
            cookies_list = []
            for name, value in initial_cookies.items():
                cookie_obj = {
                    "name": name,
                    "value": value,
                    "domain": ".perplexity.ai",  # Use root domain so subdomains can also access
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax"
                }
                cookies_list.append(cookie_obj)
            
            try:
                driver.add_cookies(cookies_list)
                logger.debug(f"✅ Successfully set {len(cookies_list)} initial Cookies")
                logger.debug(f"Cookie names: {list(initial_cookies.keys())}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to set initial Cookies: {e}")
                logger.info("💡 Botasaurus will try to get Cookies on its own")

        # Visit target page (use google_get and bypass_cloudflare to better handle Cloudflare verification)
        driver.google_get(settings.TARGET_URL, bypass_cloudflare=True)
        
        # Wait for page to load (use sleep to wait)
        driver.sleep(5)
        
        # Check if still on verification page (more comprehensive check)
        title = driver.title
        current_url = driver.current_url
        logger.debug(f"Page title: {title}, URL: {current_url}")
        
        # Check multiple Cloudflare indicators: title, URL, page content
        is_cloudflare = (
            "Just a moment" in title or 
            "Cloudflare" in title or 
            "cloudflare" in current_url.lower() or
            "challenge" in current_url.lower() or
            "verify" in current_url.lower()
        )
        
        if is_cloudflare:
            logger.warning("⚠️ Cloudflare verification page detected, Botasaurus may be handling it...")
            
            # Try to further confirm via page content
            try:
                page_text = driver.run_js("return document.body.innerText || ''")
                if "cloudflare" in page_text.lower() or "ddos" in page_text.lower() or "verifying" in page_text.lower():
                    logger.warning("⚠️ Page content confirms it's a Cloudflare verification page")
            except:
                pass
            
            # Wait extra time for verification to complete (may be automatic or require manual)
            driver.sleep(15)
            
            # Check again
            title = driver.title
            current_url = driver.current_url
            is_still_cloudflare = (
                "Just a moment" in title or
                "Cloudflare" in title or
                "cloudflare" in current_url.lower()
            )
            
            if is_still_cloudflare:
                logger.error("❌ Still on Cloudflare verification page, trying different strategies...")
                
                # Strategy 1: Refresh page
                driver.reload()
                driver.sleep(10)
                
                # Check again
                title = driver.title
                if "Just a moment" in title or "Cloudflare" in title:
                    logger.error("❌ Still on verification page after refresh, trying different URL...")
                    
                    # Strategy 2: Try accessing login page directly instead of homepage
                    driver.get("https://www.perplexity.ai/login")
                    driver.sleep(10)
                    
                    # Final check
                    title = driver.title
                    if "Just a moment" in title or "Cloudflare" in title:
                        logger.error("❌ All strategies failed, Cloudflare verification may not be automatically bypassable")
                        # Continue execution, let user handle manually or return error
        
        # Get all Cookies (prefer using get_cookies_dict)
        cookies_dict = {}
        try:
            cookies_dict = driver.get_cookies_dict()
            logger.debug(f"Got {len(cookies_dict)} Cookies using get_cookies_dict")
        except AttributeError:
            try:
                cookies = driver.get_cookies()
                cookies_dict = {c["name"]: c["value"] for c in cookies}
                logger.debug(f"Got {len(cookies_dict)} Cookies using get_cookies")
            except AttributeError:
                # Last attempt: get via JavaScript
                cookie_str = driver.run_js("return document.cookie")
                if cookie_str:
                    cookies_dict = {pair.split("=")[0]: "=".join(pair.split("=")[1:]) for pair in cookie_str.split("; ") if pair}
                    logger.debug(f"Got {len(cookies_dict)} Cookies using JavaScript")
                else:
                    logger.debug("No Cookies obtained")
        
        # Log all Cookie keys for debugging
        logger.debug(f"Cookie keys: {list(cookies_dict.keys())}")
        
        # Check for critical Cookies
        if "pplx.visitor-id" not in cookies_dict:
            raise Exception("❌ Critical Cookie pplx.visitor-id not found")
        
        logger.info(f"✅ Botasaurus successfully obtained {len(cookies_dict)} Cookies")
        return cookies_dict

    def _update_env_file(self, new_cookies: Dict[str, str]):
        """
        [Persistence] Write latest Cookies back to .env file
        """
        try:
            # Construct Cookie string
            cookie_str = "; ".join([f"{k}={v}" for k, v in new_cookies.items()])
            env_path = ".env"
            
            if not os.path.exists(env_path):
                return

            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            new_lines = []
            updated = False
            for line in lines:
                if line.startswith("PPLX_COOKIE="):
                    new_lines.append(f'PPLX_COOKIE="{cookie_str}"\n')
                    updated = True
                else:
                    new_lines.append(line)
            
            if not updated:
                new_lines.append(f'PPLX_COOKIE="{cookie_str}"\n')

            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            
            logger.info("💾 Latest Cookies automatically saved to .env file (persistence successful)")
            
        except Exception as e:
            logger.error(f"❌ Failed to save Cookies to file: {e}")

    async def refresh_context(self, force=False):
        """
        Use Botasaurus to launch browser, visit page, auto-bypass shield, update Cookies
        """
        if not force and (time.time() - self.last_refresh_time < self.refresh_interval) and self.cached_cookies:
            return True

        logger.info("🔄 Launching Botasaurus browser for session keep-alive/renewal...")
        
        try:
            # Prepare data: contains initial Cookies and User-Agent
            data = {
                "cookies": self.cached_cookies,
                "user_agent": self.cached_user_agent
            }
            
            # Botasaurus is synchronous, run in thread pool in async environment
            new_cookies = await asyncio.to_thread(
                self.__class__._refresh_cookies_with_browser,
                data
            )
            
            # Check if Botasaurus returned valid result
            if new_cookies is None:
                logger.error("❌ Botasaurus returned None (possibly in debug mode or encountered verification issues)")
                return False
            
            if not isinstance(new_cookies, dict):
                logger.error(f"❌ Botasaurus returned non-dict type: {type(new_cookies)}")
                return False
            
            # Update cache
            self.cached_cookies = new_cookies
            self.last_refresh_time = time.time()
            logger.info(f"✅ Cookie refresh successful! Count: {len(self.cached_cookies)}")
            
            # Auto write back to file
            self._update_env_file(new_cookies)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Browser operation exception: {e}")
            return False

    def get_headers(self) -> Dict[str, str]:
        import re
        
        # Extract Chrome version from User-Agent
        chrome_version = "142"  # Default value
        if self.cached_user_agent:
            match = re.search(r'Chrome/(\d+)\.', self.cached_user_agent)
            if match:
                chrome_version = match.group(1)
        
        # Clean User-Agent: remove possible escape characters and extra characters
        user_agent = self.cached_user_agent
        if user_agent:
            # Remove possible trailing ^ or other escape characters
            user_agent = user_agent.rstrip('^" ').replace('^\"', '').replace('\"', '')
        
        return {
            "Host": "www.perplexity.ai",
            "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36",
            "Accept": "text/event-stream",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json",
            "Origin": settings.TARGET_URL,
            "Referer": f"{settings.TARGET_URL}/search/new",
            "Priority": "u=1, i",
            "sec-ch-ua": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not A(Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-perplexity-request-reason": "perplexity-query-state-provider"
        }

    def _update_env_with_cookies_and_ua(self, cookies: Dict[str, str], user_agent: str = None):
        """
        Update both Cookie and User-Agent in .env file simultaneously
        """
        try:
            env_path = ".env"
            if not os.path.exists(env_path):
                return

            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            new_lines = []
            cookie_updated = False
            ua_updated = False
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            ua = user_agent or self.cached_user_agent
            
            for line in lines:
                if line.startswith("PPLX_COOKIE="):
                    new_lines.append(f'PPLX_COOKIE="{cookie_str}"\n')
                    cookie_updated = True
                elif line.startswith("PPLX_USER_AGENT="):
                    new_lines.append(f'PPLX_USER_AGENT="{ua}"\n')
                    ua_updated = True
                else:
                    new_lines.append(line)
            
            if not cookie_updated:
                new_lines.append(f'PPLX_COOKIE="{cookie_str}"\n')
            if not ua_updated:
                new_lines.append(f'PPLX_USER_AGENT="{ua}"\n')

            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            
            logger.info("💾 Cookie and User-Agent saved to .env file")
            
        except Exception as e:
            logger.error(f"❌ Failed to save to .env file: {e}")

    def _save_account_data(self, account_name: str, cookies: Dict[str, str], user_agent: str = None,
                           is_update: bool = False, source: str = "manual") -> str:
        """
        Save account data to local directory (data/cookies/ and data/sessions/)
        Enhanced version: includes call statistics, timestamps and account status info
        
        Args:
            account_name: Account name
            cookies: Cookie dictionary
            user_agent: User-Agent string
            is_update: Whether it's an update operation (False means new)
            source: Data source ("manual", "import", "browser", "auto_refresh")
        
        Returns:
            Account directory path, None if failed
        """
        try:
            # Create account directory
            account_dir = os.path.join("data", "cookies", account_name)
            os.makedirs(account_dir, exist_ok=True)
            
            # Save Cookie to JSON file
            cookie_file = os.path.join(account_dir, "cookies.json")
            cookie_data = {
                "account_name": account_name,
                "cookies": cookies,
                "user_agent": user_agent or self.cached_user_agent,
                "saved_at": time.time(),
                "cookie_count": len(cookies),
                "version": "2.0"  # New version marker
            }
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookie_data, f, indent=2, ensure_ascii=False)
            
            # Save Cookie as text format (compatible with original format)
            cookie_txt_file = os.path.join(account_dir, "cookies.txt")
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            with open(cookie_txt_file, 'w', encoding='utf-8') as f:
                f.write(f"# Cookie for {account_name}\n")
                f.write(f"# Save time: {time.ctime()}\n")
                f.write(f"# User-Agent: {user_agent or self.cached_user_agent}\n")
                f.write(f"# Source: {source}\n\n")
                f.write(cookie_str)
            
            # Save session info (enhanced version)
            session_file = os.path.join("data", "sessions", f"{account_name}.json")
            
            # If updating, try to read existing session info to maintain statistics
            session_data = {
                "account_name": account_name,
                "created_at": time.time() if not is_update else self._get_session_value(session_file, "created_at", time.time()),
                "updated_at": time.time(),
                "last_login": time.time(),
                "last_used": None,  # Last call time
                "cookie_file": cookie_file,
                "status": "active",
                "source": source,
                "stats": {
                    "total_calls": self._get_session_value(session_file, "stats.total_calls", 0),
                    "success_calls": self._get_session_value(session_file, "stats.success_calls", 0),
                    "failed_calls": self._get_session_value(session_file, "stats.failed_calls", 0),
                    "consecutive_failures": self._get_session_value(session_file, "stats.consecutive_failures", 0),
                    "last_success": self._get_session_value(session_file, "stats.last_success", None),
                    "last_failure": self._get_session_value(session_file, "stats.last_failure", None)
                },
                "auto_maintenance": {
                    "enabled": True,
                    "last_check": None,
                    "failure_count": 0,
                    "next_check": time.time() + 3600  # Check after 1 hour
                },
                "directory_info": {
                    "account_dir": account_dir,
                    "cookie_json": cookie_file,
                    "cookie_txt": cookie_txt_file,
                    "session_file": session_file
                },
                "version": "2.0"
            }
            
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"💾 Account data saved to local directory: {account_dir} (source: {source})")
            return account_dir
            
        except Exception as e:
            logger.error(f"❌ Failed to save account data: {e}")
            return None
    
    def _get_session_value(self, session_file: str, key_path: str, default_value: Any) -> Any:
        """
        Read specified key value from session file
        
        Args:
            session_file: Session file path
            key_path: Key path, e.g. "stats.total_calls"
            default_value: Default value
        
        Returns:
            Read value or default value
        """
        if not os.path.exists(session_file):
            return default_value
        
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Support nested key paths
            keys = key_path.split('.')
            value = data
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default_value
            return value
        except Exception:
            return default_value

    @staticmethod
    @browser(**INTERACTIVE_BROWSER_OPTIONS)
    def _interactive_login_with_browser(driver, data) -> Dict[str, Any]:
        """
        Interactive login: open browser window, let user log in manually, return Cookies and User-Agent
        data: dict containing account_name
        """
        account_name = data.get("account_name", "New Account")
        logger.info(f"🔄 Starting interactive login flow: {account_name}")
        
        # Navigate to Perplexity home (login page), use google_get and bypass_cloudflare to handle Cloudflare verification
        driver.google_get("https://www.perplexity.ai", bypass_cloudflare=True)
        
        # Wait for page load and check Cloudflare verification status
        driver.sleep(5)
        
        # Check if still on verification page
        title = driver.title
        current_url = driver.current_url
        logger.debug(f"Page title: {title}, URL: {current_url}")
        
        if "Just a moment" in title or "Cloudflare" in title or "cloudflare" in current_url:
            logger.warning("⚠️ Cloudflare verification page detected, manual handling required...")
            
            # Use driver.prompt() to pause execution and let user complete verification manually
            # This will show a prompt in console and wait for user to press Enter
            prompt_message = (
                f"⚠️ Cloudflare verification page detected!\n\n"
                f"Account: {account_name}\n"
                f"Current page: {current_url}\n\n"
                f"Please complete Cloudflare verification in the browser window:\n"
                f"1. Click the verification button if needed\n"
                f"2. Wait for the page to redirect to Perplexity\n"
                f"3. After verification is complete, press Enter to continue the login flow\n\n"
                f"Press Enter to continue..."
            )
            
            try:
                driver.prompt(prompt_message)
                logger.info("✅ User confirmed Cloudflare verification is complete")
                
                # Wait for page to stabilize after verification
                driver.sleep(5)
                
                # Check if still on verification page
                title = driver.title
                current_url = driver.current_url
                if "Just a moment" in title or "Cloudflare" in title:
                    logger.warning("⚠️ Still on Cloudflare page after verification, trying reload...")
                    driver.reload()
                    driver.sleep(8)
            except Exception as e:
                logger.warning(f"⚠️ driver.prompt() failed (possibly non-interactive mode), continuing: {e}")
                # If prompt fails, wait for automatic verification
                driver.sleep(15)
        
        # Show login prompt message
        alert_message = f"Please log in to your Perplexity account\\n\\nAccount: {account_name}\\n\\nAfter login, keep the page open and click OK."
        driver.run_js(f"alert('{alert_message}');")
        
        # Wait for user to close alert and log in
        driver.sleep(15)  # Give user time to close popup and start login
        
        logger.info("⏳ Waiting for user login...")
        
        # Check if login succeeded (look for critical Cookies)
        for i in range(40):  # Wait up to 40*3 = 120 seconds (2 minutes)
            # Get all Cookies (prefer using get_cookies_dict)
            cookies_dict = {}
            try:
                cookies_dict = driver.get_cookies_dict()
                logger.debug(f"Got {len(cookies_dict)} Cookies using get_cookies_dict")
            except AttributeError:
                try:
                    cookies = driver.get_cookies()
                    cookies_dict = {c["name"]: c["value"] for c in cookies}
                    logger.debug(f"Got {len(cookies_dict)} Cookies using get_cookies")
                except AttributeError:
                    # Last attempt: get via JavaScript
                    cookie_str = driver.run_js("return document.cookie")
                    if cookie_str:
                        cookies_dict = {pair.split("=")[0]: "=".join(pair.split("=")[1:]) for pair in cookie_str.split("; ") if pair}
                        logger.debug(f"Got {len(cookies_dict)} Cookies using JavaScript")
                    else:
                        logger.debug("No Cookies obtained")
            
            # Log all Cookie keys for debugging
            logger.debug(f"Cookie keys: {list(cookies_dict.keys())}")
            
            # Check critical Cookies (Perplexity uses pplx.visitor-id and session-token)
            if "pplx.visitor-id" in cookies_dict:
                logger.info(f"✅ Login successful! Obtained {len(cookies_dict)} Cookies")
                
                # Get current User-Agent
                user_agent = driver.user_agent
                
                # Show success prompt
                driver.run_js("alert('✅ Login successful! Cookies captured.\\n\\nYou can now close the browser window.');")
                driver.sleep(3)  # Let user see the message
                
                return {
                    "cookies": cookies_dict,
                    "user_agent": user_agent,
                    "account_name": account_name,
                    "success": True,
                    "cookie_count": len(cookies_dict)
                }
            
            # Check every 3 seconds
            driver.sleep(3)
            
            # Show status every 10 checks
            if i % 10 == 0:
                remaining = 40 - i
                logger.info(f"⏳ Waiting for login... Remaining time: {remaining*3} seconds")
        
        # Timeout, login failed
        driver.run_js("alert('❌ Login timeout, no valid Cookies detected.\\n\\nPlease ensure you have successfully logged into your Perplexity account.');")
        driver.sleep(5)
        raise Exception("❌ Login timeout, no valid Cookies detected. Please ensure you have successfully logged in.")

    async def interactive_login(self, account_name: str = "New Account") -> Dict[str, Any]:
        """
        Async wrapper: perform interactive login and update configuration
        """
        logger.info(f"🚀 Starting interactive login: {account_name}")
        
        try:
            # Run Botasaurus synchronous function in a separate thread
            result = await asyncio.to_thread(
                self.__class__._interactive_login_with_browser,
                {"account_name": account_name}
            )
            
            if result.get("success"):
                # Update cache
                self.cached_cookies = result["cookies"]
                self.cached_user_agent = result["user_agent"]
                self.last_refresh_time = time.time()
                
                # Save to .env file (global configuration)
                self._update_env_with_cookies_and_ua(
                    result["cookies"], 
                    result["user_agent"]
                )
                
                # Save to local directory (account-specific data)
                account_dir = self._save_account_data(
                    account_name,
                    result["cookies"],
                    result["user_agent"],
                    source="browser"
                )
                
                # Update result
                result["account_dir"] = account_dir
                result["local_saved"] = account_dir is not None
                
                logger.info(f"✅ Interactive login completed! Account: {account_name}, data directory: {account_dir}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Interactive login failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "account_name": account_name
            }

    def get_cookies(self) -> Dict[str, str]:
        return self.cached_cookies

    def parse_cookie_string(self, text: str, account_name: str = "Imported Account") -> Dict[str, Any]:
        """
        Extract Cookies and User-Agent from arbitrary text (similar to config_wizard.py)
        Supported formats: HAR JSON, PowerShell, cURL, plain Cookie string
        """
        import re
        import json
        
        logger.info(f"🔍 Starting to parse Cookie string, account: {account_name}")
        
        cookie_str = ""
        user_agent = ""
        text = text.strip()
        
        # 1. Try JSON parsing (HAR format)
        if text.startswith('{') or text.startswith('['):
            try:
                data = json.loads(text)
                # Recursively search for Cookie and User-Agent
                def search_json(obj, path=""):
                    nonlocal cookie_str, user_agent
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            if isinstance(key, str) and key.lower() == 'cookie' and isinstance(value, str):
                                cookie_str = value
                            elif isinstance(key, str) and 'user-agent' in key.lower() and isinstance(value, str):
                                user_agent = value
                            elif isinstance(value, (dict, list)):
                                search_json(value, f"{path}.{key}")
                    elif isinstance(obj, list):
                        for item in obj:
                            search_json(item, path)
                
                search_json(data)
            except:
                pass  # Not valid JSON
        
        # 2. If still not found, try PowerShell format
        if not cookie_str:
            pattern = r'New-Object System\.Net\.Cookie\("([^"]+)",\s*"([^"]+)"'
            matches = re.findall(pattern, text)
            if matches:
                cookie_parts = []
                for key, value in matches:
                    cookie_parts.append(f"{key}={value}")
                cookie_str = "; ".join(cookie_parts)
        
        # 3. If still not found, try generic regex (key=value format)
        if not cookie_str:
            # Look for lines containing pplx.visitor-id
            lines = text.splitlines()
            for line in lines:
                if "pplx.visitor-id" in line and "=" in line:
                    if "Cookie:" in line:
                        cookie_str = line.split("Cookie:", 1)[1].strip()
                    elif ";" in line and "=" in line:
                        cookie_str = line.strip()
                    break
        
        # 4. Try to directly parse as Cookie string (user may have pasted raw Cookies)
        if not cookie_str and "=" in text and ";" in text:
            # Check if it looks like a Cookie string
            cookie_candidates = re.findall(r'([^=;]+=[^=;]+)(?:;|$)', text)
            if cookie_candidates and len(cookie_candidates) > 1:
                cookie_str = "; ".join(cookie_candidates)
        
        # 5. Extract User-Agent
        if not user_agent:
            ua_match = re.search(r'User-Agent["\']?\s*[:=]\s*["\']?([^"\']+)["\']?', text, re.IGNORECASE)
            if ua_match:
                user_agent = ua_match.group(1).strip()
        
        # 6. If still no User-Agent, use default value
        if not user_agent:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36"
        
        # 7. Process result
        if cookie_str:
            # Parse Cookie string into dict
            cookies_dict = {}
            for pair in cookie_str.split(';'):
                pair = pair.strip()
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    cookies_dict[key.strip()] = value.strip()
            
            logger.info(f"✅ Parse successful! Extracted {len(cookies_dict)} Cookies")
            
            # Save account data
            account_dir = self._save_account_data(account_name, cookies_dict, user_agent, source="import")
            
            # Also update cached Cookies (take effect immediately)
            self.cached_cookies = cookies_dict
            self.cached_user_agent = user_agent
            self.last_refresh_time = time.time()
            logger.info(f"✅ Updated cached Cookies, total {len(cookies_dict)}")
            
            return {
                "success": True,
                "account_name": account_name,
                "cookie_count": len(cookies_dict),
                "user_agent": user_agent,
                "cookies_dict": cookies_dict,
                "account_dir": account_dir,
                "local_saved": account_dir is not None
            }
        else:
            logger.warning("❌ Failed to extract valid Cookies from text")
            return {
                "success": False,
                "error": "Failed to extract valid Cookies from text. Please ensure the content contains 'pplx.visitor-id' or a complete Cookie string.",
                "account_name": account_name
            }

    def get_account_session(self, account_name: str) -> Dict[str, Any]:
        """
        Get account session data
        """
        session_file = os.path.join("data", "sessions", f"{account_name}.json")
        if not os.path.exists(session_file):
            return None
        
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read session file: {e}")
            return None

    async def verify_cookie(self, account_name: str, headless: bool = True) -> Dict[str, Any]:
        """
        Verify Cookie validity (optionally show browser)
        
        Args:
            account_name: Account name
            headless: Whether to use headless mode (True for background verification, False to show browser)
        
        Returns:
            Verification result dict
        """
        logger.info(f"🔍 Starting Cookie validity verification, account: {account_name}")
        
        # Get session data
        session_data = self.get_account_session(account_name)
        if not session_data:
            return {
                "success": False,
                "valid": False,
                "error": "Account session data does not exist",
                "account_name": account_name
            }
        
        cookie_file = session_data.get("cookie_file")
        if not cookie_file or not os.path.exists(cookie_file):
            return {
                "success": False,
                "valid": False,
                "error": "Cookie file does not exist",
                "account_name": account_name
            }
        
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookie_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read Cookie file: {e}")
            return {
                "success": False,
                "valid": False,
                "error": f"Failed to read Cookie file: {e}",
                "account_name": account_name
            }
        
        cookies = cookie_data.get("cookies", {})
        user_agent = cookie_data.get("user_agent", self.cached_user_agent)
        
        if not cookies:
            return {
                "success": False,
                "valid": False,
                "error": "Cookie data is empty",
                "account_name": account_name
            }
        
        # Prepare verification data
        data = {
            "cookies": cookies,
            "user_agent": user_agent,
            "account_name": account_name
        }
        
        try:
            # Use Botasaurus to verify Cookies
            # Note: here we use _refresh_cookies_with_browser only for verification
            # We pass existing Cookies to check if access works
            result = await asyncio.to_thread(
                self.__class__._refresh_cookies_with_browser,
                data
            )
            
            # If a Cookie dict is returned successfully, verification passed
            if result and isinstance(result, dict) and "pplx.visitor-id" in result:
                # Update last verification time in session data
                session_data["last_verification"] = time.time()
                session_data["verification_status"] = "valid"
                
                # Save updated session data
                session_file = os.path.join("data", "sessions", f"{account_name}.json")
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(session_data, f, indent=2, ensure_ascii=False)
                
                return {
                    "success": True,
                    "valid": True,
                    "account_name": account_name,
                    "cookie_count": len(result),
                    "message": "✅ Cookie verification passed!",
                    "verification_time": time.time()
                }
            else:
                return {
                    "success": False,
                    "valid": False,
                    "account_name": account_name,
                    "error": "Cookie verification failed: no valid Cookies obtained",
                    "verification_time": time.time()
                }
                
        except Exception as e:
            logger.error(f"Cookie verification exception: {e}")
            return {
                "success": False,
                "valid": False,
                "account_name": account_name,
                "error": f"Verification exception: {str(e)}",
                "verification_time": time.time()
            }