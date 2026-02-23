from manim import *
import json
import os

class PlayerPlottingScene(Scene):
    def construct(self):
        # Configuration variables
        steps_ahead = 0.2
        line_thickness = 2
        path_thickness = 3
        text_display_distance = 0.3

        # ── READ JSON PATH FROM ENVIRONMENT (injected by server.py) ──────────────
        json_path = os.environ.get(
            "PLAYBOOK_JSON_PATH",
            "/Users/prathmeshgawali/sam3-demo/json/playbookscript.json"   # fallback for manual runs
        )

        with open(json_path, 'r') as f:
            data = json.load(f)

        # ── DIMENSIONS ────────────────────────────────────────────────────────────
        # Support both "imageDimensions" (React) and "image_dimensions" (legacy)
        dims = data.get("imageDimensions") or data.get("image_dimensions", {})
        json_width  = dims["width"]
        json_height = dims["height"]

        self.camera.frame_width  = json_width  / 100
        self.camera.frame_height = json_height / 100

        # ── WHITE BACKGROUND ──────────────────────────────────────────────────────
        white_rect = Rectangle(
            width=self.camera.frame_width,
            height=self.camera.frame_height,
            color=WHITE, fill_color=WHITE, fill_opacity=1, stroke_width=0
        )
        self.add(white_rect)

        # ── COORDINATE CONVERSION ─────────────────────────────────────────────────
        def json_to_manim_coords(x, y):
            x_manim = (x - json_width  / 2) / 100
            y_manim = -(y - json_height / 2) / 100
            return np.array([x_manim, y_manim, 0])

        # ── AFTERIMAGE ────────────────────────────────────────────────────────────
        def create_grey_afterimage(player_group, position):
            afterimage = player_group.copy()
            for i, mobject in enumerate(afterimage):
                if isinstance(mobject, (Circle, Square)):
                    if i == 0:
                        mobject.set_fill(color="#CCCCCC", opacity=0.8)
                        mobject.set_stroke(color="#CCCCCC", width=0)
                    elif i == 1:
                        mobject.set_fill(color="#666666", opacity=0.8)
                        mobject.set_stroke(color="#666666", width=0)
                elif isinstance(mobject, Text):
                    mobject.set_color(WHITE)
                    mobject.set_opacity(0.9)
            afterimage.move_to(position)
            return afterimage

        # ── TEXT LABEL ────────────────────────────────────────────────────────────
        def create_path_text_label(text_info, manim_coords, text_type="generic"):
            label = text_info.get("label", "")
            if not label:
                return None
            text_label = Text(label.upper(), font_size=12, color=BLACK, weight=BOLD)
            text_label.move_to(manim_coords)
            text_label.set_z_index(5)
            return text_label

        # ── FIND TEXT DISPLAY TIME ────────────────────────────────────────────────
        def find_text_display_time(text_pos, path_points, total_time):
            if not path_points or len(path_points) < 2:
                return 0.5
            distances = [np.linalg.norm(text_pos[:2] - p[:2]) for p in path_points]
            min_idx = np.argmin(distances)
            if len(path_points) == 2:
                return 0.5
            return min_idx / (len(path_points) - 1)

        # ── COLLECT PLAYERS ───────────────────────────────────────────────────────
        square_player_center = None
        square_player_id     = None
        players_dict         = {}
        all_paths            = VGroup()
        afterimages          = VGroup()
        all_path_texts       = VGroup()

        for player_data in data["players"]:
            center_x = player_data["center"]["x"]
            center_y = player_data["center"]["y"]
            manim_center  = json_to_manim_coords(center_x, center_y)
            display_label = player_data.get("display_label")
            player_type   = player_data["type"]
            base_size     = 0.18

            if player_type == "circle":
                outer_shape = Circle(radius=base_size, color=BLACK)
                outer_shape.set_fill(color=BLACK, opacity=1)
                outer_shape.set_stroke(color=BLACK, width=0)
                inner_shape = Circle(radius=base_size * 0.75, color=WHITE)
                inner_shape.set_fill(color=WHITE, opacity=1)
                inner_shape.set_stroke(color=WHITE, width=0)
                player_group = VGroup(outer_shape, inner_shape)
                player_group.move_to(manim_center)

            elif player_type == "square":
                side_length = base_size * 2
                outer_shape = Square(side_length=side_length, color=BLACK)
                outer_shape.set_fill(color=BLACK, opacity=1)
                outer_shape.set_stroke(color=BLACK, width=0)
                inner_shape = Square(side_length=side_length * 0.75, color=WHITE)
                inner_shape.set_fill(color=WHITE, opacity=1)
                inner_shape.set_stroke(color=WHITE, width=0)
                player_group = VGroup(outer_shape, inner_shape)
                player_group.move_to(manim_center)
                square_player_center = manim_center
                square_player_id     = player_data.get("player_id")
            else:
                print(f"DEBUG: Unknown player type: {player_type}, skipping")
                continue

            if display_label:
                label_text = Text(display_label, font_size=15, color=BLACK, weight=BOLD)
                label_text.move_to(manim_center)
                max_width  = inner_shape.width  * 0.6
                max_height = inner_shape.height * 0.6
                if label_text.width  > max_width:
                    label_text.scale_to_fit_width(max_width)
                if label_text.height > max_height:
                    label_text.scale_to_fit_height(max_height)
                player_group.add(label_text)

            self.add(player_group)
            player_group.original_position = np.array(player_group.get_center(), dtype=float)

            player_id = player_data["player_id"]
            players_dict[player_id] = {
                "group":             player_group,
                "type":              player_type,
                "data":              player_data,
                "original_position": manim_center.copy(),
                "display_label":     display_label,
            }

        # ── SCRIMMAGE LINE ────────────────────────────────────────────────────────
        if square_player_center is not None:
            scrimmage_y = square_player_center[1] + steps_ahead
            left_x  = -self.camera.frame_width  / 2
            right_x =  self.camera.frame_width  / 2
            scrimmage_line = Line(
                start=[left_x, scrimmage_y, 0],
                end=[right_x,  scrimmage_y, 0],
                color=GREY, stroke_width=line_thickness
            )
            self.add(scrimmage_line)

        self.wait(1)

        # ── ANIMATE ROUTES ────────────────────────────────────────────────────────
        for player_id, player_info in players_dict.items():
            player_data = player_info["data"]

            if not (player_data.get("has_primary_routes") and player_data.get("primary_routes")):
                continue

            route = player_data["primary_routes"][0]
            mask_points = route.get("mask_points", [])

            if not mask_points or len(mask_points) < 2:
                continue

            player_group    = player_info["group"]
            original_position = player_info["original_position"]

            manim_points = [
                json_to_manim_coords(p[0], p[1])
                for p in mask_points
                if isinstance(p, list) and len(p) >= 2
            ]

            if len(manim_points) < 2:
                continue

            # Afterimage at original spot
            afterimage = create_grey_afterimage(player_group, original_position)
            self.add(afterimage)
            afterimages.add(afterimage)

            # Path
            path = VMobject()
            path.set_points_smoothly(manim_points)
            path.set_stroke(color=BLACK, width=path_thickness, opacity=1.0)
            display_path = path.copy()

            # Animation duration
            path_length = sum(
                np.linalg.norm(manim_points[i+1] - manim_points[i])
                for i in range(len(manim_points) - 1)
            )
            animation_time = min(2.0 + path_length * 0.5, 5.0)

            player_group.set_z_index(10)

            # Text
            player_text_animations = []
            path_text_animations   = []

            if player_data.get("has_associated_text") and player_data.get("associated_text"):
                for text_info in player_data["associated_text"]:
                    tx = text_info["position"]["x"]
                    ty = text_info["position"]["y"]
                    text_pos   = json_to_manim_coords(tx, ty)
                    text_label = create_path_text_label(text_info, text_pos)
                    if not text_label:
                        continue
                    text_label.set_opacity(0)
                    self.add(text_label)
                    all_path_texts.add(text_label)
                    anim = text_label.animate.set_opacity(1).set_z_index(5)
                    assoc = text_info.get("association_type", "unknown")
                    if assoc == "player":
                        player_text_animations.append(anim)
                    else:
                        t = find_text_display_time(text_pos, manim_points, animation_time) * animation_time
                        path_text_animations.append((t, anim))

            if player_text_animations:
                self.play(*player_text_animations)

            self.play(
                MoveAlongPath(player_group, display_path, run_time=animation_time),
                Create(display_path, run_time=animation_time),
                rate_func=linear
            )

            for t_sec, anim in path_text_animations:
                current_time = self.renderer.time
                if t_sec > current_time:
                    self.wait(t_sec - current_time)
                self.play(anim)

            player_group.set_z_index(10)
            all_paths.add(display_path)
            self.wait(0.5)

        for player_info in players_dict.values():
            player_info["group"].set_z_index(10)

        self.wait(5)