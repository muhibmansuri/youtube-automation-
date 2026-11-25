# 🎬 CodeAura Cinema Studio - Autonomous AI Movie Generator & Pipeline

An end-to-end automated AI movie generation application and automation pipeline that continuously orchestrates the TAAFT 8-second Video Generator interface (`https://theresanaiforthat.com/@taaft/video-generator/?ref=header`) to create seamless, continuous 2 to 3-hour feature films with strict visual, character, and scene continuity.

---

## 🌟 Key Architecture & Capabilities

### 1. Master Story & Scene Breakdown Engine (AI Scriptwriter)
- **Gemini AI Integration:** Breaks complex storylines into sequential 8-second scene prompts (e.g., `SCENE_001` to `SCENE_900` for a 120-minute feature).
- **Strict Visual DNA Locking:** Injects locked protagonist physical descriptors (facial features, eye color, hairstyle, exact costume/wardrobe fabrics) into every prompt.
- **Reference Anchors:** Automatically directs the AI video model:
  - `<Image 1>`: Master Character Sheet / Reference Image.
  - `<Image 2>`: Extracted exact final frame of the previous scene.

### 2. Persistent Browser Automation Worker (Playwright)
- **Persistent User Profile (`./browser_profile`):** Preserves session cookies, tokens, and Cloudflare clearance permanently so the user only logs in once.
- **Interactive Browser Launcher:** Dedicated one-click button to open headed Chromium for manual login or Cloudflare Turnstile completion.
- **Automatic Form Filling & Uploads:**
  - Injects scene prompts into `"Your prompt"`.
  - Attaches Master Character Reference + Previous Scene's Last Frame into `"IMAGES (OPTIONAL)"`.
  - Configures Model (`Quality` / `Fast`) and Orientation (`Landscape`).
  - **Strict Prompt Protection:** Explicitly unchecks `"Enhance my prompt"` so custom continuity tokens remain unaltered.
- **Smart Polling & Download:** Handles ~18–20 minute generation latency per clip with a 30-minute timeout, intercepting and saving `clip_001.mp4`, `clip_002.mp4`, etc.
- **Daily Quota Manager:** Monitors the `"X of 100 videos left today"` counter. If quota hits 0, pauses execution gracefully and preserves state in SQLite.

### 3. Frame-to-Frame Continuity Processor (OpenCV & FFmpeg)
- Automatically extracts the exact final frame from each completed video clip (`clip_XXX.mp4` → `last_frame_XXX.jpg`).
- Validates frame integrity (detects and filters out blank or corrupt frames).
- Chains `last_frame_XXX.jpg` into `SCENE_XXX+1` as `<Image 2>` so motion and lighting flow continuously without jarring jumps.

### 4. Auto-Stitching & Movie Compiler (FFmpeg)
- Seamlessly concatenates hundreds of 8-second clips into a unified 1080p or 4K MP4 master movie.
- **Direct Concat Demuxer:** Ultra-fast lossless stitching.
- **Cinematic Crossfade Blending:** Smooth 0.3s `xfade` blending across scene boundaries.
- **Audio Processing:** EBU R128 audio normalization (`loudnorm`) and optional cinematic background music overlay with volume ducking.

### 5. Hollywood Cyberpunk Web Dashboard (Flask + Dark Mode)
- **Project & Character Studio:** Set runtime, storyline, genre, and upload master reference images.
- **Visual Storyboard & Queue:** Scene cards with prompt editors, status badges, frame previews, and clip playback.
- **Live Automation Center:** Playwright controls, real-time headless browser screen stream, and terminal log console.
- **Screening Room:** Full master movie player and direct download.

---

## 🚀 Quick Start Guide

### Step 1: Install Dependencies
Ensure you have Python 3.10+ installed:
```powershell
pip install -r requirements.txt
playwright install chromium
```

### Step 2: Start the Web App
Run the Windows batch launcher:
```powershell
run.bat
```
Or start via terminal:
```powershell
python app.py
```
Open your browser at: **`http://127.0.0.1:5000`**

### Step 3: Configure Gemini API Key
1. Go to **5. Settings & Diagnostics** in the dashboard.
2. Enter your **Gemini API Key** and click **Save Settings**.
3. Click **Test Connection** to verify.

### Step 4: One-Time Manual Login to TAAFT
1. Click **"Launch Browser Login"** in the top navigation bar.
2. An interactive browser window will open at `https://theresanaiforthat.com/@taaft/video-generator/?ref=header`.
3. Sign in to your account and pass any Cloudflare verification.
4. Close the browser window once logged in. Your session is now saved in `./browser_profile` for all future automated runs.

### Step 5: Create a Movie & Generate Scenes
1. Go to **1. Movie Setup & Characters**.
2. Set your **Movie Title**, **Genre**, **Target Duration** (e.g. 120 minutes = 900 clips), and **Storyline**.
3. Upload 1 to 3 **Master Character Reference Images**.
4. Switch to **2. Storyboard & Scene Queue** and click **"Generate Scenes with Gemini"**.
5. Review and customize the generated sequential prompts.

### Step 6: Start Autonomous Generation
1. Switch to **3. Live Automation Center**.
2. Click **"Start Automation"**.
3. Watch the live browser feed and real-time terminal logs as clips are generated, downloaded, and continuity-chained.

### Step 7: Compile the Final Film
1. When clips are ready, navigate to **4. Movie Compiler Studio**.
2. Select your transition mode (`Fast Lossless` or `Cinematic Crossfade`) and resolution (`1080p` or `4K`).
3. Click **"Compile Full Feature Film"** and enjoy your continuous movie in the screening room!

---

## 📁 Project Structure

```
d:\Auto youtube video genratore\
├── app.py                      # Flask REST API & SSE Event Stream Server
├── config.py                   # Global configuration & FFmpeg auto-discovery
├── database.py                 # SQLite database models & state persistence
├── requirements.txt            # Python dependencies
├── run.bat                     # Windows one-click batch launcher
├── core/
│   ├── continuity.py           # OpenCV frame extraction & validation
│   ├── scriptwriter.py         # Gemini prompt breakdown & consistency engine
│   ├── browser_worker.py       # Playwright automation worker for TAAFT
│   ├── movie_compiler.py       # FFmpeg concatenation & audio mixer
│   └── pipeline_manager.py     # Central automation orchestrator
├── templates/
│   └── index.html              # Hollywood dark-mode single-page dashboard
├── static/
│   ├── css/style.css           # Custom dark glassmorphic styling
│   ├── js/app.js               # Reactive frontend logic & SSE listener
│   └── img/                    # UI icons and stream placeholders
├── browser_profile/            # Persistent Chromium user data directory
└── projects/                   # Multi-project storage
    └── {project_id}/
        ├── master_refs/        # Uploaded character & style sheets
        ├── clips/              # Downloaded 8s clips (clip_001.mp4...)
        ├── last_frames/        # Extracted final frames (last_frame_001.jpg...)
        ├── audio/              # Background soundtracks
        └── output/             # Stitched full movie (.mp4)
```
