import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path
from config import DB_PATH

class Database:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Database, cls).__new__(cls)
                cls._instance._init_db()
            return cls._instance

    def _get_connection(self):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Projects table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                genre TEXT DEFAULT 'Cinematic Sci-Fi',
                storyline TEXT NOT NULL,
                target_duration_mins INTEGER DEFAULT 120,
                total_scenes INTEGER DEFAULT 900,
                character_profile TEXT DEFAULT '',
                master_ref_images TEXT DEFAULT '[]',
                status TEXT DEFAULT 'DRAFT',
                model_type TEXT DEFAULT 'Quality',
                orientation TEXT DEFAULT 'Landscape',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)

            # Scenes table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                scene_number INTEGER NOT NULL,
                title TEXT DEFAULT '',
                scene_act TEXT DEFAULT '',
                prompt TEXT NOT NULL,
                visual_action TEXT DEFAULT '',
                camera_movement TEXT DEFAULT '',
                lighting_style TEXT DEFAULT '',
                character_details TEXT DEFAULT '',
                continuity_notes TEXT DEFAULT '',
                ref_images TEXT DEFAULT '[]',
                last_frame_path TEXT DEFAULT '',
                clip_path TEXT DEFAULT '',
                status TEXT DEFAULT 'PENDING',
                generation_time_seconds REAL DEFAULT 0,
                error_message TEXT DEFAULT '',
                extend_from_prev INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE (project_id, scene_number)
            )
            """)

            # Pipeline State table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_state (
                project_id TEXT PRIMARY KEY,
                is_running INTEGER DEFAULT 0,
                is_paused INTEGER DEFAULT 0,
                current_scene_number INTEGER DEFAULT 0,
                quota_left INTEGER DEFAULT 100,
                quota_total INTEGER DEFAULT 100,
                reset_at TEXT DEFAULT '',
                last_screenshot_path TEXT DEFAULT '',
                status_message TEXT DEFAULT 'Idle',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """)

            # Logs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """)

            # Settings table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """)
            conn.commit()

    # --- Project Methods ---
    def create_project(self, project_id, name, genre, storyline, target_duration_mins, character_profile="", master_ref_images=None, model_type="Quality", orientation="Landscape"):
        now = datetime.now().isoformat()
        total_scenes = max(1, int(round((target_duration_mins * 60) / 8)))
        images_json = json.dumps(master_ref_images or [])
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO projects (id, name, genre, storyline, target_duration_mins, total_scenes, character_profile, master_ref_images, status, model_type, orientation, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
            """, (project_id, name, genre, storyline, target_duration_mins, total_scenes, character_profile, images_json, model_type, orientation, now, now))
            
            # Initialize pipeline state
            cursor.execute("""
            INSERT OR REPLACE INTO pipeline_state (project_id, is_running, is_paused, current_scene_number, quota_left, quota_total, reset_at, last_screenshot_path, status_message, updated_at)
            VALUES (?, 0, 0, 0, 100, 100, '', '', 'Project initialized', ?)
            """, (project_id, now))
            conn.commit()
        return self.get_project(project_id)

    def get_project(self, project_id):
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["master_ref_images"] = json.loads(data.get("master_ref_images") or "[]")
            return data

    def list_projects(self):
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["master_ref_images"] = json.loads(d.get("master_ref_images") or "[]")
                result.append(d)
            return result

    def update_project(self, project_id, **kwargs):
        now = datetime.now().isoformat()
        kwargs["updated_at"] = now
        if "master_ref_images" in kwargs and isinstance(kwargs["master_ref_images"], list):
            kwargs["master_ref_images"] = json.dumps(kwargs["master_ref_images"])
        
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [project_id]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE projects SET {fields} WHERE id = ?", values)
            conn.commit()
        return self.get_project(project_id)

    def delete_project(self, project_id):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM pipeline_state WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM logs WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

    # --- Scene Methods ---
    def insert_scenes_batch(self, project_id, scenes_list):
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for s in scenes_list:
                ref_json = json.dumps(s.get("ref_images", []))
                cursor.execute("""
                INSERT OR REPLACE INTO scenes (
                    project_id, scene_number, title, scene_act, prompt, visual_action, camera_movement,
                    lighting_style, character_details, continuity_notes, ref_images, last_frame_path,
                    clip_path, status, generation_time_seconds, error_message, extend_from_prev, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id, s["scene_number"], s.get("title", f"Scene {s['scene_number']}"),
                    s.get("scene_act", ""), s["prompt"], s.get("visual_action", ""),
                    s.get("camera_movement", ""), s.get("lighting_style", ""),
                    s.get("character_details", ""), s.get("continuity_notes", ""),
                    ref_json, s.get("last_frame_path", ""), s.get("clip_path", ""),
                    s.get("status", "PENDING"), s.get("generation_time_seconds", 0),
                    s.get("error_message", ""), s.get("extend_from_prev", 0), now, now
                ))
            conn.commit()

    def get_scenes(self, project_id, status=None):
        with self._get_connection() as conn:
            if status:
                rows = conn.execute("SELECT * FROM scenes WHERE project_id = ? AND status = ? ORDER BY scene_number ASC", (project_id, status)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM scenes WHERE project_id = ? ORDER BY scene_number ASC", (project_id,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["ref_images"] = json.loads(d.get("ref_images") or "[]")
                result.append(d)
            return result

    def get_scene(self, project_id, scene_number):
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM scenes WHERE project_id = ? AND scene_number = ?", (project_id, scene_number)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["ref_images"] = json.loads(d.get("ref_images") or "[]")
            return d

    def update_scene(self, project_id, scene_number, **kwargs):
        now = datetime.now().isoformat()
        kwargs["updated_at"] = now
        if "ref_images" in kwargs and isinstance(kwargs["ref_images"], list):
            kwargs["ref_images"] = json.dumps(kwargs["ref_images"])
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [project_id, scene_number]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE scenes SET {fields} WHERE project_id = ? AND scene_number = ?", values)
            conn.commit()
        return self.get_scene(project_id, scene_number)

    def get_next_pending_scene(self, project_id):
        with self._get_connection() as conn:
            row = conn.execute("""
            SELECT * FROM scenes 
            WHERE project_id = ? AND status IN ('PENDING', 'FAILED')
            ORDER BY scene_number ASC LIMIT 1
            """, (project_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["ref_images"] = json.loads(d.get("ref_images") or "[]")
            return d

    def get_scene_stats(self, project_id):
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ?", (project_id,)).fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ? AND status = 'COMPLETED'", (project_id,)).fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ? AND status = 'PENDING'", (project_id,)).fetchone()[0]
            generating = conn.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ? AND status = 'GENERATING'", (project_id,)).fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ? AND status = 'FAILED'", (project_id,)).fetchone()[0]
            return {
                "total": total,
                "completed": completed,
                "pending": pending,
                "generating": generating,
                "failed": failed,
                "progress_percent": round((completed / total * 100), 1) if total > 0 else 0
            }

    # --- Pipeline State Methods ---
    def get_pipeline_state(self, project_id):
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM pipeline_state WHERE project_id = ?", (project_id,)).fetchone()
            if not row:
                now = datetime.now().isoformat()
                conn.execute("INSERT OR REPLACE INTO pipeline_state (project_id, updated_at) VALUES (?, ?)", (project_id, now))
                conn.commit()
                row = conn.execute("SELECT * FROM pipeline_state WHERE project_id = ?", (project_id,)).fetchone()
            return dict(row)

    def update_pipeline_state(self, project_id, **kwargs):
        now = datetime.now().isoformat()
        kwargs["updated_at"] = now
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [project_id]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE pipeline_state SET {fields} WHERE project_id = ?", values)
            conn.commit()
        return self.get_pipeline_state(project_id)

    # --- Logs Methods ---
    def add_log(self, project_id, level, message):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            conn.execute("INSERT INTO logs (project_id, timestamp, level, message) VALUES (?, ?, ?, ?)",
                         (project_id, now, level.upper(), message))
            conn.commit()

    def get_logs(self, project_id, limit=100):
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM logs WHERE project_id = ? ORDER BY id DESC LIMIT ?", (project_id, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_logs(self, project_id):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM logs WHERE project_id = ?", (project_id,))
            conn.commit()

    # --- Settings Methods ---
    def set_setting(self, key, value):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def get_setting(self, key, default=""):
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def get_all_settings(self):
        with self._get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

db = Database()
