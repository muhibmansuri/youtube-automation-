import os
import sys
import subprocess
from pathlib import Path
from config import BROWSER_PROFILE_DIR, TAAFT_URL

def launch():
    profile_dir = Path(BROWSER_PROFILE_DIR).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    target_url = TAAFT_URL

    print("=" * 65)
    print("      CodeAura Cinema Studio - Interactive Browser Login Launcher")
    print("=" * 65)
    print(f"Profile Directory: {profile_dir}")
    print(f"Target URL:        {target_url}")
    print("\nStarting browser window...")

    # Strategy 1: Check for real Google Chrome installation on Windows
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]

    selected_browser = None
    for cp in chrome_paths:
        if os.path.exists(cp):
            selected_browser = cp
            break

    if selected_browser:
        browser_name = "Google Chrome" if "chrome.exe" in selected_browser.lower() else "Microsoft Edge"
        print(f"Detected {browser_name} at: {selected_browser}")
        print("Launching visible browser with persistent session...")

        cmd = [
            selected_browser,
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            target_url
        ]

        try:
            print("\n" + "#" * 65)
            print("👉 BROWSER OPENED! Please:")
            print("   1. Complete the Cloudflare verification ('Verify you are human').")
            print("   2. Log in to your TAAFT account.")
            print("   3. Once logged in, CLOSE the browser window to save session cookies.")
            print("#" * 65 + "\n")
            
            # Run browser and wait until user closes it
            subprocess.run(cmd)
            print("Browser closed. Session cookies saved successfully into ./browser_profile!")
            return
        except Exception as e:
            print(f"Direct browser launch note: {e}. Falling back to Playwright...")

    # Strategy 2: Fallback to Playwright Chromium
    import asyncio
    from playwright.async_api import async_playwright

    async def _pw_launch():
        print("Launching Playwright Chromium...")
        async with async_playwright() as p:
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized"
            ]
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=args,
                ignore_default_args=["--enable-automation"],
                viewport=None
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(target_url)

            print("\n" + "#" * 65)
            print("👉 BROWSER OPENED! Please:")
            print("   1. Complete the Cloudflare verification ('Verify you are human').")
            print("   2. Log in to your TAAFT account.")
            print("   3. Once logged in, CLOSE the browser window to save session cookies.")
            print("#" * 65 + "\n")

            while context.pages:
                await asyncio.sleep(1)
            await context.close()
            print("Browser closed. Session saved successfully!")

    asyncio.run(_pw_launch())

if __name__ == "__main__":
    launch()
