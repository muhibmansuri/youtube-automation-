import os
import wave
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
import numpy as np
from config import FFMPEG_PATH


class CinemaFoleyEngine:
    """
    Hollywood Micro-Foley & SFX Synthesizer + Timeline Mixer.
    Generates realistic physical sound effects (Police Siren, Door Creak, Thunder,
    Cinema Bass Impact, Clock Ticks, Telephone Ring, Heartbeat, Footsteps, Electric Buzz)
    and places them at exact scene timestamps.
    """

    SR = 48000

    def __init__(self, ffmpeg_path: Optional[str] = None, log_callback: Optional[Callable[[str, str], None]] = None):
        self.ffmpeg_path = ffmpeg_path or FFMPEG_PATH
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    @staticmethod
    def _save_stereo_wav(path: str, left: np.ndarray, right: np.ndarray):
        peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))), 1e-6)
        if peak > 0.95:
            left = left * (0.92 / peak)
            right = right * (0.92 / peak)
        stereo = np.stack([np.clip(left, -0.98, 0.98), np.clip(right, -0.98, 0.98)], axis=1)
        pcm = (stereo * 32767.0).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(CinemaFoleyEngine.SR)
            wf.writeframes(pcm.tobytes())

    def synth_sfx(self, sfx_type: str, out_wav: str) -> bool:
        sr = self.SR
        rng = np.random.default_rng(101)

        if sfx_type == "police_siren":
            dur = 5.5
            t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
            # Distant Doppler wail (620Hz <-> 960Hz)
            freq = 790.0 + 170.0 * np.sin(2 * np.pi * 0.55 * t)
            phase = 2 * np.pi * np.cumsum(freq) / sr
            sig = (0.55 * np.sin(phase) + 0.25 * np.sin(2 * phase) + 0.10 * np.sin(3 * phase))
            # Distant city echo & fade in/out
            env = np.minimum(1.0, t / 1.2) * np.minimum(1.0, (dur - t) / 1.5) * 0.35
            sig *= env
            left = sig
            right = np.roll(sig, int(0.035 * sr)) * 0.85

        elif sfx_type == "door_creak":
            dur = 2.6
            t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
            # Metallic stick-slip creak pulses + resonant wood/metal body
            f_creak = 185.0 + 65.0 * np.sin(2 * np.pi * 2.2 * t)
            sig = np.zeros_like(t)
            for mult, amp in [(1.0, 0.5), (1.73, 0.35), (2.41, 0.25), (3.85, 0.15)]:
                sig += amp * np.sin(2 * np.pi * f_creak * mult * t)
            # Stick-slip amplitude modulation
            mod = 0.5 + 0.5 * np.sin(2 * np.pi * (18.0 - 5.0 * t) * t)
            env = np.exp(-t * 0.7) * np.minimum(1.0, t / 0.15)
            sig = sig * mod * env * 0.55
            # Add heavy door thud at 2.1s
            thud_idx = int(2.0 * sr)
            thud_len = int(0.35 * sr)
            lt = np.arange(thud_len, dtype=np.float32) / sr
            thud = np.sin(2 * np.pi * (95.0 - 50.0 * lt) * lt) * np.exp(-lt * 12.0) * 0.7
            sig[thud_idx:thud_idx + thud_len] += thud
            left = sig
            right = np.roll(sig, int(0.015 * sr)) * 0.92

        elif sfx_type == "thunder":
            dur = 4.5
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
            noise = rng.normal(0, 1.0, n).astype(np.float32)
            # Heavy lowpass rolling thunder
            roll = np.convolve(noise, np.ones(180, dtype=np.float32) / 180.0, mode="same")
            crack = np.convolve(noise, np.ones(18, dtype=np.float32) / 18.0, mode="same") * np.exp(-t * 6.0) * 0.8
            env = (1.0 - np.exp(-t * 18.0)) * np.exp(-t * 0.75)
            sig = (roll * 2.8 + crack) * env * 0.75
            left = sig
            right = np.roll(sig, int(0.04 * sr))

        elif sfx_type == "bass_impact":
            dur = 2.8
            t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
            # Hollywood trailer sub drop (110Hz -> 32Hz) + transient punch
            f_drop = 32.0 + 78.0 * np.exp(-t * 4.5)
            phase = 2 * np.pi * np.cumsum(f_drop) / sr
            sub = np.sin(phase) * np.exp(-t * 1.4) * 0.85
            punch = rng.normal(0, 0.35, len(t)).astype(np.float32) * np.exp(-t * 22.0)
            sig = sub + punch
            left = sig
            right = sig

        elif sfx_type == "clock_tick":
            dur = 3.2
            n = int(sr * dur)
            sig = np.zeros(n, dtype=np.float32)
            for tick_t in [0.3, 1.3, 2.3]:
                idx = int(tick_t * sr)
                lt = np.arange(int(0.12 * sr), dtype=np.float32) / sr
                click = (np.sin(2 * np.pi * 1450.0 * lt) * 0.5 + np.sin(2 * np.pi * 3200.0 * lt) * 0.3) * np.exp(-lt * 55.0)
                sig[idx:idx + len(click)] += click * 0.65
            left = sig
            right = np.roll(sig, int(0.008 * sr)) * 0.9

        elif sfx_type == "phone_ring":
            dur = 3.5
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
            ring = (np.sin(2 * np.pi * 440.0 * t) + np.sin(2 * np.pi * 480.0 * t)) * 0.35
            # Classic ring burst: 0.2-1.2s and 1.8-2.8s
            gate = (((t >= 0.2) & (t <= 1.2)) | ((t >= 1.8) & (t <= 2.8))).astype(np.float32)
            trem = 0.5 + 0.5 * np.sin(2 * np.pi * 20.0 * t)
            sig = ring * gate * trem * 0.6
            left = sig
            right = np.roll(sig, int(0.012 * sr))

        elif sfx_type == "heartbeat":
            dur = 3.6
            n = int(sr * dur)
            sig = np.zeros(n, dtype=np.float32)
            for bt in [0.2, 1.2, 2.2]:
                for off, amp in [(0.0, 0.75), (0.26, 0.45)]:
                    idx = int((bt + off) * sr)
                    lt = np.arange(int(0.22 * sr), dtype=np.float32) / sr
                    thump = np.sin(2 * np.pi * (70.0 - 30.0 * lt / 0.22) * lt) * np.exp(-lt * 15.0) * amp
                    sig[idx:idx + len(thump)] += thump
            left = sig
            right = sig

        elif sfx_type == "footsteps":
            dur = 3.2
            n = int(sr * dur)
            sig = np.zeros(n, dtype=np.float32)
            for st in [0.25, 0.90, 1.55, 2.20]:
                idx = int(st * sr)
                lt = np.arange(int(0.16 * sr), dtype=np.float32) / sr
                step_noise = rng.normal(0, 0.5, len(lt)).astype(np.float32)
                step_low = np.sin(2 * np.pi * 110.0 * lt) * 0.4
                step = (np.convolve(step_noise, np.ones(16, dtype=np.float32) / 16.0, mode="same") + step_low) * np.exp(-lt * 24.0)
                sig[idx:idx + len(step)] += step * 0.65
            left = sig
            right = np.roll(sig, int(0.01 * sr)) * 0.95

        elif sfx_type == "electric_buzz":
            dur = 3.0
            t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
            sig = (0.4 * np.sin(2 * np.pi * 120.0 * t) + 0.2 * np.sin(2 * np.pi * 240.0 * t)) * 0.3
            env = np.minimum(1.0, t / 0.3) * np.minimum(1.0, (dur - t) / 0.5)
            sig *= env
            left = sig
            right = sig
        else:
            return False

        self._save_stereo_wav(out_wav, left, right)
        return True

    @staticmethod
    def detect_scene_sfx(prompt: str) -> List[str]:
        low = (prompt or "").lower()
        cues = []
        if "police siren" in low or "siren" in low:
            cues.append("police_siren")
        if "door creak" in low or "broken apartment door" in low or "door" in low and "creak" in low:
            cues.append("door_creak")
        if "thunder" in low or "lightning" in low:
            cues.append("thunder")
        if "impact" in low or "bass hit" in low:
            cues.append("bass_impact")
        if "clock tick" in low:
            cues.append("clock_tick")
        if "ringtone" in low or "telephone" in low and "ring" in low:
            cues.append("phone_ring")
        if "heartbeat" in low:
            cues.append("heartbeat")
        if "footsteps" in low:
            cues.append("footsteps")
        if "electrical buzzing" in low or "buzzing" in low:
            cues.append("electric_buzz")
        return cues

    def build_foley_track(self,
                          scene_timings: List[Tuple[float, str]],  # (start_time_sec, prompt)
                          total_duration: float,
                          output_foley_wav: str) -> bool:
        """
        Places detected micro-Foley SFX at exact scene timestamps across the whole movie.
        """
        events: List[Tuple[float, str]] = []
        for start_t, prompt in scene_timings:
            for cue in self.detect_scene_sfx(prompt):
                # J-Cut Audio Bridge: start incoming SFX 0.55s before the visual cut (except opening 0.0s)
                sfx_t = max(0.0, start_t - 0.55) if start_t > 1.0 else 0.15
                events.append((sfx_t, cue))

        if not events:
            return False

        self.log("info", f"🔊 Synthesizing & placing {len(events)} Micro-Foley SFX cues (Police Siren, Door Creak, Thunder, Impacts)...")
        with tempfile.TemporaryDirectory() as tmpdir:
            sfx_cache = {}
            inputs = ["-f", "lavfi", "-t", f"{total_duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            filter_parts = ["[0:a]volume=1.0[base]"]
            mix_labels = ["[base]"]

            for idx, (t_sec, cue) in enumerate(events, 1):
                if cue not in sfx_cache:
                    wav_p = os.path.join(tmpdir, f"{cue}.wav")
                    if self.synth_sfx(cue, wav_p):
                        sfx_cache[cue] = wav_p
                wav_p = sfx_cache.get(cue)
                if not wav_p:
                    continue
                inputs.extend(["-i", wav_p])
                delay_ms = int(round(t_sec * 1000))
                filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume=0.85[f{idx}]")
                mix_labels.append(f"[f{idx}]")

            filter_parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:normalize=0[out]")
            cmd = [self.ffmpeg_path, "-y"] + inputs + [
                "-filter_complex", ";".join(filter_parts),
                "-map", "[out]",
                "-c:a", "pcm_s16le",
                output_foley_wav
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_foley_wav):
                self.log("success", f"✅ Micro-Foley SFX Track ready ({len(events)} cues placed)!")
                return True
            self.log("warning", f"Foley mix warning: {res.stderr[-250:]}")
            return False
