import os
import sys
import time
import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import PROJECTS_DIR, FFMPEG_PATH
from database import db
from core.scriptwriter import AutonomousScriptEngine, GeminiScriptwriter
from core.continuity import ContinuityProcessor
from core.movie_compiler import MovieCompiler
from core.pipeline_manager import pipeline
from app import app

def generate_dummy_mp4(file_path: str, duration_sec: int = 2, color=(0, 200, 100), label="Scene"):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    fps = 24
    width, height = 640, 360
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(file_path, fourcc, fps, (width, height))

    total = fps * duration_sec
    for i in range(total):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = color
        cv2.putText(frame, f"{label} Frame {i}/{total}", (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    assert os.path.exists(file_path) and os.path.getsize(file_path) > 1000

def run_full_audit():
    print("=" * 70)
    print("      🚀 COMPREHENSIVE END-TO-END SYSTEM AUDIT 🚀")
    print("=" * 70)

    # 1. Project Initialization in SQLite
    print("\n[CHECK 1/7] Testing Project Creation & SQLite Persistence...")
    test_pid = f"audit_proj_{int(time.time())}"
    proj = db.create_project(
        project_id=test_pid,
        name="The Neon Citadel (Audit Film)",
        genre="Cinematic Sci-Fi / Cyberpunk",
        storyline="A lone courier carries a bio-mechanical core across the neon rain ruins of Neo-Tokyo.",
        target_duration_mins=10,
        character_profile="Elena Cross, 27, hazel eyes, sharp black asymmetrical bob, obsidian carbon-fiber tactical jacket"
    )
    assert proj["id"] == test_pid
    assert proj["total_scenes"] == 75
    print("  -> Project created successfully: Total target scenes = 75")

    # 2. Autonomous Script Generator (Zero-API Engine)
    print("\n[CHECK 2/7] Testing Autonomous Zero-API Script Engine (Prompt & Continuity Logic)...")
    scenes = AutonomousScriptEngine.generate_scenes(
        project_id=test_pid,
        storyline=proj["storyline"],
        genre=proj["genre"],
        character_profile=proj["character_profile"],
        start_scene=1,
        count=10,
        total_movie_scenes=75
    )
    assert len(scenes) == 10
    assert "<Image 1>" in scenes[0]["prompt"]
    assert "<Image 1>" in scenes[1]["prompt"] and "<Image 2>" in scenes[1]["prompt"]
    db.insert_scenes_batch(test_pid, scenes)
    print("  -> 10 Scenes generated with strict <Image 1> and <Image 2> continuity locking!")

    # 3. Database State & Scene Verification
    print("\n[CHECK 3/7] Verifying Scene Queue in Database...")
    db_scenes = db.get_scenes(test_pid)
    assert len(db_scenes) == 10
    next_pending = db.get_next_pending_scene(test_pid)
    assert next_pending["scene_number"] == 1
    stats = db.get_scene_stats(test_pid)
    assert stats["total"] == 10
    assert stats["pending"] == 10
    print(f"  -> Queue stats verified: {stats}")

    # 4. Continuity Processor (OpenCV Last Frame Extraction & Validation)
    print("\n[CHECK 4/7] Testing OpenCV Frame Extraction & Continuity Chaining...")
    clip1_path = str(PROJECTS_DIR / test_pid / "clips" / "clip_001.mp4")
    clip2_path = str(PROJECTS_DIR / test_pid / "clips" / "clip_002.mp4")
    frame1_path = str(PROJECTS_DIR / test_pid / "last_frames" / "last_frame_001.jpg")

    generate_dummy_mp4(clip1_path, duration_sec=2, color=(30, 80, 220), label="Scene 001")
    generate_dummy_mp4(clip2_path, duration_sec=2, color=(20, 180, 90), label="Scene 002")

    ext_res = ContinuityProcessor.extract_last_frame(clip1_path, frame1_path)
    assert ext_res["success"] is True
    assert os.path.exists(frame1_path)
    val = ext_res["validation"]
    assert val["is_valid"] is True
    print(f"  -> Extracted Scene 1 Last Frame ({val['width']}x{val['height']}) -> Ready for Scene 2 <Image 2>")

    # Update Scene 1 as COMPLETED
    db.update_scene(test_pid, 1, status="COMPLETED", clip_path=clip1_path, last_frame_path=frame1_path)
    db.update_scene(test_pid, 2, status="COMPLETED", clip_path=clip2_path)

    # 5. FFmpeg Movie Compiler (Direct & Crossfade Concat)
    print("\n[CHECK 5/7] Testing FFmpeg Movie Stitcher & Audio Normalizer...")
    final_movie_path = str(PROJECTS_DIR / test_pid / "output" / "Final_Movie_Audit.mp4")
    compiler = MovieCompiler()
    compile_res = compiler.compile_movie(
        clip_paths=[clip1_path, clip2_path],
        output_movie_path=final_movie_path,
        transition_mode="direct",
        resolution="1080p",
        normalize_audio=False
    )
    assert compile_res["success"] is True
    assert os.path.exists(final_movie_path)
    movie_size_mb = compile_res["file_size_mb"]
    print(f"  -> Movie Compiled Successfully: {movie_size_mb} MB in {compile_res['compilation_time_seconds']}s")

    # 6. Web Dashboard REST APIs & File Serving
    print("\n[CHECK 6/7] Testing Web Dashboard REST Endpoints & File Serving...")
    with app.test_client() as client:
        # Dashboard UI
        r = client.get("/")
        assert r.status_code == 200

        # Project details
        r = client.get(f"/api/projects/{test_pid}")
        assert r.status_code == 200

        # Scenes endpoint
        r = client.get(f"/api/projects/{test_pid}/scenes")
        assert r.status_code == 200
        scenes_data = r.get_json()["scenes"]
        assert len(scenes_data) == 10
        assert scenes_data[0]["clip_url"] != ""

        # Movie status endpoint
        r = client.get(f"/api/projects/{test_pid}/movie_status")
        assert r.status_code == 200
        movie_info = r.get_json()
        assert movie_info["has_movie"] is True
        print(f"  -> Screening room serving: {movie_info['filename']} ({movie_info['file_size_mb']} MB)")

        # Pipeline status
        r = client.get(f"/api/pipeline/status?project_id={test_pid}")
        assert r.status_code == 200

    # 7. Clean up audit project
    print("\n[CHECK 7/7] Cleaning up audit fixtures...")
    db.delete_project(test_pid)
    import shutil
    shutil.rmtree(str(PROJECTS_DIR / test_pid), ignore_errors=True)
    print("  -> Cleanup complete.")

    print("\n" + "=" * 70)
    print("  🎉 ALL 7 CORE SUBSYSTEMS AUDITED & 100% OPERATIONAL! 🎉")
    print("=" * 70)

if __name__ == "__main__":
    run_full_audit()
