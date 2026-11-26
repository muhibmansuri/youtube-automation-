import os
import json
import re
import math
from typing import List, Dict, Any, Optional
from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODEL
from database import db

class AutonomousScriptEngine:
    """
    Offline Cinematic Screenplay Director (Zero-API Mode).
    Generates high-fidelity, sequential 8-second cinematic prompts with strict continuity
    without requiring any external API key, cost, or network connection.
    """

    GENRE_THEMES = {
        "Cinematic Sci-Fi / Cyberpunk": {
            "lens": "35mm anamorphic lens, shallow depth of field, subtle chromatic aberration",
            "lighting": "Volumetric neon cyan and magenta rim light, dark moody shadows, rain-slicked asphalt reflections",
            "atmosphere": "Dystopian towering megastructures, holographic advertisements, misty rain and steam vents",
            "palette": "Teal, amber, deep obsidian black, neon purple",
            "actions": [
                "walking determinedly through a dense neon-lit alleyway, checking a glowing holographic datapad",
                "stepping under a flickering neon overhang, raindrops dripping from the collar of the coat",
                "surveying a crowded futuristic street market, scanning passing synth-human crowds",
                "running fingers across an encrypted cyber-terminal mounted on a rust-stained wall",
                "turning sharply around a dark corner as sirens echo in the distant rain",
                "standing atop a high rooftop balcony looking out over the sprawling futuristic cityscape",
                "adjusting tactical wrist gauntlet as digital telemetry scrolls across the visor",
                "entering a dimly lit subterranean bar with smoke swirling under amber neon tubes",
                "examining an extracted glowing memory shard under close inspection",
                "drawing a sleek sidearm cautiously while approaching a locked blast door"
            ]
        },
        "High-Octane Action Thriller": {
            "lens": "Panavision 50mm prime, high contrast, cinematic shutter angle",
            "lighting": "Hard directional sunlight, gritty amber dust motes, dramatic chiaroscuro shadows",
            "atmosphere": "Urban concrete corridors, intense heat haze, debris scattering in the wind",
            "palette": "Warm golden amber, charcoal slate, metallic gunmetal",
            "actions": [
                "moving tactically along a perimeter wall with eyes scanning the elevated windows",
                "reloading equipment with precise military discipline while crouched behind cover",
                "sprinting down a deserted industrial fire escape, boots echoing on metal stairs",
                "pausing behind a pillar to catch breath, eyes intense and focused on the target ahead",
                "breaching an iron security doorway and scanning the empty hangar beyond",
                "raising binoculars to survey an approaching armored convoy in the distance",
                "checking tactical watch timer as countdown ticks down to zero",
                "navigating through an abandoned warehouse corridor illuminated by shafts of dusty light"
            ]
        },
        "Dark Fantasy & Mythic Epic": {
            "lens": "Arri Master Prime, soft organic bloom, rich cinematic texture",
            "lighting": "Flickering torchlight, moonlight piercing dense fog, ember glow from ancient ruins",
            "atmosphere": "Ancient crumbling stone pillars, winding cobblestone paths, ethereal mist",
            "palette": "Earthy moss green, weathered bronze, midnight indigo, torch amber",
            "actions": [
                "trekking through an overgrown ancient courtyard surrounded by towering Gothic ruins",
                "raising an ornate lantern to inspect weathered runes carved into a mossy stone altar",
                "stepping through towering stone arches as fog swirls around weathered boots",
                "pausing by a dark reflecting pool beneath ancient monolithic statues",
                "grasping the hilt of a sheathed weapon while gazing up at a looming dark citadel",
                "kneeling to touch glowing arcane dust lingering on cold flagstones",
                "walking along a misty castle rampart as stormy clouds roll over mountain peaks"
            ]
        },
        "Neo-Noir Crime Detective": {
            "lens": "Vintage Cooke anamorphic, heavy atmospheric bokeh, classic film grain",
            "lighting": "Venetian blind shadow cuts, harsh tungsten streetlamp, neon beer sign reflections",
            "atmosphere": "Fog-drenched wet city streets, classic urban brownstones, melancholic night rain",
            "palette": "Warm sepia, charcoal grey, cigarette amber, rainy cyan",
            "actions": [
                "stepping out of the shadows beneath a rusted streetlamp, pulling trenchcoat collar tight",
                "inspecting a mysterious sealed dossier under the amber glow of a street corner lamp",
                "walking slowly down rain-drenched pavement, reflections stretching across puddles",
                "glancing up at a dimly lit third-floor office window with venetian blinds drawn",
                "lighting a match against the brick wall, illuminating weary determined eyes for a moment",
                "checking a pocket watch and scanning the quiet midnight street for an informant",
                "stepping through revolving brass doors into a quiet marble-tiled lobby"
            ]
        }
    }

    CAMERA_MOTIONS = [
        "Slow cinematic push-in dolly shot over 8 seconds, keeping intense eye focus",
        "Smooth horizontal tracking pan from left to right following protagonist's movement",
        "Low-angle tilt up from rain-slicked pavement to protagonist's determined face",
        "Steady medium shot with subtle organic handheld camera breathing and shallow focus",
        "Over-the-shoulder slow tracking shot maintaining protagonist's perspective",
        "High-angle slowly rotating pedestal shot descending towards protagonist",
        "Dynamic slow tracking dolly pulling backward just ahead of protagonist's steps",
        "Tight profile tracking shot gliding alongside protagonist through the environment"
    ]

    @classmethod
    def _clean_complete_summary(cls, bullets: List[str], max_chars: int = 340) -> str:
        """Joins bullet sentences cleanly without EVER cutting off a word mid-sentence."""
        parts = []
        total = 0
        for b in bullets:
            s = b.strip()
            if not s:
                continue
            if not s.endswith("."):
                s += "."
            if total + len(s) + 1 > max_chars and parts:
                break
            parts.append(s)
            total += len(s) + 1
        return " ".join(parts)

    @classmethod
    def _extract_character_blocks(cls, storyline: str) -> Dict[str, str]:
        """Extracts named character appearance locks (e.g. CHARACTER 1: INSPECTOR ARJUN) cleanly without truncation."""
        chars: Dict[str, str] = {}
        if not storyline:
            return chars

        pattern = re.compile(
            r"(?m)^\s*(?:\*{1,2})?\s*CHARACTER\s+\d+\s*:\s*([^\n\*]+?)(?:\*{1,2})?\s*$",
            re.IGNORECASE
        )
        matches = list(pattern.finditer(storyline))
        for idx, m in enumerate(matches):
            raw_name = m.group(1).strip()
            clean_name = re.sub(r"\([^)]*\)", "", raw_name).strip()
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(storyline)
            body = storyline[start:end]
            stop_m = re.search(r"(?m)^\s*(?:#{1,4}\s+|---)", body)
            if stop_m:
                body = body[:stop_m.start()]
            bullets = [re.sub(r"^\s*[-*•]\s*", "", ln).strip() for ln in body.splitlines() if ln.strip()]
            # Skip non-visual voice-only characters (e.g. Unknown Caller "face is never revealed")
            joined_low = " ".join(bullets).lower()
            if "never revealed" in joined_low or "only his voice" in joined_low:
                continue
            summary = cls._clean_complete_summary(bullets, max_chars=360)
            if clean_name and summary:
                chars[clean_name] = summary
        return chars

    @classmethod
    def _detect_location(cls, visual_text: str, current_location: str) -> str:
        """Maintains continuous scene location across consecutive clips so backgrounds never jump."""
        v = visual_text.lower()
        # Brief flashbacks / close-ups keep active location context unless explicit transition
        if "flashback" in v and "driving" in v:
            return "Inside a car driving on a dark rain-soaked road at night (15-year flashback)"
        if "flashback" in v and "apartment" in v:
            return "Inside the dark abandoned apartment during a stormy night (15-year flashback)"
        if "flashback" in v and "walking" in v:
            return "Dark rain-drenched Indian street at night (15-year flashback)"
        if "damaged car" in v or "car accident" in v:
            return "Dark rain-soaked road with a damaged car and flashing red-blue emergency lights (15-year flashback)"
        if "aerial cinematic shot" in v:
            return "Midnight aerial view over a dark rain-drenched Indian city"
        if "narrow rainy street" in v:
            return "Narrow deserted rain-soaked Indian street outside an abandoned apartment building at night"
        if "abandoned apartment" in v or "apartment entrance" in v or "broken apartment door" in v or "dark apartment" in v:
            return "Dimly lit abandoned apartment interior at midnight, rain tapping on windows"
        if "deserted rainy street" in v or "walks toward his old police station" in v:
            return "Deserted rain-slicked midnight street with dim streetlights and fog"
        if "abandoned police station" in v or "old police station" in v:
            return "Abandoned dark Indian police station interior with dusty desks, broken windows and flickering lights"
        if "investigation room" in v:
            return "Dark abandoned police investigation room illuminated by a flashlight beam"
        if "end of the corridor" in v or "old mirror" in v or "mirror" in v:
            return "Dimly lit abandoned police station corridor with an old weathered mirror at night"
        return current_location

    @classmethod
    def parse_structured_script(cls,
                                project_id: str,
                                storyline: str,
                                genre: str,
                                character_profile: str = "",
                                num_master_refs: int = 0) -> List[Dict[str, Any]]:
        """
        Detects if the user pasted an explicit scene-by-scene Master Script (e.g., Scene 01 .. Scene 75).
        Builds Hollywood-grade 8-second prompts preserving exact Visuals, Location continuity,
        On-Screen Character visual locks (never hallucinating characters into empty sky/object shots),
        Voice-Over vs Lip-Sync Hindi Dialogue distinction, and Woofer/Sub-bass cinematic sound design.
        """
        if not storyline:
            return []

        scene_header_re = re.compile(
            r"(?m)^\s*(?:#{1,4}\s*)?(?:\*{1,2})?\s*Scene\s*_?\s*(\d{1,4})\b([^\n]*?)(?:\*{1,2})?\s*$",
            re.IGNORECASE
        )
        matches = list(scene_header_re.finditer(storyline))
        if len(matches) < 2:
            return []

        act_re = re.compile(r"(?m)^\s*(?:#{1,4}\s*)?(?:\*{1,2})?\s*(ACT\s+[0-9IVX]+[^\n\*]*)", re.IGNORECASE)
        act_positions = [(m.start(), m.group(1).strip().rstrip("*").strip()) for m in act_re.finditer(storyline)]

        def _get_act_for_pos(pos: int) -> str:
            current = "Main Story"
            for a_pos, a_name in act_positions:
                if a_pos <= pos:
                    current = a_name
                else:
                    break
            return current

        extracted_chars = cls._extract_character_blocks(storyline)
        char_list = list(extracted_chars.items())  # Ordered: [0]=Character 1 (<Image 1>), [1]=Character 2 (<Image 2>)
        theme_data = cls.GENRE_THEMES.get(genre, cls.GENRE_THEMES["Neo-Noir Crime Detective"])

        is_noir = ("neo-noir" in storyline.lower()) or ("noir" in genre.lower()) or ("horror" in genre.lower())
        style_lock = (
            "Live-action feature film footage shot on ARRI Alexa Mini LF, Cooke Anamorphic 40mm lens, "
            "24fps with natural 180-degree shutter motion blur and subtle 35mm Kodak Vision3 film grain, "
            "real human skin texture with pores and rain sheen, practical motivated lighting (streetlamps, flashlight beam, dim moonlight), "
            "deep dark-blue, charcoal black and subtle dark-red grading, authentic breathing and natural movement, "
            "no CGI gloss, no plastic skin, no morphing, no unnatural slow motion, no subtitles."
        ) if is_noir else f"Live-action 35mm feature film footage. {theme_data['lens']}. {theme_data['lighting']}."

        scenes: List[Dict[str, Any]] = []
        seen_nums = set()
        current_location = "Dark rain-drenched Indian city at midnight"

        for i, m in enumerate(matches):
            s_num = int(m.group(1))
            if s_num in seen_nums:
                continue
            seen_nums.add(s_num)

            header_rest = re.sub(r"^\s*[—\-–:]+\s*", "", m.group(2).strip().rstrip("*").strip())
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(storyline)
            body = storyline[start:end]

            stop_m = re.search(r"(?m)^\s*(?:#{1,4}\s+|---\s*$|\*{1,2}\s*FINAL\s+OBJECTIVE)", body)
            if stop_m:
                body = body[:stop_m.start()]

            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            visual_parts = []
            audio_parts = []
            onscreen_dialogues = []
            offscreen_voices = []
            note_texts = []
            extra_parts = []

            for ln in lines:
                low = ln.lower()
                if low.startswith("visual:"):
                    visual_parts.append(ln.split(":", 1)[1].strip())
                elif low.startswith("audio:"):
                    audio_parts.append(ln.split(":", 1)[1].strip())
                elif low.startswith("note:"):
                    note_texts.append(ln.split(":", 1)[1].strip())
                elif low.startswith("voice-over") or low.startswith("voiceover"):
                    offscreen_voices.append(f"Off-screen Hindi voice-over (mature deep Indian male voice, DO NOT move lips on camera): {ln.split(':', 1)[-1].strip()}")
                elif low.startswith("unknown caller:") or low.startswith("caller:"):
                    offscreen_voices.append(f"Off-screen deep rough 45yo Indian male Hindi voice with subtle telephone distortion (caller unseen): {ln.split(':', 1)[-1].strip()}")
                elif "whisper" in low.split(":", 1)[0]:
                    offscreen_voices.append(f"Off-screen eerie soft whispering Indian female Hindi voice: {ln.split(':', 1)[-1].strip()}")
                elif any(low.startswith(k) for k in ["dialogue", "maya:", "arjun:"]):
                    speaker = ln.split(":", 1)[0].strip()
                    spoken = ln.split(":", 1)[1].strip() if ":" in ln else ln
                    voice_hint = "soft eerie Indian female Hindi voice" if "maya" in speaker.lower() else "mature deep slightly rough Indian male Hindi voice"
                    onscreen_dialogues.append(f"On-screen spoken Hindi dialogue with natural accurate lip-sync ({speaker}, {voice_hint}): {spoken}")
                else:
                    extra_parts.append(ln)

            visual_text = " ".join(visual_parts) if visual_parts else " ".join(extra_parts)
            if note_texts:
                visual_text = f"{visual_text} Handwritten note clearly reads: {' '.join(note_texts)}".strip()
            audio_text = " ".join(audio_parts)

            # Update persistent location (flashbacks use scene-local location without erasing present location)
            scene_location = cls._detect_location(visual_text, current_location)
            if "flashback" not in scene_location.lower() and "aerial" not in visual_text.lower():
                current_location = scene_location

            # Detect ONLY characters physically visible on screen in visual_text
            vis_low = visual_text.lower()
            # Strip quoted text (like file titles "MAYA SHARMA — MURDER CASE" or newspaper headlines) before character detection!
            vis_no_quotes = re.sub(r'"[^"]*"', "", vis_low)

            onscreen_char_locks = []
            present_char_indices = []  # 1-based index into char_list

            for c_idx, (cname, cdesc) in enumerate(char_list, start=1):
                key_tokens = [tok.lower() for tok in cname.split() if len(tok) > 2 and tok.lower() not in ("inspector", "police", "unknown")]
                is_named = any(re.search(rf"\b{re.escape(tok)}\b", vis_no_quotes) for tok in key_tokens)
                # Also detect pronoun-only continuation for main protagonist (e.g. "He enters", "His mobile phone", "Close-up of his face")
                is_protagonist_pronoun = (
                    c_idx == 1
                    and not any(k in vis_no_quotes for k in ["aerial", "wall clock", "newspaper headline", "file title", "broken apartment door", "dark apartment hallway"])
                    and bool(re.search(r"\b(he|his|him)\b", vis_no_quotes))
                )
                is_maya_pronoun = (
                    c_idx == 2
                    and bool(re.search(r"\b(woman|she|her eyes|her maroon)\b", vis_no_quotes))
                )
                if is_named or is_protagonist_pronoun or is_maya_pronoun:
                    present_char_indices.append(c_idx)
                    img_ref_note = f" (match face & outfit strictly to <Image {c_idx}>)" if (num_master_refs >= c_idx or num_master_refs == 0 and c_idx == 1) else ""
                    onscreen_char_locks.append(f"{cname}{img_ref_note}: {cdesc}")

            char_block = " ".join(onscreen_char_locks)

            # Reference image continuity clause aligned with actual attached image slots:
            # Slot 1..num_master_refs = Master Character Sheets; Last slot (for s_num > 1) = Prev Scene Last Frame
            ref_images = []
            if num_master_refs >= 2:
                ref_images = ["<Image 1>", "<Image 2>"] + (["<Image 3>"] if s_num > 1 else [])
                prev_tag = "<Image 3>"
            elif num_master_refs == 1:
                ref_images = ["<Image 1>"] + (["<Image 2>"] if s_num > 1 else [])
                prev_tag = "<Image 2>"
            else:
                ref_images = ["<Image 1>"] if s_num == 1 else ["<Image 1>", "<Image 2>"]
                prev_tag = "<Image 2>"

            if s_num == 1:
                continuity_clause = "Opening cinematic establishing shot."
            else:
                if present_char_indices and num_master_refs >= 2:
                    char_tags = " and ".join([f"<Image {idx}>" for idx in present_char_indices if idx <= num_master_refs])
                    continuity_clause = (
                        f"Continuity: Lock exact character identity from {char_tags}. "
                        f"Continue seamlessly from ending frame, lighting, and motion of {prev_tag}."
                    )
                elif present_char_indices:
                    continuity_clause = (
                        f"Continuity: Lock exact character identity from <Image 1>. "
                        f"Continue seamlessly from ending frame, lighting, and motion of {prev_tag}."
                    )
                else:
                    continuity_clause = f"Continuity: Continue seamlessly from the lighting, atmosphere, and camera flow of {prev_tag}."

            # Sound & Woofer design
            base_sound = "Continuous dark thriller background score with subtle 30-50Hz sub-bass rumble and clear Hindi dialogue mix."
            clean_audio = audio_text.rstrip(" .")
            sound_block = f"{clean_audio}. {base_sound}" if clean_audio else base_sound

            prompt_pieces = [f"8-second continuous Hollywood thriller scene ({header_rest})." if header_rest else "8-second continuous Hollywood thriller scene."]
            prompt_pieces.append(f"Location: {scene_location}.")
            if visual_text:
                prompt_pieces.append(f"Visual Action: {visual_text}")
            if char_block:
                prompt_pieces.append(f"On-Screen Character Lock: {char_block}")
            if onscreen_dialogues:
                prompt_pieces.append(" ".join(onscreen_dialogues))
            if offscreen_voices:
                prompt_pieces.append(" ".join(offscreen_voices))
            prompt_pieces.append(f"Sound & Woofer Design: {sound_block}")
            prompt_pieces.append(f"Cinematography: {style_lock}")
            prompt_pieces.append(continuity_clause)

            full_prompt = " ".join(prompt_pieces)
            act_name = _get_act_for_pos(m.start())

            scenes.append({
                "project_id": project_id,
                "scene_number": s_num,
                "title": f"Scene {s_num:02d}" + (f" ({header_rest})" if header_rest else ""),
                "scene_act": act_name,
                "prompt": full_prompt,
                "visual_action": visual_text or " ".join(lines)[:200],
                "camera_movement": "Smooth neo-noir cinematic tracking / slow push-in",
                "lighting_style": "Dark blue, black & subtle dark-red neo-noir rain lighting",
                "character_details": char_block,
                "continuity_notes": f"Chain from last frame of Scene {s_num - 1:02d} | {scene_location}" if s_num > 1 else f"Opening shot | {scene_location}",
                "ref_images": ref_images,
                "extend_from_prev": 0,
                "status": "PENDING"
            })

        scenes.sort(key=lambda x: x["scene_number"])
        return scenes

    @classmethod
    def generate_scenes(cls,
                         project_id: str,
                         storyline: str,
                         genre: str,
                         character_profile: str,
                         start_scene: int,
                         count: int,
                         total_movie_scenes: int,
                         master_ref_descriptions: str = "") -> List[Dict[str, Any]]:
        """
        Synthesizes sequential 8-second scenes aligned with a 5-Act cinematic narrative arc.
        If the storyline already contains an explicit multi-scene Master Script (e.g. Scene 01..75),
        parses and preserves EVERY exact scene from the user's script automatically!
        """
        num_refs = len([x for x in master_ref_descriptions.split(",") if x.strip()]) if master_ref_descriptions else 0
        parsed_master = cls.parse_structured_script(
            project_id=project_id,
            storyline=storyline,
            genre=genre,
            character_profile=character_profile,
            num_master_refs=num_refs
        )
        if parsed_master:
            return parsed_master

        theme_data = cls.GENRE_THEMES.get(genre, cls.GENRE_THEMES["Cinematic Sci-Fi / Cyberpunk"])
        scenes = []

        end_scene = min(start_scene + count - 1, total_movie_scenes)

        for s_num in range(start_scene, end_scene + 1):
            progress_ratio = (s_num - 1) / max(1, total_movie_scenes - 1)

            # Determine Act and Narrative Focus
            if progress_ratio < 0.20:
                act_name = "Act I: Exposition & Inciting Incident"
                story_beat = "Establishing protagonist identity, setting the tone, and uncovering the first critical clue"
            elif progress_ratio < 0.45:
                act_name = "Act II-A: Investigation & Rising Stakes"
                story_beat = "Pursuing leads, navigating hostile territory, rising danger and suspense"
            elif progress_ratio < 0.70:
                act_name = "Act II-B: The Midpoint Twist & Reversal"
                story_beat = "A shocking revelation turns the stakes upside down, escaping imminent entrapment"
            elif progress_ratio < 0.90:
                act_name = "Act III: The Climax & Final Confrontation"
                story_beat = "Infiltrating the core stronghold, facing the antagonist force directly, peak cinematic intensity"
            else:
                act_name = "Resolution: The Aftermath"
                story_beat = "Dust settling over the battlefield, truth unveiled, contemplative cinematic closing imagery"

            # Dynamic Action Selection based on beat index
            actions_list = theme_data["actions"]
            action_snippet = actions_list[(s_num - 1) % len(actions_list)]
            camera_motion = cls.CAMERA_MOTIONS[(s_num - 1) % len(cls.CAMERA_MOTIONS)]

            # Build locked character descriptor
            char_desc = character_profile.strip() if character_profile.strip() else "the protagonist"

            # Construct locked continuity prompt specifically for TAAFT
            if s_num == 1:
                continuity_clause = "Continuity: Establish protagonist matching <Image 1> Master Character Sheet."
                ref_images = ["<Image 1>"]
            else:
                continuity_clause = (
                    "Continuity: Strictly lock protagonist facial features, hairstyle, and outfit from <Image 1>. "
                    "Start precisely from the ending camera framing, posture, and lighting of <Image 2> for unbroken motion flow."
                )
                ref_images = ["<Image 1>", "<Image 2>"]

            shot_framing = [
                "Extreme Close-Up on eyes and micro-expressions",
                "Over-the-Shoulder dramatic framing",
                "Subtle Dutch Angle tension shot",
                "Slow cinematic dolly push-in",
                "Atmospheric wide establishing shot"
            ][(s_num - 1) % 5]
            foley_cue = [
                "Heavy midnight rain, distant thunder",
                "Metallic door creak, distant police siren",
                "Slow footsteps on wet floor, subtle heartbeat",
                "Three deep clock ticks, tense silence",
                "Deep cinematic sub-bass impact"
            ][(s_num - 1) % 5]

            full_prompt = (
                f"Live-action 35mm ARRI Alexa feature film footage. {theme_data['lens']}. "
                f"Framing: {shot_framing}. "
                f"Protagonist: {char_desc}, real human skin pores, natural micro-blinking, subtle breathing, emotional gaze, "
                f"mouth completely closed, NO talking or random lip movement on camera, no CGI gloss, no plastic skin. "
                f"Action (8s continuous): {action_snippet} as part of {story_beat}. "
                f"Camera: {camera_motion}. "
                f"Lighting: {theme_data['lighting']}, {theme_data['atmosphere']}. Color grading: {theme_data['palette']}. "
                f"Sound & Woofer Design: {foley_cue}. "
                f"{continuity_clause}"
            )

            scene_obj = {
                "project_id": project_id,
                "scene_number": s_num,
                "title": f"Scene {s_num:03d} - {act_name.split(':')[0]}",
                "scene_act": act_name,
                "prompt": full_prompt,
                "visual_action": f"{action_snippet} ({story_beat})",
                "camera_movement": camera_motion,
                "lighting_style": theme_data["lighting"],
                "character_details": char_desc,
                "continuity_notes": f"Chain from last frame of scene {s_num-1}" if s_num > 1 else "Opening master shot",
                "ref_images": ref_images,
                "extend_from_prev": 0,
                "status": "PENDING"
            }
            scenes.append(scene_obj)

        return scenes


