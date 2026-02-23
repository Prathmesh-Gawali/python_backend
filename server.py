from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json, os, subprocess, uuid, shutil, sys

app = Flask(__name__)
CORS(app)

BASE_DIR        = os.path.dirname(__file__)
OUTPUT_DIR      = os.path.join(BASE_DIR, "manim_outputs")
MANIM_SCRIPT    = os.path.join(BASE_DIR, "animators", "manim_pb.py")
PIPELINE_SCRIPT = os.path.join(BASE_DIR, "parsers/pipeline.py")
GENERATE_AUDIO_SCRIPT = os.path.join(BASE_DIR, "parsers/generate_audio.py")
MANIM_BIN       = os.path.expanduser("~/playbook-backend/venv/bin/manim")
PYTHON_BIN      = os.path.expanduser("~/playbook-backend/venv/bin/python")

# audio_script.json lives one level above server.py (i.e. playbook-backend/)
AUDIO_SCRIPT_PATH = os.path.join(BASE_DIR, "audio_script.json")

# animation_data.json lives one level above server.py
ANIMATION_DATA_PATH = os.path.join(BASE_DIR, "animation_data.json")

# Manim media output base directory
MANIM_MEDIA_BASE = os.path.join(BASE_DIR, "media", "videos")

os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Run Strategy — receive animationData + selectedStrategy,
# write animation_data.json, clear the relevant manim output folder,
# run the appropriate animator script, and stream back the .mp4 video.
#
# selectedStrategy.type mapping:
#   "passConcepts"    → animate_play_pc.py / AnimatePlayPC
#   "passProtections" → animate_play_pp.py / AnimatePlayPP
#   "run"             → animate_play_rp.py / AnimatePlayRP
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/run-strategy", methods=["POST"])
def run_strategy():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON received"}), 400

        animation_data    = data.get("animationData")
        selected_strategy = data.get("selectedStrategy")

        if not animation_data:
            return jsonify({"error": "animationData is required"}), 400
        if not selected_strategy:
            return jsonify({"error": "selectedStrategy is required"}), 400

        strategy_type = selected_strategy.get("type", "")
        print(f"[run-strategy] Received strategy type: '{strategy_type}'")
        print(f"[run-strategy] selectedStrategy: {json.dumps(selected_strategy, indent=2)}")

        # ── Map strategy type → animator script + class name + output folder ──
        # type values from the React app:
        #   "passConcepts"    → PC animator
        #   "passProtections" → PP animator
        #   "run"             → RP animator
        if strategy_type == "passConcepts":
            animator_script = os.path.join(BASE_DIR, "animators", "animate_play_pc.py")
            manim_class     = "AnimatePlayPC"
            output_folder   = os.path.join(MANIM_MEDIA_BASE, "animate_play_pc")
        elif strategy_type == "passProtections":
            animator_script = os.path.join(BASE_DIR, "animators", "animate_play_pp.py")
            manim_class     = "AnimatePlayPP"
            output_folder   = os.path.join(MANIM_MEDIA_BASE, "animate_play_pp")
        elif strategy_type == "run":
            animator_script = os.path.join(BASE_DIR, "animators", "animate_play_rp.py")
            manim_class     = "AnimatePlayRP"
            output_folder   = os.path.join(MANIM_MEDIA_BASE, "animate_play_rp")
        else:
            return jsonify({
                "error": f"Unknown strategy type: '{strategy_type}'. "
                         f"Expected 'passConcepts', 'passProtections', or 'run'."
            }), 400

        # ── 1. Write animation_data.json (used by all three animator scripts) ─
        with open(ANIMATION_DATA_PATH, "w") as f:
            json.dump(animation_data, f, indent=2)
        print(f"[run-strategy] Wrote animation_data.json for type '{strategy_type}'")

        # ── 2. Clear ONLY this animator's output folder to avoid caching ─────
        if os.path.exists(output_folder):
            shutil.rmtree(output_folder)
            print(f"[run-strategy] Cleared output folder: {output_folder}")
        os.makedirs(output_folder, exist_ok=True)

        # ── 3. Run the manim animator ─────────────────────────────────────────
        #    -qh = high quality render (matches config.pixel_height = 1440,
        #           config.frame_rate = 30 inside animate_play_*.py → 1440p30)
        #    We run from BASE_DIR so relative paths in the scripts resolve correctly.
        print(f"[run-strategy] Running: {MANIM_BIN} -qh {animator_script} {manim_class}")
        result = subprocess.run(
            [MANIM_BIN, "-qh", animator_script, manim_class],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=1800,   # 30-min timeout for long renders
        )

        if result.returncode != 0:
            print("=== MANIM STDOUT ===")
            print(result.stdout[-2000:])
            print("=== MANIM STDERR ===")
            print(result.stderr[-4000:])
            return jsonify({
                "error":   "Manim rendering failed",
                "details": result.stderr[-4000:]
            }), 500

        # ── 4. Find the rendered .mp4 inside the output folder ───────────────
        # Expected path: media/videos/animate_play_pc/1440p30/AnimatePlayPC.mp4
        video_path = None
        for root, _, files in os.walk(output_folder):
            for fname in files:
                if fname.endswith(".mp4"):
                    video_path = os.path.join(root, fname)
                    break
            if video_path:
                break

        if not video_path or not os.path.exists(video_path):
            # List what's actually in the folder to help debug
            folder_contents = []
            for root, dirs, files in os.walk(output_folder):
                for f in files:
                    folder_contents.append(os.path.join(root, f))
            print(f"[run-strategy] Output folder contents: {folder_contents}")
            return jsonify({
                "error":    "No .mp4 found after render",
                "searched": output_folder,
                "contents": folder_contents
            }), 500

        print(f"[run-strategy] Render complete: {video_path}")

        # ── 5. Return the video file to the browser ───────────────────────────
        return send_file(
            video_path,
            mimetype="video/mp4",
            as_attachment=False,
            download_name=f"{manim_class}.mp4",
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Render timed out (>30 min)"}), 500
    except Exception as e:
        import traceback
        print(f"[run-strategy] Exception: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING ENDPOINT: Receive updated audioScript from the React UI,
# write it to audio_script.json, run generate_audio.py, and return
# the updated audioScript (with duration fields populated).
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/generate-audio", methods=["POST"])
def generate_audio_endpoint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON received"}), 400

        # 1. Write the incoming audioScript to audio_script.json
        with open(AUDIO_SCRIPT_PATH, "w") as f:
            json.dump(data, f, indent=2)

        # 2. Run generate_audio.py
        result = subprocess.run(
            [PYTHON_BIN, GENERATE_AUDIO_SCRIPT],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=600,
        )

        if result.returncode != 0:
            print("=== GENERATE_AUDIO STDERR ===")
            print(result.stderr)
            return jsonify({
                "error":   "Audio generation failed",
                "details": result.stderr[-4000:]
            }), 500

        # 3. Read back the updated audio_script.json
        with open(AUDIO_SCRIPT_PATH, "r") as f:
            updated_script = json.load(f)

        return jsonify({"audioScript": updated_script}), 200

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Audio generation timed out (>10 min)"}), 500
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING ENDPOINT: Analyze uploaded image through the full ML pipeline
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image file provided"}), 400

        image_file = request.files["image"]
        if image_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        job_id  = str(uuid.uuid4())
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        ext        = os.path.splitext(image_file.filename)[1] or ".png"
        image_path = os.path.join(job_dir, f"input_image{ext}")
        image_file.save(image_path)

        env = os.environ.copy()
        env["PIPELINE_IMAGE_PATH"] = image_path
        env["PIPELINE_OUTPUT_DIR"] = job_dir

        result = subprocess.run(
            [PYTHON_BIN, PIPELINE_SCRIPT],
            capture_output=True,
            text=True,
            cwd=job_dir,
            env=env,
            timeout=900,
        )

        if result.returncode != 0:
            print("=== PIPELINE STDERR ===")
            print(result.stderr)
            return jsonify({
                "error":   "Pipeline processing failed",
                "details": result.stderr[-4000:]
            }), 500

        script_json_path = os.path.join(job_dir, "script.json")
        if not os.path.exists(script_json_path):
            return jsonify({"error": "Pipeline did not produce script.json"}), 500

        with open(script_json_path, "r") as f:
            script_data = json.load(f)

        video_url = None
        video_path_file = os.path.join(job_dir, "video_path.txt")
        if os.path.exists(video_path_file):
            with open(video_path_file, "r") as vf:
                video_abs = vf.read().strip()
            if video_abs and os.path.exists(video_abs):
                video_url = f"/job/{job_id}/video"
        else:
            for root, _, files in os.walk(os.path.join(job_dir, "media")):
                for f in files:
                    if f.endswith(".mp4"):
                        video_url = f"/job/{job_id}/video"
                        with open(video_path_file, "w") as vf:
                            vf.write(os.path.join(root, f))
                        break
                if video_url:
                    break

        return jsonify({
            "job_id":    job_id,
            "script":    script_data,
            "video_url": video_url,
        }), 200

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pipeline timed out (>15 min)"}), 500
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Serve the rendered animation video for a given job
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/job/<job_id>/video")
def serve_job_video(job_id):
    if ".." in job_id or "/" in job_id:
        return jsonify({"error": "Invalid job_id"}), 400

    video_path_file = os.path.join(OUTPUT_DIR, job_id, "video_path.txt")
    if not os.path.exists(video_path_file):
        return jsonify({"error": "Video not found for this job"}), 404

    with open(video_path_file, "r") as f:
        video_abs = f.read().strip()

    if not video_abs or not os.path.exists(video_abs):
        return jsonify({"error": "Video file missing on disk"}), 404

    return send_file(
        video_abs,
        mimetype="video/mp4",
        as_attachment=False,
        download_name="playbook_animation.mp4",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Serve the processed output image for a given job (fallback)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/job/<job_id>/output_image")
def serve_output_image(job_id):
    if ".." in job_id or "/" in job_id:
        return jsonify({"error": "Invalid job_id"}), 400

    image_path = os.path.join(OUTPUT_DIR, job_id, "final_output.png")
    if not os.path.exists(image_path):
        image_path = os.path.join(OUTPUT_DIR, job_id, "yolo_output.png")

    if not os.path.exists(image_path):
        return jsonify({"error": "Output image not found"}), 404

    return send_file(image_path, mimetype="image/png")


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING ENDPOINT: Generate Manim animation video from playbook JSON
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/generate-video", methods=["POST"])
def generate_video():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON received"}), 400

        job_id  = str(uuid.uuid4())
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        json_path = os.path.join(job_dir, "playbookscript.json")
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        env = os.environ.copy()
        env["PLAYBOOK_JSON_PATH"] = json_path

        result = subprocess.run(
            [
                MANIM_BIN, "-ql",
                "--output_file", "output",
                MANIM_SCRIPT,
                "PlayerPlottingScene",
            ],
            capture_output=True,
            text=True,
            cwd=job_dir,
            env=env,
            timeout=300,
        )

        if result.returncode != 0:
            print("=== MANIM STDERR ===")
            print(result.stderr)
            return jsonify({
                "error":   "Manim rendering failed",
                "details": result.stderr[-4000:]
            }), 500

        video_path = None
        for root, _, files in os.walk(job_dir):
            for f in files:
                if f.endswith(".mp4"):
                    video_path = os.path.join(root, f)
                    break
            if video_path:
                break

        if not video_path:
            return jsonify({"error": "No .mp4 found after render"}), 500

        return send_file(
            video_path,
            mimetype="video/mp4",
            as_attachment=False,
            download_name="playbook_animation.mp4",
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Render timed out (>5 min)"}), 500
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    print("✅  Playbook backend → http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=True)