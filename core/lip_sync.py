import os
import subprocess
from pathlib import Path
from typing import Optional, Callable
from config import BASE_DIR


WAV2LIP_DIR = BASE_DIR / "tools" / "wav2lip"
WAV2LIP_CKPT = WAV2LIP_DIR / "checkpoints" / "wav2lip_gan.pth"


class LipSyncEngine:
    """
    Local GPU AI Lip-Sync Engine (Wav2Lip / MuseTalk hook).
    When PyTorch + Wav2Lip checkpoint are installed in tools/wav2lip,
    re-animates actor lip movements to match synthesized Hindi/English audio syllable-by-syllable.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            return os.path.exists(WAV2LIP_DIR / "inference.py") and os.path.exists(WAV2LIP_CKPT)
        except ImportError:
            return False

    def sync_clip(self, video_path: str, audio_path: str, output_path: str) -> dict:
        if not self.is_available():
            return {
                "success": False,
                "error": "Wav2Lip/PyTorch not installed in tools/wav2lip. Using tight smart-cut editing instead."
            }
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "python", str(WAV2LIP_DIR / "inference.py"),
                "--checkpoint_path", str(WAV2LIP_CKPT),
                "--face", video_path,
                "--audio", audio_path,
                "--outfile", output_path,
                "--pads", "0", "10", "0", "0",
                "--nosmooth"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_path):
                self.log("success", f"💋 AI Lip-Sync completed: {os.path.basename(output_path)}")
                return {"success": True, "output_path": output_path}
            return {"success": False, "error": res.stderr[-300:]}
        except Exception as e:
            return {"success": False, "error": str(e)}
