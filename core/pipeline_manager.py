import os
import sys
import time
import json
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from config import PROJECTS_DIR, BROWSER_PROFILE_DIR, TAAFT_URL, MAX_DAILY_VIDEOS
from database import db
from core.continuity import ContinuityProcessor
from core.browser_worker import TAAFTBrowserWorker
from core.voice_synthesizer import VoiceSynthesizer
from core.movie_compiler import MovieCompiler

class PipelineManager:
    """Central orchestrator managing browser automation, scene queue, continuity, and recovery."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PipelineManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.active_project_id: Optional[str] = None
        self.is_running = False
        self.is_paused = False
        self.current_worker: Optional[TAAFTBrowserWorker] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.event_subscribers = []
        self.headless = True

    def register_event_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        """Registers a listener for live UI push notifications (SSE / SocketIO)."""
        self.event_subscribers.append(callback)

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        """Dispatches real-time update to all subscribers."""
        payload = {"type": event_type, "data": data, "timestamp": time.time()}
        for sub in list(self.event_subscribers):
            try:
                sub(payload)
            except Exception:
                pass

    def log(self, project_id: str, level: str, message: str):
        """Logs message to database and broadcasts to UI console."""
        db.add_log(project_id or "global", level, message)
        self.emit_event("log", {
            "project_id": project_id,
            "level": level.upper(),
            "message": message,
            "timestamp": time.strftime("%H:%M:%S")
        })

    def get_status(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns the current state of the pipeline and scene queue."""
        pid = project_id or self.active_project_id
        if not pid:
            return {
                "is_running": False,
                "is_paused": False,
                "status": "IDLE",
                "message": "No active project",
                "stats": {"total": 0, "completed": 0, "pending": 0, "failed": 0, "progress_percent": 0}
            }

        state = db.get_pipeline_state(pid)
        stats = db.get_scene_stats(pid)
        return {
            "project_id": pid,
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "status": "RUNNING" if self.is_running and not self.is_paused else ("PAUSED" if self.is_paused else "IDLE"),
            "current_scene_number": state.get("current_scene_number", 0),
            "quota_left": state.get("quota_left", 100),
            "quota_total": state.get("quota_total", 100),
            "status_message": state.get("status_message", ""),
            "last_screenshot_path": state.get("last_screenshot_path", ""),
            "stats": stats
        }

    def start_pipeline(self, project_id: str, headless: bool = True) -> Dict[str, Any]:
        """Launches the automated generation worker loop in a background thread."""
        with self._lock:
            if (self._thread and self._thread.is_alive()) or (self.is_running and not self.is_paused):
                if self.is_paused and self._thread and self._thread.is_alive():
                    self.is_paused = False
                    db.update_pipeline_state(project_id, is_running=1, is_paused=0, status_message="Pipeline resumed")
                    self.emit_event("pipeline_resumed", {"project_id": project_id})
                    return {"success": True, "message": "Pipeline resumed successfully"}
                return {"success": False, "message": "Pipeline is already running."}

            self.active_project_id = project_id
            self.headless = headless
            self.is_running = True
            self.is_paused = False

            db.update_pipeline_state(project_id, is_running=1, is_paused=0, status_message="Pipeline started")
            db.update_project(project_id, status="PROCESSING")

            self._thread = threading.Thread(target=self._run_loop_thread, args=(project_id,), daemon=True)
            self._thread.start()

            self.log(project_id, "info", f"🎬 Automation Pipeline started for Project: {project_id}")
            self.emit_event("pipeline_started", {"project_id": project_id})
            return {"success": True, "message": "Pipeline started successfully"}

    def pause_pipeline(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Pauses the queue after current clip completes."""
        pid = project_id or self.active_project_id
        self.is_paused = True
        if pid:
            db.update_pipeline_state(pid, is_paused=1, status_message="Paused")
            self.log(pid, "warning", "⏸️ Pipeline execution paused.")
        self.emit_event("pipeline_paused", {"project_id": pid})
        return {"success": True, "message": "Pipeline paused"}

    def resume_pipeline(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Resumes the paused automation worker."""
        pid = project_id or self.active_project_id
        if not pid:
            return {"success": False, "message": "No active project to resume"}

        self.is_paused = False
        db.update_pipeline_state(pid, is_paused=0, status_message="Resumed")
        self.log(pid, "info", "▶️ Pipeline resumed.")
        self.emit_event("pipeline_resumed", {"project_id": pid})
        return {"success": True, "message": "Pipeline resumed"}

    def stop_pipeline(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Gracefully halts the automation worker."""
        pid = project_id or self.active_project_id
        self.is_running = False
        self.is_paused = False

        if self.current_worker:
            self.current_worker.request_stop()

        if pid:
            db.update_pipeline_state(pid, is_running=0, is_paused=0, status_message="Stopped")
            self.log(pid, "warning", "⏹️ Pipeline stopped by user.")

        self.emit_event("pipeline_stopped", {"project_id": pid})
        return {"success": True, "message": "Pipeline stopped"}

    def launch_interactive_browser(self) -> Dict[str, Any]:
        """
        Launches an interactive Chromium / Chrome browser window in a separate,
        top-level Windows process so the user can easily log in to Google/TAAFT
        and solve Cloudflare verification directly on their desktop.
        """
        import subprocess
        launcher_script = Path(__file__).resolve().parent.parent / "launch_browser.py"
        creation_flags = 0x00000010 if sys.platform == "win32" else 0  # CREATE_NEW_CONSOLE

        try:
            self.log("global", "info", "🌐 Spawning interactive browser window for manual login...")
            subprocess.Popen([sys.executable, str(launcher_script)], creationflags=creation_flags)
            return {"success": True, "message": "Interactive browser window launched! Check your taskbar / screen."}
        except Exception as e:
            self.log("global", "error", f"Failed to launch browser: {str(e)}")
            return {"success": False, "error": str(e)}

    def _run_loop_thread(self, project_id: str):
        """Worker thread entry point running asyncio event loop."""
        this_thread = threading.current_thread()
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._pipeline_execution_loop(project_id))
        except Exception as e:
            self.log(project_id, "error", f"Pipeline thread crashed: {str(e)}")
        finally:
            if self._thread is this_thread:
                self.is_running = False
                db.update_pipeline_state(project_id, is_running=0)
            loop.close()

    async def _pipeline_execution_loop(self, project_id: str):
        """Asynchronous execution loop sequentially generating 8-second clips."""
        project = db.get_project(project_id)
        if not project:
            self.log(project_id, "error", f"Project {project_id} not found in database.")
            return

        proj_dir = PROJECTS_DIR / project_id
        clips_dir = proj_dir / "clips"
        frames_dir = proj_dir / "last_frames"
        preview_path = str(proj_dir / "browser_preview.jpg")

        clips_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        worker = TAAFTBrowserWorker(
            profile_dir=BROWSER_PROFILE_DIR,
            headless=self.headless,
            log_callback=lambda lvl, msg: self.log(project_id, lvl, msg),
            preview_callback=lambda p: self.emit_event("browser_preview", {"image_url": f"/projects/{project_id}/browser_preview.jpg?t={int(time.time())}"})
        )
        self.current_worker = worker

        try:
            await worker.initialize()
            consecutive_failures = 0

            while self.is_running:
                # Check for pause
                while self.is_paused and self.is_running:
                    await asyncio.sleep(2)
                if not self.is_running:
                    break

                # Reload project settings dynamically (allows changing model_type or orientation mid-run)
                project = db.get_project(project_id) or project

                # Get next pending or failed scene
                scene = db.get_next_pending_scene(project_id)
                if not scene:
                    self.log(project_id, "success", "🎉 All scenes in the movie have been successfully generated!")
                    self.log(project_id, "info", "🎬 Automatically starting master feature film compilation...")
                    db.update_pipeline_state(project_id, status_message="Auto-Compiling Master Film...")

                    try:
                        self._auto_compile_project(project_id, project)
                    except Exception as ce:
                        self.log(project_id, "error", f"Auto-compilation error: {str(ce)}")

                    db.update_project(project_id, status="COMPLETED")
                    db.update_pipeline_state(project_id, is_running=0, status_message="Completed")
                    self.emit_event("project_completed", {"project_id": project_id})
                    break

                scene_num = scene["scene_number"]
                db.update_scene(project_id, scene_num, status="GENERATING")
                db.update_pipeline_state(project_id, current_scene_number=scene_num, status_message=f"Generating Scene #{scene_num:03d}")
                self.emit_event("scene_updated", {"scene_number": scene_num, "status": "GENERATING"})

                # Determine reference images cleanly:
                # Attach Master Character Sheet(s) only when the scene prompt references them
                # (prevents faces bleeding into pure aerial city / object / paper-file shots)
                ref_images = []
                master_images = [m for m in (project.get("master_ref_images") or []) if m and os.path.exists(m)]
                prompt_low = (scene.get("prompt") or "").lower()
                needs_master = any(f"<image {idx}>" in prompt_low for idx in range(1, len(master_images) + 1))
                if master_images and needs_master:
                    ref_images.extend(master_images)

                # Fetch last frame of previous scene for seamless frame-to-frame continuity
                if scene_num > 1:
                    prev_scene = db.get_scene(project_id, scene_num - 1)
                    if prev_scene and prev_scene.get("last_frame_path") and os.path.exists(prev_scene["last_frame_path"]):
                        prev_frame = prev_scene["last_frame_path"]
                        ref_images.append(prev_frame)
                        slot_num = len(ref_images)
                        self.log(project_id, "info", f"🔗 Chaining last frame of Scene #{scene_num-1:03d} as <Image {slot_num}> ({os.path.basename(prev_frame)})")
                    else:
                        # If previous scene last frame not yet extracted, check if clip exists to extract it
                        prev_clip = str(clips_dir / f"clip_{scene_num-1:03d}.mp4")
                        if os.path.exists(prev_clip):
                            extracted = ContinuityProcessor.extract_last_frame(prev_clip, str(frames_dir / f"last_frame_{scene_num-1:03d}.jpg"))
                            if extracted.get("success"):
                                ref_images.append(extracted["frame_path"])
                                db.update_scene(project_id, scene_num-1, last_frame_path=extracted["frame_path"])

                # In Fast Mode, TAAFT has a platform constraint: attaching 2 or more images
                # automatically locks the generator to 'Quality' tier (lockTierImages: 2).
                # To guarantee Fast Mode without losing characters, we use Smart 1-Image Routing:
                # - Scene with Arjun only -> 01_inspector_arjun_master.jpg
                # - Scene with Maya only -> 02_maya_master.jpg
                # - Scene with BOTH Arjun & Maya -> 03_arjun_maya_duo_master.jpg (Side-by-side composite!)
                is_fast_mode = "fast" in (project.get("model_type") or "fast").lower()
                if is_fast_mode:
                    master_refs_dir = proj_dir / "master_refs"
                    arjun_img = str(master_refs_dir / "01_inspector_arjun_master.jpg")
                    maya_img = str(master_refs_dir / "02_maya_master.jpg")
                    duo_img = str(master_refs_dir / "03_arjun_maya_duo_master.jpg")

                    # Auto-generate duo composite if missing
                    if os.path.exists(arjun_img) and os.path.exists(maya_img) and not os.path.exists(duo_img):
                        try:
                            from PIL import Image
                            im1 = Image.open(arjun_img)
                            im2 = Image.open(maya_img)
                            h = min(im1.height, im2.height)
                            im1_r = im1.resize((int(im1.width * h / im1.height), h), Image.Resampling.LANCZOS)
                            im2_r = im2.resize((int(im2.width * h / im2.height), h), Image.Resampling.LANCZOS)
                            comb = Image.new('RGB', (im1_r.width + im2_r.width, h))
                            comb.paste(im1_r, (0, 0))
                            comb.paste(im2_r, (im1_r.width, 0))
                            comb.save(duo_img, quality=95)
                        except Exception as duo_err:
                            self.log(project_id, "warning", f"Could not create duo composite: {duo_err}")

                    has_arjun = "arjun" in prompt_low
                    has_maya = "maya" in prompt_low

                    if has_arjun and has_maya and os.path.exists(duo_img):
                        ref_images = [duo_img]
                        self.log(project_id, "info", f"⚡ Fast Mode Dual-Character Scene: Using Duo Composite (Arjun + Maya in 1 image) to keep Fast Tier active!")
                    elif has_maya and not has_arjun and os.path.exists(maya_img):
                        ref_images = [maya_img]
                        self.log(project_id, "info", f"⚡ Fast Mode Solo Maya Scene: Using Maya Master anchor to keep Fast Tier active.")
                    elif os.path.exists(arjun_img):
                        ref_images = [arjun_img]
                        self.log(project_id, "info", f"⚡ Fast Mode Detective Scene: Using Arjun Master anchor to keep Fast Tier active.")
                    elif ref_images:
                        ref_images = [ref_images[0]]

                output_clip = str(clips_dir / f"clip_{scene_num:03d}.mp4")

                # Call browser worker
                gen_res = await worker.generate_scene_clip(
                    scene_number=scene_num,
                    prompt_text=scene["prompt"],
                    ref_image_paths=ref_images,
                    output_clip_path=output_clip,
                    preview_save_path=preview_path,
                    model=project.get("model_type", "Fast"),
                    orientation=project.get("orientation", "Landscape"),
                    extend_mode=bool(scene.get("extend_from_prev", 0))
                )

                if gen_res.get("success"):
                    # Extract last frame for continuity
                    last_frame_file = str(frames_dir / f"last_frame_{scene_num:03d}.jpg")
                    self.log(project_id, "info", f"Extracting exact final frame for Scene #{scene_num:03d}...")
                    frame_res = ContinuityProcessor.extract_last_frame(output_clip, last_frame_file)

                    last_frame_saved = last_frame_file if frame_res.get("success") else ""
                    if frame_res.get("success"):
                        self.log(project_id, "success", f"Final frame extracted ({frame_res.get('method')}): last_frame_{scene_num:03d}.jpg")

                    # Raw Original Audio Mode: Keep the exact original video & audio from TAAFT untouched
                    # (No synthetic dubbing overwrite, no muting)
                    self.log(project_id, "info", f"🎬 Keeping exact original video & audio for Scene #{scene_num:03d} (Untouched).")

                    db.update_scene(
                        project_id,
                        scene_num,
                        status="COMPLETED",
                        clip_path=output_clip,
                        last_frame_path=last_frame_saved,
                        generation_time_seconds=gen_res.get("generation_time_seconds", 0),
                        error_message=""
                    )
                    consecutive_failures = 0
                    self.emit_event("scene_updated", {
                        "scene_number": scene_num, 
                        "status": "COMPLETED", 
                        "clip_url": f"/projects/{project_id}/clips/clip_{scene_num:03d}.mp4",
                        "frame_url": f"/projects/{project_id}/last_frames/last_frame_{scene_num:03d}.jpg"
                    })

                elif gen_res.get("quota_exhausted"):
                    self.log(project_id, "warning", "⚠️ Daily 100 video limit reached. Pausing automation until reset.")
                    self.is_paused = True
                    db.update_scene(project_id, scene_num, status="PENDING")
                    db.update_pipeline_state(project_id, is_paused=1, quota_left=0, status_message="Daily limit reached (paused)")
                    self.emit_event("quota_limit_reached", {"project_id": project_id})
                    break

                elif gen_res.get("login_required") or gen_res.get("blocked_by_cf"):
                    msg = "TAAFT Account Login required" if gen_res.get("login_required") else "Cloudflare challenge encountered"
                    self.log(project_id, "error", f"🛑 {msg}. Automation paused. Please launch Interactive Browser / login.bat to log in.")
                    self.is_paused = True
                    db.update_scene(project_id, scene_num, status="PENDING")
                    db.update_pipeline_state(project_id, is_paused=1, status_message=msg)
                    self.emit_event("verification_required", {"project_id": project_id})
                    break

                elif gen_res.get("stopped"):
                    db.update_scene(project_id, scene_num, status="PENDING")
                    break

                else:
                    consecutive_failures += 1
                    err_text = gen_res.get("error", "Unknown generation error")
                    self.log(project_id, "error", f"Scene #{scene_num:03d} failed: {err_text}")
                    db.update_scene(project_id, scene_num, status="FAILED", error_message=err_text)
                    self.emit_event("scene_updated", {"scene_number": scene_num, "status": "FAILED", "error": err_text})

                    if "closed" in err_text.lower() or "target page" in err_text.lower():
                        self.log(project_id, "warning", "🔄 Resetting closed browser instance before next attempt...")
                        await worker.close()

                    if consecutive_failures >= 5:
                        self.log(project_id, "error", "🛑 Pipeline paused after 5 consecutive failures. Check logs and restart.")
                        self.is_paused = True
                        db.update_pipeline_state(project_id, is_paused=1, status_message="Paused after 5 consecutive errors")
                        break

                # Short delay between clips
                await asyncio.sleep(5)

        except Exception as e:
            self.log(project_id, "error", f"Pipeline encountered fatal exception: {str(e)}")
        finally:
            await worker.close()
            if self.current_worker is worker:
                self.current_worker = None
                self.is_running = False
                db.update_pipeline_state(project_id, is_running=0)

    def _auto_compile_project(self, project_id: str, project: dict):
        """Automatically triggers Cinema Master compilation upon 100% completion of all scenes."""
        from core.cinema_audio import CinemaAudioStudio

        completed_scenes = db.get_scenes(project_id, status="COMPLETED")
        completed_scenes = sorted(completed_scenes, key=lambda s: s["scene_number"])
        valid_scenes = [s for s in completed_scenes if s.get("clip_path") and os.path.exists(s["clip_path"])]
        clip_paths = [s["clip_path"] for s in valid_scenes]

        if not clip_paths:
            self.log(project_id, "warning", "No valid clips found for auto-compilation.")
            return

        output_dir = PROJECTS_DIR / project_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        sanitized_name = "".join([c if c.isalnum() or c in " _-" else "_" for c in project.get("name", "Movie")]).strip()
        output_movie = str(output_dir / f"{sanitized_name}_Cinema_Master_1080p.mp4")

        # Check or generate background soundtrack
        audio_dir = PROJECTS_DIR / project_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))
        bg_audio = str(audio_files[0]) if audio_files else None

        audio_studio = CinemaAudioStudio(log_callback=lambda lvl, msg: self.log(project_id, lvl, msg))
        if not bg_audio:
            auto_score = str(audio_dir / "auto_thriller_score.wav")
            if audio_studio.generate_thriller_soundscape(auto_score, duration_sec=60.0):
                bg_audio = auto_score

        voices_dir = PROJECTS_DIR / project_id / "voices"
        master_voice_wav = str(output_dir / "master_storytelling_voice.wav")
        master_srt = str(output_dir / f"{sanitized_name}_Subtitles.srt")
        st_res = audio_studio.build_storytelling_track(
            scenes=valid_scenes,
            voices_dir=voices_dir,
            output_voice_wav=master_voice_wav,
            output_srt_path=master_srt,
            progress_callback=lambda pct, msg: self.emit_event("compile_progress", {"percent": pct, "message": msg})
        )
        voice_wav = master_voice_wav if (st_res.get("success") and st_res.get("has_voice")) else None
        srt_path = master_srt if (st_res.get("success") and os.path.exists(master_srt)) else None

        compiler = MovieCompiler(log_callback=lambda lvl, msg: self.log(project_id, lvl, msg))
        self.emit_event("compile_progress", {"percent": 32.0, "message": "Initiating automatic cinema master compilation..."})

        res = compiler.compile_movie(
            clip_paths=clip_paths,
            output_movie_path=output_movie,
            transition_mode="direct",
            background_audio_path=bg_audio,
            storytelling_voice_path=voice_wav,
            subtitle_path=srt_path,
            music_volume=0.22,
            normalize_audio=True,
            enhance_quality=True,
            cinema_widescreen=True,
            resolution="1080p",
            progress_callback=lambda pct, msg: self.emit_event("compile_progress", {"percent": pct, "message": msg})
        )

        if res.get("success"):
            movie_filename = os.path.basename(output_movie)
            self.log(project_id, "success", f"🍿 Master Film Auto-Compiled! File: {movie_filename} ({res.get('file_size_mb')} MB)")
            self.emit_event("compile_completed", {
                "movie_url": f"/projects/{project_id}/output/{movie_filename}",
                "file_size_mb": res.get("file_size_mb"),
                "total_clips": res.get("total_clips")
            })

pipeline = PipelineManager()
