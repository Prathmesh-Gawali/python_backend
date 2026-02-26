from manim import *
import json
import os
import numpy as np
import time
import cv2  # Required for VideoMobject
from PIL import Image, ImageOps  # Required for image operations
from dataclasses import dataclass

config.pixel_height = 1440
config.pixel_width = 2560
config.frame_rate = 30
config.max_quads_count = 100000

# Custom VideoMobject class for embedding videos - FIXED VERSION
@dataclass
class VideoStatus:
    time: float = 0
    videoObject: cv2.VideoCapture = None
    
    def __deepcopy__(self, memo):
        return self

class VideoMobject(ImageMobject):
    def __init__(self, filename=None, imageops=None, speed=1.0, loop=False, **kwargs):
        self.filename = filename
        self.imageops = imageops
        self.speed = speed
        self.loop = loop
        self.status = VideoStatus()
        
        # Initialize with a placeholder image first to satisfy ImageMobject requirements
        placeholder_array = np.zeros((100, 100, 4), dtype=np.uint8)
        placeholder_array[:, :, 3] = 255  # Fully opaque
        super().__init__(placeholder_array, **kwargs)
        
        # Initialize video capture
        self.status.videoObject = cv2.VideoCapture(filename)
        if not self.status.videoObject.isOpened():
            print(f"Error: Could not open video file {filename}")
            return
            
        # Read first frame to initialize the image
        self.status.videoObject.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = self.status.videoObject.read()
        
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            if imageops is not None:
                img = imageops(img)
            
            # Convert to RGBA if needed
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Update the pixel array with the actual video frame
            self.pixel_array = np.array(img)
            self.add_updater(self.videoUpdater)
        else:
            print(f"Error: Could not read first frame from video file {filename}")

    def videoUpdater(self, mobj, dt):
        if dt == 0:
            return
        status = self.status
        status.time += 1000 * dt * mobj.speed
        self.status.videoObject.set(cv2.CAP_PROP_POS_MSEC, status.time)
        ret, frame = self.status.videoObject.read()
        
        if not ret and self.loop:
            status.time = 0
            self.status.videoObject.set(cv2.CAP_PROP_POS_MSEC, status.time)
            ret, frame = self.status.videoObject.read()
            
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            if mobj.imageops is not None:
                img = mobj.imageops(img)
            
            # Convert to RGBA if needed
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            mobj.pixel_array = np.array(img)