class GeminiScriptwriter:
    """Breakdown story concepts into continuous 8-second cinematic scene prompts with strict visual continuity."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = DEFAULT_GEMINI_MODEL):
        self.api_key = api_key or get_gemini_api_key()
        # Auto-upgrade deprecated models to current Gemini 3.8 Flash
        if not model_name or "gemini-2.5" in model_name or "gemini-1.5" in model_name:
            model_name = DEFAULT_GEMINI_MODEL
        self.model_name = model_name
        self._client = None
        self._init_client()

    def _init_client(self, target_model: Optional[str] = None):
        if not self.api_key:
            return
        model_to_use = target_model or self.model_name
        try:
            import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=self.api_key)
            self._client = genai_legacy.GenerativeModel(model_to_use)
            self._client_type = "legacy"
            self.model_name = model_to_use
        except Exception:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
                self._client_type = "new"
                self.model_name = model_to_use
            except Exception:
                self._client = None

    def test_connection(self) -> dict:
        """Tests the Gemini API connection with the configured key."""
        if not self.api_key:
            return {"success": False, "error": "No Gemini API key configured. You can still use Autonomous Zero-API Mode!"}

        try:
            prompt = "Return a JSON object: {\"status\": \"ok\", \"message\": \"Gemini API Connected Successfully\"}"
            response_text = self._generate_text(prompt)
            return {"success": True, "message": f"Gemini API connection verified using {self.model_name}!", "response": response_text[:100]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_text(self, prompt: str) -> str:
        """Generates text from Gemini using either new or legacy client with automatic model fallback."""
        if not self._client:
            self._init_client()
        if not self._client:
            raise RuntimeError("Gemini API key is missing or client failed to initialize.")

        candidate_models = [self.model_name, "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.5-flash"]
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None
        for m in candidate_models:
            try:
                if getattr(self, "_client_type", "") == "legacy":
                    import google.generativeai as genai_legacy
                    genai_legacy.configure(api_key=self.api_key)
                    legacy_model = genai_legacy.GenerativeModel(m)
                    response = legacy_model.generate_content(prompt)
                    self.model_name = m
                    return response.text
                else:
                    response = self._client.models.generate_content(
                        model=m,
                        contents=prompt
                    )
                    self.model_name = m
                    return response.text
            except Exception as err:
                err_str = str(err)
                last_error = err
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    continue
                else:
                    raise err

        if last_error:
            raise last_error
        raise RuntimeError("Failed to generate content from any Gemini model.")

    def generate_scene_batch(self, 
                             project_id: str,
                             storyline: str, 
                             genre: str, 
                             character_profile: str, 
                             start_scene: int, 
                             count: int, 
                             total_movie_scenes: int,
                             master_ref_descriptions: str = "",
                             use_autonomous_engine: bool = False) -> List[Dict[str, Any]]:
        """
        Generates a batch of sequential 8-second scene prompts.
        If use_autonomous_engine is True or if Gemini API is unavailable/fails,
        seamlessly uses the AutonomousScriptEngine (Zero-API Mode) so the workflow never breaks.
        """
        # Always check first if user pasted an explicit scene-by-scene Master Script (e.g. Scene 01 .. Scene 75)
        num_refs = len([x for x in master_ref_descriptions.split(",") if x.strip()]) if master_ref_descriptions else 0
        parsed_master = AutonomousScriptEngine.parse_structured_script(
            project_id=project_id,
            storyline=storyline,
            genre=genre,
            character_profile=character_profile,
            num_master_refs=num_refs
        )
        if parsed_master:
            return parsed_master

        # If user selected Autonomous Zero-API mode or no API key is present
        if use_autonomous_engine or not self.api_key:
            return AutonomousScriptEngine.generate_scenes(
                project_id=project_id,
                storyline=storyline,
                genre=genre,
                character_profile=character_profile,
                start_scene=start_scene,
                count=count,
                total_movie_scenes=total_movie_scenes,
                master_ref_descriptions=master_ref_descriptions
            )

        end_scene = min(start_scene + count - 1, total_movie_scenes)

        prompt = f"""
