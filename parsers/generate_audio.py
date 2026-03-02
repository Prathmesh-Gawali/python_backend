from gtts import gTTS
import json
import os
import time
import subprocess
import shutil
from pathlib import Path
from tqdm import tqdm


def generate_gtts_audio(text, filename):
    """Generate audio using gTTS (male‑like voice)"""
    if filename.exists():
        filename.unlink()
    try:
        tts = gTTS(text=text, lang='en', tld='com', slow=False)
        tts.save(str(filename))
        time.sleep(0.5)  # allow file write to complete
        return True
    except Exception as e:
        print(f"Error generating audio for {filename}: {e}")
        return False


def generate_audio():
    # This script lives at: playbook-backend/parsers/generate_audio.py
    # So script_dir  = playbook-backend/parsers/
    # And parent dir = playbook-backend/
    script_dir = Path(__file__).parent

    # audio_script.json lives at playbook-backend/audio_script.json
    audio_script_path = script_dir.parent / 'audio_script.json'
    if not audio_script_path.exists():
        print(f"Error: audio_script.json not found at {audio_script_path}")
        return
    with open(audio_script_path, 'r') as f:
        audio_script = json.load(f)

    # Route definitions from shared_assets
    route_defs_path = script_dir.parent / 'shared_assets/football_routes.json'
    if not route_defs_path.exists():
        print(f"Warning: route definitions not found at {route_defs_path}")
        route_definitions = {"routes": {}}
    else:
        with open(route_defs_path, 'r') as f:
            route_definitions = json.load(f)

    # audio_output/male — clear existing files first, then regenerate
    base_audio_dir = script_dir.parent / 'audio_output'
    male_dir = base_audio_dir / 'male'

    if male_dir.exists():
        print(f"Clearing old audio files from {male_dir}")
        shutil.rmtree(male_dir)
    male_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nAudio will be saved to: {male_dir}")

    # Temp dir for original‑speed files (used only for duration measurement)
    temp_dir = base_audio_dir / 'temp_original'
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # ── Process each segment ─────────────────────────────────────────────────
    segments = audio_script['segments']
    for segment in tqdm(segments, desc="Generating audio segments"):
        original_text = segment['text']
        name = segment['name']
        extended_text = original_text

        # Extend with route description if available
        if 'route_type' in segment:
            route_type = segment['route_type']
            if route_type and route_type in route_definitions.get('routes', {}):
                route_desc = route_definitions['routes'][route_type].get('audio_description', [])
                if route_desc:
                    route_text = " ".join(route_desc)
                    transition = f" Here's more about the {route_type} route: "
                    extended_text += transition + route_text

        # Generate original‑speed version for duration measurement
        temp_filename = temp_dir / f"{name}_original.mp3"
        generate_gtts_audio(original_text, temp_filename)

        original_duration = get_mp3_duration_ffprobe(temp_filename)

        # Generate final (potentially extended) version
        final_filename = male_dir / f"{name}.mp3"
        generate_gtts_audio(extended_text, final_filename)

        segment['original_audio_duration'] = round(original_duration, 2)

    # Speed up all files
    speed_up_audio_files(male_dir)
    speed_up_audio_files(temp_dir)

    # Update original_audio_duration with sped‑up values from temp files
    for segment in segments:
        temp_filename = temp_dir / f"{segment['name']}_original.mp3"
        if temp_filename.exists():
            sped_up_duration = get_mp3_duration_ffprobe(temp_filename)
            segment['original_audio_duration'] = round(sped_up_duration, 2)

    # Write updated durations back to audio_script.json
    update_audio_durations(audio_script, male_dir, audio_script_path)

    # Clean up temp directory
    shutil.rmtree(temp_dir)

    print("\n" + "=" * 50)
    print("AUDIO GENERATION COMPLETE!")
    print(f"Generated audio in: {male_dir}")
    print("Updated audio_script.json with duration fields.")
    print("=" * 50)


def speed_up_audio_files(audio_dir):
    """Speed up all MP3 files in a directory by 1.125× using ffmpeg."""
    for audio_file in audio_dir.glob("*.mp3"):
        try:
            temp_file = audio_file.with_suffix('.temp.mp3')
            cmd = [
                'ffmpeg',
                '-i', str(audio_file),
                '-filter:a', 'atempo=1.125',
                '-y',
                str(temp_file)
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            audio_file.unlink()
            temp_file.rename(audio_file)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Warning: Could not speed up {audio_file}: {e}")
            print("FFmpeg might not be installed. Audio will remain at normal speed.")


def get_mp3_duration_ffprobe(mp3_path):
    """Get accurate duration of an MP3 file using ffprobe."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(mp3_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        print(f"Error getting duration with ffprobe for {mp3_path}: {e}")
        return get_mp3_duration_estimate(mp3_path)


def get_mp3_duration_estimate(mp3_path):
    """Fallback: estimate MP3 duration from file size (assumes ~128 kbps)."""
    try:
        file_size = mp3_path.stat().st_size
        duration = file_size / 16000
        return max(0.5, duration)
    except Exception:
        return 1.0


def update_audio_durations(audio_script, audio_dir, audio_script_path):
    """Update audio_script.json with accurate durations + HEAVY DEBUG"""
    print("\n" + "="*60)
    print("DEBUG: ENTERING update_audio_durations")
    print(f"Target file: {audio_script_path.absolute()}")
    print(f"File exists before write: {audio_script_path.exists()}")
    
    for segment in tqdm(audio_script['segments'], desc="Updating durations"):
        audio_path = audio_dir / f"{segment['name']}.mp3"
        if audio_path.exists():
            try:
                duration = get_mp3_duration_ffprobe(audio_path)
                segment['duration'] = round(duration, 2)
                print(f"✓ {segment['name']:20} → duration={segment['duration']}s  "
                      f"(orig={segment.get('original_audio_duration','N/A')})")
            except Exception as e:
                print(f"✗ Failed to read {audio_path}: {e}")
                segment['duration'] = estimate_duration_from_text(segment['text'])
        else:
            print(f"⚠ Audio file missing: {audio_path}")
            segment['duration'] = estimate_duration_from_text(segment['text'])

    # FORCE WRITE WITH ERROR HANDLING
    try:
        with open(audio_script_path, 'w', encoding='utf-8') as f:
            json.dump(audio_script, f, indent=2, ensure_ascii=False)
        print(f"\nSUCCESS: Wrote updated audio_script.json with {len(audio_script['segments'])} segments")
        print(f"File size after write: {audio_script_path.stat().st_size} bytes")
    except Exception as e:
        print(f"CRITICAL WRITE ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("="*60)


def estimate_duration_from_text(text):
    """Fallback duration estimation based on word count."""
    word_count = len(text.split())
    return max(1.0, word_count / 3.5)


if __name__ == "__main__":
    generate_audio()