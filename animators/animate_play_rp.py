from manim import *
import json
import os
import numpy as np
import time
import cv2  # Required for VideoMobject
from PIL import Image, ImageOps  # Required for image operations
from dataclasses import dataclass

# Configure rendering settings to match code 1
config.pixel_height = 1440
config.pixel_width = 2560
config.frame_rate = 30
config.max_quads_count = 100000      # Reduce for cleaner vector rendering

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

class AnimatePlayRP(Scene):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audio_durations = {}
        self.yard_to_point = None
        
        # Load animation data with correct path (parent directory) – normalized and logged
        animation_data_path = os.path.join(os.path.dirname(__file__), '..', 'animation_data.json')
        animation_data_path = os.path.normpath(animation_data_path)
        print(f"[AnimatePlayRP] Loading animation data from: {animation_data_path}")
        with open(animation_data_path, 'r') as f:
            self.animation_data = json.load(f)
        
        # Extract formation name from file path - kept for potential use but not for audio
        current_file_path = os.path.abspath(__file__)
        formation_dir = os.path.basename(os.path.dirname(current_file_path))
        self.formation_name = formation_dir  # Use original: "(Blue)_R_Twin_K93_Panther"
    
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

    def play_tackle_sound(self):
        """Play tackle sound for block assignments — once per segment"""
        if getattr(self, '_tackle_sound_played', False):
            return
        self._tackle_sound_played = True
        tackle_sound_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'protection.mp3'
        )
        tackle_sound_path = os.path.normpath(tackle_sound_path)
        
        if os.path.exists(tackle_sound_path):
            self.add_sound(tackle_sound_path)
        else:
            print(f"Tackle sound file not found: {tackle_sound_path}")

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

    def play_blocking_sound(self):
        """Play blocking sound for run blocking animations — once per segment"""
        if getattr(self, '_blocking_sound_played', False):
            return
        self._blocking_sound_played = True
        blocking_sound_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'shared_assets', 'protection.mp3'
        )
        blocking_sound_path = os.path.normpath(blocking_sound_path)
        
        if os.path.exists(blocking_sound_path):
            self.add_sound(blocking_sound_path)
        else:
            print(f"Blocking sound file not found: {blocking_sound_path}")

    def preload_audio_durations(self):
        # Load audio script with correct path (parent directory)
        audio_script_path = os.path.join(os.path.dirname(__file__), '..', 'audio_script.json')
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
                # Check if it's run blocking or pass protection
                protection_scheme = self.animation_data["protection"]["scheme"]
                if protection_scheme == "run_blocking":
                    self.offensive_line_protection_enhanced(players, audio_duration)
                else:
                    self.pass_protection_animation(players, audio_duration)
            elif segment_name.endswith("_route"):
                # Check if this player should be animated in protection phase or route phase
                player_pos = segment_name.replace('_route', '')
                route_data = self.get_route_data(player_pos)
                
                # For pass protection, only animate non-blocking players in route phase
                protection_scheme = self.animation_data["protection"]["scheme"]
                if protection_scheme == "pass_protection":
                    if route_data and route_data.get("blocking_assignment"):
                        # Skip - these were animated in protection phase
                        self.wait(audio_duration)
                    else:
                        # Animate non-blocking routes
                        self.player_route_animation(players, segment_name, audio_duration)
                else:
                    # Run play logic (original)
                    if route_data and route_data.get("type") == "protection" and route_data.get("blocking_assignment"):
                        self.blocking_assignment_animation(players, player_pos, audio_duration)
                    else:
                        self.player_route_animation(players, segment_name, audio_duration)
            elif segment_name.startswith("qb_read"):
                self.qb_read_animation(players, segment_name, audio_duration)
            elif "passing" in segment_name:
                # Check if it's a run play to use run options animation
                if self.animation_data["protection"]["scheme"] == "run_blocking":
                    if "primary" in segment_name:
                        self.run_options_animation(players, "primary", audio_duration)
                    elif "checkdowns" in segment_name:
                        self.handoff_animation(players, audio_duration)
                else:
                    self.passing_options_animation(players, segment_name, audio_duration)
            elif segment_name == "qb_dropback":
                self.qb_dropback_animation(players, audio_duration)
    
    def get_route_data(self, player_pos):
        """Helper function to get route data for a player"""
        routes = self.animation_data.get("routes", {})
        if player_pos in routes:
            return routes[player_pos]
        
        # Handle OL routes (ol_0, ol_1, etc.)
        if player_pos.startswith("ol_"):
            return routes.get(player_pos)
        
        return None

    def play_audio(self, segment_name):
        # Simplified audio path: directly in ../audio_output/male/
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
        
        # Use .width property instead of deprecated get_width()
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
            stroke_width=yard_scale*0.2  # Increased stroke width
        )
        self.add(scrimmage_line)
        
        return field, yard_scale, yard_to_point

    def setup_players(self, yard_to_point, yard_scale):
        def create_player(position, x_yards, y_yards, team="offense", color_override=None, label=None):
            point = yard_to_point(x_yards, y_yards)
            team_colors = {"offense": "#B85300", "defense": "#000080"}
            inner_color = color_override if color_override else team_colors[team]
            
            # FURTHER REDUCED sizes to 75% of already reduced size
            outer = Circle(radius=0.225, color=WHITE,  # Reduced from 0.3 to 0.225 (75% of 75%)
                          fill_opacity=1, stroke_width=3)
            inner = Circle(radius=0.17, color=inner_color,  # Reduced from 0.225 to 0.17 (75% of 75%)
                          fill_opacity=1)
            
            # Use provided label if available, otherwise use position
            display_label = label if label else position
            
            # FURTHER REDUCED TEXT SIZE for player labels - from 20 to 14
            label_text = Text(display_label, font_size=6, color=WHITE, weight=BOLD)  # Reduced from 20 to 14
            label_text.scale_to_fit_width(outer.width * 0.3)
            label_text.scale_to_fit_height(outer.width * 0.3)
            
            player = VGroup(outer, inner, label_text)
            player.move_to(point)
            
            # Store original position for every created player
            player.original_position = np.array(player.get_center(), dtype=float)
            return player

        # Create players based on animation_data.json
        formation = self.animation_data["formation"]["positions"]
        
        # Offensive line
        offensive_line = VGroup()
        for ol_pos in formation["ol"]:
            player = create_player("O", ol_pos["x"], ol_pos["y"], "offense", ol_pos.get("color", None), ol_pos.get("display_label", None))
            offensive_line.add(player)
        
        # Skill positions with custom colors from animation_data
        qb = create_player("Q", formation["qb"]["x"], formation["qb"]["y"], "offense", formation["qb"].get("color", None), formation["qb"].get("display_label", None))
        rb = create_player("R", formation["rb"]["x"], formation["rb"]["y"], "offense", formation["rb"].get("color", None), formation["rb"].get("display_label", None))
        
        # FIX: Add FB (Fullback) player - CHECK IF EXISTS IN FORMATION
        fb = VGroup()
        if "fb" in formation:
            fb = create_player("F", formation["fb"]["x"], formation["fb"]["y"], "offense", formation["fb"].get("color", None), formation["fb"].get("display_label", None))
            print("DEBUG: Created FB player")
        else:
            print("DEBUG: No FB in formation")
        
        # Check if TE_T exists in formation
        te_t = VGroup()
        if "te_t" in formation:
            te_t = create_player("T", formation["te_t"]["x"], formation["te_t"]["y"], "offense", formation["te_t"].get("color", None), formation["te_t"].get("display_label", None))
            print("DEBUG: Created TE_T player")
        else:
            print("DEBUG: No TE_T in formation")
        
        te = create_player("T", formation["te"]["x"], formation["te"]["y"], "offense", formation["te"].get("color", None), formation["te"].get("display_label", None))
        x_wr = create_player("W", formation["wr_x"]["x"], formation["wr_x"]["y"], "offense", formation["wr_x"].get("color", None), formation["wr_x"].get("display_label", None))
        z_wr = create_player("W", formation["wr_z"]["x"], formation["wr_z"]["y"], "offense", formation["wr_z"].get("color", None), formation["wr_z"].get("display_label", None))
        
        # Defense - using positions from JSON file with consistent positioning
        defense_positions = self.animation_data["defense"]["positions"]
        defensive_players = VGroup()
        
        # Store specific defensive players we need for protection
        dl_players = {}
        defense_dict = {}
        
        # Create individual defensive players
        for i, (player_key, player_data) in enumerate(defense_positions.items()):
            player = create_player(
                player_data["label"][0] if player_data["label"] else "D",
                player_data["x"], 
                player_data["y"], 
                "defense", 
                player_data.get("color", None),
                player_data.get("display_label", None)
            )
            defensive_players.add(player)
            
            # Store all defensive players by key for easy access
            defense_dict[player_key] = player
            
            # Store specific defensive linemen for protection scheme
            if player_data["label"] in ["E", "N", "T"]:
                # Use position as key, append number if duplicate
                label = player_data["label"]
                if label in dl_players:
                    dl_players[f"{label}{i}"] = player
                else:
                    dl_players[label] = player
        
        football_point = yard_to_point(0, 4.0)
        football = self.create_football(football_point, yard_scale)
        
        # FIX: Include FB in offense group if it exists - ROBUST HANDLING
        offense = VGroup(offensive_line, qb, rb, te, x_wr, z_wr)
        if len(fb) > 0:  # Add FB if it exists
            offense.add(fb)
            print("DEBUG: Added FB to offense group")
        if len(te_t) > 0:  # Only add te_t if it exists
            offense.add(te_t)
            print("DEBUG: Added TE_T to offense group")
        
        self.add(offense, defensive_players, football)
        
        # FIX: Complete players dictionary with all players - ROBUST HANDLING
        players_dict = {
            "ol": offensive_line, "qb": qb, "rb": rb,
            "x_wr": x_wr, "te": te, "z_wr": z_wr, 
            "football": football, "defense": defensive_players,
            "dl_players": dl_players,  # Specific defensive linemen for protection
            **defense_dict  # Add individual defensive players
        }
        
        # Add FB if it exists
        if len(fb) > 0:
            players_dict["fb"] = fb
            print("DEBUG: Added FB to players_dict")
            
        # Add TE_T if it exists
        if len(te_t) > 0:
            players_dict["te_t"] = te_t
            print("DEBUG: Added TE_T to players_dict")
            
        print(f"DEBUG: Final players_dict keys: {list(players_dict.keys())}")
        return players_dict
    
    def create_football(self, point, scale):
        football = Circle(
            radius=scale*0.6,  # Reduced size
            color="#D37F00",
            fill_opacity=1,
            stroke_width=2  # Reduced stroke width
        )
        football.move_to(point)
        
        stripe1 = Line(
            football.get_left(),
            football.get_right(),
            color="#FFFFFF",
            stroke_width=scale*0.15  # Reduced stroke width
        )
        stripe2 = Line(
            football.get_top(),
            football.get_bottom(),
            color="#FFFFFF",
            stroke_width=scale*0.15  # Reduced stroke width
        )
        return VGroup(football, stripe1, stripe2)

    def create_route_path(self, path_points, route_style="curved", sharp_points=None):
        """Create a route path with the specified style (curved, sharp, or mixed)"""
        path = VMobject()
        
        # CRITICAL FIX: Ensure we have at least 2 points for a valid path
        if len(path_points) < 2:
            print(f"Warning: Insufficient path points ({len(path_points)}). Creating default path.")
            # Create a minimal valid path with 2 points
            if len(path_points) == 1:
                path_points.append(path_points[0] + np.array([0.1, 0.1, 0]))
            else:
                path_points = [np.array([0, 0, 0]), np.array([1, 1, 0])]
        
        if route_style == "curved":
            # Original implementation - smooth curved routes
            path.set_points_smoothly(path_points)
        elif route_style == "sharp" or route_style == "block" or route_style == "panther":
            # Sharp routes - straight lines between points (treat custom "block" or "panther" as sharp)
            path.set_points_as_corners(path_points)
        elif route_style == "mixed":
            # Mixed routes - combine curved and sharp segments
            if sharp_points is None:
                sharp_points = []
            
            # Sort and ensure sharp points are valid
            sharp_points = sorted([p for p in sharp_points if 0 <= p < len(path_points)])
            
            if not sharp_points:
                # No sharp points specified, use curved
                path.set_points_smoothly(path_points)
            else:
                # Create segments between sharp points
                segments = []
                start_idx = 0
                
                # Add the end point to ensure we cover the entire path
                all_segment_points = sharp_points + [len(path_points)-1]
                
                for end_idx in all_segment_points:
                    if end_idx >= start_idx:
                        segment_points = path_points[start_idx:end_idx+1]
                        
                        if len(segment_points) >= 2:
                            # Determine if this segment should be sharp or curved
                            # If the start point is a sharp point, make the segment sharp
                            if start_idx in sharp_points or len(segment_points) <= 2:
                                # Use sharp corners for this segment
                                segment = VMobject()
                                segment.set_points_as_corners(segment_points)
                                segments.append(segment)
                            else:
                                # Use smooth curves for this segment
                                segment = VMobject()
                                segment.set_points_smoothly(segment_points)
                                segments.append(segment)
                        
                        start_idx = end_idx
                
                # If we have multiple segments, we need to combine them
                if len(segments) == 1:
                    path = segments[0]
                elif len(segments) > 1:
                    # Combine all segments into one path
                    all_points = []
                    for segment in segments:
                        all_points.extend(segment.get_points())
                    path.set_points(all_points)
        
        # Set higher stroke width for better visibility
        path.set_stroke(width=4)  # Slightly reduced from 5
        
        # CRITICAL FIX: Validate the path has points before returning
        if path.has_no_points():
            print("Warning: Created path has no points. Creating fallback path.")
            # Create a simple fallback path
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
        
        # Convert to numpy arrays (ensure float)
        p_last = np.array(path_points[-1], dtype=float)
        p_prev = np.array(path_points[-2], dtype=float)
        
        last_segment = p_last - p_prev
        last_segment_length = np.linalg.norm(last_segment[:2])
        
        if last_segment_length == 0:
            return VGroup()
        
        # Normalize the direction vector (2D)
        direction = last_segment[:2] / last_segment_length
        
        # Perpendicular unit vector in 2D
        perpendicular_2d = np.array([-direction[1], direction[0]])
        perpendicular = np.array([perpendicular_2d[0], perpendicular_2d[1], 0.0])
        
        # Create a short line perpendicular to the route (centered at end point)
        protection_line_length = 0.6  # scene units (tweak as needed)
        start_pt = p_last - perpendicular * (protection_line_length / 2)
        end_pt = p_last + perpendicular * (protection_line_length / 2)
        
        protection_line = Line(start_pt, end_pt, color=WHITE, stroke_width=4)
        return protection_line

    def create_blocking_indicator(self, defender_pos):
        """Create a visual indicator for blocking assignment - UPDATED: removed dotted line, smaller blue circle"""
        # Create a blue circle around the defender with reduced radius
        defender_circle = Circle(radius=0.3, color=BLUE, stroke_width=3)  # Reduced radius from 0.5 to 0.3, changed color to BLUE
        defender_circle.move_to(defender_pos)
        
        return defender_circle  # Return only the circle, no dotted line

    def create_clash_effect(self, position):
        """Create a clash effect when blocker and defender meet"""
        clash_circle = Circle(radius=0.4, color=RED, fill_opacity=0.7, stroke_width=3)
        clash_circle.move_to(position)
        return clash_circle

    def create_blocking_dotted_line(self, start_pos, end_pos):
        """NEW: Create a blue dotted line for block assignments"""
        dotted_line = DashedLine(start_pos, end_pos, color=BLUE, stroke_width=3, dash_length=0.2)
        return dotted_line

    def formation_intro(self, players, field, audio_duration):
        # REMOVED: pre_snap_movement call
        
        # Get formation data from JSON
        formation_name = self.animation_data["formation"]["name"]
        play_name = self.animation_data["formation"]["play_name"]
        formation_description = self.animation_data["formation"]["description"]
        
        # Get key players to highlight - ROBUST HANDLING
        key_players = []
        for player_key in ["z_wr", "x_wr", "te", "rb", "qb"]:
            if player_key in players and len(players[player_key]) > 0:
                key_players.append(players[player_key])
        
        # Add FB if exists
        if "fb" in players and len(players["fb"]) > 0:
            key_players.append(players["fb"])
        
        # Add TE_T if exists
        if "te_t" in players and len(players["te_t"]) > 0:
            key_players.append(players["te_t"])
        
        print(f"DEBUG: Highlighting {len(key_players)} players in formation intro")
        
        highlights = VGroup()
        for player in key_players:
            # player[0] is outer circle - reduced highlight size proportionally
            highlight = Circle(radius=player[0].radius*1.5, color=YELLOW, stroke_width=4)
            highlight.move_to(player)
            highlights.add(highlight)
        
        # Use formation data from JSON for text
        formation_text = Text(f"{formation_name} - {play_name}", font_size=36, color=YELLOW, weight=BOLD)
        formation_text.to_edge(UP)
        
        # Add formation details from JSON
        formation_details = Text(
            formation_description,
            font_size=24,
            color=WHITE,
            weight=BOLD
        )
        formation_details.next_to(formation_text, DOWN)
        
        start_time = time.time()
        
        # NEW: Pulse the yellow rings instead of player movement
        self.play(FadeIn(highlights, run_time=0.5))
        
        # FIXED: Create exactly three pulse cycles for the highlights using AnimationGroup
        pulse_animations = []
        for highlight in highlights:
            # Create exactly three pulse cycles (scale up and down three times)
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
        
        # Play text and pulsing animations together
        self.play(
            Write(formation_text, run_time=1), 
            Write(formation_details, run_time=1),
            *pulse_animations
        )
        
        self.wait(1)  # Additional display time
        
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
        # Play whistle sound during snap
        self.play_whistle_sound()
        
        center = players["ol"][2]
        snap_path = ArcBetweenPoints(
            center.get_center(),
            players["qb"].get_center(),
            angle=-TAU/4
        )
        snap_path.set_stroke(width=4)  # Reduced from 5
        
        # Add a snap effect
        snap_circle = Circle(radius=0.45, color=WHITE, fill_opacity=0.5, stroke_width=3).move_to(center.get_center())  # Reduced sizes
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

    def offensive_line_protection_enhanced(self, players, audio_duration):
        """Enhanced offensive line protection for run blocking"""
        protection_assignments = self.animation_data["protection"]["assignments"]
        protection_scheme = self.animation_data["protection"]["scheme"]
        
        # FIX: Play protection sound for OL protection
        self.play_protection_sound()
        
        # Use protection scheme from JSON for text
        prot_text = Text(f"{protection_scheme.replace('_', ' ').title()}", font_size=28, color=RED, weight=BOLD)
        prot_text.to_edge(UP)
        
        start_time = time.time()
        self.play(Write(prot_text, run_time=0.5))
        
        # Get OL route data
        routes = self.animation_data.get("routes", {})
        
        # Create blocking indicators for each OL - UPDATED: using new create_blocking_indicator
        blocking_indicators = VGroup()
        ol_animations = []
        
        # NEW: Store all route elements for cleanup
        route_elements = VGroup()
        protection_indicators = VGroup()
        
        # NEW: Store dotted lines for block assignments
        blocking_dotted_lines = VGroup()
        
        for i, assignment in enumerate(protection_assignments):
            ol_index = assignment["ol_index"]
            
            # Get OL player
            ol_player = players["ol"][ol_index]
            
            # Get the route data for this OL to find the correct defender
            ol_route_key = f"ol_{ol_index}"
            if ol_route_key in routes:
                route_data = routes[ol_route_key]
                
                # FIXED: Animate OL routes even if they don't have blocking assignments
                # Calculate route path regardless of blocking assignment
                start_pos = np.array(ol_player.get_center(), dtype=float).copy()
                current_pos = start_pos.copy()
                step_positions = [current_pos.copy()]
                
                for step in route_data.get("steps", []):
                    dx = step.get("right", 0) - step.get("left", 0)
                    dy = step.get("up", 0) - step.get("down", 0)
                    new_pos = current_pos + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
                    step_positions.append(new_pos.copy())
                    current_pos = new_pos
                
                # Create route path
                if len(step_positions) >= 2:
                    route_path = self.create_route_path(step_positions, route_data.get("route_style", "sharp"))
                    route_path.set_color(route_data.get("color", "#B85300"))
                    
                    # Create protection indicator at end
                    protection_indicator = self.create_protection_indicator(step_positions)
                    
                    # STORE elements for cleanup
                    route_elements.add(route_path)
                    protection_indicators.add(protection_indicator)
                    
                    # Add animation for this OL
                    ol_animations.append(
                        Succession(
                            Create(route_path, run_time=1),
                            MoveAlongPath(ol_player, route_path, run_time=2),
                            Create(protection_indicator, run_time=0.3)
                        )
                    )
                
                # FIXED: Only create blocking indicators if there's a blocking assignment
                blocking_assignment = route_data.get("blocking_assignment")
                if blocking_assignment:
                    # Calculate endpoint FIRST
                    endpoint = current_pos.copy()  # Calculate endpoint from the route
                    
                    # Handle both "defender" and "defenders" keys
                    defender_key = None
                    if "defender" in blocking_assignment:
                        defender_key = blocking_assignment["defender"]
                    elif "defenders" in blocking_assignment and blocking_assignment["defenders"]:
                        defender_key = blocking_assignment["defenders"][0]  # Use first defender
                    
                    if defender_key:
                        # Get defender by key from the defense dictionary
                        defender = players.get(defender_key)
                        
                        if defender is not None:
                            # Create blocking indicator
                            indicator = self.create_blocking_indicator(defender.get_center())
                            blocking_indicators.add(indicator)
                            
                            # NEW: Create blue dotted line from OL start position to endpoint
                            dotted_line = self.create_blocking_dotted_line(start_pos, endpoint)
                            blocking_dotted_lines.add(dotted_line)
                        else:
                            print(f"DEBUG: Defender {defender_key} not found for OL {ol_index}")
                    else:
                        print(f"DEBUG: No defender key found in blocking assignment for OL {ol_index}")
                else:
                    print(f"DEBUG: No blocking assignment found for OL {ol_index}, but will still animate route")
            else:
                print(f"DEBUG: No route data found for OL {ol_index}")
        
        # Show all blocking indicators first (only if there are any)
        if len(blocking_indicators) > 0:
            self.play(LaggedStart(*[Create(indicator) for indicator in blocking_indicators], run_time=1))
        else:
            print("DEBUG: No blocking indicators to show")
        
        # Show dotted lines for block assignments
        if len(blocking_dotted_lines) > 0:
            self.play(LaggedStart(*[Create(line) for line in blocking_dotted_lines], run_time=1))
        
        # Then animate all OL movements simultaneously (only if there are any)
        if ol_animations:
            self.play(LaggedStart(*ol_animations, lag_ratio=0.2), run_time=3)
        else:
            print("DEBUG: No OL animations to play")
        
        # NEW: Play tackle sound when blockers reach defenders
        if len(blocking_indicators) > 0:
            self.play_tackle_sound()
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        # FIXED: Clean up ALL elements including route paths and protection indicators
        fade_outs = [FadeOut(prot_text, run_time=0.5)]
        
        if len(blocking_indicators) > 0:
            fade_outs.append(FadeOut(blocking_indicators, run_time=0.5))
        
        if len(route_elements) > 0:
            fade_outs.append(FadeOut(route_elements, run_time=0.5))
            
        if len(protection_indicators) > 0:
            fade_outs.append(FadeOut(protection_indicators, run_time=0.5))
        
        if len(blocking_dotted_lines) > 0:
            fade_outs.append(FadeOut(blocking_dotted_lines, run_time=0.5))
        
        self.play(*fade_outs)

    def pass_protection_animation(self, players, audio_duration):
        """NEW: Pass protection animation - animate all blocking players simultaneously"""
        protection_scheme = self.animation_data["protection"]["scheme"]
        
        # Play protection sound
        self.play_protection_sound()
        
        # Use protection scheme from JSON for text
        prot_text = Text("Pass Protection", font_size=28, color=RED, weight=BOLD)
        prot_text.to_edge(UP)
        
        start_time = time.time()
        self.play(Write(prot_text, run_time=0.5))
        
        # Get all players with blocking assignments
        routes = self.animation_data.get("routes", {})
        blocking_players = []
        
        # NEW: Store all animation elements for cleanup
        all_route_elements = VGroup()
        all_protection_indicators = VGroup()
        all_defender_paths = VGroup()
        all_clash_effects = VGroup()
        all_blocking_dotted_lines = VGroup()  # NEW: Store dotted lines
        
        # Find all players with blocking assignments
        for player_key, route_data in routes.items():
            if route_data.get("blocking_assignment"):
                blocking_players.append((player_key, route_data))
        
        print(f"DEBUG: Found {len(blocking_players)} players with blocking assignments")
        
        # Animate all blocking players and their defenders simultaneously
        animations = []
        clash_effects = []
        
        for player_key, route_data in blocking_players:
            # Get the offensive player
            if player_key.startswith("ol_"):
                # OL player
                ol_index = int(player_key.split("_")[1])
                if ol_index < len(players["ol"]):
                    offensive_player = players["ol"][ol_index]
                else:
                    continue
            else:
                # Skill position player
                if player_key in players and len(players[player_key]) > 0:
                    offensive_player = players[player_key]
                else:
                    continue
            
            # Get blocking assignment
            blocking_assignment = route_data.get("blocking_assignment", {})
            defender_keys = blocking_assignment.get("defenders", [])
            
            # Calculate offensive player's endpoint
            start_pos = np.array(offensive_player.get_center(), dtype=float).copy()
            current_pos = start_pos.copy()
            step_positions = [current_pos.copy()]
            
            for step in route_data.get("steps", []):
                dx = step.get("right", 0) - step.get("left", 0)
                dy = step.get("up", 0) - step.get("down", 0)
                new_pos = current_pos + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
                step_positions.append(new_pos.copy())
                current_pos = new_pos
            
            endpoint = current_pos.copy()
            
            # Create offensive player path
            if len(step_positions) >= 2:
                route_path = self.create_route_path(step_positions, route_data.get("route_style", "sharp"))
                route_path.set_color(route_data.get("color", "#B85300"))
                
                # Create protection indicator at end
                protection_indicator = self.create_protection_indicator(step_positions)
                
                # STORE elements for cleanup
                all_route_elements.add(route_path)
                all_protection_indicators.add(protection_indicator)
                
                # Add offensive player animation
                animations.append(Create(route_path, run_time=1))
                animations.append(MoveAlongPath(offensive_player, route_path, run_time=2))
                animations.append(Create(protection_indicator, run_time=0.3))
            
            # Animate defenders to the same endpoint
            for defender_key in defender_keys:
                defender = players.get(defender_key)
                if defender is None:
                    continue
                
                # NEW: Create blue dotted line from offensive player's start to defender
                dotted_line = self.create_blocking_dotted_line(start_pos, endpoint)
                all_blocking_dotted_lines.add(dotted_line)
                
                # Calculate direct path for defender to endpoint
                defender_path = Line(defender.get_center(), endpoint, color="#000080")
                defender_path.set_stroke(width=4)
                
                # STORE defender path for cleanup
                all_defender_paths.add(defender_path)
                
                # Add defender animation
                animations.append(Create(defender_path, run_time=1))
                animations.append(MoveAlongPath(defender, defender_path, run_time=2))
                
                # Create clash effect at endpoint
                clash_effect = self.create_clash_effect(endpoint)
                clash_effects.append(clash_effect)
                all_clash_effects.add(clash_effect)
        
        # Show dotted lines first
        if len(all_blocking_dotted_lines) > 0:
            self.play(LaggedStart(*[Create(line) for line in all_blocking_dotted_lines], run_time=1))
        
        # Play all animations simultaneously
        if animations:
            self.play(LaggedStart(*animations, lag_ratio=0.1), run_time=3)
        
        # Show clash effects and play tackle sound
        if clash_effects:
            self.play(LaggedStart(*[GrowFromCenter(effect) for effect in clash_effects], lag_ratio=0.05), run_time=1)
            self.play_tackle_sound()  # NEW: Play tackle sound when clash happens
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        # FIXED: Clean up ALL elements
        fade_outs = [FadeOut(prot_text, run_time=0.5)]
        
        if len(all_route_elements) > 0:
            fade_outs.append(FadeOut(all_route_elements, run_time=0.5))
        
        if len(all_protection_indicators) > 0:
            fade_outs.append(FadeOut(all_protection_indicators, run_time=0.5))
        
        if len(all_defender_paths) > 0:
            fade_outs.append(FadeOut(all_defender_paths, run_time=0.5))
        
        if len(all_clash_effects) > 0:
            fade_outs.append(FadeOut(all_clash_effects, run_time=0.5))
        
        if len(all_blocking_dotted_lines) > 0:
            fade_outs.append(FadeOut(all_blocking_dotted_lines, run_time=0.5))
        
        self.play(*fade_outs)

    def blocking_assignment_animation(self, players, player_key, audio_duration):
        """Animation for individual blocking assignments - FIXED VERSION"""
        route_data = self.get_route_data(player_key)
        if not route_data or not route_data.get("blocking_assignment"):
            print(f"DEBUG: No blocking assignment found for {player_key}")
            return

        blocking_assignment = route_data["blocking_assignment"]

        # Get all defenders from the blocking assignment
        defender_keys = []
        if "defender" in blocking_assignment:
            defender_keys.append(blocking_assignment["defender"])
        elif "defenders" in blocking_assignment and blocking_assignment["defenders"]:
            defender_keys = blocking_assignment["defenders"]
        else:
            print(f"DEBUG: No defenders found in blocking assignment for {player_key}")
            return

        # ---- FIX: Map JSON player key to internal players dict key ----
        json_to_internal = {
            "wr_x": "x_wr",
            "wr_z": "z_wr",
            "te": "te",
            "fb": "fb",
            "rb": "rb",
            "qb": "qb",
        }
        internal_key = json_to_internal.get(player_key, player_key)
        blocker = players.get(internal_key)
        if blocker is None or len(blocker) == 0:
            print(f"DEBUG: Blocker {player_key} (internal: {internal_key}) not found")
            # Wait full duration to avoid audio overlap
            self.wait(audio_duration)
            return
        # ---------------------------------------------------------------

        # Get all valid defenders
        defenders = []
        for defender_key in defender_keys:
            defender = players.get(defender_key)
            if defender and len(defender) > 0:
                defenders.append(defender)
            else:
                print(f"DEBUG: Defender {defender_key} not found")

        if not defenders:
            print(f"DEBUG: No valid defenders found for {player_key}")
            return

        # Play blocking sound
        self.play_blocking_sound()

        # Create blocking assignment text
        block_type = route_data.get("label", "Block")
        defender_names = ", ".join(defender_keys)
        assignment_text = Text(f"{player_key.upper()} vs {defender_names} - {block_type}",
                            font_size=24, color=route_data.get("color", "#6A0572"), weight=BOLD)
        assignment_text.to_edge(UP)

        start_time = time.time()
        self.play(Write(assignment_text, run_time=0.5))

        # Calculate blocker's endpoint from route steps
        start_pos = np.array(blocker.get_center(), dtype=float).copy()
        current_pos = start_pos.copy()
        step_positions = [current_pos.copy()]

        for step in route_data.get("steps", []):
            dx = step.get("right", 0) - step.get("left", 0)
            dy = step.get("up", 0) - step.get("down", 0)
            new_pos = current_pos + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
            step_positions.append(new_pos.copy())
            current_pos = new_pos

        endpoint = current_pos.copy()

        # Create blocking indicators for each defender and dotted lines
        blocking_indicators = VGroup()
        blocking_dotted_lines = VGroup()

        for defender in defenders:
            indicator = self.create_blocking_indicator(defender.get_center())
            blocking_indicators.add(indicator)

            # Blue dotted line from blocker to endpoint
            dotted_line = self.create_blocking_dotted_line(blocker.get_center(), endpoint)
            blocking_dotted_lines.add(dotted_line)

        self.play(Create(blocking_indicators, run_time=0.5))

        if len(blocking_dotted_lines) > 0:
            self.play(LaggedStart(*[Create(line) for line in blocking_dotted_lines], run_time=1))

        # Create blocker's route path
        if len(step_positions) >= 2:
            route_path = self.create_route_path(step_positions, route_data.get("route_style", "sharp"))
            route_path.set_color(route_data.get("color", "#6A0572"))

            # Protection indicator at end
            protection_indicator = self.create_protection_indicator(step_positions)

            # Defender paths (if requested)
            defender_paths = VGroup()
            defender_path_data = blocking_assignment.get("defender_path")
            draw_defender_path = blocking_assignment.get("draw_defender_path", False)

            if draw_defender_path and defender_path_data:
                for defender in defenders:
                    # Calculate defender's path points from its current position using steps
                    def_steps = defender_path_data.get("steps", [])
                    def_start = np.array(defender.get_center(), dtype=float).copy()
                    def_current = def_start.copy()
                    def_points = [def_current.copy()]

                    for step in def_steps:
                        dx = step.get("right", 0) - step.get("left", 0)
                        dy = step.get("up", 0) - step.get("down", 0)
                        new_pos = def_current + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
                        def_points.append(new_pos.copy())
                        def_current = new_pos

                    # Create path for defender (use same style as blocker or "sharp")
                    if len(def_points) >= 2:
                        def_route_style = defender_path_data.get("route_style", "sharp")
                        def_path = self.create_route_path(def_points, def_route_style)
                        def_path.set_color("#000080")  # Navy blue for defender
                        def_path.set_stroke(width=4)
                        defender_paths.add(def_path)

            clash_effects = []

            # Animate blocker and defenders
            self.play(Create(route_path, run_time=1))
            self.play(
                MoveAlongPath(blocker, route_path, run_time=2),
                LaggedStart(*[MoveAlongPath(defender, Line(defender.get_center(), endpoint, color="#000080", stroke_width=4))
                            for defender in defenders], lag_ratio=0.1),
            )
            self.play(Create(protection_indicator, run_time=0.3))

            # Clash effect and tackle sound
            clash_effect = self.create_clash_effect(endpoint)
            clash_effects.append(clash_effect)
            if clash_effects:
                self.play(LaggedStart(*[GrowFromCenter(effect) for effect in clash_effects], lag_ratio=0.05), run_time=1)
                self.play_tackle_sound()

        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)

        # Clean up all elements
        fade_outs = [
            FadeOut(assignment_text, run_time=0.5),
            FadeOut(blocking_indicators, run_time=0.5)
        ]

        if 'route_path' in locals():
            fade_outs.append(FadeOut(route_path, run_time=0.5))
        if 'protection_indicator' in locals():
            fade_outs.append(FadeOut(protection_indicator, run_time=0.5))
        if 'defender_paths' in locals() and len(defender_paths) > 0:
            fade_outs.append(FadeOut(defender_paths, run_time=0.5))
        if 'clash_effects' in locals() and len(clash_effects) > 0:
            fade_outs.append(FadeOut(*clash_effects, run_time=0.5))
        if len(blocking_dotted_lines) > 0:
            fade_outs.append(FadeOut(blocking_dotted_lines, run_time=0.5))

        self.play(*fade_outs)


    def player_route_animation(self, players, segment_name, audio_duration):
        # NEW: Extract player position by reading from the right side
        if segment_name.endswith('_route'):
            # Remove '_route' from the end to get player position
            player_pos = segment_name[:-6]  # Remove 6 characters: '_route'
        else:
            # If it doesn't end with '_route', use the segment name as-is
            player_pos = segment_name

        print(f"DEBUG: Processing route for player: '{player_pos}', segment: '{segment_name}'")
        
        # Get the player object - FIXED: Proper handling of all player types
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
        elif player_pos == "fb":  # FIX: Add FB route handling
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
        
        # FIXED: Play protection sound for ALL route types that are protection, not just WR routes
        route_type = route_data.get("type", "")
        if route_type == "protection":
            self.play_protection_sound()
            print(f"DEBUG: Playing protection sound for {player_pos} (route type: {route_type})")
        elif route_type in ["square_in", "post", "flag", "flat", "corner", "drag", "panther", "spot"]:
            self.play_chase_sound()
        elif route_type == "route":  # Run routes
            self.play_chase_sound()
        
        # FIXED: ALWAYS use player's CURRENT center for route calculation to ensure consistency
        start_pos = np.array(player.get_center(), dtype=float).copy()
        current_pos = start_pos.copy()
        step_positions = [current_pos.copy()]
        
        # Process steps to create the complete path
        steps = route_data.get("steps", [])
        for step in steps:
            dx = step.get("right", 0) - step.get("left", 0)
            dy = step.get("up", 0) - step.get("down", 0)
            new_pos = current_pos + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
            step_positions.append(new_pos.copy())
            current_pos = new_pos
        
        # FIXED: IMPROVED CURVED PATH DETECTION - Use ArcBetweenPoints for better curved paths
        path_segments = []
        curved_segments = []
        
        # First, let's check if we have enough points for any curved segments
        if len(step_positions) >= 3:  # Need at least 3 points for a curved segment
            i = 0
            while i < len(steps):
                current_step = steps[i]
                step_style = current_step.get("style", route_data.get("route_style", "curved"))
                
                if step_style in ["curved", "smooth"] and i + 1 < len(steps):
                    # Check if next step is also curved
                    next_step_style = steps[i + 1].get("style", route_data.get("route_style", "curved"))
                    if next_step_style in ["curved", "smooth"]:
                        # We have at least 2 consecutive curved steps (3 points)
                        # Create an arc through these 3 points
                        p0 = step_positions[i]
                        p1 = step_positions[i + 1] 
                        p2 = step_positions[i + 2]
                        
                        # Create a quadratic bezier through these points for a smooth curve
                        # Use ArcBetweenPoints for better visual curve
                        curved_path = ArcBetweenPoints(p0, p2, angle=0.5)
                        curved_path.set_color(route_data.get("color", WHITE))
                        curved_path.set_stroke(width=4)
                        
                        curved_segments.append({
                            'path': curved_path,
                            'start_idx': i,
                            'end_idx': i + 1,  # Covers 2 steps
                            'points': [p0, p1, p2]
                        })
                        
                        # Skip the next step since we covered it
                        i += 2
                        continue
                
                # If we didn't create a curved segment, create a regular segment
                start_segment = step_positions[i]
                end_segment = step_positions[i + 1]
                step_style = steps[i].get("style", route_data.get("route_style", "curved"))
                
                if step_style in ["curved", "smooth"]:
                    # Single curved step - use arc
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
                i += 1
        else:
            # Not enough points for curved segments, create regular segments
            for i in range(len(steps)):
                start_segment = step_positions[i]
                end_segment = step_positions[i + 1]
                step_style = steps[i].get("style", route_data.get("route_style", "curved"))
                
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
        
        # FIXED: Create a mapping of which steps are covered by curved segments
        curved_coverage = set()
        for curved_seg in curved_segments:
            curved_coverage.add(curved_seg['start_idx'])
            curved_coverage.add(curved_seg['end_idx'])
        
        # FIXED: Create individual segments for steps not covered by curved segments
        individual_segments = []
        for i in range(len(steps)):
            if i not in curved_coverage:
                start_segment = step_positions[i]
                end_segment = step_positions[i + 1]
                step_style = steps[i].get("style", route_data.get("route_style", "curved"))
                
                if step_style in ["curved", "smooth"]:
                    # Single curved step - use arc
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
                individual_segments.append(segment)
        
        # FIXED ISSUE 1: Use ONLY route type for protection detection, not route_style
        # Create appropriate end marker based on route type - FIXED CONDITION
        route_end_marker = None
        if len(step_positions) >= 2:
            last_point = step_positions[-1]
            second_last_point = step_positions[-2]
            vec = np.array(last_point) - np.array(second_last_point)
            vec2 = vec.copy()
            length = np.linalg.norm(vec2[:2])
            if length != 0:
                direction = vec2 / length
            else:
                direction = np.array([0, 1, 0])
            
            # FIX: Only check route type, not route_style for protection
            if route_data.get("type") == "protection":
                # Use perpendicular protection indicator ONLY for protection type
                route_end_marker = self.create_protection_indicator(step_positions)
            else:
                # Regular arrow end marker for all other routes
                arrow_tip = Triangle(fill_opacity=1, stroke_width=0, color=route_data.get("color", WHITE))
                arrow_tip.set_height(0.3)
                arrow_tip.rotate(np.arctan2(direction[1], direction[0]) - PI/2)
                arrow_tip.move_to(last_point + direction * 0.2)
                route_end_marker = arrow_tip
        
        # Create route label if present
        route_label = Text(route_data.get("label", ""), font_size=20, color=route_data.get("color", WHITE), weight=BOLD)
        route_label.next_to(player, UP)
        
        # Handle secondary options (dashed) in same coordinate frame - UPDATED: Added style detection
        secondary_paths = VGroup()
        secondary_markers = VGroup()
        if "secondary_options" in route_data:
            for secondary in route_data["secondary_options"]:
                branch_point = secondary.get("branch_point", 0)
                if branch_point < len(step_positions):
                    sec_start = np.array(step_positions[branch_point], dtype=float).copy()
                    sec_current = sec_start.copy()
                    sec_points = [sec_current]
                    
                    for step in secondary.get("steps", []):
                        dx = step.get("right", 0) - step.get("left", 0)
                        dy = step.get("up", 0) - step.get("down", 0)
                        sec_current = sec_current + np.array([dx * self.yard_scale, dy * self.yard_scale * 1.5, 0])
                        sec_points.append(sec_current.copy())
                    
                    # Determine the secondary route style based on majority of steps - NEW
                    if len(secondary.get("steps", [])) > 0:
                        sharp_steps = 0
                        curved_steps = 0
                        
                        for step in secondary.get("steps", []):
                            step_style = step.get("style", secondary.get("route_style", "curved"))
                            if step_style in ["sharp", "block", "panther"]:
                                sharp_steps += 1
                            else:
                                curved_steps += 1
                        
                        # Determine majority style
                        if sharp_steps > curved_steps:
                            secondary_route_style = "sharp"
                        else:
                            secondary_route_style = "curved"
                    else:
                        secondary_route_style = secondary.get("route_style", "curved")
                    
                    # Create dashed secondary path
                    if len(sec_points) == 2:
                        sec_path = DashedLine(sec_points[0], sec_points[1], color=secondary.get("color", YELLOW), stroke_width=3, dash_length=0.2)
                    else:
                        sec_path = self.create_route_path(sec_points, secondary_route_style, secondary.get("sharp_turn_points", []))
                        sec_path.set_color(secondary.get("color", YELLOW))
                        sec_path.set_stroke(width=3, opacity=0.8)
                        from manim import DashedVMobject
                        sec_path = DashedVMobject(sec_path, num_dashes=20)
                    
                    secondary_paths.add(sec_path)
                    
                    # FIXED ISSUE 1: Apply same protection logic to secondary routes
                    # Add end marker for secondary
                    if len(sec_points) >= 2:
                        s_last = sec_points[-1]
                        s_prev = sec_points[-2]
                        s_vec = s_last - s_prev
                        s_len = np.linalg.norm(s_vec[:2])
                        if s_len != 0:
                            s_dir = s_vec / s_len
                        else:
                            s_dir = np.array([0, 1, 0])
                        
                        # FIX: Apply same protection logic to secondary routes
                        if route_data.get("type") == "protection":
                            # Use protection indicator for secondary routes of protection type
                            sec_protection_marker = self.create_protection_indicator(sec_points)
                            secondary_markers.add(sec_protection_marker)
                        else:
                            s_arrow = Triangle(fill_opacity=1, stroke_width=0, color=secondary.get("color", YELLOW))
                            s_arrow.set_height(0.25)
                            s_arrow.rotate(np.arctan2(s_dir[1], s_dir[0]) - PI/2)
                            s_arrow.move_to(s_last + s_dir * 0.2)
                            secondary_markers.add(s_arrow)
        
        # Start route animation
        start_time = time.time()
        
        # Show route label first
        self.play(Write(route_label, run_time=0.5))
        
        # DEBUG: Print what we found
        print(f"DEBUG: Found {len(curved_segments)} curved segments and {len(individual_segments)} individual segments")
        
        # FIXED: IMPROVED ANIMATION - Handle curved segments and individual segments separately
        # First animate curved segments (if any)
        if curved_segments:
            for curved_seg in curved_segments:
                print(f"DEBUG: Animating curved segment from {curved_seg['start_idx']} to {curved_seg['end_idx']}")
                # Draw the curved path
                self.play(Create(curved_seg['path'], run_time=0.7))
                
                # Animate player along curved path
                self.play(MoveAlongPath(player, curved_seg['path'], run_time=2.0))
        
        # Then animate individual segments
        if individual_segments:
            segment_draw_time = 0.5 / len(individual_segments) if individual_segments else 0
            segment_move_time = 3.0 / len(individual_segments) if individual_segments else 0
            
            for i, segment in enumerate(individual_segments):
                # Draw the current segment
                self.play(Create(segment, run_time=segment_draw_time))
                
                # Move player along this segment
                if not segment.has_no_points():
                    self.play(MoveAlongPath(player, segment, run_time=segment_move_time))
                else:
                    # Fallback: move directly to end of segment
                    end_pos = step_positions[i + 1]
                    self.play(player.animate.move_to(end_pos), run_time=segment_move_time)
        
        # Draw secondary paths after main route is complete
        if len(secondary_paths) > 0:
            self.play(Create(secondary_paths, run_time=0.5))
            if len(secondary_markers) > 0:
                self.play(GrowFromCenter(secondary_markers, run_time=0.3))
        
        # FIXED ISSUE 2: Show the end marker ONLY ONCE at the very end after all segments
        # Show the appropriate end marker
        if route_end_marker:
            if route_data.get("type") == "protection":
                # Protection line: create (no grow)
                self.play(Create(route_end_marker, run_time=0.3))
            else:
                self.play(GrowFromCenter(route_end_marker, run_time=0.3))
        
        elapsed = time.time() - start_time
        
        # NEW: Wait for original audio duration + 0.5 seconds before playing video
        # Find the segment to get original_audio_duration
        original_audio_duration = 0
        for segment in self.audio_durations['segments']:
            if segment['name'] == segment_name:
                original_audio_duration = segment.get('original_audio_duration', 0)
                break
        
        if original_audio_duration > 0:
            # Calculate how much time we need to wait for the original audio to finish
            time_to_wait = original_audio_duration - elapsed
            if time_to_wait > 0:
                self.wait(time_to_wait)
            
            # Wait additional 0.5 seconds
            self.wait(0.5)
            
            # Calculate remaining time for video
            video_remaining = audio_duration - (elapsed + time_to_wait + 0.5)
        else:
            # Fallback to old method if no original_audio_duration
            self.wait(2)
            elapsed += 2
            video_remaining = max(0, audio_duration - elapsed)
        
        # Play side video if available and we have remaining time
        if video_remaining > 0 and "type" in route_data:
            route_type = route_data["type"]
            # Video files in shared_assets/route_animator/ (prefer 720p60, then 2160p60, then 480p15)
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
            # Check in order: 720p60, 2160p60, 480p15
            if os.path.exists(video_path_720p):
                video_path = os.path.normpath(video_path_720p)
            elif os.path.exists(video_path_2160p):
                video_path = os.path.normpath(video_path_2160p)
            else:
                video_path = os.path.normpath(video_path_480p)
            
            if os.path.exists(video_path):
                try:
                    route_video = VideoMobject(filename=video_path, speed=1.0, loop=True if video_remaining > 10 else False)
                    
                    # Scale video to cover 70% of screen with 15% margins on all sides
                    screen_width = config.frame_width
                    screen_height = config.frame_height
                    
                    # Target size is 70% of screen dimensions
                    target_width = screen_width * 0.7
                    target_height = screen_height * 0.7
                    
                    # Scale the video to fit within the target dimensions while maintaining aspect ratio
                    route_video.set_width(target_width)
                    if route_video.height > target_height:
                        route_video.set_height(target_height)
                    
                    # Center the video on screen
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
        
        # Cleanup - fade out everything
        fade_outs = [FadeOut(route_label, run_time=0.5)]
        
        # Fade out all curved segments
        for curved_seg in curved_segments:
            fade_outs.append(FadeOut(curved_seg['path'], run_time=0.5))
        
        # Fade out all individual segments
        for segment in individual_segments:
            fade_outs.append(FadeOut(segment, run_time=0.5))
        
        if route_end_marker:
            fade_outs.append(FadeOut(route_end_marker, run_time=0.5))
        if len(secondary_paths) > 0:
            fade_outs.append(FadeOut(secondary_paths, run_time=0.5))
        if len(secondary_markers) > 0:
            fade_outs.append(FadeOut(secondary_markers, run_time=0.5))
        
        self.play(*fade_outs)

    def qb_dropback_animation(self, players, audio_duration):
        """NEW: Simple QB dropback animation for pass protection plays"""
        start_time = time.time()
        
        # Create dropback text
        dropback_text = Text("QB Dropback", font_size=28, color=BLUE, weight=BOLD)
        dropback_text.to_edge(UP)
        
        self.play(Write(dropback_text, run_time=0.5))
        
        # Get QB and football
        qb = players["qb"]
        football = players["football"]
        
        # Calculate dropback steps (simple 5-step drop)
        start_pos = np.array(qb.get_center(), dtype=float).copy()
        dropback_distance = 7 * self.yard_scale  # 7 yards dropback
        
        # Create dropback path
        dropback_path = Line(
            start_pos,
            start_pos + np.array([0, -dropback_distance, 0]),
            color=BLUE,
            stroke_width=4
        )
        
        # Animate QB dropback
        self.play(Create(dropback_path, run_time=1))
        self.play(
            MoveAlongPath(qb, dropback_path, run_time=2),
            MoveAlongPath(football, dropback_path, run_time=2)
        )
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        self.play(
            FadeOut(dropback_text, run_time=0.5),
            FadeOut(dropback_path, run_time=0.5)
        )

    def qb_read_animation(self, players, segment_name, audio_duration):
        # FIXED: Use direct mapping from segment name to read progression
        # Create a mapping from segment name suffix to player position
        read_target_mapping = {
            "z": "wr_z",
            "te": "te", 
            "x": "wr_x"
        }
        
        # Extract the read target from segment name (e.g. "qb_read_z" -> "z")
        read_target = segment_name.split('_')[-1]
        
        # Get the player position from mapping
        player_pos = read_target_mapping.get(read_target)
        
        if not player_pos:
            print(f"DEBUG: Unknown read target: {read_target}")
            return
        
        # Find the corresponding read in progression
        target_read = None
        read_progression = self.animation_data.get("read_progression", [])
        
        for read in read_progression:
            if read.get("player") == player_pos:
                target_read = read
                break
        
        if not target_read:
            print(f"DEBUG: No read progression found for player: {player_pos}")
            return
        
        # Map JSON player keys to players dictionary keys - ROBUST HANDLING
        player_key_mapping = {
            "wr_x": "x_wr",
            "wr_z": "z_wr",
            "te": "te",
            "rb": "rb",
            "fb": "fb"
        }
        
        player_key = player_key_mapping.get(player_pos, player_pos)
        
        if player_key not in players or len(players[player_key]) == 0:
            print(f"DEBUG: Player key '{player_key}' not found in players dictionary")
            return
            
        target = players[player_key]
        color = target_read.get("color", WHITE)

        # ENHANCED: Sharper visuals with better stroke widths
        arrow = Arrow(
            players["qb"].get_center(), target.get_center(),
            color=color, buff=0.2, stroke_width=6,
            max_tip_length_to_length_ratio=0.2,
            stroke_opacity=0.9
        )

        # ENHANCED: Better QB range circle visibility
        qb_range = Circle(
            radius=players["qb"][0].radius * 25,
            color=color,
            stroke_width=4,
            fill_opacity=0.25,
            stroke_opacity=0.8
        )
        qb_range.move_to(players["qb"].get_center())

        # ENHANCED: Sharper target circle
        circle = Circle(radius=target[0].radius*1.2, color=color, stroke_width=4)
        circle.move_to(target.get_center())

        start_time = time.time()
        # Add QB Reads heading
        qb_reads_text = Text("QB Reads", font_size=32, color=WHITE, weight=BOLD)
        qb_reads_text.to_edge(UP)
        
        # FIX: Removed duplicate animation calls
        self.play(
            Write(qb_reads_text, run_time=0.3),
            Create(arrow, run_time=0.3),
            Create(qb_range, run_time=0.3),
            Create(circle, run_time=0.3)
        )

        # ENHANCED: Faster pulsing effect
        self.play(
            circle.animate.scale(1.2).set_stroke(opacity=0.8),
            run_time=0.3
        )
        self.play(
            circle.animate.scale(1/1.2).set_stroke(opacity=1),
            run_time=0.3
        )

        elapsed = time.time() - start_time

        # ENHANCED: More accurate timing calculation
        remaining = max(0, audio_duration - elapsed)

        # ENHANCED: Add visual indication if we need to wait
        if remaining > 0:
            self.wait(remaining)

        # ENHANCED: Faster fade out
        self.play(
            FadeOut(arrow, run_time=0.2),
            FadeOut(qb_range, run_time=0.2),
            FadeOut(circle, run_time=0.2),
            FadeOut(qb_reads_text, run_time=0.2)  # FIX: Also fade out the QB Reads text
        )

    def run_options_animation(self, players, option_type, audio_duration):
        """Animation for run options (primary run lanes) - FIXED VERSION"""
        run_lanes = self.animation_data.get("run_lanes", {})
        
        # Map JSON player keys to players dictionary keys - ROBUST HANDLING
        player_key_mapping = {
            "wr_x": "x_wr",
            "wr_z": "z_wr", 
            "te": "te",
            "rb": "rb",
            "fb": "fb"
        }
        
        if option_type == "primary":
            # Highlight primary run lanes from JSON
            targets = []
            target_keys = []
            for json_player_key in run_lanes.get("primary", []):
                # Map to players dictionary key
                player_key = player_key_mapping.get(json_player_key, json_player_key)
                if player_key in players and len(players[player_key]) > 0:
                    targets.append(players[player_key])
                    target_keys.append(player_key)
            color = "#FF6B6B"  # Reddish color for primary
            label = "Primary Run Option"
        else:
            return
        
        circles = VGroup()
        dashed_lines = VGroup()  # NEW: Group for all dashed lines
        
        for target, target_key in zip(targets, target_keys):
            # ENHANCED: Better circle visibility
            area = Circle(
                radius=target[0].radius * 3,
                color=color,
                stroke_width=3,
                fill_opacity=0.2,
                stroke_opacity=0.9
            )
            area.move_to(target.get_center())
            circles.add(area)
            
            # NEW: Create dashed line from QB to each target
            if "qb" in players and len(players["qb"]) > 0:
                dashed_line = DashedLine(
                    players["qb"].get_center(),
                    target.get_center(),
                    color=color,
                    stroke_width=4,
                    dash_length=0.3
                )
                dashed_lines.add(dashed_line)
        
        # ENHANCED: Better text visibility
        option_text = Text(label, font_size=26, color=color, weight=BOLD)
        option_text.to_edge(UP)
        
        start_time = time.time()
        
        # FIXED: Check if there are circles before creating LaggedStart
        animations = []
        
        # Add dashed lines animation if there are any
        if len(dashed_lines) > 0:
            line_animations = [Create(line) for line in dashed_lines]
            animations.append(LaggedStart(*line_animations, run_time=0.7))
        
        if len(circles) > 0:
            circle_animations = [Create(circle) for circle in circles]
            animations.append(LaggedStart(*circle_animations, run_time=0.7))
        
        # Always add the text animation
        animations.append(Write(option_text, run_time=0.7))
        
        # Play animations if we have any
        if animations:
            self.play(*animations)
        
        # ENHANCED: Faster pulsing - only if we have circles
        if len(circles) > 0:
            self.play(
                circles.animate.scale(1.1).set_stroke(opacity=0.8).set_fill(opacity=0.25),
                dashed_lines.animate.set_stroke(opacity=0.8),  # Also pulse dashed lines
                run_time=0.3
            )
            self.play(
                circles.animate.scale(1/1.1).set_stroke(opacity=0.9).set_fill(opacity=0.2),
                dashed_lines.animate.set_stroke(opacity=1.0),  # Reset dashed lines opacity
                run_time=0.3
            )
        
        elapsed = time.time() - start_time
        
        # ENHANCED: More accurate timing
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        # ENHANCED: Faster cleanup
        fade_outs = [FadeOut(option_text, run_time=0.3)]
        if len(circles) > 0:
            fade_outs.append(FadeOut(circles, run_time=0.3))
        if len(dashed_lines) > 0:
            fade_outs.append(FadeOut(dashed_lines, run_time=0.3))
        
        self.play(*fade_outs)

    def handoff_animation(self, players, audio_duration):
        """Animation for QB to RB handoff in run plays"""
        start_time = time.time()
        
        # Create handoff text
        handoff_text = Text("QB-RB Handoff", font_size=28, color=GREEN, weight=BOLD)
        handoff_text.to_edge(UP)
        
        self.play(Write(handoff_text, run_time=0.5))
        
        # Get QB and RB positions
        qb = players["qb"]
        rb = players["rb"]
        football = players["football"]
        
        # Create handoff path - arc from QB to RB
        handoff_path = ArcBetweenPoints(
            qb.get_center(),
            rb.get_center(),
            angle=-TAU/8
        )
        handoff_path.set_stroke(color=GREEN, width=4)
        
        # Animate football handoff
        self.play(
            Create(handoff_path, run_time=1),
            MoveAlongPath(football, handoff_path, run_time=1.5)
        )
        
        # Show RB with possession (highlight)
        rb_highlight = Circle(radius=rb[0].radius*1.3, color=GREEN, stroke_width=4)
        rb_highlight.move_to(rb.get_center())
        
        self.play(Create(rb_highlight, run_time=0.3))
        self.play(FadeOut(rb_highlight, run_time=0.3))
        
        elapsed = time.time() - start_time
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        self.play(
            FadeOut(handoff_text, run_time=0.5),
            FadeOut(handoff_path, run_time=0.5)
        )

    def passing_options_animation(self, players, segment_name, audio_duration):
        """Animation for passing options - FIXED VERSION"""
        passing_options = self.animation_data.get("passing_options", {})
        
        # FIXED: Map JSON player keys to players dictionary keys - ROBUST HANDLING
        player_key_mapping = {
            "wr_x": "x_wr",
            "wr_z": "z_wr", 
            "te": "te",
            "rb": "rb",
            "fb": "fb"
        }
        
        if "primary" in segment_name:
            # Highlight primary receivers from JSON
            targets = []
            target_keys = []
            for json_player_key in passing_options.get("primary", []):
                # Map to players dictionary key
                player_key = player_key_mapping.get(json_player_key, json_player_key)
                if player_key in players and len(players[player_key]) > 0:
                    targets.append(players[player_key])
                    target_keys.append(player_key)
            color = "#FF6B6B"  # Reddish color for primary
            label = "Primary Targets"
        else:
            # Highlight checkdown receivers from JSON
            targets = []
            target_keys = []
            for json_player_key in passing_options.get("checkdowns", []):
                # Map to players dictionary key
                player_key = player_key_mapping.get(json_player_key, json_player_key)
                if player_key in players and len(players[player_key]) > 0:
                    targets.append(players[player_key])
                    target_keys.append(player_key)
            color = "#4ECDC4"  # Teal color for checkdowns
            label = "Checkdown Options"
        
        circles = VGroup()
        dashed_lines = VGroup()  # NEW: Group for all dashed lines
        
        for target, target_key in zip(targets, target_keys):
            # ENHANCED: Better circle visibility
            area = Circle(
                radius=target[0].radius * 3,
                color=color,
                stroke_width=3,
                fill_opacity=0.2,
                stroke_opacity=0.9
            )
            area.move_to(target.get_center())
            circles.add(area)
            
            # NEW: Create dashed line from QB to each target
            if "qb" in players and len(players["qb"]) > 0:
                dashed_line = DashedLine(
                    players["qb"].get_center(),
                    target.get_center(),
                    color=color,
                    stroke_width=4,
                    dash_length=0.3
                )
                dashed_lines.add(dashed_line)
        
        # ENHANCED: Better text visibility
        option_text = Text(label, font_size=26, color=color, weight=BOLD)
        option_text.to_edge(UP)
        
        start_time = time.time()
        
        # FIXED: Check if there are circles before creating LaggedStart
        animations = []
        
        # Add dashed lines animation if there are any
        if len(dashed_lines) > 0:
            line_animations = [Create(line) for line in dashed_lines]
            animations.append(LaggedStart(*line_animations, run_time=0.7))
        
        if len(circles) > 0:
            circle_animations = [Create(circle) for circle in circles]
            animations.append(LaggedStart(*circle_animations, run_time=0.7))
        
        # Always add the text animation
        animations.append(Write(option_text, run_time=0.7))
        
        # Play animations if we have any
        if animations:
            self.play(*animations)
        
        # ENHANCED: Faster pulsing - only if we have circles
        if len(circles) > 0:
            self.play(
                circles.animate.scale(1.1).set_stroke(opacity=0.8).set_fill(opacity=0.25),
                dashed_lines.animate.set_stroke(opacity=0.8),  # Also pulse dashed lines
                run_time=0.3
            )
            self.play(
                circles.animate.scale(1/1.1).set_stroke(opacity=0.9).set_fill(opacity=0.2),
                dashed_lines.animate.set_stroke(opacity=1.0),  # Reset dashed lines opacity
                run_time=0.3
            )
        
        elapsed = time.time() - start_time
        
        # ENHANCED: More accurate timing
        remaining = max(0, audio_duration - elapsed)
        if remaining > 0:
            self.wait(remaining)
        
        # ENHANCED: Faster cleanup
        fade_outs = [FadeOut(option_text, run_time=0.3)]
        if len(circles) > 0:
            fade_outs.append(FadeOut(circles, run_time=0.3))
        if len(dashed_lines) > 0:
            fade_outs.append(FadeOut(dashed_lines, run_time=0.3))
        
        self.play(*fade_outs)