You are a Lead AI Cinematographer crafting sequential prompts for the TAAFT 8-second Video Generator.
Every prompt must ensure unbroken character, wardrobe, lighting, and camera continuity.

CRITICAL CONTINUITY & HOLLYWOOD REALISM SPECIFICATIONS:
1. Platform Constraint: Each video generated is exactly 8 seconds long. Action must fit within 8s.
2. Human Realism Lock: Every shot must specify "Live-action 35mm ARRI Alexa footage, real human skin pores, natural micro-blinking, subtle breathing, emotional gaze, no CGI gloss, no plastic skin".
3. Lip-Sync & Narrator Control (VERY IMPORTANT):
   - For Off-Screen Narrator / Voice-Over scenes: explicitly write "mouth completely closed, silent intense expression, NO lip movement on camera" AND put the Hindi/English narrator line in quotes after `Off-screen voice-over: "..."` (max 10-12 words so it finishes cleanly).
   - For Visual/Action-only scenes: write "no talking, silent tense reaction" and include explicit `Sound & Woofer Design:` tags (e.g., `police siren`, `door creak`, `thunder`, `footsteps`, `heartbeat`, `clock ticks`, `phone ringtone`, `bass impact`).
   - Never put ALL-CAPS on-screen text or headlines inside quotation marks `""`.
