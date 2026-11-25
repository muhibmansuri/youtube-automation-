import os
import re
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, List
from config import FFMPEG_PATH

class VoiceSynthesizer:
    """
    Studio-grade Neural Voice Synthesizer supporting 14+ Human-like Neural Voices 
    (Hindi, Gujarati, Indian English, US/UK Cinema) via Microsoft Azure Neural Engine,
    plus optional ElevenLabs ultra-realistic emotional voice generation.
    """

    VOICE_CATALOG = {
        # --- HINDI VOICES ---
        "hi_arjun": {
            "name": "Inspector Arjun (Hindi Male - Gritty Detective)",
            "voice": "hi-IN-MadhurNeural",
            "rate": "-4%",
            "pitch": "-3Hz",
            "language": "Hindi",
            "gender": "Male",
            "category": "Cinema Detective",
            "description": "Deep, mature, gritty neo-noir detective voice"
        },
        "hi_maya": {
            "name": "Maya (Hindi Female - Mysterious)",
            "voice": "hi-IN-SwaraNeural",
            "rate": "-5%",
            "pitch": "+0Hz",
            "language": "Hindi",
            "gender": "Female",
            "category": "Mystery / Drama",
            "description": "Soft, natural, eerie mysterious woman"
        },
        "hi_kabir": {
            "name": "Kabir (Hindi Male - Intense Action)",
            "voice": "hi-IN-MadhurNeural",
            "rate": "+4%",
            "pitch": "+1Hz",
            "language": "Hindi",
            "gender": "Male",
            "category": "Action / Hero",
            "description": "Sharp, energetic, commanding Bollywood action lead"
        },
        "hi_ananya": {
            "name": "Ananya (Hindi Female - Emotional Drama)",
            "voice": "hi-IN-SwaraNeural",
            "rate": "-6%",
            "pitch": "+2Hz",
            "language": "Hindi",
            "gender": "Female",
            "category": "Emotional Drama",
            "description": "Gentle, emotional, heartfelt female dialogue"
        },
        "hi_caller": {
            "name": "Unknown Caller (Hindi Male - Telephone FX)",
            "voice": "hi-IN-MadhurNeural",
            "rate": "-5%",
            "pitch": "-6Hz",
            "telephone_filter": True,
            "language": "Hindi",
            "gender": "Male",
            "category": "Thriller FX",
            "description": "Dark distorted telephone voice with bandpass filter"
        },

        # --- GUJARATI VOICES ---
        "gu_niranjan": {
            "name": "Niranjan (Gujarati Male - Authentic)",
            "voice": "gu-IN-NiranjanNeural",
            "rate": "-2%",
            "pitch": "+0Hz",
            "language": "Gujarati",
            "gender": "Male",
            "category": "Regional Cinema",
            "description": "Crisp, authentic, natural Gujarati male voice"
        },
        "gu_dhwani": {
            "name": "Dhwani (Gujarati Female - Sweet & Clear)",
            "voice": "gu-IN-DhwaniNeural",
            "rate": "-2%",
            "pitch": "+0Hz",
            "language": "Gujarati",
            "gender": "Female",
            "category": "Regional Cinema",
            "description": "Melodious, expressive Gujarati female voice"
        },

        # --- INDIAN ENGLISH VOICES ---
        "in_prabhat": {
            "name": "Prabhat (Indian English Male - Modern Lead)",
            "voice": "en-IN-PrabhatNeural",
            "rate": "-3%",
            "pitch": "-1Hz",
            "language": "Indian English",
            "gender": "Male",
            "category": "Modern Cinema",
            "description": "Confident, urban Indian English male narration/dialogue"
        },
        "in_neerja": {
            "name": "Neerja (Indian English Female - Sophisticated)",
            "voice": "en-IN-NeerjaNeural",
            "rate": "-3%",
            "pitch": "+0Hz",
            "language": "Indian English",
            "gender": "Female",
            "category": "Modern Cinema",
            "description": "Sophisticated, smooth urban Indian English female voice"
        },

        # --- HOLLYWOOD / CINEMATIC ENGLISH ---
        "us_christopher": {
            "name": "Christopher (Hollywood Movie Trailer Male)",
            "voice": "en-US-ChristopherNeural",
            "rate": "-5%",
            "pitch": "-4Hz",
            "language": "English (US)",
            "gender": "Male",
            "category": "Hollywood Cinematic",
            "description": "Deep blockbuster cinema trailer & documentary voice"
        },
        "us_aria": {
            "name": "Aria (Hollywood Cinema Female - Expressive)",
            "voice": "en-US-AriaNeural",
            "rate": "-2%",
            "pitch": "+0Hz",
            "language": "English (US)",
            "gender": "Female",
            "category": "Hollywood Cinematic",
            "description": "Highly realistic, emotionally expressive cinematic female"
        },
        "us_guy": {
            "name": "Guy (Cinematic Storyteller Male)",
            "voice": "en-US-GuyNeural",
            "rate": "-4%",
            "pitch": "-2Hz",
            "language": "English (US)",
            "gender": "Male",
            "category": "Cinematic Storyteller",
            "description": "Compelling narrative voice for audiobooks & films"
        },
        "us_eric": {
            "name": "Eric (Gritty Crime Thriller Male)",
            "voice": "en-US-EricNeural",
            "rate": "-3%",
            "pitch": "-3Hz",
            "language": "English (US)",
            "gender": "Male",
            "category": "Crime Thriller",
            "description": "Raw, gritty, dark street-cop thriller voice"
        },

        # --- URDU / DRAMATIC HINDI ---
        "ur_asad": {
            "name": "Asad (Poetic / Heavy Dramatic Male)",
            "voice": "ur-PK-AsadNeural",
            "rate": "-4%",
            "pitch": "-3Hz",
            "language": "Urdu / Hindi",
            "gender": "Male",
            "category": "Dramatic Poetry",
            "description": "Deep baritone, poetic, historical and dramatic narration"
        }
    }

    # Backward compatibility map
    VOICE_MAP = {
        "arjun": VOICE_CATALOG["hi_arjun"],
        "maya": VOICE_CATALOG["hi_maya"],
        "caller": VOICE_CATALOG["hi_caller"],
        "narrator": VOICE_CATALOG["hi_arjun"],
        "kabir": VOICE_CATALOG["hi_kabir"],
        "ananya": VOICE_CATALOG["hi_ananya"],
        "niranjan": VOICE_CATALOG["gu_niranjan"],
        "dhwani": VOICE_CATALOG["gu_dhwani"],
        "prabhat": VOICE_CATALOG["in_prabhat"],
        "neerja": VOICE_CATALOG["in_neerja"],
        "christopher": VOICE_CATALOG["us_christopher"],
        "aria": VOICE_CATALOG["us_aria"],
        "guy": VOICE_CATALOG["us_guy"],
        "eric": VOICE_CATALOG["us_eric"],
        "asad": VOICE_CATALOG["ur_asad"]
    }

    @classmethod
    def list_available_voices(cls) -> List[Dict]:
        """Returns all 14 curated human-like studio voices for UI selection."""
        return [
            {"id": key, **meta}
            for key, meta in cls.VOICE_CATALOG.items()
        ]

    @classmethod
    def extract_dialogue(cls, prompt_text: str) -> Optional[Dict[str, str]]:
        """
        Parses dialogue or voice-over lines and identifies the speaking character
        from a scene prompt.
        """
        if not prompt_text:
            return None

        # Find quoted text (dialogue or voice-over)
        matches = list(re.finditer(r'["“]([^"”]{2,200})["”]', prompt_text))
        if not matches:
            return None

        for m in matches:
            text = m.group(1).strip()
            # Ignore technical prompt strings that happen to be quoted
            if text.startswith("<Image") or len(text) < 2:
                continue

            # Check context prefix (up to 150 chars before the quote)
            idx = m.start()
            prefix = prompt_text[max(0, idx - 150):idx].lower()

            if any(k in prefix for k in ["maya", "whisper", "female", "woman"]):
                character = "hi_maya"
            elif any(k in prefix for k in ["caller", "telephone", "phone"]):
                character = "hi_caller"
            elif any(k in prefix for k in ["kabir", "action", "angry"]):
                character = "hi_kabir"
            elif any(k in prefix for k in ["ananya", "crying", "emotional"]):
                character = "hi_ananya"
            elif any(k in prefix for k in ["arjun", "inspector", "dialogue arjun"]):
                character = "hi_arjun"
            elif "voice-over" in prefix or "narrat" in prefix:
                character = "hi_arjun"
            else:
                character = "hi_arjun"

            profile = cls.VOICE_CATALOG.get(character, cls.VOICE_CATALOG["hi_arjun"])
            return {
                "character": character,
                "text": text,
                "voice_profile": profile["voice"],
                "voice_name": profile["name"]
            }

        return None

    @classmethod
    async def generate_speech_async(cls, 
                                   text: str, 
                                   character: str = "hi_arjun", 
                                   output_path: str = "",
                                   elevenlabs_api_key: Optional[str] = None,
                                   elevenlabs_voice_id: Optional[str] = None) -> bool:
        """
        Synthesizes high-fidelity human speech using Microsoft Neural Edge-TTS
        or ElevenLabs (if configured).
        """
        # 1. Optional ElevenLabs Engine (if API key provided)
        if elevenlabs_api_key and elevenlabs_voice_id:
            try:
                import urllib.request
                import json
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": elevenlabs_api_key
                }
                payload = json.dumps({
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
                }).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    with open(output_path, "wb") as f:
                        f.write(resp.read())
                if os.path.exists(output_path) and os.path.getsize(output_path) > 300:
                    return True
            except Exception as ele_err:
                print(f"[VOICE ELEVENLABS NOTICE] {ele_err}. Falling back to Neural Studio...")

        # 2. Microsoft Neural Studio Engine
        try:
            import edge_tts
        except ImportError:
            print("[VOICE ERROR] edge-tts is not installed.")
            return False

        char_key = character.lower().strip()
        config = cls.VOICE_CATALOG.get(char_key, cls.VOICE_MAP.get(char_key, cls.VOICE_CATALOG["hi_arjun"]))
        voice = config["voice"]
        rate = config.get("rate", "+0%")
        pitch = config.get("pitch", "+0Hz")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        raw_output = output_path + ".raw.mp3" if config.get("telephone_filter") else output_path

        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(raw_output)

            # Apply vintage telephone filter for Unknown Caller
            if config.get("telephone_filter") and os.path.exists(raw_output):
                tf_cmd = [
                    FFMPEG_PATH, "-y",
                    "-i", raw_output,
                    "-af", "highpass=f=300,lowpass=f=3400,volume=1.2",
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    output_path
                ]
                subprocess.run(tf_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(raw_output):
                    try: os.remove(raw_output)
                    except Exception: pass

            return os.path.exists(output_path) and os.path.getsize(output_path) > 300

        except Exception as e:
            print(f"[VOICE ERROR] Synthesis failed: {e}")
            if os.path.exists(raw_output):
                try: os.remove(raw_output)
                except Exception: pass
            return False

    @classmethod
    def generate_speech(cls, text: str, character: str = "hi_arjun", output_path: str = "") -> bool:
        """Synchronous wrapper for generate_speech_async."""
        try:
            return asyncio.run(cls.generate_speech_async(text, character, output_path))
        except Exception as e:
            print(f"[VOICE ERROR] Sync execution failed: {e}")
            return False

    @classmethod
    def attach_voice_to_clip(cls, 
                             clip_path: str, 
                             voice_audio_path: str, 
                             output_clip_path: str, 
                             duck_bg: float = 0.0) -> bool:
        """
        Merges neural dialogue onto an 8-second video clip.
        duck_bg defaults to 0.0: MUTES TAAFT's distorted robotic AI noise completely,
        leaving pure, crystal-clear dialogue and zero glitching.
        """
        if not os.path.exists(clip_path) or not os.path.exists(voice_audio_path):
            return False

        Path(output_clip_path).parent.mkdir(parents=True, exist_ok=True)

        if duck_bg <= 0.01:
            # Clean Cinema Mode: Completely replace TAAFT's noisy audio with pure neural dialogue!
            cmd = [
                FFMPEG_PATH, "-y",
                "-i", clip_path,
                "-i", voice_audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-ar", "48000",
                "-ac", "2",
                "-b:a", "192k",
                output_clip_path
            ]
        else:
            # Ducked blend mode
            cmd = [
                FFMPEG_PATH, "-y",
                "-i", clip_path,
                "-i", voice_audio_path,
                "-filter_complex",
                f"[0:a]volume={duck_bg}[orig_a];[1:a]volume=1.2[vox_a];[orig_a][vox_a]amix=inputs=2:duration=first[a_out]",
                "-map", "0:v",
                "-map", "[a_out]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-ar", "48000",
                "-ac", "2",
                "-b:a", "192k",
                output_clip_path
            ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and os.path.exists(output_clip_path)
        except Exception as e:
            print(f"[VOICE ATTACH ERROR] {e}")
            return False

    @classmethod
    def mute_clip_audio(cls, clip_path: str, output_clip_path: str) -> bool:
        """
        Replaces noisy robotic audio in non-dialogue clips with clean 48kHz digital silence,
        preventing TAAFT AI audio artifacts during compilation.
        """
        if not os.path.exists(clip_path):
            return False
        Path(output_clip_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", clip_path,
            "-af", "volume=0.0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-ar", "48000",
            "-ac", "2",
            "-b:a", "192k",
            output_clip_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and os.path.exists(output_clip_path)
        except Exception as e:
            print(f"[MUTE AUDIO ERROR] {e}")
            return False

