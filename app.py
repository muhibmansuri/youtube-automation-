import os
import time
import json
import queue
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename
from config import (
    BASE_DIR,
    PROJECTS_DIR,
    DB_PATH,
    DEFAULT_GEMINI_MODEL,
    FFMPEG_PATH,
    get_gemini_api_key
)
from database import db
from core.scriptwriter import GeminiScriptwriter
from core.continuity import ContinuityProcessor
from core.movie_compiler import MovieCompiler
from core.voice_synthesizer import VoiceSynthesizer
from core.pipeline_manager import pipeline

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = "taaft-movie-gen-secret-2026"
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB max upload

# SSE Event Queues
event_queues = []

def sse_event_listener(event):
    for q in list(event_queues):
        try:
            q.put_nowait(event)
        except Exception:
            pass

pipeline.register_event_subscriber(sse_event_listener)

# --- Static & Project File Serving ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/projects/<project_id>/<folder>/<filename>")
def serve_project_file(project_id, folder, filename):
    folder_path = PROJECTS_DIR / project_id / folder
    return send_from_directory(str(folder_path), filename)

@app.route("/projects/<project_id>/<filename>")
def serve_project_root_file(project_id, filename):
    proj_path = PROJECTS_DIR / project_id
    return send_from_directory(str(proj_path), filename)