4. Character Identity Lock: Always describe the protagonist with identical specific visual tags:
   {character_profile}
5. Reference Image Integration:
   - <Image 1>: Master Character Sheet.
   - <Image 2>: The exact last frame of the previous scene.
   For scene 1: "Match character identity from <Image 1>."
   For scenes > 1: "Maintain strict character visual identity from <Image 1>. Start precisely from ending composition, pose, and lighting of <Image 2> for flawless continuous camera flow."
6. Shot Variety & Tension Pacing: Alternate framing across scenes (Extreme Close-Up on eyes, Over-the-Shoulder, Dutch Angle, Slow Dolly Push-In, Atmospheric Wide) with clear 8-second camera motion.
7. Visual Atmosphere: Specify practical motivated lighting, lens, and environment.

PROJECT DETAILS:
- Storyline: {storyline}
- Genre: {genre}
- Current Scene Batch: SCENE_{start_scene:03d} to SCENE_{end_scene:03d} (out of {total_movie_scenes} total scenes)

OUTPUT FORMAT:
Return strictly a valid JSON array of scene objects without markdown code fences:
[
  {{
    "scene_number": {start_scene},
    "title": "Scene title",
    "scene_act": "Act I",
    "prompt": "Cinematic 8k, photorealistic 35mm film still. Protagonist [character]. [8s action]. Camera: [camera movement]. Lighting: [lighting]. Continuity: Maintain character from <Image 1> and start from <Image 2>.",
    "visual_action": "Action description",
    "camera_movement": "Camera direction",
    "lighting_style": "Lighting specs",
    "character_details": "{character_profile}",
    "continuity_notes": "Continuity notes",
    "extend_from_prev": 0
  }}
]
"""
        try:
            raw_text = self._generate_text(prompt)
            scenes = self._extract_json(raw_text)

            if not isinstance(scenes, list):
                if isinstance(scenes, dict) and "scenes" in scenes:
                    scenes = scenes["scenes"]
                else:
                    scenes = [scenes]

            normalized_scenes = []
            for idx, s in enumerate(scenes):
                scene_num = start_scene + idx
                if scene_num > total_movie_scenes:
                    break
                
                prompt_text = s.get("prompt", "")
                if scene_num > 1 and "<Image 1>" not in prompt_text:
                    prompt_text += " [Continuity: Match character identity from <Image 1> and start from exact posture and lighting in <Image 2>]"
                elif scene_num == 1 and "<Image 1>" not in prompt_text:
                    prompt_text += " [Continuity: Match character identity from <Image 1>]"

                normalized = {
                    "project_id": project_id,
                    "scene_number": scene_num,
                    "title": s.get("title", f"Scene {scene_num:03d}"),
                    "scene_act": s.get("scene_act", "Act I"),
                    "prompt": prompt_text.strip(),
                    "visual_action": s.get("visual_action", ""),
                    "camera_movement": s.get("camera_movement", ""),
                    "lighting_style": s.get("lighting_style", ""),
                    "character_details": s.get("character_details", character_profile),
                    "continuity_notes": s.get("continuity_notes", ""),
                    "extend_from_prev": int(s.get("extend_from_prev", 0)),
                    "status": "PENDING"
                }
                normalized_scenes.append(normalized)

            return normalized_scenes

        except Exception as e:
            # Fallback seamlessly to Autonomous Zero-API Engine if Gemini fails!
            return AutonomousScriptEngine.generate_scenes(
                project_id=project_id,
                storyline=storyline,
                genre=genre,
                character_profile=character_profile,
                start_scene=start_scene,
                count=count,
                total_movie_scenes=total_movie_scenes,
                master_ref_descriptions=master_ref_descriptions
            )

    def regenerate_single_scene_prompt(self, 
                                        project_id: str, 
                                        scene_number: int, 
                                        storyline: str, 
                                        genre: str, 
                                        character_profile: str,
                                        prev_scene_prompt: str = "",
                                        next_scene_prompt: str = "",
                                        user_instruction: str = "") -> Dict[str, Any]:
        """Regenerates or refines a single scene prompt with bridge continuity between prev and next."""
        try:
            prompt = f"""
