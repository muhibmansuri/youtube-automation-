import os
import sys
import subprocess
import re
import time
import asyncio
from pathlib import Path
from typing import List, Optional, Callable
from playwright.async_api import async_playwright, BrowserContext, Page
from config import (
    BROWSER_PROFILE_DIR,
    TAAFT_URL,
    GENERATION_TIMEOUT_SECONDS,
    POLLING_INTERVAL_SECONDS,
    SCREENSHOT_INTERVAL_SECONDS,
    MAX_DAILY_VIDEOS
)

class TAAFTBrowserWorker:
    """Automates the TAAFT Video Generator interface using Playwright with persistent sessions."""

    def __init__(self, 
                 profile_dir: Optional[Path] = None, 
                 headless: bool = True,
                 log_callback: Optional[Callable[[str, str], None]] = None,
                 preview_callback: Optional[Callable[[str], None]] = None):
        self.profile_dir = Path(profile_dir or BROWSER_PROFILE_DIR)
        self.headless = headless
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))
        self.preview_callback = preview_callback
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._stop_requested = False
        self._last_dialog_message: Optional[str] = None

    def request_stop(self):
        """Signals worker to gracefully abort current operations."""
        self._stop_requested = True

    async def initialize(self):
        """Initializes the persistent browser context."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()

        # Clean any stale lock files if browser crashed previously
        for lock_name in ["SingletonLock", "lockfile", "SingletonCookie", "SingletonSocket", "parent.lock"]:
            try:
                lf = self.profile_dir / lock_name
                if lf.exists():
                    lf.unlink()
            except Exception:
                pass

        if sys.platform == "win32":
            try:
                kill_script = (
                    f"Get-Process chrome, msedge -ErrorAction SilentlyContinue | "
                    f"Where-Object {{ try {{ (Get-CimInstance Win32_Process -Filter \"ProcessId = $($_.Id)\").CommandLine -like '*{self.profile_dir.name}*' }} catch {{ $false }} }} | "
                    f"Stop-Process -Force -ErrorAction SilentlyContinue"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", kill_script], capture_output=True, timeout=5)
            except Exception:
                pass

        # Detect real Google Chrome or Edge to avoid version mismatch with profile
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        ]
        selected_executable = None
        for cp in chrome_paths:
            if os.path.exists(cp):
                selected_executable = cp
                break

        # Stealth and realistic args to bypass unnecessary bot flags
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-browser-side-navigation",
            "--disable-gpu",
            "--start-maximized"
        ]

        launch_kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
            "args": launch_args,
            "ignore_default_args": ["--enable-automation"],
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "accept_downloads": True
        }

        if selected_executable:
            self.log("info", f"Using installed system browser: {selected_executable}")
            launch_kwargs["executable_path"] = selected_executable

        try:
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as launch_err:
            if "closed" in str(launch_err).lower() or "target" in str(launch_err).lower():
                self.log("warning", "Browser launch failed. An existing Chrome instance might still be running or holding the profile lock.")
                self.log("info", "Retrying launch without executable_path fallback...")
                launch_kwargs.pop("executable_path", None)
                self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            else:
                raise launch_err

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(45000)

        async def _on_dialog(dialog):
            msg = dialog.message
            self._last_dialog_message = msg
            self.log("warning", f"TAAFT browser dialog: {msg}")
            try:
                await dialog.dismiss()
            except Exception:
                pass

        self.page.on("dialog", lambda d: asyncio.create_task(_on_dialog(d)))
        self.log("info", f"Persistent browser profile loaded from: {self.profile_dir}")

    async def close(self):
        """Closes browser context and playwright runtime."""
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.page = None
        self.context = None
        self.playwright = None

    async def capture_screenshot(self, save_path: str):
        """Saves current page screenshot for UI live preview."""
        try:
            if self.page and not self.page.is_closed():
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                await self.page.screenshot(path=save_path, full_page=False)
                try:
                    Path(save_path).with_suffix(".html").write_text(await self.page.content(), encoding="utf-8")
                except Exception:
                    pass
                if self.preview_callback:
                    self.preview_callback(save_path)
        except Exception:
            pass

    async def ensure_browser_alive(self):
        """Checks if browser context/page is still open; if closed or crashed, re-initializes it."""
        needs_reinit = False
        if not self.context or not self.page:
            needs_reinit = True
        else:
            try:
                if self.page.is_closed():
                    needs_reinit = True
                else:
                    await self.page.evaluate("1")
            except Exception:
                needs_reinit = True

        if needs_reinit:
            self.log("warning", "🔄 Browser page/window was closed. Automatically re-opening browser session...")
            await self.close()
            await asyncio.sleep(1.5)
            await self.initialize()

    async def navigate_to_taaft(self, preview_save_path: Optional[str] = None) -> dict:
        """Navigates to TAAFT and checks for Cloudflare verification or login state."""
        await self.ensure_browser_alive()
        self.log("info", f"Navigating to TAAFT Video Generator: {TAAFT_URL}")
        try:
            response = await self.page.goto(TAAFT_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)

            if preview_save_path:
                await self.capture_screenshot(preview_save_path)

            title = await self.page.title()
            content = await self.page.content()

            # Check Cloudflare challenge
            if "Just a moment..." in title or "cf-turnstile" in content or "challenge-running" in content or "security verification" in content.lower():
                self.log("warning", "🛑 Cloudflare Turnstile verification detected! Manual human verification needed.")
                self.log("info", "👉 Please click 'Open Interactive Browser' in the dashboard to complete the verification once.")
                return {
                    "success": False,
                    "blocked_by_cf": True,
                    "message": "Cloudflare anti-bot challenge detected. Please launch the interactive browser to verify."
                }

            # Check if user is logged in
            is_logged_in = await self._check_logged_in()
            quota_info = await self.check_daily_quota()

            return {
                "success": True,
                "is_logged_in": is_logged_in,
                "quota_info": quota_info,
                "page_title": title
            }
        except Exception as e:
            self.log("error", f"Navigation error: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _check_logged_in(self) -> bool:
        """Determines if the current session is logged into TAAFT."""
        try:
            # Look for common login/signup links vs logged-in state
            login_btn = await self.page.query_selector("a:has-text('Log in'), button:has-text('Log in'), a:has-text('Sign In'), button:has-text('Sign in with Google')")
            if login_btn and await login_btn.is_visible():
                return False
            return True
        except Exception:
            return True

    async def check_daily_quota(self) -> dict:
        """Parses the 'X of 100 videos left today' counter from the DOM."""
        try:
            text = await self.page.inner_text("body")
            # Regex match: "100 of 100 videos left today" or "42 of 100 videos left"
            match = re.search(r"(\d+)\s+of\s+(\d+)\s+videos\s+left", text, re.IGNORECASE)
            if match:
                left = int(match.group(1))
                total = int(match.group(2))
                self.log("info", f"Daily Quota: {left} of {total} videos remaining today.")
                return {"videos_left": left, "total_quota": total, "is_exhausted": left == 0}
            
            # Alternative match: "X videos left"
            alt_match = re.search(r"(\d+)\s+videos?\s+left\s+today", text, re.IGNORECASE)
            if alt_match:
                left = int(alt_match.group(1))
                return {"videos_left": left, "total_quota": MAX_DAILY_VIDEOS, "is_exhausted": left == 0}
            
            return {"videos_left": MAX_DAILY_VIDEOS, "total_quota": MAX_DAILY_VIDEOS, "is_exhausted": False}
        except Exception as e:
            self.log("warning", f"Could not inspect quota: {str(e)}")
            return {"videos_left": MAX_DAILY_VIDEOS, "total_quota": MAX_DAILY_VIDEOS, "is_exhausted": False}

    async def generate_scene_clip(self, 
                                  scene_number: int,
                                  prompt_text: str,
                                  ref_image_paths: List[str],
                                  output_clip_path: str,
                                  preview_save_path: str,
                                  model: str = "Quality",
                                  orientation: str = "Landscape",
                                  extend_mode: bool = False,
                                  timeout_seconds: int = GENERATION_TIMEOUT_SECONDS) -> dict:
        """
        Executes the full automated workflow for a single 8-second clip on TAAFT:
        1. Fills prompt
        2. Uploads reference images (Master Char + Last Frame)
        3. Configures Model and Orientation
        4. Ensures 'Enhance my prompt' is unchecked
        5. Clicks Generate
        6. Polls until Download button appears
        7. Downloads and saves clip
        """
        self._stop_requested = False
        Path(output_clip_path).parent.mkdir(parents=True, exist_ok=True)

        self.log("info", f"--- Starting generation for Scene #{scene_number:03d} {'[EXTEND MODE]' if extend_mode else ''} ---")

        used_extend_flow = False
        prev_download_href = ""

        # Try TAAFT's native 'Extend video' (#videogen_extend_open) BEFORE reloading the page
        if extend_mode and scene_number > 1 and self.page and not self.page.is_closed():
            try:
                extend_open_btn = await self.page.query_selector("#videogen_extend_open:not(.hidden)")
                if extend_open_btn and await extend_open_btn.is_visible():
                    # Remember previous clip's download href so we don't accidentally re-download it
                    cur_dl = await self.page.query_selector("#videogen_download")
                    if cur_dl:
                        prev_download_href = (await cur_dl.get_attribute("href") or "").strip()

                    self.log("info", "🎬 Using TAAFT native 'Extend video' for 100% seamless unbroken continuation...")
                    await extend_open_btn.scroll_into_view_if_needed()
                    try:
                        await extend_open_btn.click(force=True, timeout=5000)
                    except Exception:
                        await self.page.evaluate("document.querySelector('#videogen_extend_open')?.click()")
                    await asyncio.sleep(1.5)

                    ext_prompt_el = await self.page.query_selector(".videogen_extend_prompt")
                    ext_submit_btn = await self.page.query_selector(".videogen_extend_submit")
                    if ext_prompt_el and ext_submit_btn and await ext_prompt_el.is_visible():
                        # Attach character master ref images only (no need for last_frame since TAAFT extends natively)
                        ext_valid_imgs = [img for img in ref_image_paths if img and os.path.exists(img) and "last_frame_" not in os.path.basename(img)]
                        ext_attached = 0
                        if ext_valid_imgs:
                            ext_file_inp = await self.page.query_selector(".videogen_extend_image_input")
                            if ext_file_inp:
                                try:
                                    await ext_file_inp.set_input_files(ext_valid_imgs)
                                    await asyncio.sleep(2)
                                    ext_attached = len(ext_valid_imgs)
                                    self.log("info", f"Attached {ext_attached} character reference(s) to Extend flow.")
                                except Exception as ex_img_err:
                                    self.log("warning", f"Extend image upload note: {str(ex_img_err)}")

                        ext_prompt = self._sanitize_image_tags(prompt_text, ext_attached)
                        try:
                            await ext_prompt_el.click(force=True, timeout=5000)
                        except Exception:
                            pass
                        await ext_prompt_el.fill(ext_prompt)
                        await ext_prompt_el.dispatch_event("input")
                        await ext_prompt_el.dispatch_event("change")

                        # Ensure Extend's 'Enhance my prompt' toggle is unchecked
                        ext_enh = await self.page.query_selector(".videogen_extend_enhance")
                        if ext_enh and await ext_enh.is_checked():
                            await ext_enh.uncheck()

                        self._last_dialog_message = None
                        await ext_submit_btn.scroll_into_view_if_needed()
                        try:
                            await ext_submit_btn.click(force=True, timeout=5000)
                        except Exception:
                            await self.page.evaluate("document.querySelector('.videogen_extend_submit')?.click()")
                        await asyncio.sleep(5)
                        await self.capture_screenshot(preview_save_path)
                        used_extend_flow = True
                        self.log("info", "✅ Native 'Extend video' submitted successfully!")
            except Exception as ext_err:
                self.log("warning", f"Native Extend mode unavailable ({str(ext_err)}). Falling back to Last-Frame chaining...")
                used_extend_flow = False
                prev_download_href = ""

        if not used_extend_flow:
            # Step 0: Ensure page is ready
            nav_res = await self.navigate_to_taaft(preview_save_path)
            if not nav_res.get("success"):
                return nav_res

            if not nav_res.get("is_logged_in", True):
                self.log("warning", "🛑 TAAFT Account Login Required! TAAFT requires a free Google/Email login to generate videos.")
                return {
                    "success": False,
                    "login_required": True,
                    "message": "TAAFT Account Login Required. Please click 'Launch Browser Login' or run login.bat and sign in with Google once."
                }

            # Check quota
            quota = await self.check_daily_quota()
            if quota.get("is_exhausted"):
                self.log("warning", "Daily generation limit reached (0 videos left today). Pausing pipeline.")
                return {"success": False, "quota_exhausted": True, "message": "Daily generation quota exhausted"}

            # Step 1: Upload Reference Images FIRST so we know exact attached count for <Image N> tags
            valid_images = [img for img in ref_image_paths if img and os.path.exists(img)]
            attached_count = 0
            if valid_images:
                self.log("info", f"Attaching {len(valid_images)} reference image(s): {[os.path.basename(p) for p in valid_images]}")
                file_input = await self._find_file_input()
                if file_input:
                    try:
                        await file_input.set_input_files(valid_images)
                        await asyncio.sleep(2)
                        # Verify how many images TAAFT actually accepted in #videogen_image_list
                        uploaded_items = await self.page.query_selector_all("#videogen_image_list li.videogen_image")
                        attached_count = len(uploaded_items) if uploaded_items else len(valid_images)
                        self.log("info", f"Reference images attached ({attached_count} active in TAAFT).")
                    except Exception as img_err:
                        self.log("warning", f"File input upload note: {str(img_err)}")
                else:
                    self.log("warning", "File input element not directly found. Continuing without reference images...")

            # Step 2: Sanitize <Image N> tags to match exact number of attached images
            sanitized_prompt = self._sanitize_image_tags(prompt_text, attached_count)
            if sanitized_prompt != prompt_text:
                self.log("info", f"Adjusted <Image N> references in prompt for {attached_count} attached image(s).")

            # Input Prompt into "Your prompt" textarea
            self.log("info", f"Entering prompt ({len(sanitized_prompt)} chars)...")
            prompt_textarea = await self._find_prompt_textarea()
            if not prompt_textarea:
                await self.capture_screenshot(preview_save_path)
                return {"success": False, "error": "Could not locate 'Your prompt' textarea on TAAFT interface."}

            # Clear and fill prompt
            await prompt_textarea.scroll_into_view_if_needed()
            try:
                await prompt_textarea.click(force=True, timeout=5000)
            except Exception:
                await self.page.evaluate("document.querySelector('textarea#prompt, #videogen_prompt')?.focus()")
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")
            await prompt_textarea.fill(sanitized_prompt)
            await prompt_textarea.dispatch_event("input")
            await prompt_textarea.dispatch_event("change")
            await asyncio.sleep(1)

            # Step 3: Model and Orientation Configuration
            await self._select_model(model)
            await self._select_orientation(orientation)

            # Step 4: Ensure 'Enhance my prompt' is strictly UNCHECKED
            await self._ensure_prompt_enhance_unchecked()

            await self.capture_screenshot(preview_save_path)

            # Step 5: Click Generate Button
            self._last_dialog_message = None
            generate_btn = await self._find_generate_button()
            if not generate_btn:
                await self.capture_screenshot(preview_save_path)
                return {"success": False, "error": "Could not locate 'Generate' button on TAAFT."}

            self.log("info", "Clicking 'Generate' button (#generate)...")

            # Wait briefly if an upload overlay or .loading is still settling
            try:
                await self.page.wait_for_selector(".generate_wrap.loading", state="detached", timeout=8000)
            except Exception:
                pass

            clicked = False
            # Method 1: Playwright force click (bypasses pointer interception)
            try:
                await generate_btn.scroll_into_view_if_needed()
                await generate_btn.click(force=True, timeout=5000)
                clicked = True
            except Exception as f_err:
                self.log("warning", f"Notice during element click: {f_err}. Using DOM direct click...")

            # Method 2: Native DOM JavaScript evaluation (immune to overlays like #ctrl or .generate_wrap)
            if not clicked:
                try:
                    await self.page.evaluate("""() => {
                        const btn = document.querySelector('button#generate') || document.querySelector('#generate') || document.querySelector('.generate_button_top');
                        if (btn) {
                            const wrap = btn.closest('.generate_wrap');
                            if (wrap) wrap.classList.remove('loading');
                            btn.disabled = false;
                            btn.removeAttribute('disabled');
                            btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            btn.click();
                        }
                    }""")
                    clicked = True
                    self.log("info", "Triggered direct DOM native click on #generate button.")
                except Exception as dom_err:
                    self.log("error", f"DOM click execution error: {dom_err}")

            await asyncio.sleep(5)

            # Scroll #videogen_panel into view so live preview shows progress bar instead of comments
            try:
                panel_el = await self.page.query_selector("#videogen_panel")
                if panel_el and await panel_el.is_visible():
                    await panel_el.scroll_into_view_if_needed()
            except Exception:
                pass
            await self.capture_screenshot(preview_save_path)

            # Immediately check if TAAFT rejected the submission (e.g. .videogen_error)
            immediate_err = await self._check_generation_errors()
            if immediate_err:
                self.log("error", f"TAAFT rejected generation: {immediate_err}")
                return {"success": False, "error": immediate_err}

            # Verify generation actually started (#videogen_panel with progress or #videogen_runs visible)
            panel_started = await self._is_generation_active()
            if not panel_started:
                alt_gen = await self.page.query_selector(".generate_button_top")
                if alt_gen and await alt_gen.is_visible():
                    self.log("info", "Trying secondary Generate button (.generate_button_top)...")
                    try:
                        await alt_gen.click(force=True, timeout=5000)
                    except Exception:
                        await self.page.evaluate("document.querySelector('.generate_button_top')?.click()")
                    await asyncio.sleep(5)
                    await self.capture_screenshot(preview_save_path)
                    immediate_err = await self._check_generation_errors()
                    if immediate_err:
                        self.log("error", f"TAAFT rejected generation: {immediate_err}")
                        return {"success": False, "error": immediate_err}

        # Step 6: Smart Wait & Generation Polling
        start_time = time.time()
        live_info = await self._get_live_taaft_status()
        self.log("info", f"Generation initiated! Polling for completion (timeout: {timeout_seconds // 60}m)... {live_info}")

        last_screenshot_time = time.time()
        download_ready = False

        while (time.time() - start_time) < timeout_seconds:
            if self._stop_requested:
                self.log("warning", f"Scene #{scene_number:03d} generation aborted by user stop request.")
                return {"success": False, "stopped": True, "message": "User stopped execution"}

            elapsed_mins = int((time.time() - start_time) // 60)
            elapsed_secs = int((time.time() - start_time) % 60)

            # Periodic screenshot for dashboard
            if (time.time() - last_screenshot_time) >= SCREENSHOT_INTERVAL_SECONDS:
                await self.capture_screenshot(preview_save_path)
                last_screenshot_time = time.time()

            # Check for error banners / modals
            error_msg = await self._check_generation_errors()
            if error_msg:
                self.log("error", f"TAAFT reported error: {error_msg}")
                await self.capture_screenshot(preview_save_path)
                return {"success": False, "error": error_msg}

            # Check for Download button or completed video element
            download_btn = await self._find_download_button(ignore_href=prev_download_href)
            if download_btn:
                self.log("success", f"Download ready after {elapsed_mins}m {elapsed_secs}s!")
                download_ready = True
                break

            # Log status heartbeat every 60s with live TAAFT phase & ETA
            if elapsed_secs == 0 or elapsed_secs % 60 < POLLING_INTERVAL_SECONDS:
                live_info = await self._get_live_taaft_status()
                self.log("info", f"Waiting for clip generation... Elapsed: {elapsed_mins}m {elapsed_secs:02d}s {live_info}")

            await asyncio.sleep(POLLING_INTERVAL_SECONDS)

        if not download_ready:
            await self.capture_screenshot(preview_save_path)
            return {"success": False, "error": f"Generation timed out after {timeout_seconds // 60} minutes"}

        # Step 7: Download and save the clip
        self.log("info", f"Downloading completed clip to: {output_clip_path}")
        download_success = await self._perform_download(output_clip_path, ignore_href=prev_download_href)

        if download_success and os.path.exists(output_clip_path) and os.path.getsize(output_clip_path) > 10000:
            duration_taken = time.time() - start_time
            self.log("success", f"Scene #{scene_number:03d} successfully saved ({os.path.getsize(output_clip_path) // 1024} KB) in {int(duration_taken // 60)}m {int(duration_taken % 60)}s!")
            await self.capture_screenshot(preview_save_path)
            return {
                "success": True,
                "clip_path": output_clip_path,
                "generation_time_seconds": round(duration_taken, 1),
                "scene_number": scene_number
            }
        else:
            return {"success": False, "error": "Failed to download or write video file to disk"}

    async def _find_prompt_textarea(self):
        # Exact TAAFT prompt box: <div id="generator-user-input-wrap"><textarea id="user_input" placeholder="Enter your prompt here">
        selectors = [
            "#generator-user-input-wrap textarea#user_input",
            "textarea#user_input",
            "textarea[placeholder='Enter your prompt here']",
            "textarea#videogen_prompt",
            "textarea#prompt"
        ]
        for sel in selectors:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                return el

        # Fallback: scan all textareas and pick the first visible non-search, non-comment textarea
        all_ta = await self.page.query_selector_all("textarea")
        for ta in all_ta:
            try:
                if not await ta.is_visible():
                    continue
                cls = (await ta.get_attribute("class") or "").lower()
                tid = (await ta.get_attribute("id") or "").lower()
                if "search" in cls or "search" in tid or "comment" in cls or "comment" in tid:
                    continue
                return ta
            except Exception:
                continue
        return None

    async def _find_file_input(self):
        # Specific TAAFT videogen image file input
        inp = await self.page.query_selector("#videogen_image_input")
        if inp:
            return inp
        file_inputs = await self.page.query_selector_all("input[type='file']")
        for inp in file_inputs:
            return inp
        return None

    async def _select_model(self, model: str):
        try:
            tier = "fast" if "fast" in model.lower() else "quality"
            # 1. First attempt: Force unlock and select tier via DOM evaluation
            selected_tier = await self.page.evaluate("""(targetTier) => {
                const pills = Array.from(document.querySelectorAll('#videogen_model_pills .videogen_pill'));
                if (!pills.length) return null;
                let targetBtn = null;
                pills.forEach(p => {
                    const t = (p.getAttribute('data-videogen-tier') || '').toLowerCase();
                    if (t === targetTier) {
                        targetBtn = p;
                        p.disabled = false;
                        p.removeAttribute('disabled');
                        p.classList.remove('videogen_tier_locked');
                        p.classList.add('selected');
                        p.setAttribute('aria-checked', 'true');
                        p.setAttribute('tabindex', '0');
                    } else {
                        p.classList.remove('selected');
                        p.setAttribute('aria-checked', 'false');
                        p.setAttribute('tabindex', '-1');
                    }
                });
                if (targetBtn) {
                    try { targetBtn.click(); } catch(e) {}
                }
                const active = document.querySelector('#videogen_model_pills .videogen_pill.selected');
                return active ? active.getAttribute('data-videogen-tier') : null;
            }""", tier)

            if selected_tier and selected_tier.lower() == tier:
                self.log("info", f"⚡ Successfully selected model on TAAFT: {model.title()} (tier={selected_tier})")
                return

            # 2. Fallback: standard selector click
            btn = await self.page.query_selector(f"button[data-videogen-tier='{tier}']")
            if btn and await btn.is_visible():
                await btn.click(force=True)
                self.log("info", f"Selected model: {model} (tier={tier})")
                return

            btn_alt = await self.page.query_selector(f"button:has-text('{model}')")
            if btn_alt and await btn_alt.is_visible():
                await btn_alt.click(force=True)
                self.log("info", f"Selected model: {model}")
        except Exception as e:
            self.log("warning", f"Notice during model selection ({model}): {str(e)}")

    async def _select_orientation(self, orientation: str):
        try:
            # TAAFT orientation radio: name="videogen_orientation"
            radios = await self.page.query_selector_all("input[name='videogen_orientation']")
            for r in radios:
                val = await r.get_attribute("value")
                # Usually "landscape" or "portrait"
                if val and orientation.lower() in val.lower():
                    await r.check()
                    self.log("info", f"Selected orientation: {orientation}")
                    return
            btn = await self.page.query_selector(f"button:has-text('{orientation}'), label:has-text('{orientation}')")
            if btn:
                await btn.click()
                self.log("info", f"Selected orientation: {orientation}")
        except Exception:
            pass

    async def _ensure_prompt_enhance_unchecked(self):
        """Unchecks 'Enhance my prompt' to protect prompt fidelity."""
        try:
            # Exact TAAFT checkbox id: #videogen_enhance_prompt
            enhance_checkbox = await self.page.query_selector("#videogen_enhance_prompt")
            if not enhance_checkbox:
                enhance_checkbox = await self.page.query_selector("input[type='checkbox']:has(+ label:has-text('Enhance')), input[type='checkbox'][name*='enhance' i]")

            if enhance_checkbox:
                is_checked = await enhance_checkbox.is_checked()
                if is_checked:
                    self.log("info", "Unchecking 'Enhance my prompt' to preserve exact continuity instructions.")
                    await enhance_checkbox.uncheck()
                else:
                    self.log("info", "'Enhance my prompt' is already unchecked.")
        except Exception as e:
            self.log("warning", f"Enhance prompt toggle check note: {str(e)}")

    async def _find_generate_button(self):
        # Exact TAAFT generate button: <button id="generate" class="shadow">Generate</button>
        selectors = [
            "button#generate",
            "#generate",
            ".generate_button_top",
            "button:has-text('Generate')",
            "button:has-text('Create Video')"
        ]
        for sel in selectors:
            btn = await self.page.query_selector(sel)
            if btn and await btn.is_visible():
                return btn
        return None

    def _sanitize_image_tags(self, prompt: str, attached_count: int) -> str:
        """
        Ensures the prompt never mentions <Image k> when fewer than k images are attached.
        TAAFT rejects generation with 'Your prompt mentions <Image 1>, but that image is not attached.'
        """
        if not prompt:
            return prompt

        cleaned = prompt
        if attached_count <= 0:
            # Remove all <Image N> tags and clean leftover empty connectors/parentheses
            cleaned = re.sub(r"\(\s*<Image\s*\d+>\s*\)", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"from\s+<Image\s*\d+>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"in\s+<Image\s*\d+>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<Image\s*\d+>", "", cleaned, flags=re.IGNORECASE)
        else:
            # Remap any <Image k> where k > attached_count to <Image {attached_count}>
            def _remap(match):
                idx = int(match.group(1))
                if idx > attached_count:
                    return f"<Image {attached_count}>"
                return match.group(0)
            cleaned = re.sub(r"<Image\s*(\d+)>", _remap, cleaned, flags=re.IGNORECASE)

        # Tidy up double spaces or awkward punctuation left by removal
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
        return cleaned.strip()

    async def _is_generation_active(self) -> bool:
        """Checks if TAAFT's #videogen_panel progress/status or #videogen_runs became active."""
        try:
            # Note: #videogen_panel.videogen_message_only is shown for validation errors, NOT active runs!
            panel = await self.page.query_selector("#videogen_panel:not(.hidden):not(.videogen_message_only)")
            if panel and await panel.is_visible():
                return True
            run_card = await self.page.query_selector("#videogen_runs .videogen_run")
            if run_card and await run_card.is_visible():
                return True
        except Exception:
            pass
        return False

    async def _get_live_taaft_status(self) -> str:
        """Reads live phase, ETA, and progress percentage from TAAFT's #videogen_panel."""
        parts = []
        try:
            phase_el = await self.page.query_selector("#videogen_phase, .videogen_run_phase")
            if phase_el and await phase_el.is_visible():
                txt = (await phase_el.inner_text()).strip()
                if txt:
                    parts.append(txt)
            eta_el = await self.page.query_selector("#videogen_eta, .videogen_run_eta")
            if eta_el and await eta_el.is_visible():
                txt = (await eta_el.inner_text()).strip()
                if txt:
                    parts.append(f"ETA: {txt}")
            queue_el = await self.page.query_selector("#videogen_queue:not(.hidden), .videogen_run_queue:not(.hidden)")
            if queue_el and await queue_el.is_visible():
                txt = (await queue_el.inner_text()).strip()
                if txt:
                    parts.append(txt)
            prog_el = await self.page.query_selector("#videogen_progress")
            if prog_el and await prog_el.is_visible():
                val = await prog_el.get_attribute("aria-valuenow")
                if val and val != "0":
                    parts.append(f"{val}%")
        except Exception:
            pass
        return f"| TAAFT: {' · '.join(parts)}" if parts else ""

    async def _find_download_button(self, ignore_href: str = ""):
        """Checks TAAFT's exact download buttons (#videogen_download / .videogen_run_download) and result video."""
        # 1. Primary TAAFT download link inside #videogen_panel
        exact_selectors = [
            "#videogen_download:not(.hidden)",
            ".videogen_run_download:not(.hidden)",
            "a[href*='video-generation-download']"
        ]
        for sel in exact_selectors:
            btn = await self.page.query_selector(sel)
            if btn and await btn.is_visible():
                href = (await btn.get_attribute("href") or "").strip()
                if href and href != "#" and href != ignore_href:
                    return btn

        # 2. Check if #videogen_result or .videogen_run_result has a rendered <video> with valid src (only when not waiting for extend href change)
        if not ignore_href:
            try:
                res_video = await self.page.query_selector("#videogen_result:not(.hidden) video, .videogen_run_result:not(.hidden) video")
                if res_video and await res_video.is_visible():
                    src = await res_video.get_attribute("src")
                    if not src:
                        source_el = await res_video.query_selector("source")
                        if source_el:
                            src = await source_el.get_attribute("src")
                    if src and (src.startswith("http") or src.startswith("/")):
                        return res_video
            except Exception:
                pass

        return None

    async def _check_generation_errors(self) -> Optional[str]:
        try:
            if self._last_dialog_message:
                msg = self._last_dialog_message
                self._last_dialog_message = None
                return f"TAAFT Alert: {msg}"

            # Check for login modal: "Sign in to continue"
            login_modal = await self.page.query_selector("text='Sign in to continue', text='Sign in with Google', div:has-text('Sign in to continue')")
            if login_modal and await login_modal.is_visible():
                return "Account Login Required: TAAFT is showing 'Sign in to continue'. Please run login.bat (or Launch Browser Login) and click 'Sign in with Google' to complete login."

            # Check TAAFT's exact error class (.videogen_error) FIRST!
            vg_err = await self.page.query_selector("#videogen_message.videogen_error, .videogen_run_message.videogen_error, .videogen_error")
            if vg_err and await vg_err.is_visible():
                txt = (await vg_err.inner_text()).strip()
                if txt:
                    return txt

            # Check TAAFT's status/error message boxes
            for msg_sel in ["#videogen_message:not(.hidden)", ".videogen_run_message:not(.hidden)"]:
                msg_el = await self.page.query_selector(msg_sel)
                if msg_el and await msg_el.is_visible():
                    txt = (await msg_el.inner_text()).strip()
                    low = txt.lower()
                    if txt and any(k in low for k in ["error", "fail", "sorry", "limit", "invalid", "blocked", "cannot", "try again", "too long", "sign in", "quota", "expired", "not attached"]):
                        return txt

            err_el = await self.page.query_selector(".error-message, .alert-danger, div:has-text('Generation failed')")
            if err_el and await err_el.is_visible():
                txt = (await err_el.inner_text()).strip()
                if txt:
                    return txt
        except Exception:
            pass
        return None

    async def _download_via_context_request(self, url: str, target_save_path: str) -> bool:
        """Downloads a video URL using Playwright's authenticated browser context cookies."""
        try:
            if url.startswith("/"):
                url = "https://theresanaiforthat.com" + url
            self.log("info", f"Downloading video via authenticated session: {url[:80]}...")
            resp = await self.context.request.get(url, timeout=120000)
            if resp.ok:
                data = await resp.body()
                if len(data) > 10000:
                    Path(target_save_path).write_bytes(data)
                    return True
                else:
                    self.log("warning", f"Downloaded payload too small ({len(data)} bytes).")
            else:
                self.log("warning", f"Authenticated download HTTP {resp.status}")
        except Exception as e:
            self.log("warning", f"Authenticated request download note: {str(e)}")
        return False

    async def _perform_download(self, target_save_path: str, ignore_href: str = "") -> bool:
        """Downloads the completed video from #videogen_download or #videogen_result video."""
        # 1. Best method: Read href directly from #videogen_download / .videogen_run_download and fetch with session cookies
        for sel in ["#videogen_download:not(.hidden)", ".videogen_run_download:not(.hidden)", "a[href*='video-generation-download']"]:
            btn = await self.page.query_selector(sel)
            if btn and await btn.is_visible():
                href = (await btn.get_attribute("href") or "").strip()
                if href and href != "#" and href != ignore_href:
                    if await self._download_via_context_request(href, target_save_path):
                        return True
                    # Fallback: try Playwright expect_download click
                    try:
                        async with self.page.expect_download(timeout=45000) as download_info:
                            await btn.click()
                        download = await download_info.value
                        await download.save_as(target_save_path)
                        if os.path.exists(target_save_path) and os.path.getsize(target_save_path) > 10000:
                            return True
                    except Exception as e:
                        self.log("warning", f"Download click intercept note: {str(e)}")

        # 2. Fallback: extract <video> src inside #videogen_result or .videogen_run_result
        try:
            videos = await self.page.query_selector_all("#videogen_result video, .videogen_run_result video, video")
            for video_el in videos:
                src = await video_el.get_attribute("src")
                if not src:
                    source_el = await video_el.query_selector("source")
                    if source_el:
                        src = await source_el.get_attribute("src")
                if src and (src.startswith("http") or src.startswith("/")):
                    if await self._download_via_context_request(src, target_save_path):
                        return True
        except Exception as vid_err:
            self.log("warning", f"Video src fallback note: {str(vid_err)}")

        return False
