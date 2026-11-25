import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable
from config import BASE_DIR, FFMPEG_PATH

REALESRGAN_DIR = BASE_DIR / "tools" / "realesrgan"
REALESRGAN_EXE = REALESRGAN_DIR / "realesrgan-ncnn-vulkan.exe"

class VideoAIUpscaler:
    """
    CodeAura Cinema Studio - Hardware Accelerated AI Video Upscaler.
    Uses Real-ESRGAN Vulkan NCNN to upscale video frames to native 4K (3840x2160)
    using the NVIDIA GPU directly.
    """

    def __init__(self, 
                 realesrgan_exe: Optional[str] = None,
                 ffmpeg_path: Optional[str] = None,
                 log_callback: Optional[Callable[[str, str], None]] = None):
        self.realesrgan_exe = str(realesrgan_exe or REALESRGAN_EXE)
        self.ffmpeg_path = ffmpeg_path or FFMPEG_PATH
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    def is_available(self) -> bool:
        """Check if Real-ESRGAN binary and models are available."""
        return os.path.exists(self.realesrgan_exe)

    def upscale_video_to_4k(self,
                            input_video_path: str,
                            output_video_path: str,
                            scale: int = 4,
                            model_name: str = "realesrgan-x4plus",
                            gpu_id: int = 0,
                            progress_callback: Optional[Callable[[float, str], None]] = None) -> dict:
        """
        Upscales an input video (clip or full movie) to 4K using Real-ESRGAN Neural Network.
        """
        if not os.path.exists(input_video_path):
            return {"success": False, "error": f"Input video not found: {input_video_path}"}

        if not self.is_available():
            return {"success": False, "error": f"Real-ESRGAN executable not found at: {self.realesrgan_exe}"}

        start_time = time.time()
        Path(output_video_path).parent.mkdir(parents=True, exist_ok=True)

        temp_workspace = tempfile.mkdtemp(prefix="realesrgan_upscale_")
        raw_frames_dir = os.path.join(temp_workspace, "raw_frames")
        upscaled_frames_dir = os.path.join(temp_workspace, "upscaled_frames")
        extracted_audio_path = os.path.join(temp_workspace, "audio.aac")

        os.makedirs(raw_frames_dir, exist_ok=True)
        os.makedirs(upscaled_frames_dir, exist_ok=True)

        try:
            # Step 1: Detect frame rate (FPS) of input video
            fps = self._get_video_fps(input_video_path)
            self.log("info", f"🚀 Starting AI 4K Upscaling ({model_name}, {scale}x) on: {os.path.basename(input_video_path)} at {fps} FPS")
            if progress_callback:
                progress_callback(5.0, "Extracting video frames for AI enhancement...")

            # Step 2: Extract frames to PNG
            extract_cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_video_path,
                "-qscale:v", "1",
                "-qmin", "1", "-qmax", "1",
                os.path.join(raw_frames_dir, "frame_%06d.png")
            ]
            subprocess.run(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            raw_frames = sorted(os.listdir(raw_frames_dir))
            total_frames = len(raw_frames)
            self.log("info", f"Extracted {total_frames} frames. Beginning GPU Neural Super-Resolution...")

            # Step 3: Extract audio track if present
            audio_cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_video_path,
                "-vn", "-c:a", "copy",
                extracted_audio_path
            ]
            has_audio = False
            a_res = subprocess.run(audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if a_res.returncode == 0 and os.path.exists(extracted_audio_path) and os.path.getsize(extracted_audio_path) > 500:
                has_audio = True

            # Step 4: Run Real-ESRGAN NCNN Vulkan
            models_dir = os.path.join(os.path.dirname(self.realesrgan_exe), "models")
            esrgan_cmd = [
                self.realesrgan_exe,
                "-i", raw_frames_dir,
                "-o", upscaled_frames_dir,
                "-n", model_name,
                "-s", str(scale),
                "-m", models_dir,
                "-g", str(gpu_id),
                "-f", "png"
            ]

            if progress_callback:
                progress_callback(25.0, f"AI Upscaling {total_frames} frames on NVIDIA GPU...")

            esrgan_proc = subprocess.run(esrgan_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if esrgan_proc.returncode != 0:
                self.log("error", f"Real-ESRGAN failed: {esrgan_proc.stderr[-400:]}")
                return {"success": False, "error": esrgan_proc.stderr[-400:]}

            if progress_callback:
                progress_callback(85.0, "Encoding enhanced 4K master film...")

            # Step 5: Re-encode upscaled frames to 4K MP4 with high-bitrate libx264
            reencode_cmd = [
                self.ffmpeg_path, "-y",
                "-r", str(fps),
                "-i", os.path.join(upscaled_frames_dir, "frame_%06d.png")
            ]

            if has_audio:
                reencode_cmd.extend(["-i", extracted_audio_path])

            reencode_cmd.extend([
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "16",
                "-pix_fmt", "yuv420p",
                "-b:v", "40M",
                "-maxrate", "50M",
                "-bufsize", "70M"
            ])

            if has_audio:
                reencode_cmd.extend(["-c:a", "aac", "-b:a", "256k", "-shortest"])

            reencode_cmd.append(output_video_path)

            encode_res = subprocess.run(reencode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if encode_res.returncode != 0 or not os.path.exists(output_video_path):
                self.log("error", f"4K Re-encoding failed: {encode_res.stderr[-400:]}")
                return {"success": False, "error": encode_res.stderr[-400:]}

            elapsed = round(time.time() - start_time, 1)
            file_size_mb = round(os.path.getsize(output_video_path) / (1024 * 1024), 2)
            self.log("success", f"✨ AI 4K Master Video Created: {file_size_mb} MB in {elapsed}s!")

            if progress_callback:
                progress_callback(100.0, "AI 4K Upscaling complete!")

            return {
                "success": True,
                "output_path": output_video_path,
                "file_size_mb": file_size_mb,
                "elapsed_seconds": elapsed,
                "total_frames": total_frames
            }

        except Exception as e:
            self.log("error", f"Upscaling exception: {str(e)}")
            return {"success": False, "error": str(e)}

        finally:
            # Clean up temporary frames
            if os.path.exists(temp_workspace):
                try:
                    shutil.rmtree(temp_workspace)
                except Exception:
                    pass

    def _get_video_fps(self, video_path: str) -> float:
        """Extracts the frame rate (FPS) of a video using FFmpeg/ffprobe or defaults to 24.0."""
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            if fps and fps > 1.0:
                return round(fps, 3)
        except Exception:
            pass
        return 24.0

upscaler = VideoAIUpscaler()
