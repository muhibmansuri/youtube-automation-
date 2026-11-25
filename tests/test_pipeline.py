import os
import sys
import time
import numpy as np
import cv2

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import FFMPEG_PATH, PROJECTS_DIR
from database import db
from core.continuity import ContinuityProcessor
from core.movie_compiler import MovieCompiler
from app import app

def generate_synthetic_clip(file_path: str, duration_sec: int = 2, color=(0, 128, 255)):
    """Creates a small valid synthetic MP4 video clip for verification tests."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    fps = 24
    width, height = 640, 360
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(file_path, fourcc, fps, (width, height))

    total_frames = fps * duration_sec
    for i in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = color
        # Add dynamic moving text to simulate video
        cv2.putText(frame, f"Frame {i}/{total_frames}", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        out.write(frame)

    out.release()
    assert os.path.exists(file_path) and os.path.getsize(file_path) > 1000

def test_database_crud():
    print("Testing Database CRUD...")
    test_id = f"test_proj_{int(time.time())}"
    p = db.create_project(
        project_id=test_id,
        name="Test Cyberpunk Film",
        genre="Sci-Fi",
        storyline="A synthetic detective searches for truth in a neon rain city.",
        target_duration_mins=10,
        character_profile="Female runner, blue eyes, leather jacket"
    )
    assert p["id"] == test_id
    assert p["total_scenes"] == 75  # 10m * 60s / 8s = 75

    # Insert test scenes
    scenes = [
        {
            "scene_number": 1,
            "title": "Opening Neon Alley",
            "prompt": "Cinematic 8k. Protagonist walks down rainy neon alley.",
            "status": "PENDING"
        },
        {
            "scene_number": 2,
            "title": "Terminal Hack",
            "prompt": "Cinematic 8k. Protagonist plugs datapad into terminal.",
            "status": "PENDING"
        }
    ]
    db.insert_scenes_batch(test_id, scenes)
    all_s = db.get_scenes(test_id)
    assert len(all_s) == 2

    # Update scene
    updated = db.update_scene(test_id, 1, status="COMPLETED")
    assert updated["status"] == "COMPLETED"

    # Stats
    stats = db.get_scene_stats(test_id)
    assert stats["total"] == 2
    assert stats["completed"] == 1
    assert stats["pending"] == 1

    # Cleanup test project
    db.delete_project(test_id)
    print("Database CRUD test: PASSED")

def test_continuity_processor():
    print("Testing Continuity Processor (OpenCV Frame Extraction)...")
    test_clip = "tests/test_clip_001.mp4"
    test_frame = "tests/test_frame_001.jpg"

    generate_synthetic_clip(test_clip, duration_sec=2, color=(50, 100, 200))

    # Extract last frame
    res = ContinuityProcessor.extract_last_frame(test_clip, test_frame)
    assert res["success"] is True, f"Extraction failed: {res.get('error')}"
    assert os.path.exists(test_frame)
    assert res["validation"]["is_valid"] is True
    print(f"Extracted frame: {res['validation']['width']}x{res['validation']['height']}, Method: {res['method']}")

    # Clean up
    if os.path.exists(test_clip): os.remove(test_clip)
    if os.path.exists(test_frame): os.remove(test_frame)
    print("Continuity Processor test: PASSED")

def test_movie_compiler():
    print("Testing FFmpeg Movie Compiler...")
    clip1 = "tests/clip_001.mp4"
    clip2 = "tests/clip_002.mp4"
    out_movie = "tests/test_movie_compiled.mp4"

    generate_synthetic_clip(clip1, duration_sec=2, color=(0, 150, 255))
    generate_synthetic_clip(clip2, duration_sec=2, color=(255, 100, 50))

    compiler = MovieCompiler()
    res = compiler.compile_movie(
        clip_paths=[clip1, clip2],
        output_movie_path=out_movie,
        transition_mode="direct",
        resolution="1080p",
        normalize_audio=False
    )

    assert res["success"] is True, f"Compilation failed: {res.get('error')}"
    assert os.path.exists(out_movie) and os.path.getsize(out_movie) > 5000
    print(f"Movie compiled: {res['file_size_mb']} MB in {res['compilation_time_seconds']}s")

    # Clean up
    for f in [clip1, clip2, out_movie]:
        if os.path.exists(f): os.remove(f)
    print("Movie Compiler test: PASSED")

def test_flask_endpoints():
    print("Testing Flask REST APIs...")
    with app.test_client() as client:
        # GET index
        r = client.get("/")
        assert r.status_code == 200
        assert b"TAAFT" in r.data

        # GET settings
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True

        # GET projects
        r = client.get("/api/projects")
        assert r.status_code == 200

        # POST create project
        r = client.post("/api/projects", json={
            "name": "Integration Test Movie",
            "genre": "Neo-Noir",
            "storyline": "Detective unravels mystery",
            "target_duration_mins": 5
        })
        assert r.status_code == 200
        proj_id = r.get_json()["project"]["id"]

        # GET scenes for project
        r = client.get(f"/api/projects/{proj_id}/scenes")
        assert r.status_code == 200

        # DELETE project
        r = client.delete(f"/api/projects/{proj_id}")
        assert r.status_code == 200

    print("Flask REST APIs test: PASSED")

if __name__ == "__main__":
    test_database_crud()
    test_continuity_processor()
    test_movie_compiler()
    test_flask_endpoints()
    print("\nALL SYSTEM TESTS PASSED SUCCESSFULLY! 🚀")
