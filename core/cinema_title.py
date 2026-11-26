import os
import subprocess
from pathlib import Path
from typing import Optional, Callable
from PIL import Image, ImageDraw, ImageFont
from config import FFMPEG_PATH


class CinemaTitleGenerator:
    """
    Generates Hollywood-grade 2.39:1 Widescreen Opening Title Sequence
    and Closing End Credits MP4 clips with smooth fade-in/fade-out and sub-bass boom.
    """

    def __init__(self, ffmpeg_path: Optional[str] = None, log_callback: Optional[Callable[[str, str], None]] = None):
        self.ffmpeg_path = ffmpeg_path or FFMPEG_PATH
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    @staticmethod
    def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        candidates = [
            r"C:\Windows\Fonts\georgiab.ttf" if bold else r"C:\Windows\Fonts\georgia.ttf",
            r"C:\Windows\Fonts\timesbd.ttf" if bold else r"C:\Windows\Fonts\times.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
        for p in candidates:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _render_card_image(self, top_label: str, main_title: str, sub_label: str, out_png: str, width: int = 1920, height: int = 1080):
        img = Image.new("RGB", (width, height), (4, 6, 12))
        draw = ImageDraw.Draw(img)

        # Subtle dark cinema radial glow in center
        cx, cy = width // 2, height // 2
        for r in range(420, 0, -20):
            alpha = int(16 * (1 - r / 420))
            draw.ellipse((cx - r * 2, cy - r, cx + r * 2, cy + r), fill=(12 + alpha, 16 + alpha, 28 + alpha))

        # 2.39:1 pure black cinema bars
        bar_h = (height - 804) // 2
        draw.rectangle((0, 0, width, bar_h), fill=(0, 0, 0))
        draw.rectangle((0, height - bar_h, width, height), fill=(0, 0, 0))

        f_top = self._load_font(28, bold=False)
        f_main = self._load_font(86, bold=True)
        f_sub = self._load_font(30, bold=False)

        if top_label:
            bbox = draw.textbbox((0, 0), top_label, font=f_top)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, cy - 120), top_label, fill=(180, 155, 100), font=f_top)

        if main_title:
            bbox = draw.textbbox((0, 0), main_title, font=f_main)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, cy - 45), main_title, fill=(242, 238, 228), font=f_main)

        if sub_label:
            bbox = draw.textbbox((0, 0), sub_label, font=f_sub)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, cy + 85), sub_label, fill=(150, 160, 180), font=f_sub)

        img.save(out_png)

    def create_title_clip(self,
                          title: str,
                          output_mp4: str,
                          subtitle: str = "A NEO-NOIR CRIME THRILLER",
                          studio_line: str = "AI CINEMA STUDIO PRESENTS",
                          duration: float = 4.5) -> bool:
        """Creates a 4.5s Opening Title Card MP4 with fade-in/out and sub-bass cinematic boom."""
        try:
            Path(output_mp4).parent.mkdir(parents=True, exist_ok=True)
            png_path = output_mp4 + ".png"
            self._render_card_image(studio_line, title.upper(), subtitle, png_path)

            boom_expr = "0.55*sin(2*PI*(55-22*t/3.5)*t)*exp(-t*1.1)"
            cmd = [
                self.ffmpeg_path, "-y",
                "-loop", "1", "-t", f"{duration:.2f}", "-i", png_path,
                "-f", "lavfi", "-t", f"{duration:.2f}", "-i", f"aevalsrc='{boom_expr}':s=48000",
                "-vf", f"fade=t=in:st=0:d=1.0,fade=t=out:st={duration-0.9:.2f}:d=0.9,format=yuv420p",
                "-af", f"aformat=sample_rates=48000:channel_layouts=stereo,afade=t=out:st={duration-0.8:.2f}:d=0.8",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", "24",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                "-shortest", output_mp4
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if os.path.exists(png_path):
                os.remove(png_path)
            return res.returncode == 0 and os.path.exists(output_mp4)
        except Exception as e:
            self.log("warning", f"Title card generation failed: {e}")
            return False

    def create_credits_clip(self,
                            title: str,
                            output_mp4: str,
                            end_line: str = "TO BE CONTINUED...",
                            credit_line: str = "DIRECTED BY AUTONOMOUS AI CINEMA STUDIO",
                            duration: float = 5.0) -> bool:
        """Creates a 5s Closing Credits / Cliffhanger Outro MP4."""
        try:
            Path(output_mp4).parent.mkdir(parents=True, exist_ok=True)
            png_path = output_mp4 + ".png"
            self._render_card_image(title.upper(), end_line, credit_line, png_path)

            cmd = [
                self.ffmpeg_path, "-y",
                "-loop", "1", "-t", f"{duration:.2f}", "-i", png_path,
                "-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", f"fade=t=in:st=0:d=1.0,fade=t=out:st={duration-1.0:.2f}:d=1.0,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", "24",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                "-shortest", output_mp4
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if os.path.exists(png_path):
                os.remove(png_path)
            return res.returncode == 0 and os.path.exists(output_mp4)
        except Exception as e:
            self.log("warning", f"End credits generation failed: {e}")
            return False
