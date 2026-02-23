from manim import *
import json
import os

class PlayerPlottingScene(Scene):
    def construct(self):
        # Configuration variables
        steps_ahead = 0.2  # Number of steps ahead of square player to draw scrimmage line
        line_thickness = 2  # Thickness of the scrimmage line
        path_thickness = 3  # Thickness of the player paths
        text_display_distance = 0.3  # Distance threshold for showing text along path
        
        # Read JSON file - prefer env var injected by pipeline/server, fall back to hardcoded default
        json_path = os.environ.get(
            "PLAYBOOK_JSON_PATH",
            "/Users/prathmeshgawali/sam3-demo/outputs/script.json"
        )
        
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        # Get dimensions from JSON
        json_width = data["image_dimensions"]["width"]
        json_height = data["image_dimensions"]["height"]
        
        # Set the frame to match JSON dimensions
        self.camera.frame_width = json_width / 100  # Convert to Manim units
        self.camera.frame_height = json_height / 100  # Convert to Manim units
        
        # Create a white rectangle covering the entire frame (background)
        white_rect = Rectangle(
            width=self.camera.frame_width,
            height=self.camera.frame_height,
            color=WHITE,
            fill_color=WHITE,
            fill_opacity=1,
            stroke_width=0
        )
        
        # Add the white background first (lowest z-index)
        self.add(white_rect)
        
        # Function to convert JSON coordinates to Manim coordinates
        def json_to_manim_coords(x, y):
            """
            Convert JSON pixel coordinates to Manim coordinates.
            JSON: (0,0) at top-left, (json_width, json_height) at bottom-right
            Manim: (0,0) at center, positive y is UP, positive x is RIGHT
            """
            # Convert x: from JSON (0 to width) to Manim (-width/2 to width/2)
            x_manim = (x - json_width/2) / 100
            
            # Convert y: from JSON (0 to height) to Manim (height/2 to -height/2)
            # Note: Invert y because JSON has y increasing downward, Manim has y increasing upward
            y_manim = -(y - json_height/2) / 100
            
            return np.array([x_manim, y_manim, 0])
        
        # Function to create a grey afterimage of a player with INVERTED color scheme
        def create_grey_afterimage(player_group, position):
            """
            Create a grey version of the player to use as an afterimage
            Returns a copy of the player in grey colors with INVERTED color scheme:
            - Outer shape: Light grey
            - Inner shape: Dark grey (for contrast)
            - Text: White (for readability on dark grey)
            """
            # Create a deep copy of the player group
            afterimage = player_group.copy()
            
            # Track if we found text element
            text_found = False
            
            # Set all elements to appropriate colors with reduced opacity
            for i, mobject in enumerate(afterimage):
                if isinstance(mobject, Circle) or isinstance(mobject, Square):
                    # For shapes
                    if i == 0:  # Outer shape (first element)
                        # Light grey outer
                        mobject.set_fill(color="#CCCCCC", opacity=0.8)  # Light grey
                        mobject.set_stroke(color="#CCCCCC", width=0)
                    elif i == 1:  # Inner shape (second element)
                        # Dark grey inner for contrast
                        mobject.set_fill(color="#666666", opacity=0.8)  # Dark grey
                        mobject.set_stroke(color="#666666", width=0)
                elif isinstance(mobject, Text):
                    # For text, set color to WHITE for better contrast on dark grey inner
                    mobject.set_color(WHITE)
                    mobject.set_opacity(0.9)  # Higher opacity for readability
                    text_found = True
            
            # Move to the specified position
            afterimage.move_to(position)
            return afterimage
        
        # Function to create text labels for paths
        def create_path_text_label(text_info, manim_coords, text_type="generic"):
            """
            Create a text label for a path
            text_info: Dictionary with text information from JSON
            manim_coords: Position in Manim coordinates
            text_type: Type of text (path or player)
            """
            label = text_info.get("label", "")
            if not label:
                return None
            
            # Create text in ALL CAPS as requested - REDUCED FONT SIZE from 14 to 10
            text_label = Text(
                label.upper(),  # Convert to uppercase
                font_size=12,  # REDUCED from 14 to 10
                color=BLACK,
                weight=BOLD
            )
            text_label.move_to(manim_coords)
            
            # Set z-index to be above paths but below players
            text_label.set_z_index(5)
            
            return text_label
        
        # Function to find the closest point on path to text position
        def find_text_display_time(text_pos, path_points, total_time):
            """
            Find when to display text based on its position along the path
            Returns the time (0 to 1) when text should appear
            """
            if not path_points or len(path_points) < 2:
                return 0.5  # Middle of animation
            
            # Calculate distances from text position to all path points
            distances = []
            for point in path_points:
                dist = np.linalg.norm(text_pos[:2] - point[:2])
                distances.append(dist)
            
            # Find the point with minimum distance
            min_idx = np.argmin(distances)
            
            # Calculate time based on position along path
            if len(path_points) == 2:
                return 0.5  # Simple midpoint for straight lines
            
            # For paths with multiple points, estimate position
            return min_idx / (len(path_points) - 1)
        
        # Find the square player to use as reference for scrimmage line
        square_player_center = None
        square_player_id = None
        
        # Store players dictionary for animation
        players_dict = {}
        # Store all paths for keeping them visible
        all_paths = VGroup()
        # Store all afterimages
        afterimages = VGroup()
        # Store all path text labels
        all_path_texts = VGroup()
        
        # Plot players from JSON data and find square player
        players_data = data["players"]
        
        for player_data in players_data:
            # Get player center coordinates
            center_x = player_data["center"]["x"]
            center_y = player_data["center"]["y"]
            
            # Convert to Manim coordinates
            manim_center = json_to_manim_coords(center_x, center_y)
            
            # Get alphabet label
            alphabet = player_data.get("alphabet")
            
            # Use consistent size for both circle and square players
            base_size = 0.18  # This is the radius for circles, half-side for squares
            
            # Create the player with ring structure
            player_type = player_data["type"]
            
            if player_type == "circle":
                # Create outer circle (black)
                outer_shape = Circle(
                    radius=base_size,
                    color=BLACK
                )
                outer_shape.set_fill(color=BLACK, opacity=1)
                outer_shape.set_stroke(color=BLACK, width=0)
                
                # Create inner circle (white)
                inner_shape = Circle(
                    radius=base_size * 0.75,  # 75% of outer size
                    color=WHITE
                )
                inner_shape.set_fill(color=WHITE, opacity=1)
                inner_shape.set_stroke(color=WHITE, width=0)
                
                # Create player group
                player_group = VGroup(outer_shape, inner_shape)
                player_group.move_to(manim_center)
                
            elif player_type == "square":
                # Calculate square side length from base_size (diameter of circle)
                side_length = base_size * 2  # side = diameter of circle
                
                # Create outer square (black)
                outer_shape = Square(
                    side_length=side_length,
                    color=BLACK
                )
                outer_shape.set_fill(color=BLACK, opacity=1)
                outer_shape.set_stroke(color=BLACK, width=0)
                
                # Create inner square (white)
                inner_shape = Square(
                    side_length=side_length * 0.75,  # 75% of outer size
                    color=WHITE
                )
                inner_shape.set_fill(color=WHITE, opacity=1)
                inner_shape.set_stroke(color=WHITE, width=0)
                
                # Create player group
                player_group = VGroup(outer_shape, inner_shape)
                player_group.move_to(manim_center)
                
                # Store square player center for scrimmage line
                square_player_center = manim_center
                square_player_id = player_data.get("player_id")
                print(f"DEBUG: Found square player (ID: {square_player_id}) at ({center_x}, {center_y}) -> ({manim_center[0]:.2f}, {manim_center[1]:.2f})")
            else:
                # Skip unknown player types
                print(f"DEBUG: Unknown player type: {player_type}, skipping")
                continue
            
            # Add alphabet label if available
            if alphabet:
                # Create text with alphabet in BLACK
                label_text = Text(
                    alphabet,
                    font_size=15,  # Adjust font size
                    color=BLACK,
                    weight=BOLD
                )
                label_text.move_to(manim_center)
                
                # Scale text to fit inside inner shape
                max_width = inner_shape.width * 0.6  # 60% of inner shape width
                max_height = inner_shape.height * 0.6  # 60% of inner shape height
                
                if label_text.width > max_width:
                    label_text.scale_to_fit_width(max_width)
                if label_text.height > max_height:
                    label_text.scale_to_fit_height(max_height)
                
                # Add text to player group
                player_group.add(label_text)
            
            # Add player to scene
            self.add(player_group)
            
            # Store original position reference (for consistency with original code)
            player_group.original_position = np.array(player_group.get_center(), dtype=float)
            
            # Store player in dictionary for animation
            player_id = player_data["player_id"]
            players_dict[player_id] = {
                "group": player_group,
                "type": player_type,
                "data": player_data,
                "original_position": manim_center.copy(),  # Store original position
                "alphabet": alphabet  # Store alphabet for afterimage creation
            }
            
            print(f"DEBUG: Placed {player_type} player at ({center_x}, {center_y}) -> ({manim_center[0]:.2f}, {manim_center[1]:.2f}) with alphabet: {alphabet}")
        
        # Draw scrimmage line if square player was found
        if square_player_center is not None:
            # Calculate scrimmage line position (a few steps ahead of square player)
            scrimmage_y = square_player_center[1] + steps_ahead
            
            # Define the left and right boundaries of the line
            # Use the entire frame width
            left_x = -self.camera.frame_width / 2
            right_x = self.camera.frame_width / 2
            
            # Create the scrimmage line with grey color
            scrimmage_line = Line(
                start=[left_x, scrimmage_y, 0],
                end=[right_x, scrimmage_y, 0],
                color=GREY,  # Changed from BLACK to GREY
                stroke_width=line_thickness
            )
            
            # Add scrimmage line to scene (removed label)
            self.add(scrimmage_line)
            
            print(f"DEBUG: Drew scrimmage line at y={scrimmage_y:.2f} (steps_ahead={steps_ahead}), thickness={line_thickness}")
            print(f"DEBUG: Square player at y={square_player_center[1]:.2f}, line at y={scrimmage_y:.2f}")
            print(f"DEBUG: Line spans from x={left_x:.2f} to x={right_x:.2f} (full frame width)")
        
        # Wait a bit to show initial positions
        self.wait(1)
        
        # Now animate players along their routes
        for player_id, player_info in players_dict.items():
            player_data = player_info["data"]
            
            # Check if player has primary routes
            if player_data.get("has_primary_routes") and player_data.get("primary_routes"):
                primary_routes = player_data["primary_routes"]
                
                # For now, animate only the first primary route
                if primary_routes and len(primary_routes) > 0:
                    route = primary_routes[0]
                    
                    # Get mask points
                    mask_points = route.get("mask_points", [])
                    
                    if mask_points and len(mask_points) > 1:
                        player_group = player_info["group"]
                        original_position = player_info["original_position"]
                        
                        # Convert mask points to Manim coordinates
                        manim_points = []
                        for point in mask_points:
                            if isinstance(point, list) and len(point) >= 2:
                                x, y = point[0], point[1]
                                manim_point = json_to_manim_coords(x, y)
                                manim_points.append(manim_point)
                        
                        if len(manim_points) >= 2:
                            # Create a grey afterimage at the original position
                            afterimage = create_grey_afterimage(player_group, original_position)
                            
                            # Add afterimage to scene
                            self.add(afterimage)
                            afterimages.add(afterimage)
                            
                            print(f"DEBUG: Created grey afterimage for player {player_id} at original position")
                            
                            # Create path from points - Always use BLACK
                            route_color = BLACK  # Changed from route color to BLACK
                            
                            # Create a smooth path through the points
                            path = VMobject()
                            path.set_points_smoothly(manim_points)
                            # Use BLACK with increased thickness
                            path.set_stroke(color=route_color, width=path_thickness, opacity=1.0)  # Full opacity
                            
                            # Add the path to the scene first (but don't display yet)
                            # We'll create it during animation
                            display_path = path.copy()
                            
                            # Get route type for debugging
                            route_type = route.get("path_type", "unknown")
                            print(f"DEBUG: Animating player {player_id} along {route_type} route with {len(manim_points)} points")
                            
                            # Calculate animation time based on path length
                            path_length = 0
                            for i in range(len(manim_points) - 1):
                                path_length += np.linalg.norm(manim_points[i+1] - manim_points[i])
                            
                            # Adjust animation time based on path length
                            # Base time + additional time based on length
                            animation_time = 2.0 + (path_length * 0.5)
                            animation_time = min(animation_time, 5.0)  # Cap at 5 seconds
                            
                            # IMPORTANT: Set z-index for the player to be above the path
                            player_group.set_z_index(10)  # Higher number = on top
                            
                            # Separate text animations for player and path types
                            player_text_animations = []  # Will be shown at start
                            path_text_animations = []    # Will be shown along the path
                            
                            # Process associated text
                            if player_data.get("has_associated_text") and player_data.get("associated_text"):
                                for text_info in player_data["associated_text"]:
                                    # Get text position and convert to Manim coordinates
                                    text_x = text_info["position"]["x"]
                                    text_y = text_info["position"]["y"]
                                    text_pos = json_to_manim_coords(text_x, text_y)
                                    
                                    # Create text label - pass association_type for reference
                                    text_label = create_path_text_label(text_info, text_pos, text_info.get("association_type", "unknown"))
                                    if text_label:
                                        # Add text to scene (initially invisible)
                                        text_label.set_opacity(0)
                                        self.add(text_label)
                                        all_path_texts.add(text_label)
                                        
                                        # Create animation to fade in text
                                        text_animation = text_label.animate.set_opacity(1).set_z_index(5)
                                        
                                        # Check association type
                                        association_type = text_info.get("association_type", "unknown")
                                        
                                        if association_type == "player":
                                            # Player-associated text: show immediately at start
                                            player_text_animations.append(text_animation)
                                            print(f"DEBUG: Will display PLAYER text '{text_info.get('label')}' at animation start (position: {text_x}, {text_y})")
                                        
                                        elif association_type == "path":
                                            # Path-associated text: show along the path using closeness logic
                                            display_time = find_text_display_time(text_pos, manim_points, animation_time)
                                            display_time_sec = display_time * animation_time
                                            path_text_animations.append((display_time_sec, text_animation))
                                            print(f"DEBUG: Will display PATH text '{text_info.get('label')}' at {display_time_sec:.2f}s (position: {text_x}, {text_y})")
                                        
                                        else:
                                            # Unknown type: show at midpoint (fallback)
                                            display_time = 0.5 * animation_time
                                            path_text_animations.append((display_time, text_animation))
                                            print(f"DEBUG: Will display UNKNOWN type text '{text_info.get('label')}' at {display_time:.2f}s")
                            
                            # FIRST: Show player-associated text at the start
                            if player_text_animations:
                                # Create a combined animation for all player texts
                                self.play(*[anim for anim in player_text_animations])
                            
                            # THEN: Animate the player moving along the path while creating the path
                            # First, create the path while moving the player
                            self.play(
                                MoveAlongPath(player_group, display_path, run_time=animation_time),
                                Create(display_path, run_time=animation_time),  # Create the path as we go
                                rate_func=linear
                            )
                            
                            # Play path text animations at their scheduled times
                            for display_time_sec, text_animation in path_text_animations:
                                # Wait until the display time
                                current_time = self.renderer.time
                                if display_time_sec > current_time:
                                    self.wait(display_time_sec - current_time)
                                # Fade in the text
                                self.play(text_animation)
                            
                            # Set z-index again to ensure it stays above the path
                            player_group.set_z_index(10)
                            
                            # Don't remove the path - keep it visible
                            # Add the path to the all_paths group to keep track
                            all_paths.add(display_path)
                            
                            # Wait a short moment before next player animation
                            self.wait(0.5)
        
        # Ensure all players are on top of paths at the end
        for player_info in players_dict.values():
            player_info["group"].set_z_index(10)
        
        # Keep the scene for a few more seconds
        self.wait(5)