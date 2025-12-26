import logging
import asyncio
import random
import os
import time
import math
from playwright.async_api import async_playwright
from app.core.config import settings

logger = logging.getLogger(__name__)

class TurnstileSolver:
    async def _human_mouse_move(self, page, start_x, start_y, end_x, end_y):
        """
        Simulate human mouse movement trajectory (Bezier curve + random jitter + variable speed)
        """
        steps = random.randint(30, 60) # Increase steps for smoother movement
        for i in range(steps):
            t = i / steps
            # Bezier curve interpolation
            x = start_x + (end_x - start_x) * t
            y = start_y + (end_y - start_y) * t
            
            # Add sine wave jitter (simulate hand tremor)
            x += random.uniform(-2, 2) * math.sin(t * math.pi)
            y += random.uniform(-2, 2) * math.sin(t * math.pi)
            
            await page.mouse.move(x, y)
            
            # Variable speed movement: fast in the middle, slow at both ends
            sleep_time = random.uniform(0.001, 0.01)
            if 0.2 < t < 0.8:
                sleep_time /= 2
            await asyncio.sleep(sleep_time)
            
        # Ensure precise arrival at the end
        await page.mouse.move(end_x, end_y)

    async def _apply_stealth(self, page):
        """Inject stealth script to remove automation fingerprints"""
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter(parameter);
            };
        """)

    async def get_token(self) -> str:
        logger.info("Starting Playwright (fully humanized mode)...")
        token_future = asyncio.get_running_loop().create_future()
        
        os.makedirs("/app/debug", exist_ok=True)
        timestamp = int(time.time())
        debug_prefix = f"/app/debug/run_{timestamp}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, # Recommended to keep True for debugging, rely on screenshots
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                ]
            )
            
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                record_video_dir="/app/debug",
                record_video_size={"width": 1280, "height": 720}
            )
            
            page = await context.new_page()
            await self._apply_stealth(page)

            # --- Listen for Token ---
            async def handle_request(request):
                if "/api/web/generate-basic" in request.url and request.method == "POST":
                    try:
                        post_data = request.post_data_json
                        if post_data and "turnstile_token" in post_data:
                            token = post_data["turnstile_token"]
                            logger.info(f"🔥🔥🔥 Captured Token: {token[:20]}...")
                            if not token_future.done():
                                token_future.set_result(token)
                    except:
                        pass
            page.on("request", handle_request)

            try:
                logger.info(f"Visiting: {settings.TARGET_URL}")
                await page.goto(settings.TARGET_URL, wait_until="domcontentloaded", timeout=60000)

                # 1. Input Prompt (keep original logic)
                try:
                    logger.info("Looking for input field...")
                    textarea = await page.wait_for_selector('textarea', state="visible", timeout=15000)
                    
                    # Humanized click on input field
                    box = await textarea.bounding_box()
                    if box:
                        await self._human_mouse_move(page, 0, 0, box['x'] + box['width']/2, box['y'] + box['height']/2)
                        await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    
                    await asyncio.sleep(0.5)
                    await page.keyboard.type("a cyberpunk cat", delay=random.randint(50, 150)) # Random typing speed
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Input field operation exception: {e}")

                # 2. Click generate button (keep original logic)
                try:
                    logger.info("Clicking generate button...")
                    btn = await page.wait_for_selector('button:has-text("Generate")', state="visible", timeout=5000)
                    
                    # Humanized click on button
                    box = await btn.bounding_box()
                    if box:
                        await self._human_mouse_move(page, 500, 500, box['x'] + box['width']/2, box['y'] + box['height']/2)
                        await asyncio.sleep(0.2)
                        await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    else:
                        await btn.click()
                except:
                    logger.warning("Generate button not found")

                # 3. CAPTCHA handling (core upgrade: reaction time + hover + physical click)
                logger.info("Entering CAPTCHA handling process...")
                
                start_time = time.time()
                clicked = False
                
                while not token_future.done():
                    if time.time() - start_time > 60:
                        logger.error("Verification timeout")
                        break
                    
                    # Check for Error
                    if await page.get_by_text("Error").is_visible():
                        logger.error("Page shows Error, refreshing and retrying...")
                        await page.reload()
                        clicked = False
                        start_time = time.time()
                        await asyncio.sleep(3)
                        continue

                    # Find Cloudflare iframe element (get its coordinates on the main page)
                    iframe_element = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
                    
                    if iframe_element:
                        box = await iframe_element.bounding_box()
                        # Ensure iframe has rendered with dimensions
                        if box and box['width'] > 0 and box['height'] > 0:
                            if not clicked:
                                logger.info(f"Found CAPTCHA iframe, coordinates: ({box['x']}, {box['y']})")
                                await page.screenshot(path=f"{debug_prefix}_found.png")

                                # --- Key Step 1: Reaction Time ---
                                reaction_time = random.uniform(1.5, 3.0)
                                logger.info(f"Simulating human reaction time: waiting {reaction_time:.2f} seconds...")
                                await asyncio.sleep(reaction_time)

                                # --- Key Step 2: Calculate target coordinates (left checkbox position + random offset) ---
                                # Turnstile is about 300 wide, 65 high. Checkbox is on the left.
                                target_x = box['x'] + 30 + random.uniform(-5, 5)
                                target_y = box['y'] + (box['height'] / 2) + random.uniform(-5, 5)
                                
                                # --- Key Step 3: Humanized Movement ---
                                logger.info(f"Moving mouse to: ({target_x:.1f}, {target_y:.1f})")
                                # Assume current mouse is near center of screen, or at last click position
                                await self._human_mouse_move(page, 960, 540, target_x, target_y)

                                # --- Key Step 4: Hover ---
                                hover_time = random.uniform(0.3, 0.8)
                                logger.info(f"Hover confirmation: {hover_time:.2f} seconds...")
                                await asyncio.sleep(hover_time)

                                # --- Key Step 5: Physical Click ---
                                logger.info("Executing physical click (Down -> Sleep -> Up)...")
                                await page.mouse.down()
                                await asyncio.sleep(random.uniform(0.08, 0.15)) # Simulate key press duration
                                await page.mouse.up()
                                
                                clicked = True
                                logger.info("Click completed, waiting for verification to pass...")
                                await page.screenshot(path=f"{debug_prefix}_clicked.png")
                                
                            else:
                                # Already clicked, waiting for result
                                pass
                        else:
                            # iframe exists but hasn't expanded yet
                            pass
                    else:
                        # iframe not found yet
                        pass

                    # If no response 20 seconds after clicking, reset state and retry
                    if clicked and (time.time() - start_time) % 20 < 1:
                         logger.info("Waited too long, resetting state to retry...")
                         clicked = False

                    await asyncio.sleep(1)

                if token_future.done():
                    return token_future.result()
                return ""

            except Exception as e:
                logger.error(f"Process error: {e}")
                await page.screenshot(path=f"{debug_prefix}_error.png")
                return ""
            finally:
                await context.close()
                await browser.close()
                try:
                    video_files = [f for f in os.listdir("/app/debug") if f.endswith(".webm")]
                    if video_files:
                        latest = max([os.path.join("/app/debug", f) for f in video_files], key=os.path.getctime)
                        os.rename(latest, f"{debug_prefix}_recording.webm")
                except: pass