# --- SSE Realtime Stream ---
@app.route("/api/events")
def sse_stream():
    def event_stream():
        q = queue.Queue(maxsize=100)
        event_queues.append(q)
        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    event = q.get(timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    # Heartbeat
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            if q in event_queues:
                event_queues.remove(q)

    return Response(event_stream(), mimetype="text/event-stream")

# --- Project Management APIs ---
@app.route("/api/projects", methods=["GET"])
def list_projects():
    projects = db.list_projects()
    return jsonify({"success": True, "projects": projects})

@app.route("/api/projects", methods=["POST"])
def create_project():
    data = request.json or {}
    name = data.get("name", "").strip() or f"Movie_{time.strftime('%Y%m%d_%H%M%S')}"
    genre = data.get("genre", "Cinematic Sci-Fi")
    storyline = data.get("storyline", "").strip()
    target_duration = int(data.get("target_duration_mins", 120))
    character_profile = data.get("character_profile", "")
    model_type = data.get("model_type", "Quality")
    orientation = data.get("orientation", "Landscape")

    if not storyline:
        return jsonify({"success": False, "error": "Storyline / concept is required."}), 400

    project_id = f"proj_{int(time.time())}"
    proj_dir = PROJECTS_DIR / project_id
    (proj_dir / "master_refs").mkdir(parents=True, exist_ok=True)
    (proj_dir / "clips").mkdir(parents=True, exist_ok=True)
    (proj_dir / "last_frames").mkdir(parents=True, exist_ok=True)
    (proj_dir / "audio").mkdir(parents=True, exist_ok=True)
    (proj_dir / "output").mkdir(parents=True, exist_ok=True)

    project = db.create_project(
        project_id=project_id,
        name=name,
        genre=genre,
        storyline=storyline,
        target_duration_mins=target_duration,
        character_profile=character_profile,
        model_type=model_type,
        orientation=orientation
    )
    return jsonify({"success": True, "project": project})

@app.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404
    stats = db.get_scene_stats(project_id)
    pipeline_state = db.get_pipeline_state(project_id)
    return jsonify({"success": True, "project": proj, "stats": stats, "pipeline_state": pipeline_state})

@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    if pipeline.active_project_id == project_id and pipeline.is_running:
        pipeline.stop_pipeline(project_id)

    db.delete_project(project_id)
    proj_dir = PROJECTS_DIR / project_id
    if proj_dir.exists():
        try:
            shutil.rmtree(str(proj_dir), ignore_errors=True)
        except Exception:
            pass
    return jsonify({"success": True, "message": f"Project {project_id} deleted."})

@app.route("/api/projects/<project_id>/upload_ref", methods=["POST"])
def upload_reference_image(project_id):
    """Uploads Master Character Reference Images (Image 1) or background audio tracks."""
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    upload_type = request.form.get("type", "master_ref") # "master_ref" or "audio"
    files = request.files.getlist("files")
    if not files:
        return jsonify({"success": False, "error": "No files uploaded"}), 400

    saved_paths = []
    target_folder = "master_refs" if upload_type == "master_ref" else "audio"
    dest_dir = PROJECTS_DIR / project_id / target_folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            save_path = dest_dir / f"{int(time.time())}_{filename}"
            file.save(str(save_path))
            saved_paths.append(str(save_path))

    if upload_type == "master_ref":
        current_refs = proj.get("master_ref_images") or []
        updated_refs = current_refs + saved_paths
        db.update_project(project_id, master_ref_images=updated_refs)
        return jsonify({
            "success": True, 
            "uploaded": saved_paths, 
            "master_ref_images": updated_refs,
            "urls": [f"/projects/{project_id}/master_refs/{os.path.basename(p)}" for p in updated_refs]
        })
    else:
        return jsonify({"success": True, "audio_files": saved_paths})

# --- Script & Scene Management APIs ---
@app.route("/api/projects/<project_id>/generate_script", methods=["POST"])
def generate_script(project_id):
    """Uses Gemini API to generate the initial or full batch of sequential 8s scenes."""
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    data = request.json or {}
    batch_size = int(data.get("batch_size", 30))  # Default batch of 30 scenes
    start_scene = int(data.get("start_scene", 1))
    use_autonomous = data.get("mode") == "autonomous" or bool(data.get("use_autonomous", False))

    api_key = get_gemini_api_key()
    model_name = db.get_setting("gemini_model", DEFAULT_GEMINI_MODEL)
    if not model_name or "gemini-2.5" in model_name or "gemini-1.5" in model_name:
        model_name = DEFAULT_GEMINI_MODEL
        db.set_setting("gemini_model", model_name)

    writer = GeminiScriptwriter(api_key=api_key, model_name=model_name)

    try:
        engine_label = "Autonomous Zero-API Engine" if (use_autonomous or not api_key) else f"Gemini ({model_name})"
        pipeline.log(project_id, "info", f"Generating scenes {start_scene} to {start_scene + batch_size - 1} via {engine_label}...")
        master_descriptions = ", ".join([os.path.basename(p) for p in (proj.get("master_ref_images") or [])])

        scenes = writer.generate_scene_batch(
            project_id=project_id,
            storyline=proj["storyline"],
            genre=proj["genre"],
            character_profile=proj.get("character_profile", ""),
            start_scene=start_scene,
            count=batch_size,
            total_movie_scenes=proj["total_scenes"],
            master_ref_descriptions=master_descriptions,
            use_autonomous_engine=use_autonomous
        )

        db.insert_scenes_batch(project_id, scenes)
        update_fields = {"status": "SCRIPT_GENERATED"}
        if len(scenes) > 0 and len(scenes) != proj.get("total_scenes"):
            # If a structured master script was parsed (e.g. 75 exact scenes), sync project total_scenes
            from core.scriptwriter import AutonomousScriptEngine
            if AutonomousScriptEngine.parse_structured_script(project_id, proj["storyline"], proj["genre"], proj.get("character_profile", "")):
                update_fields["total_scenes"] = len(scenes)
                update_fields["target_duration_mins"] = max(1, round((len(scenes) * 8) / 60))
        db.update_project(project_id, **update_fields)
        pipeline.log(project_id, "success", f"Successfully loaded {len(scenes)} scenes with strict continuity prompts!")
        
        return jsonify({
            "success": True, 
            "scenes_generated": len(scenes),
            "stats": db.get_scene_stats(project_id)
        })

    except Exception as e:
        pipeline.log(project_id, "error", f"Script generation failed: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/projects/<project_id>/scenes", methods=["GET"])
def get_scenes(project_id):
    status_filter = request.args.get("status")
    scenes = db.get_scenes(project_id, status=status_filter)
    
    # Enrich with preview URLs and dialogue detection
    for s in scenes:
        num = s["scene_number"]
        if s.get("clip_path") and os.path.exists(s["clip_path"]):
            s["clip_url"] = f"/projects/{project_id}/clips/clip_{num:03d}.mp4"
        if s.get("last_frame_path") and os.path.exists(s["last_frame_path"]):
            s["last_frame_url"] = f"/projects/{project_id}/last_frames/last_frame_{num:03d}.jpg"
        dlg = VoiceSynthesizer.extract_dialogue(s.get("prompt", ""))
        if dlg:
            s["dialogue"] = dlg

    return jsonify({"success": True, "scenes": scenes, "stats": db.get_scene_stats(project_id)})

@app.route("/api/projects/<project_id>/scenes/<int:scene_number>", methods=["PUT"])
def update_scene(project_id, scene_number):
    data = request.json or {}
    updated = db.update_scene(project_id, scene_number, **data)
    return jsonify({"success": True, "scene": updated})

@app.route("/api/projects/<project_id>/scenes/<int:scene_number>/regenerate", methods=["POST"])
def regenerate_scene(project_id, scene_number):
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    data = request.json or {}
    user_instruction = data.get("instruction", "")

    prev_scene = db.get_scene(project_id, scene_number - 1) if scene_number > 1 else None
    next_scene = db.get_scene(project_id, scene_number + 1)

    api_key = get_gemini_api_key()
    model_name = db.get_setting("gemini_model", DEFAULT_GEMINI_MODEL)
    if not model_name or "gemini-2.5" in model_name or "gemini-1.5" in model_name:
        model_name = DEFAULT_GEMINI_MODEL
        db.set_setting("gemini_model", model_name)
    writer = GeminiScriptwriter(api_key=api_key, model_name=model_name)

    try:
        new_data = writer.regenerate_single_scene_prompt(
            project_id=project_id,
            scene_number=scene_number,
            storyline=proj["storyline"],
            genre=proj["genre"],
            character_profile=proj.get("character_profile", ""),
            prev_scene_prompt=prev_scene.get("prompt") if prev_scene else "",
            next_scene_prompt=next_scene.get("prompt") if next_scene else "",
            user_instruction=user_instruction
        )
        updated = db.update_scene(project_id, scene_number, **new_data)
        return jsonify({"success": True, "scene": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- Automation Pipeline APIs ---
@app.route("/api/pipeline/start", methods=["POST"])
def start_pipeline():
    data = request.json or {}
    project_id = data.get("project_id")
    headless = data.get("headless", True)
    model_type = data.get("model_type")

    if not project_id:
        return jsonify({"success": False, "error": "project_id is required"}), 400

    if model_type:
        db.update_project(project_id, model_type=model_type)

    res = pipeline.start_pipeline(project_id, headless=headless)
    return jsonify(res)

@app.route("/api/pipeline/pause", methods=["POST"])
def pause_pipeline():
    res = pipeline.pause_pipeline()
    return jsonify(res)

@app.route("/api/pipeline/resume", methods=["POST"])
def resume_pipeline():
    data = request.json or {}
    project_id = data.get("project_id")
    res = pipeline.resume_pipeline(project_id)
    return jsonify(res)

@app.route("/api/pipeline/stop", methods=["POST"])
def stop_pipeline():
    data = request.json or {}
    project_id = data.get("project_id")
    res = pipeline.stop_pipeline(project_id)
    return jsonify(res)

@app.route("/api/pipeline/launch_browser", methods=["POST"])
def launch_browser():
    res = pipeline.launch_interactive_browser()
    return jsonify(res)

@app.route("/api/pipeline/status", methods=["GET"])
def pipeline_status():
    project_id = request.args.get("project_id")
    status = pipeline.get_status(project_id)
    logs = db.get_logs(project_id or "global", limit=50) if project_id else []
    return jsonify({"success": True, "status": status, "logs": logs})

# --- Movie Compiler Studio APIs ---
@app.route("/api/projects/<project_id>/compile", methods=["POST"])
def compile_movie(project_id):
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    data = request.json or {}
    transition_mode = data.get("transition_mode", "direct")  # "direct" or "crossfade"
    crossfade_duration = float(data.get("crossfade_duration", 0.3))
    normalize_audio = bool(data.get("normalize_audio", True))
    resolution = data.get("resolution", "1080p")
    music_volume = float(data.get("music_volume", 0.45))
    enhance_quality = bool(data.get("enhance_quality", True))
    cinema_widescreen = bool(data.get("cinema_widescreen", True))
    audio_mode = data.get("audio_mode", "storyteller")  # "storyteller", "original_with_bgm", "original_only"
    color_grade = data.get("color_grade", "noir")       # "noir", "natural"
    burn_subtitles = bool(data.get("burn_subtitles", True))

    # Get completed scenes sorted sequentially
    completed_scenes = sorted(db.get_scenes(project_id, status="COMPLETED"), key=lambda s: s["scene_number"])
    valid_scenes = [s for s in completed_scenes if s.get("clip_path") and os.path.exists(s["clip_path"])]
    clip_paths = [s["clip_path"] for s in valid_scenes]

    if not clip_paths:
        return jsonify({"success": False, "error": "No completed clips found to compile."}), 400

    output_dir = PROJECTS_DIR / project_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    import time as _t
    stamp = _t.strftime("%H%M%S")
    output_movie = str(output_dir / f"{proj['name']}_Edit_{audio_mode}_{resolution}_{stamp}.mp4")

    # Check or generate background thriller score
    audio_dir = PROJECTS_DIR / project_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))
    bg_audio = str(audio_files[0]) if audio_files else None

    compiler = MovieCompiler(log_callback=lambda lvl, msg: pipeline.log(project_id, lvl, msg))

    def _compile_bg():
        from core.cinema_audio import CinemaAudioStudio
        audio_studio = CinemaAudioStudio(log_callback=lambda lvl, msg: pipeline.log(project_id, lvl, msg))

        nonlocal bg_audio
        if audio_mode in ("storyteller", "original_with_bgm"):
            if not bg_audio:
                auto_score = str(audio_dir / "auto_thriller_score.wav")
                if audio_studio.generate_thriller_soundscape(auto_score, duration_sec=64.0):
                    bg_audio = auto_score
        else:
            bg_audio = None

        voice_wav = None
        srt_path = None
        if audio_mode == "storyteller" or burn_subtitles:
            voices_dir = PROJECTS_DIR / project_id / "voices"
            master_voice_wav = str(output_dir / "master_storytelling_voice.wav")
            master_srt = str(output_dir / f"{proj['name']}_Subtitles.srt")
            st_res = audio_studio.build_storytelling_track(
                scenes=valid_scenes,
                voices_dir=voices_dir,
                output_voice_wav=master_voice_wav,
                output_srt_path=master_srt,
                progress_callback=lambda pct, msg: pipeline.emit_event("compile_progress", {"percent": pct, "message": msg})
            )
            if audio_mode == "storyteller" and st_res.get("success") and st_res.get("has_voice"):
                voice_wav = master_voice_wav
            if st_res.get("success") and burn_subtitles and os.path.exists(master_srt):
                srt_path = master_srt

        res = compiler.compile_movie(
            clip_paths=clip_paths,
            output_movie_path=output_movie,
            transition_mode=transition_mode,
            crossfade_duration=crossfade_duration,
            background_audio_path=bg_audio,
            storytelling_voice_path=voice_wav,
            subtitle_path=srt_path,
            music_volume=music_volume,
            normalize_audio=normalize_audio,
            enhance_quality=enhance_quality,
            color_grade=color_grade,
            cinema_widescreen=cinema_widescreen,
            movie_title=proj.get("name"),
            resolution=resolution,
            progress_callback=lambda pct, msg: pipeline.emit_event("compile_progress", {"percent": pct, "message": msg})
        )
        if res.get("success"):
            movie_filename = os.path.basename(output_movie)
            pipeline.emit_event("compile_completed", {
                "movie_url": f"/projects/{project_id}/output/{movie_filename}",
                "file_size_mb": res.get("file_size_mb"),
                "total_clips": res.get("total_clips")
            })

    import threading
    t = threading.Thread(target=_compile_bg, daemon=True)
    t.start()

    return jsonify({"success": True, "message": f"Cinema Master compilation started for {len(clip_paths)} clips."})

@app.route("/api/projects/<project_id>/ai_upscale", methods=["POST"])
def ai_upscale_movie(project_id):
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    from core.ai_upscaler import upscaler
    if not upscaler.is_available():
        return jsonify({"success": False, "error": "Real-ESRGAN binary not found on server"}), 400

    output_dir = PROJECTS_DIR / project_id / "output"
    movies = list(output_dir.glob("*.mp4"))
    if not movies:
        return jsonify({"success": False, "error": "No compiled movie found. Please compile the movie first."}), 400

    latest_movie = max(movies, key=os.path.getmtime)
    output_4k = str(output_dir / f"{proj['name']}_Master_Film_RealESRGAN_4K.mp4")

    def _upscale_bg():
        pipeline.log(project_id, "info", "⚡ Starting Real-ESRGAN GPU AI 4K Upscaling...")
        res = upscaler.upscale_video_to_4k(
            input_video_path=str(latest_movie),
            output_video_path=output_4k,
            scale=4,
            model_name="realesrgan-x4plus",
            progress_callback=lambda pct, msg: pipeline.emit_event("compile_progress", {"percent": pct, "message": msg})
        )
        if res.get("success"):
            movie_filename = os.path.basename(output_4k)
            pipeline.emit_event("compile_completed", {
                "movie_url": f"/projects/{project_id}/output/{movie_filename}",
                "file_size_mb": res.get("file_size_mb"),
                "total_clips": res.get("total_frames")
            })

    import threading
    t = threading.Thread(target=_upscale_bg, daemon=True)
    t.start()

    return jsonify({"success": True, "message": "GPU AI 4K Super-Resolution Upscaling initiated!"})

@app.route("/api/projects/<project_id>/movie_status", methods=["GET"])
def movie_status(project_id):
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404

    output_dir = PROJECTS_DIR / project_id / "output"
    movies = sorted([m for m in output_dir.glob("*.mp4") if ".temp." not in m.name], key=os.path.getmtime, reverse=True)
    if movies:
        latest = movies[0]
        all_movies = [{
            "filename": m.name,
            "file_size_mb": round(os.path.getsize(str(m)) / (1024 * 1024), 2),
            "url": f"/projects/{project_id}/output/{m.name}"
        } for m in movies]
        return jsonify({
            "has_movie": True,
            "filename": latest.name,
            "file_size_mb": all_movies[0]["file_size_mb"],
            "url": all_movies[0]["url"],
            "all_movies": all_movies
        })
    return jsonify({"has_movie": False, "all_movies": []})

# --- Settings & Diagnostics APIs ---
@app.route("/api/settings", methods=["GET"])
def get_settings():
    settings = db.get_all_settings()
    model_name = db.get_setting("gemini_model", DEFAULT_GEMINI_MODEL)
    if not model_name or "gemini-2.5" in model_name or "gemini-1.5" in model_name:
        model_name = DEFAULT_GEMINI_MODEL
        db.set_setting("gemini_model", model_name)
    settings["gemini_model"] = model_name

    api_key = get_gemini_api_key()
    masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else ("Configured" if api_key else "")
    return jsonify({
        "success": True,
        "settings": settings,
        "gemini_api_key_configured": bool(api_key),
        "gemini_api_key_masked": masked_key,
        "ffmpeg_path": FFMPEG_PATH,
        "browser_profile": str(pipeline.current_worker.profile_dir) if pipeline.current_worker else str(BASE_DIR / "browser_profile")
    })

@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.json or {}
    if "gemini_api_key" in data and data["gemini_api_key"].strip():
        db.set_setting("gemini_api_key", data["gemini_api_key"].strip())
    if "elevenlabs_api_key" in data and data["elevenlabs_api_key"].strip():
        db.set_setting("elevenlabs_api_key", data["elevenlabs_api_key"].strip())
    if "elevenlabs_voice_id" in data and data["elevenlabs_voice_id"].strip():
        db.set_setting("elevenlabs_voice_id", data["elevenlabs_voice_id"].strip())
        os.environ["GEMINI_API_KEY"] = data["gemini_api_key"].strip()

    if "gemini_model" in data:
        db.set_setting("gemini_model", data["gemini_model"].strip())

    return jsonify({"success": True, "message": "Settings updated successfully."})

@app.route("/api/settings/test_gemini", methods=["POST"])
def test_gemini():
    api_key = get_gemini_api_key()
    writer = GeminiScriptwriter(api_key=api_key)
    res = writer.test_connection()
    return jsonify(res)

@app.route("/api/settings/test_ffmpeg", methods=["POST"])
def test_ffmpeg():
    import subprocess
    try:
        r = subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            version_line = r.stdout.splitlines()[0] if r.stdout else "FFmpeg active"
            return jsonify({"success": True, "version": version_line, "path": FFMPEG_PATH})
        return jsonify({"success": False, "error": r.stderr})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# --- Neural Voice Studio APIs ---
@app.route("/api/voices", methods=["GET"])
def get_voices():
    """Lists all available human-like neural studio voices."""
    return jsonify({
        "success": True,
        "voices": VoiceSynthesizer.list_available_voices()
    })

@app.route("/api/voices/preview", methods=["POST"])
def preview_voice():
    """Generates a real-time speech preview for UI testing."""
    data = request.json or {}
    text = data.get("text", "हेलो, यह कोडऑरा सिनेमा स्टूडियो की आवाज़ है।").strip()
    voice_id = data.get("voice_id", "hi_arjun")
    
    preview_dir = BASE_DIR / "static" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_file = str(preview_dir / f"preview_{voice_id}.mp3")
    
    success = VoiceSynthesizer.generate_speech(text, character=voice_id, output_path=out_file)
    if success and os.path.exists(out_file):
        return jsonify({
            "success": True,
            "audio_url": f"/static/previews/preview_{voice_id}.mp3?t={int(time.time())}"
        })
    return jsonify({"success": False, "error": "Voice synthesis failed."}), 500

@app.route("/api/projects/<project_id>/redub", methods=["POST"])
def redub_project_clips(project_id):
    """
    Re-extracts dialogue and synthesizes pure studio neural voices
    for all completed scene clips in a background thread, eliminating any robotic AI noise.
    """
    proj = db.get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "Project not found"}), 404
        
    def _redub_bg():
        try:
            scenes = db.get_scenes(project_id, status="COMPLETED")
            clips_dir = PROJECTS_DIR / project_id / "clips"
            voices_dir = PROJECTS_DIR / project_id / "voices"
            voices_dir.mkdir(parents=True, exist_ok=True)
            
            pipeline.log(project_id, "info", f"🎙️ Initiating audio enhancement across {len(scenes)} completed scenes...")
            redubbed_count = 0
            muted_noise_count = 0
            
            for s in scenes:
                s_num = s["scene_number"]
                clip_path = str(clips_dir / f"clip_{s_num:03d}.mp4")
                if not os.path.exists(clip_path):
                    continue
                    
                dlg = VoiceSynthesizer.extract_dialogue(s.get("prompt", ""))
                if dlg:
                    voice_file = str(voices_dir / f"voice_{s_num:03d}.mp3")
                    ok = VoiceSynthesizer.generate_speech(dlg["text"], character=dlg["character"], output_path=voice_file)
                    if ok and os.path.exists(voice_file):
                        temp_dub = str(clips_dir / f"clip_{s_num:03d}_temp.mp4")
                        if VoiceSynthesizer.attach_voice_to_clip(clip_path, voice_file, temp_dub, duck_bg=0.0):
                            os.replace(temp_dub, clip_path)
                            redubbed_count += 1
                            pipeline.log(project_id, "success", f"🎙️ Re-dubbed Scene #{s_num:03d} with studio voice ({dlg.get('voice_name', dlg['character'])})")
                else:
                    # Mute robotic TAAFT noise on ambient clips
                    temp_clean = str(clips_dir / f"clip_{s_num:03d}_clean.mp4")
                    if VoiceSynthesizer.mute_clip_audio(clip_path, temp_clean):
                        os.replace(temp_clean, clip_path)
                        muted_noise_count += 1
                        
            pipeline.log(project_id, "success", f"🎉 Audio Enhancement Finished! {redubbed_count} scenes dubbed with Neural Voice, {muted_noise_count} ambient scenes cleaned of robotic noise.")
        except Exception as e:
            pipeline.log(project_id, "error", f"Audio re-dubbing error: {str(e)}")

    import threading
    t = threading.Thread(target=_redub_bg, daemon=True)
    t.start()
    return jsonify({
        "success": True, 
        "message": "🎙️ Audio re-dubbing started in the background! Follow live progress in the Terminal Logs."
    })

if __name__ == "__main__":
    print(f"🎬 TAAFT Movie Generator Server running on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