class AnimatePlayPC(Scene):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audio_durations = {}
        self.yard_to_point = None
        
        # ── Load animation_data.json written fresh by server.py ──────────────
        # BASE_DIR = directory containing this script (animators/)
        # animation_data.json lives one level up in playbook-backend/
        animation_data_path = os.path.join(os.path.dirname(__file__), '..', 'animation_data.json')
        animation_data_path = os.path.normpath(animation_data_path)
        
        print(f"[AnimatePlayPC] Loading animation data from: {animation_data_path}")
        with open(animation_data_path, 'r') as f:
            self.animation_data = json.load(f)
        
        self.formation_name = self.animation_data["formation"]["name"]
    
    def construct(self):
        self.preload_audio_durations()
        
        field, yard_scale, yard_to_point = self.setup_field()
        self.yard_to_point = yard_to_point
        self.yard_scale = yard_scale
        players = self.setup_players(yard_to_point, yard_scale)
        
        # Play each segment in sequence matching the audio script
        for segment in self.audio_durations['segments']:
            self.play_segment(segment["name"], players, field)
    
    def play_whistle_sound(self):
        """Play whistle sound during snap"""
        whistle_sound_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'whistle.mp3'
        )
        whistle_sound_path = os.path.normpath(whistle_sound_path)
        
        if os.path.exists(whistle_sound_path):
            self.add_sound(whistle_sound_path)
        else:
            print(f"Whistle sound file not found: {whistle_sound_path}")
    
    def play_chase_sound(self):
        """Play chase sound for route animations — once per segment"""
        if getattr(self, '_chase_sound_played', False):
            return
        self._chase_sound_played = True
        chase_sound_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'chase.mp3'
        )
        chase_sound_path = os.path.normpath(chase_sound_path)
        
        if os.path.exists(chase_sound_path):
            self.add_sound(chase_sound_path)
        else:
            print(f"Chase sound file not found: {chase_sound_path}")

    def play_protection_sound(self):
        """Play protection sound for protection animations — once per segment"""
        if getattr(self, '_protection_sound_played', False):
            return
        self._protection_sound_played = True
        protection_sound_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'protection.mp3'
        )
        protection_sound_path = os.path.normpath(protection_sound_path)
        
        if os.path.exists(protection_sound_path):
            self.add_sound(protection_sound_path)
        else:
            print(f"Protection sound file not found: {protection_sound_path}")
    
    def preload_audio_durations(self):
        # Load audio script from BASE_DIR (playbook-backend/)
        audio_script_path = os.path.join(os.path.dirname(__file__), '..', 'audio_script.json')
        audio_script_path = os.path.normpath(audio_script_path)
        with open(audio_script_path, 'r') as f:
            self.audio_durations = json.load(f)
    
    def play_segment(self, segment_name, players, field=None):
            # Reset sound-played flags for each new segment
            self._tackle_sound_played = False
            self._chase_sound_played = False
            self._protection_sound_played = False
            self._blocking_sound_played = False
            # Play audio for this segment
            audio_duration = self.play_audio(segment_name)
            
            # Execute the appropriate animation for this segment
            if segment_name == "formation_intro":
                self.formation_intro(players, field, audio_duration)
            elif segment_name == "snap":
                self.snap_animation(players, audio_duration)
            elif segment_name == "protection":
                self.offensive_line_protection(players, audio_duration)
            elif segment_name.endswith("_route"):
                self.player_route_animation(players, segment_name, audio_duration)
            elif segment_name.startswith("qb_read"):
                self.qb_read_animation(players, segment_name, audio_duration)
            elif "passing" in segment_name:
                self.passing_options_animation(players, segment_name, audio_duration)
    
    def play_audio(self, segment_name):
        # Audio files are directly in audio_output/male (no formation subfolder)
        audio_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'audio_output', 'male', f"{segment_name}.mp3"
        )
        audio_path = os.path.normpath(audio_path)
        
        if os.path.exists(audio_path):
            self.add_sound(audio_path)
            # Find the segment duration from audio_script
            for segment in self.audio_durations['segments']:
                if segment['name'] == segment_name:
                    return segment.get('duration', 0)
            return 0
        else:
            print(f"Audio file not found for {segment_name}: {audio_path}")
            return 0

    def setup_field(self):
        # Correct path for field image (parent directory)
        field_img = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'Grass-football-field-clipart1.png'
        )
        field_img = os.path.normpath(field_img)
        
        # If the field image doesn't exist, create a simple green rectangle
        if not os.path.exists(field_img):
            print(f"Field image not found: {field_img}. Using placeholder.")
            field = Rectangle(
                width=config.frame_width * 0.9,
                height=config.frame_height * 0.6,
                color=GREEN,
                fill_opacity=0.7,
                stroke_width=0
            )
            field.to_edge(DOWN, buff=0.1)
        else:
            field = ImageMobject(field_img)
            field.stretch(-1, 1)
            field.scale_to_fit_width(config.frame_width * 0.9)
            field.to_edge(DOWN, buff=0.1)
        
        field_width = field.width
        field_center = field.get_center()
        yard_scale = field_width / 100
        
        def yard_to_point(x_yards, y_yards):
            x = field_center[0] + (x_yards * yard_scale)
            y = field_center[1] + (y_yards * yard_scale * 0.5)
            return np.array([x, y, 0])
        
        self.add(field)
        
        scrimmage_line = Line(
            yard_to_point(-50, 0),
            yard_to_point(50, 0),
            color=WHITE,
            stroke_width=yard_scale*0.2
        )
        self.add(scrimmage_line)
        
        return field, yard_scale, yard_to_point

    def setup_players(self, yard_to_point, yard_scale):
        def create_player(position, x_yards, y_yards, team="offense", color_override=None, label=None):
            point = yard_to_point(x_yards, y_yards)
            team_colors = {"offense": "#B85300", "defense": "#000080"}
            inner_color = color_override if color_override else team_colors[team]
            
            outer = Circle(radius=0.225, color=WHITE, fill_opacity=1, stroke_width=3)
            inner = Circle(radius=0.17, color=inner_color, fill_opacity=1)
            
            display_label = label if label else position
            
            label_text = Text(display_label, font_size=6, color=WHITE, weight=BOLD)
            label_text.scale_to_fit_width(outer.width * 0.3)
            label_text.scale_to_fit_height(outer.width * 0.3)
            
            player = VGroup(outer, inner, label_text)
            player.move_to(point)
            
            player.original_position = np.array(player.get_center(), dtype=float)
            return player

        formation = self.animation_data["formation"]["positions"]
        
        def get_display_label(player_data, default_pos):
            return player_data.get("display_label", player_data.get("label", default_pos))
        
        # Offensive line
        offensive_line = VGroup()
        for ol_pos in formation["ol"]:
            label = get_display_label(ol_pos, "O")
            player = create_player("O", ol_pos["x"], ol_pos["y"], "offense", ol_pos.get("color", None), label)
            offensive_line.add(player)
        
        qb_label = get_display_label(formation["qb"], "Q")
        qb = create_player("Q", formation["qb"]["x"], formation["qb"]["y"], "offense", formation["qb"].get("color", None), qb_label)
        
        rb_label = get_display_label(formation["rb"], "R")
        rb = create_player("R", formation["rb"]["x"], formation["rb"]["y"], "offense", formation["rb"].get("color", None), rb_label)
        
        fb = VGroup()
        if "fb" in formation:
            fb_label = get_display_label(formation["fb"], "F")
            fb = create_player("F", formation["fb"]["x"], formation["fb"]["y"], "offense", formation["fb"].get("color", None), fb_label)
            print("DEBUG: Created FB player")
        else:
            print("DEBUG: No FB in formation")
        
        te_t = VGroup()
        if "te_t" in formation:
            te_t_label = get_display_label(formation["te_t"], "T")
            te_t = create_player("T", formation["te_t"]["x"], formation["te_t"]["y"], "offense", formation["te_t"].get("color", None), te_t_label)
            print("DEBUG: Created TE_T player")
        else:
            print("DEBUG: No TE_T in formation")
        
        te_label = get_display_label(formation["te"], "T")
        te = create_player("T", formation["te"]["x"], formation["te"]["y"], "offense", formation["te"].get("color", None), te_label)
        
        x_wr_label = get_display_label(formation["wr_x"], "W")
        x_wr = create_player("W", formation["wr_x"]["x"], formation["wr_x"]["y"], "offense", formation["wr_x"].get("color", None), x_wr_label)
        
        z_wr_label = get_display_label(formation["wr_z"], "W")
        z_wr = create_player("W", formation["wr_z"]["x"], formation["wr_z"]["y"], "offense", formation["wr_z"].get("color", None), z_wr_label)
        
        defense_positions = self.animation_data["defense"]["positions"]
        defensive_players = VGroup()
        dl_players = {}
        defense_dict = {}
        
        for i, (player_key, player_data) in enumerate(defense_positions.items()):
            label = get_display_label(player_data, player_data["label"][0] if player_data["label"] else "D")
            player = create_player(
                player_data["label"][0] if player_data["label"] else "D",
                player_data["x"], 
                player_data["y"], 
                "defense", 
                player_data.get("color", None),
                label
            )
            defensive_players.add(player)
            defense_dict[player_key] = player
            
            if player_data["label"] in ["E", "N", "T"]:
                lbl = player_data["label"]
                if lbl in dl_players:
                    dl_players[f"{lbl}{i}"] = player
                else:
                    dl_players[lbl] = player
        
        football_point = yard_to_point(0, 4.0)
        football = self.create_football(football_point, yard_scale)
        
        offense = VGroup(offensive_line, qb, rb, te, x_wr, z_wr)
        if len(fb) > 0:
            offense.add(fb)
        if len(te_t) > 0:
            offense.add(te_t)
        
        self.add(offense, defensive_players, football)
        
        players_dict = {
            "ol": offensive_line, "qb": qb, "rb": rb,
            "x_wr": x_wr, "te": te, "z_wr": z_wr, 
            "football": football, "defense": defensive_players,
            "dl_players": dl_players,
            **defense_dict
        }
        
        if len(fb) > 0:
            players_dict["fb"] = fb
            
        if len(te_t) > 0:
            players_dict["te_t"] = te_t
            
        return players_dict
    
    def create_football(self, point, scale):
        football = Circle(
            radius=scale*0.6,
            color="#D37F00",
            fill_opacity=1,
            stroke_width=2
        )
        football.move_to(point)
        
        stripe1 = Line(
            football.get_left(),
            football.get_right(),
            color="#FFFFFF",
            stroke_width=scale*0.15
        )
        stripe2 = Line(
            football.get_top(),
            football.get_bottom(),
            color="#FFFFFF",
            stroke_width=scale*0.15
        )
        return VGroup(football, stripe1, stripe2)

    def create_route_path(self, path_points, route_style="curved", sharp_points=None):
        """Create a route path with the specified style (curved, sharp, or mixed)"""
        path = VMobject()
        
        if len(path_points) < 2:
            print(f"Warning: Insufficient path points ({len(path_points)}). Creating default path.")
            if len(path_points) == 1:
                path_points.append(path_points[0] + np.array([0.1, 0.1, 0]))
            else:
                path_points = [np.array([0, 0, 0]), np.array([1, 1, 0])]
        
        if route_style == "curved":
            path.set_points_smoothly(path_points)
        elif route_style == "sharp" or route_style == "block" or route_style == "panther":
            path.set_points_as_corners(path_points)
        elif route_style == "mixed":
            if sharp_points is None:
                sharp_points = []
            
            sharp_points = sorted([p for p in sharp_points if 0 <= p < len(path_points)])
            
            if not sharp_points:
                path.set_points_smoothly(path_points)
            else:
                segments = []
                start_idx = 0
                all_segment_points = sharp_points + [len(path_points)-1]
                
                for end_idx in all_segment_points:
                    if end_idx >= start_idx:
                        segment_points = path_points[start_idx:end_idx+1]
                        
                        if len(segment_points) >= 2:
                            if start_idx in sharp_points or len(segment_points) <= 2:
                                segment = VMobject()
                                segment.set_points_as_corners(segment_points)
                                segments.append(segment)
                            else:
                                segment = VMobject()
                                segment.set_points_smoothly(segment_points)
                                segments.append(segment)
                        
                        start_idx = end_idx
                
                if len(segments) == 1:
                    path = segments[0]
                elif len(segments) > 1:
                    all_points = []
                    for segment in segments:
                        all_points.extend(segment.get_points())
                    path.set_points(all_points)
        
        path.set_stroke(width=4)
        
        if path.has_no_points():
            print("Warning: Created path has no points. Creating fallback path.")
            fallback_points = [np.array([0, 0, 0]), np.array([1, 1, 0])]
            path.set_points_smoothly(fallback_points)
            
        return path

    def create_throw_indicator(self, start_pos, end_pos):
        """Create a visual indicator for QB throw"""
        throw_line = DashedLine(start_pos, end_pos, color=YELLOW, stroke_width=4)
        throw_circle = Circle(radius=0.2, color=YELLOW, stroke_width=3)
        throw_circle.move_to(end_pos)
        
        return VGroup(throw_line, throw_circle)

    def create_protection_indicator(self, path_points):
        """Create a protection indicator (short perpendicular line) at the end of a protection route"""
        if len(path_points) < 2:
            return VGroup()
        
        p_last = np.array(path_points[-1], dtype=float)
        p_prev = np.array(path_points[-2], dtype=float)
        
        last_segment = p_last - p_prev
        last_segment_length = np.linalg.norm(last_segment[:2])
        
        if last_segment_length == 0:
            return VGroup()
        
        direction = last_segment[:2] / last_segment_length
        perpendicular_2d = np.array([-direction[1], direction[0]])
        perpendicular = np.array([perpendicular_2d[0], perpendicular_2d[1], 0.0])
        
        protection_line_length = 0.6
        start_pt = p_last - perpendicular * (protection_line_length / 2)
        end_pt = p_last + perpendicular * (protection_line_length / 2)
        
        protection_line = Line(start_pt, end_pt, color=WHITE, stroke_width=4)
        return protection_line

    def formation_intro(self, players, field, audio_duration):
        formation_name = self.animation_data["formation"]["name"]
        play_name = self.animation_data["formation"]["play_name"]
        formation_description = self.animation_data["formation"]["description"]
        
        key_players = []
        for player_key in ["z_wr", "x_wr", "te", "rb", "qb"]:
            if player_key in players:
                key_players.append(players[player_key])
        
        if "fb" in players and len(players["fb"]) > 0:
            key_players.append(players["fb"])
        
        if "te_t" in players and len(players["te_t"]) > 0:
            key_players.append(players["te_t"])
        
        highlights = VGroup()
        for player in key_players:
            highlight = Circle(radius=player[0].radius*1.5, color=YELLOW, stroke_width=4)
            highlight.move_to(player)
            highlights.add(highlight)
        
        formation_text = Text(f"{formation_name} - {play_name}", font_size=36, color=YELLOW, weight=BOLD)
        formation_text.to_edge(UP)
        
        formation_details = Text(
            formation_description,
            font_size=24,
            color=WHITE,
            weight=BOLD
        )
        formation_details.next_to(formation_text, DOWN)
        
        start_time = time.time()
        
        self.play(FadeIn(highlights, run_time=0.5))
        
        pulse_animations = []
        for highlight in highlights:
            pulse_sequence = AnimationGroup(
                highlight.animate.scale(1.2).set_stroke(opacity=0.8),
                highlight.animate.scale(1/1.2).set_stroke(opacity=1),
                highlight.animate.scale(1.2).set_stroke(opacity=0.8),
                highlight.animate.scale(1/1.2).set_stroke(opacity=1),
                highlight.animate.scale(1.2).set_stroke(opacity=0.8),
                highlight.animate.scale(1/1.2).set_stroke(opacity=1),
                lag_ratio=0.1
            )
            pulse_animations.append(pulse_sequence)
        
        self.play(
            Write(formation_text, run_time=1), 
            Write(formation_details, run_time=1),
            *pulse_animations
        )
        
        self.wait(1)
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
            
        self.play(
            FadeOut(highlights, run_time=0.5), 
            FadeOut(formation_text, run_time=0.5),
            FadeOut(formation_details, run_time=0.5)
        )

    def snap_animation(self, players, audio_duration):
        self.play_whistle_sound()
        
        center = players["ol"][2]
        snap_path = ArcBetweenPoints(
            center.get_center(),
            players["qb"].get_center(),
            angle=-TAU/4
        )
        snap_path.set_stroke(width=4)
        
        snap_circle = Circle(radius=0.45, color=WHITE, fill_opacity=0.5, stroke_width=3).move_to(center.get_center())
        snap_flash = VGroup(snap_circle.copy().set_fill(WHITE, opacity=1), snap_circle.copy().set_fill(WHITE, opacity=0.5))
        
        start_time = time.time()
        self.play(
            GrowFromCenter(snap_flash, run_time=0.2),
            MoveAlongPath(players["football"], snap_path, run_time=1)
        )
        self.play(FadeOut(snap_flash, run_time=0.3))
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)

    def offensive_line_protection(self, players, audio_duration):
        protection_assignments = self.animation_data["protection"]["assignments"]
        protection_scheme = self.animation_data["protection"]["scheme"]
        
        prot_text = Text(f"{protection_scheme.title()} Protection Scheme", font_size=28, color=RED, weight=BOLD)
        prot_text.to_edge(UP)
        
        start_time = time.time()
        self.play(Write(prot_text, run_time=0.5))
        self.wait(1)
        
        pocket_lines = VGroup()
        for ol_player in players["ol"]:
            circle_radius = ol_player[0].radius
            
            left_line = Line(
                ol_player.get_center() + LEFT * circle_radius,
                ol_player.get_center() + LEFT * circle_radius + UP * circle_radius * 1.6,
                color=BLUE,
                stroke_width=3
            )
            right_line = Line(
                ol_player.get_center() + RIGHT * circle_radius,
                ol_player.get_center() + RIGHT * circle_radius + UP * circle_radius * 1.6,
                color=BLUE,
                stroke_width=3
            )
            pocket_lines.add(left_line, right_line)
        
        block_anims = []
        
        for i in range(len(players["ol"])):
            block_anims.append(players["ol"][i].animate.shift(UP*0.3))
        
        for assignment in protection_assignments:
            dl_index = assignment["dl_index"]
            block_anims.append(players["defense"][dl_index].animate.shift(DOWN*0.2))
        
        if block_anims:
            self.play(LaggedStart(*block_anims), run_time=2)
        
        pocket_animations = [Create(line) for line in pocket_lines]
        if pocket_animations:
            self.play(LaggedStart(*pocket_animations, run_time=1))
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        self.play(
            FadeOut(prot_text, run_time=0.5),
            FadeOut(pocket_lines, run_time=0.5)
        )

    def player_route_animation(self, players, segment_name, audio_duration):
        parts = segment_name.split('_')
        
        if parts[-1] == 'route':
            player_pos = '_'.join(parts[:-1])
        else:
            player_pos = parts[0]
        
        print(f"DEBUG: Processing route for player: '{player_pos}', segment: '{segment_name}'")
        
        if player_pos == "te":
            player = players["te"]
            route_data = self.animation_data["routes"]["te"]
        elif player_pos == "wr_z":
            player = players["z_wr"]
            route_data = self.animation_data["routes"]["wr_z"]
        elif player_pos == "wr_x":
            player = players["x_wr"]
            route_data = self.animation_data["routes"]["wr_x"]
        elif player_pos == "rb":
            player = players["rb"]
            route_data = self.animation_data["routes"]["rb"]
        elif player_pos == "qb":
            player = players["qb"]
            route_data = self.animation_data["routes"]["qb"]
        elif player_pos == "fb":
            if "fb" in players and len(players["fb"]) > 0:
                player = players["fb"]
                route_data = self.animation_data["routes"]["fb"]
                print(f"DEBUG: Found FB player with route data: {route_data.get('label', 'No label')}")
            else:
                print("DEBUG: FB player not found")
                return
        elif player_pos == "te_t":
            if "te_t" in players and len(players["te_t"]) > 0:
                player = players["te_t"]
                route_data = self.animation_data["routes"]["te_t"]
                print(f"DEBUG: Found TE_T player with route data: {route_data.get('label', 'No label')}")
            else:
                print("DEBUG: TE_T player not found")
                return
        else:
            print(f"DEBUG: Unknown player position: {player_pos}")
            return
        
        route_type = route_data.get("type", "")
        if route_type == "protection":
            self.play_protection_sound()
        elif route_type in ["square_in", "post", "flag", "flat", "corner", "drag", "panther", "spot"]:
            self.play_chase_sound()
        
        start_pos = np.array(player.get_center(), dtype=float).copy()
        current_pos = start_pos.copy()
        
        path_segments = []
        step_positions = [current_pos.copy()]
        
        for step in route_data.get("steps", []):
            dx = step.get("right", 0) - step.get("left", 0)
            dy = step.get("up", 0) - step.get("down", 0)
            new_pos = current_pos + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
            
            step_positions.append(new_pos.copy())
            current_pos = new_pos
        
        for i in range(len(step_positions) - 1):
            start_segment = step_positions[i]
            end_segment = step_positions[i + 1]
            
            step_style = route_data.get("steps", [])[i].get("style", route_data.get("route_style", "curved"))
            
            if step_style in ["curved", "smooth"]:
                segment = ArcBetweenPoints(start_segment, end_segment, angle=0.3)
            elif step_style in ["sharp", "panther"]:
                segment = Line(start_segment, end_segment)
            elif step_style in ["block", "protection"]:
                segment = Line(start_segment, end_segment)
                segment.set_stroke(width=6)
            else:
                segment = Line(start_segment, end_segment)
            
            segment.set_color(route_data.get("color", WHITE))
            segment.set_stroke(width=4)
            path_segments.append(segment)
        
        complete_path_points = step_positions.copy()
        complete_path = self.create_route_path(complete_path_points, 
                                            route_data.get("route_style", "curved"),
                                            route_data.get("sharp_turn_points", []))
        complete_path.set_color(route_data.get("color", WHITE))
        
        route_end_marker = VGroup()
        if len(complete_path_points) >= 2:
            last_point = complete_path_points[-1]
            second_last_point = complete_path_points[-2]
            vec = np.array(last_point) - np.array(second_last_point)
            vec2 = vec.copy()
            length = np.linalg.norm(vec2[:2])
            if length != 0:
                direction = vec2 / length
            else:
                direction = np.array([0, 1, 0])
            
            if route_data.get("type") == "protection" or route_data.get("route_style") == "block":
                route_end_marker = self.create_protection_indicator(complete_path_points)
            else:
                arrow_tip = Triangle(fill_opacity=1, stroke_width=0, color=route_data.get("color", WHITE))
                arrow_tip.set_height(0.3)
                arrow_tip.rotate(np.arctan2(direction[1], direction[0]) - PI/2)
                arrow_tip.move_to(last_point + direction * 0.2)
                route_end_marker = arrow_tip
        
        route_label = Text(route_data.get("label", ""), font_size=20, color=route_data.get("color", WHITE), weight=BOLD)
        route_label.next_to(player, UP)
        
        secondary_paths = VGroup()
        secondary_markers = VGroup()
        if "secondary_options" in route_data:
            for secondary in route_data["secondary_options"]:
                branch_point = secondary.get("branch_point", 0)
                if branch_point < len(complete_path_points):
                    sec_start = np.array(complete_path_points[branch_point], dtype=float).copy()
                    sec_current = sec_start.copy()
                    sec_points = [sec_current]
                    
                    for step in secondary.get("steps", []):
                        dx = step.get("right", 0) - step.get("left", 0)
                        dy = step.get("up", 0) - step.get("down", 0)
                        sec_current = sec_current + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
                        sec_points.append(sec_current.copy())
                    
                    if len(secondary.get("steps", [])) > 0:
                        sharp_steps = 0
                        curved_steps = 0
                        
                        for step in secondary.get("steps", []):
                            step_style = step.get("style", secondary.get("route_style", "curved"))
                            if step_style in ["sharp", "block", "panther"]:
                                sharp_steps += 1
                            else:
                                curved_steps += 1
                        
                        if sharp_steps > curved_steps:
                            secondary_route_style = "sharp"
                        else:
                            secondary_route_style = "curved"
                    else:
                        secondary_route_style = secondary.get("route_style", "curved")
                    
                    if len(sec_points) == 2:
                        sec_path = DashedLine(sec_points[0], sec_points[1], color=secondary.get("color", YELLOW), stroke_width=3, dash_length=0.2)
                    else:
                        sec_path = self.create_route_path(sec_points, secondary_route_style, secondary.get("sharp_turn_points", []))
                        sec_path.set_color(secondary.get("color", YELLOW))
                        sec_path.set_stroke(width=3, opacity=0.8)
                        from manim import DashedVMobject
                        sec_path = DashedVMobject(sec_path, num_dashes=20)
                    
                    secondary_paths.add(sec_path)
                    
                    if len(sec_points) >= 2:
                        s_last = sec_points[-1]
                        s_prev = sec_points[-2]
                        s_vec = s_last - s_prev
                        s_len = np.linalg.norm(s_vec[:2])
                        if s_len != 0:
                            s_dir = s_vec / s_len
                        else:
                            s_dir = np.array([0, 1, 0])
                        s_arrow = Triangle(fill_opacity=1, stroke_width=0, color=secondary.get("color", YELLOW))
                        s_arrow.set_height(0.25)
                        s_arrow.rotate(np.arctan2(s_dir[1], s_dir[0]) - PI/2)
                        s_arrow.move_to(s_last + s_dir * 0.2)
                        secondary_markers.add(s_arrow)
        
        start_time = time.time()
        
        self.play(Write(route_label, run_time=0.5))
        
        current_player_pos = start_pos.copy()
        for i, segment in enumerate(path_segments):
            segment_draw_time = 0.5 / len(path_segments)
            segment_move_time = 3.0 / len(path_segments)
            
            self.play(Create(segment, run_time=segment_draw_time))
            
            if not segment.has_no_points():
                self.play(MoveAlongPath(player, segment, run_time=segment_move_time))
            else:
                end_pos = step_positions[i + 1]
                self.play(player.animate.move_to(end_pos), run_time=segment_move_time)
        
        if len(secondary_paths) > 0:
            self.play(Create(secondary_paths, run_time=0.5))
            if len(secondary_markers) > 0:
                self.play(GrowFromCenter(secondary_markers, run_time=0.3))
        
        if route_end_marker:
            if route_data.get("type") == "protection" or route_data.get("route_style") == "block":
                self.play(Create(route_end_marker, run_time=0.3))
            else:
                self.play(GrowFromCenter(route_end_marker, run_time=0.3))
        
        elapsed = time.time() - start_time
        
        original_audio_duration = 0
        for segment in self.audio_durations['segments']:
            if segment['name'] == segment_name:
                original_audio_duration = segment.get('original_audio_duration', 0)
                break
        
        if original_audio_duration > 0:
            time_to_wait = original_audio_duration - elapsed
            if time_to_wait > 0:
                self.wait(time_to_wait)
            
            self.wait(0.5)
            
            video_remaining = audio_duration - (elapsed + time_to_wait + 0.5)
        else:
            self.wait(2)
            elapsed += 2
            video_remaining = max(0, audio_duration - elapsed)
        
        if video_remaining > 0 and "type" in route_data:
            route_type = route_data["type"]
            video_path_720p = os.path.join(
                os.path.dirname(__file__), 
                '..', 'shared_assets', 'route_animator', '720p60', f"{route_type}.mp4"
            )
            video_path_2160p = os.path.join(
                os.path.dirname(__file__), 
                '..', 'shared_assets', 'route_animator', '2160p60', f"{route_type}.mp4"
            )
            video_path_480p = os.path.join(
                os.path.dirname(__file__), 
                '..', 'shared_assets', 'route_animator', '480p15', f"{route_type}.mp4"
            )
            if os.path.exists(video_path_720p):
                video_path = os.path.normpath(video_path_720p)
            elif os.path.exists(video_path_2160p):
                video_path = os.path.normpath(video_path_2160p)
            else:
                video_path = os.path.normpath(video_path_480p)
            if os.path.exists(video_path):
                try:
                    route_video = VideoMobject(filename=video_path, speed=1.0, loop=True if video_remaining > 10 else False)
                    
                    screen_width = config.frame_width
                    screen_height = config.frame_height
                    target_width = screen_width * 0.95
                    target_height = screen_height * 0.8
                    
                    route_video.set_width(target_width)
                    if route_video.height > target_height:
                        route_video.set_height(target_height)
                    
                    route_video.move_to(ORIGIN)
                    
                    self.add(route_video)
                    self.wait(video_remaining)
                    self.remove(route_video)
                except Exception as e:
                    print(f"Error loading video: {e}")
                    if video_remaining > 0:
                        self.wait(video_remaining)
            else:
                print(f"Video file not found: {video_path}")
                if video_remaining > 0:
                    self.wait(video_remaining)
        
        fade_outs = [FadeOut(route_label, run_time=0.5)]
        
        for segment in path_segments:
            fade_outs.append(FadeOut(segment, run_time=0.5))
        
        if route_end_marker:
            fade_outs.append(FadeOut(route_end_marker, run_time=0.5))
        if len(secondary_paths) > 0:
            fade_outs.append(FadeOut(secondary_paths, run_time=0.5))
        if len(secondary_markers) > 0:
            fade_outs.append(FadeOut(secondary_markers, run_time=0.5))
        
        self.play(*fade_outs)

    def qb_read_animation(self, players, segment_name, audio_duration):
        read_target_mapping = {
            "z": "wr_z",
            "te": "te", 
            "x": "wr_x"
        }
        
        read_target = segment_name.split('_')[-1]
        player_pos = read_target_mapping.get(read_target)
        
        if not player_pos:
            print(f"DEBUG: Unknown read target: {read_target}")
            return
        
        target_read = None
        read_progression = self.animation_data.get("read_progression", [])
        
        for read in read_progression:
            if read.get("player") == player_pos:
                target_read = read
                break
        
        if not target_read:
            print(f"DEBUG: No read progression found for player: {player_pos}")
            return
        
        player_key_mapping = {
            "wr_x": "x_wr",
            "wr_z": "z_wr",
            "te": "te",
            "rb": "rb",
            "fb": "fb"
        }
        
        player_key = player_key_mapping.get(player_pos, player_pos)
        
        if player_key not in players:
            print(f"DEBUG: Player key '{player_key}' not found in players dictionary")
            return
            
        target = players[player_key]
        color = target_read.get("color", WHITE)

        arrow = Arrow(
            players["qb"].get_center(), target.get_center(),
            color=color, buff=0.2, stroke_width=6,
            max_tip_length_to_length_ratio=0.2,
            stroke_opacity=0.9
        )

        qb_range = Circle(
            radius=players["qb"][0].radius * 25,
            color=color,
            stroke_width=4,
            fill_opacity=0.25,
            stroke_opacity=0.8
        )
        qb_range.move_to(players["qb"].get_center())

        circle = Circle(radius=target[0].radius*1.2, color=color, stroke_width=4)
        circle.move_to(target.get_center())

        start_time = time.time()
        qb_reads_text = Text("QB Reads", font_size=32, color=WHITE, weight=BOLD)
        qb_reads_text.to_edge(UP)
        
        self.play(
            Write(qb_reads_text, run_time=0.3),
            Create(arrow, run_time=0.3),
            Create(qb_range, run_time=0.3),
            Create(circle, run_time=0.3)
        )

        self.play(
            circle.animate.scale(1.2).set_stroke(opacity=0.8),
            run_time=0.3
        )
        self.play(
            circle.animate.scale(1/1.2).set_stroke(opacity=1),
            run_time=0.3
        )

        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)

        if remaining > 0:
            self.wait(remaining)

        self.play(
            FadeOut(arrow, run_time=0.2),
            FadeOut(qb_range, run_time=0.2),
            FadeOut(circle, run_time=0.2),
            FadeOut(qb_reads_text, run_time=0.2)
        )

    def passing_options_animation(self, players, segment_name, audio_duration):
        passing_options = self.animation_data.get("passing_options", {})
        
        player_key_mapping = {
            "wr_x": "x_wr",
            "wr_z": "z_wr", 
            "te": "te",
            "rb": "rb",
            "fb": "fb"
        }
        
        if "primary" in segment_name:
            targets = []
            for json_player_key in passing_options.get("primary", []):
                player_key = player_key_mapping.get(json_player_key, json_player_key)
                if player_key in players:
                    targets.append(players[player_key])
            color = "#FF6B6B"
            label = "Primary Targets"
        else:
            targets = []
            for json_player_key in passing_options.get("checkdowns", []):
                player_key = player_key_mapping.get(json_player_key, json_player_key)
                if player_key in players:
                    targets.append(players[player_key])
            color = "#4ECDC4"
            label = "Checkdown Options"
        
        circles = VGroup()
        for target in targets:
            area = Circle(
                radius=target[0].radius * 3,
                color=color,
                stroke_width=3,
                fill_opacity=0.2,
                stroke_opacity=0.9
            )
            area.move_to(target.get_center())
            circles.add(area)
        
        option_text = Text(label, font_size=26, color=color, weight=BOLD)
        option_text.to_edge(UP)
        
        start_time = time.time()
        
        animations = []
        
        if len(circles) > 0:
            circle_animations = [Create(circle) for circle in circles]
            animations.append(LaggedStart(*circle_animations, run_time=0.7))
        
        animations.append(Write(option_text, run_time=0.7))
        
        if animations:
            self.play(*animations)
        
        if len(circles) > 0:
            self.play(
                circles.animate.scale(1.1).set_stroke(opacity=0.8).set_fill(opacity=0.25),
                run_time=0.3
            )
            self.play(
                circles.animate.scale(1/1.1).set_stroke(opacity=0.9).set_fill(opacity=0.2),
                run_time=0.3
            )
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        fade_outs = [FadeOut(option_text, run_time=0.3)]
        if len(circles) > 0:
            fade_outs.append(FadeOut(circles, run_time=0.3))
        
        self.play(*fade_outs)