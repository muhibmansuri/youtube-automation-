import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable
from config import FFMPEG_PATH
from core.voice_synthesizer import VoiceSynthesizer


class CinemaAudioStudio:
    """
    Non-destructive Master Audio Storytelling & Soundscape Engine.
    Builds a continuous, seamless narrative voiceover track, SRT subtitles,
    and procedural dark thriller ambience/sub-bass score without modifying raw video clips.
    """

    def __init__(self, ffmpeg_path: Optional[str] = None, log_callback: Optional[Callable[[str, str], None]] = None):
        self.ffmpeg_path = ffmpeg_path or FFMPEG_PATH
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    def get_media_duration(self, file_path: str, default: float = 8.0) -> float:
        """Reads exact media duration in seconds using ffmpeg."""
        try:
            res = subprocess.run([self.ffmpeg_path, "-i", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
            if m:
                hrs, mins, secs = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return hrs * 3600 + mins * 60 + secs
        except Exception:
            pass
        return default

    def generate_thriller_soundscape(self, output_wav_path: str, duration_sec: float = 64.0) -> bool:
        """
        Generates a loopable, rich Dark Thriller Cinematic Score using numpy synthesis:
        - Minor-key suspense piano / warm cello chords (D minor: D3-F3-A3-Bb3) audible on all speakers
        - Deep 60 BPM cinematic heartbeat pulse
        - Soft midnight rain ambience
        Normalized cleanly to -12 dB so it cuts through clearly with sidechain ducking.
        """
        try:
            import numpy as np
            import wave

            Path(output_wav_path).parent.mkdir(parents=True, exist_ok=True)
            sr = 48000
            n_samples = int(sr * duration_sec)
            t = np.linspace(0, duration_sec, n_samples, endpoint=False, dtype=np.float32)

            # 1. Warm D-minor Cello / Pad Progression (16s cycle: Dm -> Bb -> Gm -> A7sus4)
            # Frequencies: D3=146.83, F3=174.61, A3=220.00, Bb3=233.08, G3=196.00, C4=261.63, E3=164.81
            pad = np.zeros(n_samples, dtype=np.float32)
            chords = [
                (0.0, 16.0, [73.42, 146.83, 174.61, 220.00]),   # Dm
                (16.0, 32.0, [58.27, 116.54, 174.61, 233.08]),  # Bb
                (32.0, 48.0, [49.00, 98.00, 196.00, 233.08]),   # Gm
                (48.0, 64.0, [55.00, 110.00, 164.81, 220.00]),  # A5/A7
            ]
            for c_start, c_end, freqs in chords:
                mask = (t >= c_start) & (t < c_end)
                if not np.any(mask):
                    continue
                lt = t[mask] - c_start
                c_len = c_end - c_start
                # Smooth fade in/out over 2.5s per chord
                env = np.minimum(1.0, lt / 2.5) * np.minimum(1.0, (c_len - lt) / 2.5)
                chord_sig = np.zeros_like(lt)
                for f in freqs:
                    # Rich odd+even harmonics for warm cello/string timbre
                    chord_sig += 0.55 * np.sin(2 * np.pi * f * lt)
                    chord_sig += 0.25 * np.sin(2 * np.pi * (f * 2.0) * lt)
                    chord_sig += 0.10 * np.sin(2 * np.pi * (f * 3.0) * lt)
                pad[mask] += chord_sig * env * 0.22

            # 2. Haunting Suspense Piano / Bell Arpeggio Notes every 2.0 seconds
            melody_notes = [293.66, 349.23, 440.00, 329.63, 293.66, 466.16, 440.00, 349.23]  # D4, F4, A4, E4...
            piano_L = np.zeros(n_samples, dtype=np.float32)
            piano_R = np.zeros(n_samples, dtype=np.float32)
            step = 2.0
            idx_note = 0
            for nt in np.arange(0.5, duration_sec - 2.0, step):
                freq = melody_notes[idx_note % len(melody_notes)]
                idx_note += 1
                s_idx = int(nt * sr)
                dur_note = min(int(3.5 * sr), n_samples - s_idx)
                if dur_note <= 0:
                    continue
                lt = np.arange(dur_note, dtype=np.float32) / sr
                # Percussive piano attack + exponential cathedral decay
                env = (1.0 - np.exp(-lt * 60.0)) * np.exp(-lt * 1.45)
                sig = (0.7 * np.sin(2 * np.pi * freq * lt) +
                       0.25 * np.sin(2 * np.pi * freq * 2.0 * lt) +
                       0.08 * np.sin(2 * np.pi * freq * 3.0 * lt)) * env * 0.28
                # Subtle stereo ping-pong
                pan = 0.65 if (idx_note % 2 == 0) else 0.35
                piano_L[s_idx:s_idx + dur_note] += sig * (1.0 - pan * 0.4)
                piano_R[s_idx:s_idx + dur_note] += sig * (0.6 + pan * 0.4)

            # 3. Cinematic Heartbeat Pulse (every 1.0s: thump-thump)
            heartbeat = np.zeros(n_samples, dtype=np.float32)
            for bt in np.arange(0.0, duration_sec - 0.5, 2.0):
                for offset, amp in [(0.0, 0.35), (0.28, 0.22)]:
                    s_idx = int((bt + offset) * sr)
                    dur_b = min(int(0.22 * sr), n_samples - s_idx)
                    if dur_b <= 0:
                        continue
                    lt = np.arange(dur_b, dtype=np.float32) / sr
                    f_sweep = 75.0 - 35.0 * (lt / 0.22)
                    thump = np.sin(2 * np.pi * f_sweep * lt) * np.exp(-lt * 16.0) * amp
                    heartbeat[s_idx:s_idx + dur_b] += thump

            # 4. Soft Midnight Rain Ambience (gentle filtered white noise)
            rng = np.random.default_rng(42)
            noise = rng.normal(0, 0.03, n_samples).astype(np.float32)
            # Simple 1-pole lowpass smoothing for soft rain sound
            rain = np.convolve(noise, np.ones(12, dtype=np.float32) / 12.0, mode="same")

            mix_L = pad + piano_L + heartbeat + rain
            mix_R = pad + piano_R + heartbeat + np.roll(rain, 150)

            # Peak normalize to -3 dB so it's rich and audible
            peak = max(float(np.max(np.abs(mix_L))), float(np.max(np.abs(mix_R))), 1e-6)
            gain = 0.70 / peak
            mix_L = np.clip(mix_L * gain, -0.98, 0.98)
            mix_R = np.clip(mix_R * gain, -0.98, 0.98)

            # Seamless 1.5s loop fade
            fade_n = int(1.5 * sr)
            fade_in = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
            fade_out = np.linspace(1.0, 0.0, fade_n, dtype=np.float32)
            mix_L[:fade_n] *= fade_in
            mix_R[:fade_n] *= fade_in
            mix_L[-fade_n:] *= fade_out
            mix_R[-fade_n:] *= fade_out

            stereo = np.stack([mix_L, mix_R], axis=1)
            pcm = (stereo * 32767.0).astype(np.int16)

            with wave.open(output_wav_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm.tobytes())

            self.log("success", f"🎼 Generated Cinematic Dark Thriller Piano/Cello/Heartbeat Score: {os.path.basename(output_wav_path)}")
            return True
        except Exception as e:
            self.log("warning", f"Soundscape generation error: {e}")
            return False

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        ms = int(round((seconds - int(seconds)) * 1000))
        total_sec = int(seconds)
        hrs = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    def apply_theater_mastering(self, input_audio_path: str, output_wav_path: str) -> bool:
        """
        Applies Dolby-Cinema-style spatial mastering using Spotify's Pedalboard DSP engine:
        - Cinema Hall Reverb for wide theater room depth
        - Sub-Bass LowShelf (+4.5 dB @ 85Hz) for theater woofer punch
        - Studio Compressor & Limiter (-1.0 dB ceiling)
        """
        try:
            import numpy as np
            from pedalboard import Pedalboard, Reverb, Compressor, HighpassFilter, LowShelfFilter, Limiter
            from pedalboard.io import AudioFile

            board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=32.0),
                LowShelfFilter(cutoff_frequency_hz=85.0, gain_db=4.5, q=0.7),
                Compressor(threshold_db=-16.0, ratio=2.8, attack_ms=12.0, release_ms=160.0),
                Reverb(room_size=0.45, damping=0.65, wet_level=0.14, dry_level=0.90, width=0.85),
                Limiter(threshold_db=-1.0, release_ms=80.0),
            ])

            with AudioFile(input_audio_path) as f:
                audio = f.read(f.frames)
                sr = f.samplerate

            effected = board(audio, sr)
            with AudioFile(output_wav_path, "w", sr, effected.shape[0]) as out:
                out.write(effected)

            self.log("success", "🎭 Applied Spotify Pedalboard Dolby-Theater Hall Mastering!")
            return os.path.exists(output_wav_path)
        except Exception as e:
            self.log("warning", f"Pedalboard theater mastering skipped: {e}")
            return False

    def build_storytelling_track(self,
                                 scenes: List[Dict],
                                 voices_dir: Path,
                                 output_voice_wav: str,
                                 output_srt_path: str,
                                 force_regen: bool = False,
                                 progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict:
        """
        Synthesizes neural Hindi/English narrator & character dialogue for each scene,
        aligns them onto a single continuous timeline matching exact clip durations,
        and outputs both a master voice WAV and a synchronized SRT subtitle file.
        """
        voices_dir.mkdir(parents=True, exist_ok=True)
        Path(output_voice_wav).parent.mkdir(parents=True, exist_ok=True)

        timeline_entries: List[Tuple[float, float, str, str]] = []  # (start_sec, end_sec, voice_path, text)
        current_time = 0.0
        total = len(scenes)

        for idx, s in enumerate(scenes):
            s_num = s["scene_number"]
            clip_path = s.get("clip_path", "")
            clip_dur = self.get_media_duration(clip_path, default=8.0) if (clip_path and os.path.exists(clip_path)) else 8.0

            dlg = VoiceSynthesizer.extract_dialogue(s.get("prompt", ""))
            if dlg and dlg.get("text"):
                voice_file = str(voices_dir / f"voice_{s_num:03d}.mp3")
                if force_regen or not os.path.exists(voice_file) or os.path.getsize(voice_file) < 500:
                    if progress_callback:
                        progress_callback(10.0 + (idx / max(1, total)) * 20.0, f"Synthesizing Expressive Human Voice for Scene #{s_num:03d}...")
                    VoiceSynthesizer.generate_speech(dlg["text"], character=dlg["character"], output_path=voice_file)

                if os.path.exists(voice_file) and os.path.getsize(voice_file) > 500:
                    v_dur = self.get_media_duration(voice_file, default=4.0)
                    # Start 0.35s after scene cut for natural breathing room
                    start_t = current_time + 0.35
                    # Cap subtitle display within scene boundary
                    end_t = min(current_time + clip_dur - 0.2, start_t + v_dur)
                    timeline_entries.append((start_t, end_t, voice_file, dlg["text"]))

            current_time += clip_dur

        total_duration = current_time

        # Write synchronized SRT subtitles
        with open(output_srt_path, "w", encoding="utf-8") as srt:
            for i, (st, et, _, txt) in enumerate(timeline_entries, 1):
                srt.write(f"{i}\n{self._format_srt_time(st)} --> {self._format_srt_time(et)}\n{txt}\n\n")

        if not timeline_entries:
            self.log("info", "No dialogue/narration lines found in scenes; skipping voiceover track.")
            return {"success": True, "has_voice": False, "srt_path": output_srt_path, "total_duration": total_duration}

        self.log("info", f"🎙️ Building continuous Master Storytelling Voice Track ({len(timeline_entries)} lines across {total_duration:.1f}s)...")

        # Assemble master voice WAV in batches to stay well within Windows CLI length limits
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_files = []
            batch_size = 15
            for b_idx in range(0, len(timeline_entries), batch_size):
                batch = timeline_entries[b_idx:b_idx + batch_size]
                batch_out = os.path.join(tmpdir, f"batch_{b_idx}.wav")
                inputs = ["-f", "lavfi", "-t", f"{total_duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                filter_parts = ["[0:a]volume=1.0[base]"]
                mix_labels = ["[base]"]

                for i, (st, _, v_path, _) in enumerate(batch, 1):
                    inputs.extend(["-i", v_path])
                    delay_ms = int(round(st * 1000))
                    # Normalize each voice clip to 48kHz stereo and delay to exact timestamp
                    filter_parts.append(
                        f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                        f"adelay={delay_ms}|{delay_ms}[v{i}]"
                    )
                    mix_labels.append(f"[v{i}]")

                filter_parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:normalize=0[out]")
                cmd = [self.ffmpeg_path, "-y"] + inputs + [
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "[out]",
                    "-c:a", "pcm_s16le",
                    batch_out
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    self.log("error", f"Voice batch mix failed: {res.stderr[-300:]}")
                    return {"success": False, "error": res.stderr[-300:]}
                batch_files.append(batch_out)

            if len(batch_files) == 1:
                os.replace(batch_files[0], output_voice_wav)
            else:
                inputs = []
                labels = []
                for i, bf in enumerate(batch_files):
                    inputs.extend(["-i", bf])
                    labels.append(f"[{i}:a]")
                cmd = [self.ffmpeg_path, "-y"] + inputs + [
                    "-filter_complex", f"{''.join(labels)}amix=inputs={len(batch_files)}:duration=first:normalize=0[out]",
                    "-map", "[out]",
                    "-c:a", "pcm_s16le",
                    output_voice_wav
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    return {"success": False, "error": res.stderr[-300:]}

        self.log("success", f"✅ Master Storytelling Voice Track ready ({len(timeline_entries)} lines, SRT generated).")
        return {
            "success": True,
            "has_voice": True,
            "voice_wav": output_voice_wav,
            "srt_path": output_srt_path,
            "line_count": len(timeline_entries),
            "total_duration": total_duration
        }
