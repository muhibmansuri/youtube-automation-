import os
import subprocess
from pathlib import Path
import cv2
import numpy as np
from config import FFMPEG_PATH

class ContinuityProcessor:
    """Handles exact frame extraction, continuity validation, and visual consistency checks."""

    @staticmethod
    def extract_last_frame(video_path: str, output_image_path: str) -> dict:
        """Extracts the exact final frame of an 8-second video clip using OpenCV with FFmpeg fallback."""
        video_path = str(video_path)
        output_image_path = str(output_image_path)
        
        if not os.path.exists(video_path):
            return {"success": False, "error": f"Video file not found: {video_path}"}

        Path(output_image_path).parent.mkdir(parents=True, exist_ok=True)

        # Attempt OpenCV extraction first
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise RuntimeError(f"OpenCV cannot open video: {video_path}")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

            last_valid_frame = None
            if total_frames > 0:
                # Seek near the end
                target_frame = max(0, total_frames - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if ret and frame is not None:
                    last_valid_frame = frame

            # If seek failed or returned empty, read sequentially until end
            if last_valid_frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                while True:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break
                    last_valid_frame = frame

            cap.release()

            if last_valid_frame is not None:
                # Save high quality JPEG
                cv2.imwrite(output_image_path, last_valid_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                val = ContinuityProcessor.validate_frame(output_image_path)
                return {
                    "success": True,
                    "frame_path": output_image_path,
                    "total_frames": total_frames,
                    "fps": fps,
                    "validation": val,
                    "method": "opencv"
                }
        except Exception as cv_err:
            pass

        # Fallback to FFmpeg
        try:
            # -sseof -0.1 seeks to the final 100ms
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-sseof", "-0.1",
                "-i", video_path,
                "-update", "1",
                "-q:v", "2",
                output_image_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            if res.returncode == 0 and os.path.exists(output_image_path) and os.path.getsize(output_image_path) > 1000:
                val = ContinuityProcessor.validate_frame(output_image_path)
                return {
                    "success": True,
                    "frame_path": output_image_path,
                    "validation": val,
                    "method": "ffmpeg"
                }
            return {"success": False, "error": f"FFmpeg fallback failed: {res.stderr}"}
        except Exception as ff_err:
            return {"success": False, "error": f"All extraction methods failed: {str(ff_err)}"}

    @staticmethod
    def extract_first_frame(video_path: str, output_image_path: str) -> dict:
        """Extracts the first frame of a video clip for thumbnails and verification."""
        video_path = str(video_path)
        output_image_path = str(output_image_path)
        if not os.path.exists(video_path):
            return {"success": False, "error": "Video not found"}

        Path(output_image_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                cv2.imwrite(output_image_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                return {"success": True, "frame_path": output_image_path}
        except Exception:
            pass

        # FFmpeg fallback
        try:
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-ss", "00:00:00.000",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                output_image_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if res.returncode == 0 and os.path.exists(output_image_path):
                return {"success": True, "frame_path": output_image_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {"success": False, "error": "Could not extract first frame"}

    @staticmethod
    def validate_frame(image_path: str) -> dict:
        """Validates that the extracted image is not blank, black, or corrupted."""
        if not os.path.exists(image_path):
            return {"is_valid": False, "reason": "File does not exist"}

        size = os.path.getsize(image_path)
        if size < 500:
            return {"is_valid": False, "reason": "File size too small (<500 bytes)"}

        try:
            img = cv2.imread(image_path)
            if img is None:
                return {"is_valid": False, "reason": "Failed to decode image with OpenCV"}

            h, w, c = img.shape
            mean_val = float(np.mean(img))
            std_val = float(np.std(img))

            # If standard deviation is extremely low, frame is pure black or uniform solid color
            is_blank = std_val < 3.0 or mean_val < 2.0

            return {
                "is_valid": not is_blank,
                "width": w,
                "height": h,
                "mean_brightness": round(mean_val, 2),
                "std_contrast": round(std_val, 2),
                "is_blank": is_blank
            }
        except Exception as e:
            return {"is_valid": False, "reason": str(e)}

    @staticmethod
    def calculate_visual_similarity(image1_path: str, image2_path: str) -> float:
        """Calculates color histogram correlation (0.0 to 1.0) between two frames."""
        try:
            img1 = cv2.imread(str(image1_path))
            img2 = cv2.imread(str(image2_path))
            if img1 is None or img2 is None:
                return 0.0

            # Resize to identical small dimensions
            img1 = cv2.resize(img1, (256, 256))
            img2 = cv2.resize(img2, (256, 256))

            # Calculate HSV histograms
            hsv1 = cv2.cvtColor(img1, cv2.COLOR_BGR2HSV)
            hsv2 = cv2.cvtColor(img2, cv2.COLOR_BGR2HSV)

            hist1 = cv2.calcHist([hsv1], [0, 1], None, [50, 60], [0, 180, 0, 256])
            hist2 = cv2.calcHist([hsv2], [0, 1], None, [50, 60], [0, 180, 0, 256])

            cv2.normalize(hist1, hist1, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
            cv2.normalize(hist2, hist2, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

            correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
            return max(0.0, min(1.0, float(correlation)))
        except Exception:
            return 0.0
