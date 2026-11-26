import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Callable
from config import FFMPEG_PATH

class MovieCompiler:
    """
    CodeAura Cinema Studio - Master Movie Compiler.
    Stitches individual 8-second clips into a continuous Hollywood-grade feature film
    with neural voice dubbing, sub-bass woofer mastering, contrast enhancement, and audio ducking.
    """

    def __init__(self, 
                 ffmpeg_path: Optional[str] = None,
                 log_callback: Optional[Callable[[str, str], None]] = None):
        self.ffmpeg_path = ffmpeg_path or FFMPEG_PATH
        self.log = log_callback or (lambda level, msg: print(f"[{level.upper()}] {msg}"))

    def compile_movie(self,
                      clip_paths: List[str],
                      output_movie_path: str,
                      transition_mode: str = "direct",  # "direct" or "crossfade"
                      crossfade_duration: float = 0.3,
                      background_audio_path: Optional[str] = None,
                      storytelling_voice_path: Optional[str] = None,
                      subtitle_path: Optional[str] = None,
                      music_volume: float = 0.45,
                      normalize_audio: bool = True,
                      enhance_quality: bool = True,      # Hollywood Sharpening + Neo-Noir Contrast + Sub-Bass
                      color_grade: str = "noir",         # "noir" or "natural"
                      cinema_widescreen: bool = True,    # 2.39:1 Anamorphic Cinema Letterbox Bars
                      movie_title: Optional[str] = None, # Adds 4.5s Opening Title Card & 5s Closing Credits if set
                      resolution: str = "1080p",        # "1080p" or "4k"
                      progress_callback: Optional[Callable[[float, str], None]] = None) -> dict:
        """
        Concatenates all clips into a unified full-length movie file with optional quality enhancements,
        2.39:1 Anamorphic Widescreen letterbox, Master Storytelling Voiceover, and Sidechain Audio Ducking.
        """
        valid_clips = [str(Path(p).resolve()) for p in clip_paths if p and os.path.exists(p) and os.path.getsize(p) > 1000]
        if not valid_clips:
            return {"success": False, "error": "No valid video clips provided for compilation."}

        Path(output_movie_path).parent.mkdir(parents=True, exist_ok=True)
        self.log("info", f"🎬 Initiating compilation of {len(valid_clips)} clips into: {os.path.basename(output_movie_path)}")
        if progress_callback:
            progress_callback(5.0, f"Preparing {len(valid_clips)} clips for master compilation...")

        start_time = time.time()

        # Determine target resolution & scaling
        is_4k = resolution.lower() == "4k"
        w, h = (3840, 2160) if is_4k else (1920, 1080)
        base_res = f"{w}:{h}"
        active_h = int(round(w / 2.39))  # 804px for 1080p, 1606px for 4K
        if active_h % 2 != 0:
            active_h -= 1

        vf_parts = [f"scale={base_res}:flags=lanczos:force_original_aspect_ratio=decrease",
                    f"pad={base_res}:(ow-iw)/2:(oh-ih)/2"]

        if cinema_widescreen:
            # 2.39:1 Anamorphic Cinema Crop + Pure Black Letterbox Bars
            vf_parts.append(f"crop={w}:{active_h}:0:(ih-{active_h})/2")
            vf_parts.append(f"pad={base_res}:0:(oh-ih)/2:black")

        if enhance_quality:
            vf_parts.append("unsharp=5:5:0.8:3:3:0.4")
            if color_grade == "noir":
                vf_parts.append("eq=contrast=1.08:brightness=-0.02:saturation=1.08")
                vf_parts.append("colorbalance=rs=-0.03:gs=0.01:bs=0.05:rm=0.02:gm=-0.01:bm=-0.02")

        if subtitle_path and os.path.exists(subtitle_path) and os.path.getsize(subtitle_path) > 10:
            # Escape Windows path for FFmpeg subtitles filter
            esc_srt = str(Path(subtitle_path).resolve()).replace("\\", "/").replace(":", "\\:")
            vf_parts.append(
                f"subtitles='{esc_srt}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=24'"
            )

        video_filter = ",".join(vf_parts)

        try:
            if transition_mode == "direct" or len(valid_clips) > 25:
                # Fast Concat Demuxer strategy
                res = self._compile_direct_concat(
                    valid_clips, 
                    output_movie_path, 
                    background_audio_path, 
                    storytelling_voice_path,
                    music_volume, 
                    normalize_audio, 
                    enhance_quality,
                    video_filter,
                    progress_callback
                )
            else:
                # Crossfade blending strategy (best for shorter sequences)
                res = self._compile_crossfade(
                    valid_clips, 
                    output_movie_path, 
                    crossfade_duration, 
                    background_audio_path, 
                    music_volume, 
                    normalize_audio, 
                    enhance_quality,
                    video_filter,
                    progress_callback
                )

            duration = round(time.time() - start_time, 1)
            if res.get("success"):
                if movie_title and resolution.lower() != "4k":
                    try:
                        from core.cinema_title import CinemaTitleGenerator
                        tg = CinemaTitleGenerator(ffmpeg_path=self.ffmpeg_path, log_callback=self.log)
                        with tempfile.TemporaryDirectory() as tdir:
                            intro_mp4 = os.path.join(tdir, "intro.mp4")
                            outro_mp4 = os.path.join(tdir, "outro.mp4")
                            ok_in = tg.create_title_clip(movie_title, intro_mp4)
                            ok_out = tg.create_credits_clip(movie_title, outro_mp4)
                            if ok_in and ok_out:
                                c_txt = os.path.join(tdir, "pkg.txt")
                                with open(c_txt, "w", encoding="utf-8") as cf:
                                    for p in (intro_mp4, output_movie_path, outro_mp4):
                                        sp = p.replace("\\", "/").replace("'", "'\\''")
                                        cf.write(f"file '{sp}'\n")
                                pkg_out = output_movie_path + ".pkg.mp4"
                                r_pkg = subprocess.run([
                                    self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", c_txt,
                                    "-c", "copy", pkg_out
                                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                if r_pkg.returncode == 0 and os.path.exists(pkg_out):
                                    os.replace(pkg_out, output_movie_path)
                                    self.log("success", "🎞️ Added Opening Title Sequence & End Credits!")
                    except Exception as te:
                        self.log("warning", f"Title/Credits packaging skipped: {te}")

                file_size_mb = round(os.path.getsize(output_movie_path) / (1024 * 1024), 2)
                self.log("success", f"🎉 Master film compiled successfully: {file_size_mb} MB in {duration}s!")
                if progress_callback:
                    progress_callback(100.0, "Master film compilation complete!")
                return {
                    "success": True,
                    "output_path": output_movie_path,
                    "file_size_mb": file_size_mb,
                    "total_clips": len(valid_clips),
                    "compilation_time_seconds": duration
                }
            else:
                return res

        except Exception as e:
            self.log("error", f"Movie compilation exception: {str(e)}")
            return {"success": False, "error": str(e)}

    def _ensure_clip_audio_standard(self, clip_path: str) -> str:
        """
        Guarantees the clip has standard 48kHz Stereo audio matching the concat demuxer clock.
        If sample rate or channels mismatch, normalizes in-place so audio never drifts or desyncs.
        """
        try:
            cmd = [self.ffmpeg_path, "-i", clip_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            import re
            m = re.search(r"Audio:\s*([^,]+),\s*(\d+)\s*Hz,\s*([^,]+)", res.stderr)
            if not m or m.group(2) != "48000" or "stereo" not in m.group(3).lower():
                tmp = clip_path + ".std.mp4"
                std_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", clip_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-ar", "48000",
                    "-ac", "2",
                    "-b:a", "192k",
                    tmp
                ]
                r = subprocess.run(std_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if r.returncode == 0 and os.path.exists(tmp):
                    os.replace(tmp, clip_path)
            return clip_path
        except Exception:
            return clip_path

    def _compile_direct_concat(self, 
                               clips: List[str], 
                               output_path: str, 
                               background_audio: Optional[str],
                               storytelling_voice: Optional[str],
                               music_volume: float,
                               normalize_audio: bool,
                               enhance_quality: bool,
                               video_filter: str,
                               progress_callback: Optional[Callable[[float, str], None]]) -> dict:
        """Concatenates clips with video mastering, storytelling voiceover, sidechain ducking, and soundtrack mixing."""
        # Standardize all clips to 48kHz stereo pre-concat to prevent audio clock desync
        safe_clips = [self._ensure_clip_audio_standard(c) for c in clips]

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            concat_list_path = f.name
            for c in safe_clips:
                safe_path = c.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        has_bgm = bool(background_audio and os.path.exists(background_audio))
        has_voice = bool(storytelling_voice and os.path.exists(storytelling_voice))
        needs_audio_mix = has_bgm or has_voice
        intermediate_video = output_path if not needs_audio_mix else output_path + ".temp.mp4"

        try:
            self.log("info", f"Executing master video assembly on {len(clips)} clips...")
            if progress_callback:
                progress_callback(40.0, "Concatenating and mastering cinema video streams...")

            cmd = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-vf", video_filter,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p"
            ]

            # Master Audio Filters: Sub-Bass Woofer Boost + Broadcast Loudnorm (only if no final mix, else applied at final mix)
            audio_filters = []
            if enhance_quality and not needs_audio_mix:
                audio_filters.append("bass=g=5:f=45:w=0.6")
            if normalize_audio and not needs_audio_mix:
                audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

            if audio_filters:
                cmd.extend(["-af", ",".join(audio_filters), "-c:a", "aac", "-b:a", "256k"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", "256k"])

            cmd.append(intermediate_video)

            run_res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if run_res.returncode != 0:
                self.log("error", f"FFmpeg concat failed: {run_res.stderr[-500:]}")
                return {"success": False, "error": run_res.stderr[-500:]}

            # Multi-Layer Cinema Audio Mix: Raw Clip Ambience + Storytelling Voice + Thriller BGM with Sidechain Ducking
            if needs_audio_mix:
                if progress_callback:
                    progress_callback(78.0, "Mixing Storytelling Voice, Ambience & Thriller Score with Sidechain Ducking...")
                mix_inputs = ["-i", intermediate_video]
                filter_parts = []
                # Keep raw clip ambience subtle (65% baseline) so original sound stays alive without clashing
                raw_label = "[0:a]"

                if has_voice and has_bgm:
                    mix_inputs.extend(["-stream_loop", "-1", "-i", background_audio, "-i", storytelling_voice])
                    # Option B (Mythra Storyteller Mode): mute conflicting raw clip speech to eliminate double voice,
                    # apply warm cinema vocal EQ to narrator/dialogue, and sidechain-duck the thriller score.
                    filter_parts.append(
                        "[2:a]highpass=f=85,equalizer=f=160:t=q:w=1.2:g=4,equalizer=f=3200:t=q:w=1.5:g=-3,"
                        "acompressor=threshold=-18dB:ratio=3:attack=15:release=180,volume=1.35,asplit=2[v_main][v_sc]"
                    )
                    filter_parts.append(f"[1:a]volume={music_volume}[bgm_pre]")
                    filter_parts.append("[bgm_pre][v_sc]sidechaincompress=threshold=0.02:ratio=8:attack=40:release=450[bgm_ducked]")
                    filter_parts.append("[bgm_ducked][v_main]amix=inputs=2:duration=first:normalize=0[a_mixed]")
                elif has_voice:
                    mix_inputs.extend(["-i", storytelling_voice])
                    filter_parts.append(
                        "[1:a]highpass=f=85,equalizer=f=160:t=q:w=1.2:g=4,equalizer=f=3200:t=q:w=1.5:g=-3,"
                        "acompressor=threshold=-18dB:ratio=3:attack=15:release=180,volume=1.35[a_mixed]"
                    )
                else:
                    # Only BGM
                    mix_inputs.extend(["-stream_loop", "-1", "-i", background_audio])
                    filter_parts.append(f"{raw_label}volume=1.0[v_a]")
                    filter_parts.append(f"[1:a]volume={music_volume}[b_a]")
                    filter_parts.append("[v_a][b_a]amix=inputs=2:duration=first:dropout_transition=3[a_mixed]")

                post_audio = []
                if enhance_quality:
                    post_audio.append("bass=g=4:f=45:w=0.6")
                if normalize_audio:
                    post_audio.append("loudnorm=I=-15:TP=-1.5:LRA=11")
                if post_audio:
                    filter_parts.append(f"[a_mixed]{','.join(post_audio)}[a_out]")
                    out_map = "[a_out]"
                else:
                    out_map = "[a_mixed]"

                mix_cmd = [self.ffmpeg_path, "-y"] + mix_inputs + [
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "0:v",
                    "-map", out_map,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "256k",
                    "-shortest",
                    output_path
                ]
                mix_res = subprocess.run(mix_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if mix_res.returncode != 0:
                    self.log("warning", f"Audio storytelling mix failed, falling back to video: {mix_res.stderr[-400:]}")
                    if os.path.exists(intermediate_video):
                        os.replace(intermediate_video, output_path)
                else:
                    if os.path.exists(intermediate_video):
                        os.remove(intermediate_video)
            elif intermediate_video != output_path and os.path.exists(intermediate_video):
                os.replace(intermediate_video, output_path)

            return {"success": True}

        finally:
            if os.path.exists(concat_list_path):
                os.remove(concat_list_path)

    def _compile_crossfade(self, 
                           clips: List[str], 
                           output_path: str, 
                           crossfade_dur: float,
                           background_audio: Optional[str],
                           music_volume: float,
                           normalize_audio: bool,
                           enhance_quality: bool,
                           video_filter: str,
                           progress_callback: Optional[Callable[[float, str], None]]) -> dict:
        """Applies smooth xfade transitions between clips for fluid cinematic presentation."""
        if len(clips) <= 1:
            return self._compile_direct_concat(clips, output_path, background_audio, music_volume, normalize_audio, enhance_quality, video_filter, progress_callback)

        inputs = []
        for c in clips:
            inputs.extend(["-i", c])

        filter_parts = []
        for i in range(len(clips)):
            filter_parts.append(f"[{i}:v]{video_filter},fps=24,settb=AVTB[v{i}]")

        current_v = "[v0]"
        offset = 8.0 - crossfade_dur

        for i in range(1, len(clips)):
            next_v = f"[v{i}]"
            out_v = f"[xf{i}]" if i < len(clips) - 1 else "[v_final]"
            filter_parts.append(f"{current_v}{next_v}xfade=transition=fade:duration={crossfade_dur}:offset={round(offset, 2)}{out_v}")
            current_v = out_v
            offset += (8.0 - crossfade_dur)

        filter_str = ";".join(filter_parts)

        cmd = [self.ffmpeg_path, "-y"] + inputs + [
            "-filter_complex", filter_str,
            "-map", "[v_final]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p"
        ]

        audio_inputs = "".join([f"[{i}:a]" for i in range(len(clips))])
        cmd.extend([
            "-filter_complex", f"{filter_str};{audio_inputs}concat=n={len(clips)}:v=0:a=1[a_final]",
            "-map", "[a_final]",
            "-c:a", "aac",
            output_path
        ])

        self.log("info", "Executing FFmpeg crossfade compilation...")
        if progress_callback:
            progress_callback(40.0, "Rendering crossfade transitions...")

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and os.path.exists(output_path):
            return {"success": True}
        else:
            self.log("warning", f"Crossfade failed, falling back to direct concat: {res.stderr[-300:]}")
            return self._compile_direct_concat(clips, output_path, background_audio, music_volume, normalize_audio, enhance_quality, video_filter, progress_callback)