You are an expert AI Cinematographer. Regenerate the TAAFT 8-second video prompt for Scene #{scene_number:03d}.

STORY CONTEXT:
- Storyline: {storyline}
- Genre: {genre}
- Character DNA & Wardrobe: {character_profile}
- Previous Scene Prompt: "{prev_scene_prompt or 'None (First scene)'}"
- Next Scene Prompt: "{next_scene_prompt or 'None (Final scene)'}"
- User Custom Guidance: "{user_instruction or 'Make it intensely cinematic with strict continuity'}"

STRICT RULES:
- Exactly 8 seconds of continuous action.
- Locked character description matching {character_profile}.
- Reference pointers: <Image 1> (Master Character) and <Image 2> (Previous Scene's Last Frame) if scene > 1.

OUTPUT FORMAT:
Return strictly a valid JSON object:
{{
  "title": "Scene Title",
  "prompt": "Cinematic prompt text...",
  "visual_action": "Action description",
  "camera_movement": "Camera movement",
  "lighting_style": "Lighting specs",
  "continuity_notes": "Continuity bridging notes"
}}
"""
            raw_text = self._generate_text(prompt)
            return self._extract_json(raw_text)
        except Exception:
            # Fallback to Autonomous Engine for single scene
            scenes = AutonomousScriptEngine.generate_scenes(
                project_id=project_id,
                storyline=storyline,
                genre=genre,
                character_profile=character_profile,
                start_scene=scene_number,
                count=1,
                total_movie_scenes=scene_number
            )
            return scenes[0]

    def _extract_json(self, text: str) -> Any:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start_bracket = min(
                [pos for pos in [cleaned.find('['), cleaned.find('{')] if pos != -1] or [-1]
            )
            if start_bracket != -1:
                end_bracket = max(cleaned.rfind(']'), cleaned.rfind('}'))
                if end_bracket > start_bracket:
                    snippet = cleaned[start_bracket:end_bracket + 1]
                    try:
                        return json.loads(snippet)
                    except Exception:
                        pass
            raise ValueError(f"Failed to parse valid JSON: {text[:200]}...")
