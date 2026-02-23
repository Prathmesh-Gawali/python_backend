import os
import cv2
import numpy as np
import easyocr
from ultralytics import YOLO
import torch
from PIL import Image
import json
import re
from transformers import (
    Sam3Model,
    Sam3Processor,
)
from skimage.morphology import skeletonize
from collections import deque
import subprocess

# ==================== NEW CONSTANTS FOR TWO-PHASE ASSOCIATION ====================
SOLID_LINE_ASSOCIATION_DISTANCE = 25  # px - for primary routes (tight association)
DOTTED_LINE_ASSOCIATION_DISTANCE = 40  # px - for secondary routes (looser association)
PATH_CONTINUATION_DISTANCE = 30  # px - for connecting lines of same type
PRIMARY_ROUTE_SAMPLING_RATE = 20  # Sample every 20th point on primary route for dotted line association
BRANCHING_POINT_SEARCH_DISTANCE = 50  # px - max distance for branching point detection
# ===============================================================================

DEFAULT_COLORS = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
    (255, 128, 0),
    (128, 0, 255),
]

# ── Path resolution: prefer env vars injected by server.py, fall back to hardcoded defaults ──
_DEFAULT_IMAGE_PATH  = "/Users/prathmeshgawali/sam3-demo/images/23.png"
_DEFAULT_OUTPUT_DIR  = "/Users/prathmeshgawali/sam3-demo/outputs"

IMAGE_PATH = os.environ.get("PIPELINE_IMAGE_PATH", _DEFAULT_IMAGE_PATH)
OUTPUT_DIR = os.environ.get("PIPELINE_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)

SAM3_MODEL_PATH        = "/Users/prathmeshgawali/playbook-backend/models/sam3"
YOLO_MODEL_PATH        = "/Users/prathmeshgawali/playbook-backend/models/player/circle_square.pt"
YOLO_ALPHABET_MODEL_PATH = "/Users/prathmeshgawali/playbook-backend/models/player/alphabets.pt"

# All output files go into OUTPUT_DIR (which may be the job-specific directory)
YOLO_OUTPUT_PATH       = os.path.join(OUTPUT_DIR, "yolo_output.png")
WHITE_SHAPES_PATH      = os.path.join(OUTPUT_DIR, "white_shapes.png")
PLAYERS_ONLY_OUTPUT_PATH = os.path.join(OUTPUT_DIR, "final_output.png")
CROPPED_DIR            = os.path.join(OUTPUT_DIR, "circles")
PLAYER_JSON_PATH       = os.path.join(OUTPUT_DIR, "player.json")
TEXT_JSON_PATH         = os.path.join(OUTPUT_DIR, "text.json")
SAM3_RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "sam3_results.json")
SCRIPT_JSON_PATH       = os.path.join(OUTPUT_DIR, "script.json")

CIRCLE_RADIUS     = 15
SQUARE_SIDE       = 30
BORDER_THICKNESS  = 3
FONT_SCALE        = 0.5
FONT_THICKNESS    = 1
MASK_ALPHA        = 0.5
POINT_STEP        = 2
PATH_ASSOCIATION_DISTANCE   = 25  # Old constant, kept for backward compatibility
PATH_CHECK_POINTS           = 10
TEXT_TO_PLAYER_MAX_DISTANCE = 100
TEXT_TO_PATH_MAX_DISTANCE   = 50
ARROWHEAD_SAMPLE_POINTS     = 15
ARROWHEAD_TO_PATH_MAX_DISTANCE = 40
PATH_TAIL_PERCENTAGE        = 0.4

def get_default_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def load_sam3_models(model_path, device_choice=None):
    device = device_choice or get_default_device()
    try:
        if device == "mps":
            dtype = torch.float32
        else:
            dtype = torch.bfloat16
      
        model = Sam3Model.from_pretrained(model_path).to(device=device, dtype=dtype)
        processor = Sam3Processor.from_pretrained(model_path)
        print(f"✓ Loaded SAM3 model from '{model_path}' on device '{device}'")
        return model, processor, device, dtype
    except Exception as e:
        print(f"✗ Failed to load SAM3 models: {e}")
        return None, None, None, None

def save_sam3_json_compact(json_path, objects_data, points_per_line=30):
    def format_points_compact(points, points_per_line=30):
        if not points:
            return "[]"
      
        result = "[\n"
        for i in range(0, len(points), points_per_line):
            chunk = points[i:i + points_per_line]
            chunk_str = ','.join([f"[{x},{y}]" for x, y in chunk])
            result += f" {chunk_str}"
            if i + points_per_line < len(points):
                result += ",\n"
        result += "\n ]"
        return result
  
    json_str = '{\n "objects": [\n'
  
    for obj_idx, obj in enumerate(objects_data):
        json_str += ' {\n'
        json_str += f' "id": {obj["id"]},\n'
        json_str += f' "type": "{obj["type"]}",\n'
        json_str += f' "color": {obj["color"]},\n'
        json_str += f' "mask_points": {format_points_compact(obj["mask_points"], points_per_line)},\n'
        json_str += f' "total_points": {obj["total_points"]},\n'
        json_str += f' "sampled_points": {obj["sampled_points"]},\n'
        json_str += f' "centroid": {obj.get("centroid", [0, 0])}\n'
      
        if obj_idx < len(objects_data) - 1:
            json_str += ' },\n'
        else:
            json_str += ' }\n'
  
    json_str += ' ]\n}'
  
    with open(json_path, 'w') as f:
        f.write(json_str)

def get_8_neighbors(skeleton, point, visited=None):
    x, y = point
    neighbors = []
    for dx in [-1, 0, 1]:
        for dy in [-1, 0, 1]:
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < skeleton.shape[1] and 0 <= ny < skeleton.shape[0]:
                if skeleton[ny, nx]:
                    if visited is None or (nx, ny) not in visited:
                        neighbors.append((nx, ny))
    return neighbors

def find_skeleton_endpoints(skeleton):
    endpoints = []
    y, x = np.where(skeleton)
    for i in range(len(x)):
        px, py = x[i], y[i]
        neighbors = get_8_neighbors(skeleton, (px, py))
        if len(neighbors) == 1:
            endpoints.append((px, py))
    return endpoints

def trace_skeleton_order_greedy(skeleton, start, prev=None):
    if not np.any(skeleton):
        return []
    
    visited = set()
    ordered = []
    current = start
    
    while current is not None:
        cx, cy = current
        ordered.append(current)
        visited.add(current)
        
        neighbors = get_8_neighbors(skeleton, current, visited)
        
        if not neighbors:
            break
        
        if len(neighbors) == 1:
            next_point = neighbors[0]
        else:
            if len(ordered) > 1:
                prev_point = ordered[-2]
                dx_prev = cx - prev_point[0]
                dy_prev = cy - prev_point[1]
                
                def direction_score(p):
                    dx = p[0] - cx
                    dy = p[1] - cy
                    return dx * dx_prev + dy * dy_prev
                
                neighbors.sort(key=direction_score, reverse=True)
                next_point = neighbors[0]
            else:
                next_point = neighbors[0]
        
        current = next_point
    
    return ordered

def sort_by_principal_axis(points):
    if len(points) < 2:
        return points
    
    points_array = np.array(points)
    
    centered = points_array - np.mean(points_array, axis=0)
    
    if len(points) > 1:
        cov = np.cov(centered.T)
        eigenvalues, eigenvectors = np.linalg.eig(cov)
        principal_component = eigenvectors[:, np.argmax(eigenvalues)]
        projected = np.dot(centered, principal_component)
        sorted_indices = np.argsort(projected)
        sorted_points = points_array[sorted_indices]
        return [tuple(p) for p in sorted_points]
    else:
        return points

def order_line_points_geometrically(mask_binary, connection_point=None, target_points=80):
    if mask_binary.sum() == 0:
        return []
    
    skeleton = skeletonize(mask_binary.astype(bool))
    y_coords, x_coords = np.where(skeleton)
    points = list(zip(x_coords, y_coords))
    
    if len(points) < 2:
        return [[int(p[0]), int(p[1])] for p in points]
    
    endpoints = find_skeleton_endpoints(skeleton)
    
    if connection_point is not None:
        start = min(points, key=lambda p: calculate_distance(p, connection_point))
    elif endpoints:
        start = endpoints[0]
    else:
        start = points[0]
    
    ordered = trace_skeleton_order_greedy(skeleton, start)
    
    if len(ordered) > 10:
        start_pt = ordered[0]
        end_pt = ordered[-1]
        straight_dist = calculate_distance(start_pt, end_pt)
        path_length = sum(calculate_distance(ordered[i], ordered[i+1]) 
                         for i in range(len(ordered)-1))
        
        if path_length > 2.5 * straight_dist and straight_dist > 0:
            print(f"  Warning: Possible loop detected. Using principal axis sorting.")
            ordered = sort_by_principal_axis(points)
    
    ordered = simplify_line(ordered, target_points)
    
    return [[int(x), int(y)] for x, y in ordered]

def get_arrowhead_points(mask_binary, target_points=15):
    if mask_binary.sum() == 0:
        return []
    
    contours, _ = cv2.findContours(mask_binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        y_coords, x_coords = np.where(mask_binary)
        points = list(zip(x_coords, y_coords))
        
        if len(points) <= target_points:
            return [[int(x), int(y)] for x, y in points]
        else:
            step = max(1, len(points) // target_points)
            sampled_points = points[::step]
            return [[int(x), int(y)] for x, y in sampled_points[:target_points]]
    
    largest_contour = max(contours, key=cv2.contourArea)
    
    epsilon = 0.01 * cv2.arcLength(largest_contour, True)
    approx = cv2.approxPolyDP(largest_contour, epsilon, True)
    
    points = [point[0].tolist() for point in approx]
    
    if len(points) < target_points and len(largest_contour) > target_points:
        step = max(1, len(largest_contour) // target_points)
        sampled_indices = range(0, len(largest_contour), step)
        points = [largest_contour[i][0].tolist() for i in sampled_indices[:target_points]]
    
    return points

def simplify_line(points, target_count=80):
    if len(points) <= target_count:
        return points
    step = max(1, len(points) // target_count)
    return points[::step]

def calculate_distance(point1, point2):
    return np.sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)

def calculate_centroid(points):
    if not points:
        return [0, 0]
    
    x_sum = sum(p[0] for p in points)
    y_sum = sum(p[1] for p in points)
    
    return [int(x_sum / len(points)), int(y_sum / len(points))]

def process_with_sam3(image_path, sam3_model, sam3_processor, device, text_prompt="line", line_type="line"):
    if sam3_model is None or sam3_processor is None:
        print("SAM3 models not loaded. Skipping SAM3 processing.")
        return []
    pil_image = Image.open(image_path).convert("RGB")
    inputs = sam3_processor(images=pil_image, text=text_prompt, return_tensors="pt").to(device)
  
    with torch.no_grad():
        outputs = sam3_model(**inputs)
  
    results = sam3_processor.post_process_instance_segmentation(
        outputs,
        threshold=0.5,
        mask_threshold=0.5,
        target_sizes=[pil_image.size[::-1]],
    )[0]
  
    masks = results["masks"]
  
    if masks is None or len(masks) == 0:
        print(f"No objects found for text prompt: '{text_prompt}'")
        return []
  
    all_objects_json = []
  
    print(f"Found {len(masks)} instance(s) with SAM3 for '{text_prompt}'")
  
    for i, mask in enumerate(masks):
        mask_np = mask.cpu().numpy() if torch.is_tensor(mask) else mask
        mask_np = np.squeeze(mask_np)
      
        while mask_np.ndim > 2:
            mask_np = mask_np[0]
        mask_binary = (mask_np > 0.5)
      
        color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
      
        if np.sum(mask_binary) == 0:
            print(f" {line_type.capitalize()} {i+1}: No valid pixels found")
            continue
      
        if line_type == "arrowhead":
            mask_points = get_arrowhead_points(mask_binary, target_points=ARROWHEAD_SAMPLE_POINTS)
        else:
            mask_points = order_line_points_geometrically(
                mask_binary,
                connection_point=None,
                target_points=80
            )
        
        centroid = calculate_centroid(mask_points)
      
        original_total = int(np.sum(mask_binary))
      
        obj = {
            "id": i + 1,
            "type": line_type,
            "color": list(color),
            "mask_points": mask_points,
            "total_points": original_total,
            "sampled_points": len(mask_points),
            "centroid": centroid
        }
        all_objects_json.append(obj)
        print(f" {line_type.capitalize()} {i+1}: {original_total} pixels total, {len(mask_points)} points saved to JSON")
  
    return all_objects_json

def detect_alphabet_in_circle(crop, alphabet_model, circle_id):
    if crop is None or crop.size == 0:
        return None
  
    results = alphabet_model(
        crop,
        conf=0.3,
        iou=0.5,
        device="mps" if torch.backends.mps.is_available() else "cpu",
        verbose=False
    )
  
    detected_alphabets = []
  
    for r in results:
        boxes = r.boxes
        names = r.names
      
        for box in boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            cls_name = names[cls_id]
          
            detected_alphabets.append({
                "class": cls_name,
                "confidence": conf
            })
  
    if detected_alphabets:
        best_detection = max(detected_alphabets, key=lambda x: x["confidence"])
        print(f" Circle {circle_id}: Detected '{best_detection['class']}' (conf: {best_detection['confidence']:.2f})")
        return best_detection
    else:
        print(f" Circle {circle_id}: No alphabet detected")
        return None

def is_offensive_line_pattern(text):
    if not text:
        return False
  
    text = text.strip()
  
    if len(text) < 4 or len(text) > 10:
        return False
  
    o_count = text.lower().count('o')
  
    if o_count / len(text) >= 0.5:
        return True
  
    pattern = re.compile(r'^[OoDdJj0\-_]+$', re.IGNORECASE)
    if pattern.match(text):
        return True
  
    return False

def get_player_connection_point(player):
    center = player.get("center", {"x": 0, "y": 0})
    if isinstance(center, dict):
        cx = int(center.get("x", 0))
        cy = int(center.get("y", 0))
    elif isinstance(center, (list, tuple)):
        cx = int(center[0])
        cy = int(center[1])
    else:
        return None
  
    if player["type"] == "circle":
        connection_y = cy - CIRCLE_RADIUS - BORDER_THICKNESS
        return (cx, connection_y)
  
    return None

# ==================== NEW FUNCTIONS FOR TWO-PHASE ASSOCIATION ====================

def associate_solid_lines_to_players(player_json_path, sam3_json_path, max_distance=SOLID_LINE_ASSOCIATION_DISTANCE, check_points=PATH_CHECK_POINTS):
    """
    Phase 1: Associate only solid lines (primary routes) to players
    """
    if not os.path.exists(player_json_path):
        print(f"Player JSON not found: {player_json_path}")
        return {}
  
    with open(player_json_path, 'r') as f:
        player_data = json.load(f)
    if not os.path.exists(sam3_json_path):
        print(f"SAM3 JSON not found: {sam3_json_path}")
        return {}
  
    with open(sam3_json_path, 'r') as f:
        sam3_data = json.load(f)
  
    players = player_data.get("players", [])
    solid_paths = [obj for obj in sam3_data.get("objects", []) if obj.get("type") == "line"]
    paths_dict = {path["id"]: path for path in solid_paths}
    players_with_alphabets = [p for p in players if p.get("type") == "circle" and p.get("alphabet") is not None]
  
    print(f"\n{'='*70}")
    print(f"PHASE 1: ASSOCIATING SOLID LINES (PRIMARY ROUTES) TO PLAYERS")
    print(f"{'='*70}")
    print(f"Players with alphabets: {len(players_with_alphabets)}")
    print(f"Total solid lines: {len(solid_paths)}")
    print(f"Max association distance: {max_distance} pixels")
    print(f"Checking first AND last {check_points} points of each path")
    
    player_solid_associations = {}
    solid_path_assignments = {}
    
    for player in players_with_alphabets:
        player_id = player.get("player_id")
        alphabet = player.get("alphabet")
        connection_point = get_player_connection_point(player)
      
        if connection_point is None:
            continue
      
        print(f"\nPlayer {player_id} ('{alphabet}') - Connection point: {connection_point}")
      
        player_associations = []
        for path in solid_paths:
            path_id = path.get("id")
            if path_id in solid_path_assignments:
                continue
          
            mask_points = path.get("mask_points", [])
          
            if not mask_points:
                continue
          
            points_to_check_start = min(check_points, len(mask_points))
            points_to_check_end = min(check_points, len(mask_points))
            min_distance = float('inf')
            closest_point = None
            endpoint_type = None
            
            for i in range(points_to_check_start):
                point = mask_points[i]
                point_tuple = (point[0], point[1])
                distance = calculate_distance(connection_point, point_tuple)
              
                if distance < min_distance:
                    min_distance = distance
                    closest_point = point_tuple
                    endpoint_type = "start"
            
            for i in range(len(mask_points) - points_to_check_end, len(mask_points)):
                point = mask_points[i]
                point_tuple = (point[0], point[1])
                distance = calculate_distance(connection_point, point_tuple)
              
                if distance < min_distance:
                    min_distance = distance
                    closest_point = point_tuple
                    endpoint_type = "end"
            
            if min_distance <= max_distance:
                path_info = {
                    "path_id": path_id,
                    "connected_at": endpoint_type,
                    "distance": min_distance,
                    "continuation_chain": []
                }
                player_associations.append(path_info)
                solid_path_assignments[path_id] = player_id
                print(f" ✓ Associated Solid Line {path_id} - Distance: {min_distance:.1f}px, Connected at: {endpoint_type}")
      
        if player_associations:
            player_solid_associations[player_id] = player_associations
            print(f" Total directly connected solid lines for Player {player_id}: {len(player_associations)}")
        else:
            print(f" No solid lines associated with Player {player_id}")
  
    print(f"\n{'='*70}")
    print(f"PHASE 1.5: FINDING SOLID LINE CONTINUATIONS")
    print(f"{'='*70}")
    print(f"Max continuation distance: {PATH_CONTINUATION_DISTANCE} pixels")
  
    continuation_found = True
    iteration = 0
  
    while continuation_found and iteration < 10:
        continuation_found = False
        iteration += 1
      
        print(f"\nIteration {iteration}:")
        for player_id, path_list in player_solid_associations.items():
            for path_info in path_list:
                if path_info["continuation_chain"]:
                    last_path_id = path_info["continuation_chain"][-1]
                else:
                    last_path_id = path_info["path_id"]
              
                last_path = paths_dict.get(last_path_id)
                if not last_path:
                    continue
              
                last_mask_points = last_path.get("mask_points", [])
                if not last_mask_points:
                    continue
                
                if path_info["connected_at"] == "start":
                    endpoint_indices = range(len(last_mask_points) - check_points, len(last_mask_points))
                else:
                    endpoint_indices = range(0, check_points)
              
                endpoint_coords = [tuple(last_mask_points[i]) for i in endpoint_indices if i < len(last_mask_points) and i >= 0]
              
                for unassigned_path in solid_paths:
                    unassigned_path_id = unassigned_path.get("id")
                    if unassigned_path_id in solid_path_assignments:
                        continue
                  
                    unassigned_mask_points = unassigned_path.get("mask_points", [])
                    if not unassigned_mask_points:
                        continue
                    
                    min_distance = float('inf')
                    
                    for i in range(min(check_points, len(unassigned_mask_points))):
                        point = tuple(unassigned_mask_points[i])
                        for endpoint in endpoint_coords:
                            distance = calculate_distance(point, endpoint)
                            if distance < min_distance:
                                min_distance = distance
                    
                    for i in range(len(unassigned_mask_points) - min(check_points, len(unassigned_mask_points)), len(unassigned_mask_points)):
                        if i < 0:
                            continue
                        point = tuple(unassigned_mask_points[i])
                        for endpoint in endpoint_coords:
                            distance = calculate_distance(point, endpoint)
                            if distance < min_distance:
                                min_distance = distance
                    
                    if min_distance <= PATH_CONTINUATION_DISTANCE:
                        path_info["continuation_chain"].append(unassigned_path_id)
                        solid_path_assignments[unassigned_path_id] = player_id
                        continuation_found = True
                        print(f" ✓ Player {player_id}: Solid Line {unassigned_path_id} continues Line {last_path_id} (distance: {min_distance:.1f}px)")
  
    print(f"\n{'='*70}")
    print(f"SOLID LINE ASSOCIATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total players with solid lines: {len(player_solid_associations)}")
    print(f"Total solid lines associated: {len(solid_path_assignments)}")
    print(f"Unassociated solid lines: {len(solid_paths) - len(solid_path_assignments)}")
  
    for player_id, path_list in player_solid_associations.items():
        total_paths = sum(1 + len(p["continuation_chain"]) for p in path_list)
        print(f" Player {player_id}: {total_paths} total solid lines ({len(path_list)} direct + continuations)")
  
    return player_solid_associations

def check_dotted_to_primary_proximity(dotted_line, primary_points, max_distance, sampling_rate=PRIMARY_ROUTE_SAMPLING_RATE):
    """
    Check if a dotted line is close to ANY point in the primary path
    """
    dotted_points = dotted_line["mask_points"]
    
    if not dotted_points or not primary_points:
        return {
            "is_associated": False,
            "min_distance": float('inf'),
            "closest_primary_point": None,
            "closest_dotted_point": None
        }
    
    # Sample primary path points for efficiency
    sampling_interval = max(1, len(primary_points) // sampling_rate)
    if sampling_interval == 0:
        sampling_interval = 1
    
    primary_sample_points = primary_points[::sampling_interval]
    
    min_distance = float('inf')
    closest_primary_point = None
    closest_dotted_point = None
    
    # Sample dotted line points as well for efficiency
    dotted_sample_points = dotted_points[::max(1, len(dotted_points) // 10)]
    
    for d_point in dotted_sample_points:
        for p_point in primary_sample_points:
            distance = calculate_distance(d_point, p_point)
            if distance < min_distance:
                min_distance = distance
                closest_primary_point = p_point
                closest_dotted_point = d_point
    
    return {
        "is_associated": min_distance <= max_distance,
        "min_distance": min_distance,
        "closest_primary_point": closest_primary_point,
        "closest_dotted_point": closest_dotted_point,
        "connection_type": "path_proximity"
    }

def find_branching_point(dotted_line, primary_path_points):
    """
    Find the point on primary path where dotted line branches
    Returns: index in primary path where branching occurs
    """
    if not dotted_line["mask_points"] or not primary_path_points:
        return 0
    
    dotted_start = dotted_line["mask_points"][0]
    dotted_end = dotted_line["mask_points"][-1]
    
    # Find closest point on primary path to start of dotted line
    distances_start = []
    for i, p in enumerate(primary_path_points):
        distances_start.append(calculate_distance(p, dotted_start))
    
    min_dist_start = min(distances_start)
    branch_index_start = distances_start.index(min_dist_start)
    
    # Find closest point on primary path to end of dotted line
    distances_end = []
    for i, p in enumerate(primary_path_points):
        distances_end.append(calculate_distance(p, dotted_end))
    
    min_dist_end = min(distances_end)
    branch_index_end = distances_end.index(min_dist_end)
    
    # Choose the endpoint that's closer to the primary path
    if min_dist_end < min_dist_start:
        branch_index = branch_index_end
        # Reverse dotted line points for consistency (so it starts at branching point)
        dotted_line["mask_points"] = list(reversed(dotted_line["mask_points"]))
        print(f"    Dotted line reversed - branching from end point at index {branch_index}")
    else:
        branch_index = branch_index_start
    
    return branch_index

def associate_dotted_lines_to_players(player_solid_associations, sam3_json_path, primary_chains_data, max_distance=DOTTED_LINE_ASSOCIATION_DISTANCE):
    """
    Phase 2: Associate dotted lines (secondary routes) to players based on proximity to their primary routes
    """
    print(f"\n{'='*70}")
    print(f"PHASE 2: ASSOCIATING DOTTED LINES (SECONDARY ROUTES) TO PLAYERS")
    print(f"{'='*70}")
    print(f"Max association distance: {max_distance} pixels")
    print(f"Checking proximity to entire primary route (not just endpoints)")
    
    if not os.path.exists(sam3_json_path):
        print(f"SAM3 JSON not found: {sam3_json_path}")
        return {}
    
    with open(sam3_json_path, 'r') as f:
        sam3_data = json.load(f)
    
    dotted_lines = [obj for obj in sam3_data.get("objects", []) if obj.get("type") == "dotted line"]
    print(f"Total dotted lines to associate: {len(dotted_lines)}")
    
    player_dotted_associations = {}
    dotted_path_assignments = {}
    
    for player_id, solid_chains in player_solid_associations.items():
        print(f"\nProcessing Player {player_id}:")
        player_dotted_associations[player_id] = []
        
        # For each solid line chain this player has
        for chain_idx, chain_info in enumerate(solid_chains):
            all_path_ids = [chain_info["path_id"]] + chain_info["continuation_chain"]
            chain_key = f"{player_id}_{chain_idx}"
            
            # Get all points from this primary chain
            primary_points = []
            for path_id in all_path_ids:
                # Find the path in primary_chains_data
                for path_info in primary_chains_data.get(player_id, []):
                    if path_id in path_info["all_path_ids"]:
                        primary_points.extend(path_info["primary_route_points"])
                        break
            
            if not primary_points:
                print(f"  No primary route points found for chain {all_path_ids}")
                continue
            
            print(f"  Primary chain {all_path_ids}: {len(primary_points)} points")
            
            for dotted in dotted_lines:
                dotted_id = dotted["id"]
                if dotted_id in dotted_path_assignments:
                    continue
                
                # Check proximity to primary route
                association = check_dotted_to_primary_proximity(
                    dotted, 
                    primary_points,
                    max_distance,
                    PRIMARY_ROUTE_SAMPLING_RATE
                )
                
                if association["is_associated"]:
                    # Find branching point
                    branch_index = find_branching_point(dotted, primary_points)
                    
                    # Ensure branch_index is within bounds
                    if branch_index >= len(primary_points):
                        branch_index = len(primary_points) - 1
                    
                    branching_point = primary_points[branch_index]
                    
                    dotted_assoc = {
                        "dotted_line_id": dotted_id,
                        "primary_chain_index": chain_idx,
                        "primary_chain_ids": all_path_ids,
                        "branch_info": {
                            "index": branch_index,
                            "coordinates": branching_point,
                            "distance": association["min_distance"]
                        },
                        "dotted_line_points": dotted["mask_points"],
                        "dotted_line_color": dotted.get("color", [100, 100, 100]),
                        "connection_type": association["connection_type"]
                    }
                    
                    player_dotted_associations[player_id].append(dotted_assoc)
                    dotted_path_assignments[dotted_id] = player_id
                    
                    print(f"  ✓ Associated Dotted Line {dotted_id} - Distance: {association['min_distance']:.1f}px")
                    print(f"    Branching from primary route at point {branching_point} (index {branch_index})")
    
    print(f"\n{'='*70}")
    print(f"DOTTED LINE ASSOCIATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total dotted lines: {len(dotted_lines)}")
    print(f"Associated dotted lines: {len(dotted_path_assignments)}")
    print(f"Unassociated dotted lines: {len(dotted_lines) - len(dotted_path_assignments)}")
    
    for player_id, dotted_list in player_dotted_associations.items():
        if dotted_list:
            print(f" Player {player_id}: {len(dotted_list)} dotted lines")
    
    return player_dotted_associations

def build_primary_chains(player_solid_associations, sam3_json_path):
    """
    Build primary route chains from solid line associations for easier dotted line association
    """
    if not os.path.exists(sam3_json_path):
        return {}
    
    with open(sam3_json_path, 'r') as f:
        sam3_data = json.load(f)
    
    paths_dict = {path["id"]: path for path in sam3_data.get("objects", [])}
    primary_chains = {}
    
    for player_id, path_list in player_solid_associations.items():
        primary_chains[player_id] = []
        
        for path_info in path_list:
            main_path_id = path_info["path_id"]
            connected_at = path_info["connected_at"]
            continuation_chain = path_info["continuation_chain"]
            all_path_ids = [main_path_id] + continuation_chain
            
            # Build the complete primary route points
            primary_route_points = []
            
            # Get main path points
            main_path = paths_dict.get(main_path_id)
            if main_path:
                main_mask_points = main_path.get("mask_points", [])
                if connected_at == "end":
                    main_mask_points = list(reversed(main_mask_points))
                primary_route_points.extend(main_mask_points)
            
            # Add continuation points
            for cont_path_id in continuation_chain:
                cont_path = paths_dict.get(cont_path_id)
                if not cont_path:
                    continue
                
                cont_mask_points = cont_path.get("mask_points", [])
                if primary_route_points and cont_mask_points:
                    last_point = primary_route_points[-1]
                    dist_to_start = calculate_distance(
                        tuple(last_point),
                        tuple(cont_mask_points[0])
                    )
                    dist_to_end = calculate_distance(
                        tuple(last_point),
                        tuple(cont_mask_points[-1])
                    )
                    if dist_to_end < dist_to_start:
                        cont_mask_points = list(reversed(cont_mask_points))
                
                primary_route_points.extend(cont_mask_points)
            
            primary_chains[player_id].append({
                "all_path_ids": all_path_ids,
                "primary_route_points": primary_route_points,
                "connected_at": connected_at
            })
    
    return primary_chains

# ===============================================================================

def associate_arrowheads_to_paths(player_solid_associations, sam3_json_path, max_distance=ARROWHEAD_TO_PATH_MAX_DISTANCE, tail_percentage=PATH_TAIL_PERCENTAGE):
    print(f"\n{'='*70}")
    print(f"ASSOCIATING ARROWHEADS TO PATH SEGMENTS")
    print(f"{'='*70}")
    print(f"Max association distance: {max_distance} pixels")
    print(f"Considering last {tail_percentage*100:.0f}% of each path")
    
    if not os.path.exists(sam3_json_path):
        print(f"SAM3 JSON not found: {sam3_json_path}")
        return {}
    
    with open(sam3_json_path, 'r') as f:
        sam3_data = json.load(f)
    
    paths_dict = {obj["id"]: obj for obj in sam3_data.get("objects", []) if obj.get("type") in ["line", "dotted line"]}
    arrowheads = [obj for obj in sam3_data.get("objects", []) if obj.get("type") == "arrowhead"]
    
    print(f"Total arrowheads to associate: {len(arrowheads)}")
    
    arrowhead_assignments = {}
    path_to_arrowhead_map = {}
    
    for player_id, path_list in player_solid_associations.items():
        print(f"\nProcessing Player {player_id}:")
        
        for path_info in path_list:
            main_path_id = path_info["path_id"]
            continuation_chain = path_info["continuation_chain"]
            all_path_ids = [main_path_id] + continuation_chain
            
            path_chain_key = f"{player_id}_{'-'.join(map(str, all_path_ids))}"
            
            all_path_points = []
            for path_id in all_path_ids:
                path = paths_dict.get(path_id)
                if path:
                    all_path_points.extend(path.get("mask_points", []))
            
            if not all_path_points:
                continue
            
            total_points = len(all_path_points)
            tail_start_idx = int(total_points * (1 - tail_percentage))
            tail_points = all_path_points[tail_start_idx:]
            
            print(f"  Path chain {all_path_ids}: {total_points} points, checking last {len(tail_points)} points")
            
            best_arrowhead = None
            best_distance = float('inf')
            
            for arrowhead in arrowheads:
                arrowhead_id = arrowhead["id"]
                
                if arrowhead_id in arrowhead_assignments:
                    continue
                
                arrowhead_centroid = arrowhead.get("centroid", [0, 0])
                arrowhead_points = arrowhead.get("mask_points", [])
                
                min_dist_to_tail = float('inf')
                
                for tail_point in tail_points:
                    dist = calculate_distance(arrowhead_centroid, tail_point)
                    min_dist_to_tail = min(min_dist_to_tail, dist)
                
                for arrow_point in arrowhead_points:
                    for tail_point in tail_points:
                        dist = calculate_distance(arrow_point, tail_point)
                        min_dist_to_tail = min(min_dist_to_tail, dist)
                
                if min_dist_to_tail < best_distance:
                    best_distance = min_dist_to_tail
                    best_arrowhead = arrowhead
            if best_arrowhead is not None and best_distance <= max_distance:
                if best_distance > max_distance * 2:
                    print(f"  Warning: Arrowhead {best_arrowhead['id']} may not belong to path chain {all_path_ids}")
                
                arrowhead_id = best_arrowhead["id"]
                arrowhead_assignments[arrowhead_id] = path_chain_key
                path_to_arrowhead_map[path_chain_key] = {
                    "arrowhead_id": arrowhead_id,
                    "arrowhead_type": best_arrowhead.get("type"),
                    "arrowhead_color": best_arrowhead.get("color"),
                    "arrowhead_mask_points": best_arrowhead.get("mask_points"),
                    "arrowhead_centroid": best_arrowhead.get("centroid"),
                    "arrowhead_total_points": best_arrowhead.get("total_points"),
                    "arrowhead_sampled_points": best_arrowhead.get("sampled_points"),
                    "distance_to_path": round(best_distance, 2)
                }
                print(f"  ✓ Associated Arrowhead {arrowhead_id} - Distance: {best_distance:.1f}px")
            else:
                print(f"  ✗ No arrowhead found within {max_distance}px (closest: {best_distance:.1f}px)")
    
    print(f"\n{'='*70}")
    print(f"ARROWHEAD ASSOCIATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total arrowheads: {len(arrowheads)}")
    print(f"Associated arrowheads: {len(arrowhead_assignments)}")
    print(f"Unassociated arrowheads: {len(arrowheads) - len(arrowhead_assignments)}")
    
    return path_to_arrowhead_map

def associate_text_to_players(player_json_path, text_json_path, sam3_json_path, player_solid_associations):
    print(f"\n{'='*70}")
    print(f"ASSOCIATING TEXT TO PLAYERS")
    print(f"{'='*70}")
    if not os.path.exists(player_json_path):
        print(f"Player JSON not found: {player_json_path}")
        return {}
  
    with open(player_json_path, 'r') as f:
        player_data = json.load(f)
  
    if not os.path.exists(text_json_path):
        print(f"Text JSON not found: {text_json_path}")
        return {}
  
    with open(text_json_path, 'r') as f:
        text_data = json.load(f)
    paths_dict = {}
    if os.path.exists(sam3_json_path):
        with open(sam3_json_path, 'r') as f:
            sam3_data = json.load(f)
        paths_dict = {path["id"]: path for path in sam3_data.get("objects", [])}
  
    players = player_data.get("players", [])
    text_elements = text_data.get("text_elements", [])
  
    text_to_player_map = {}
  
    print(f"Processing {len(text_elements)} text elements...")
  
    for text_elem in text_elements:
        text_id = text_elem.get("text_id")
        text_position = text_elem.get("position", {"x": 0, "y": 0})
        text_x = text_position.get("x", 0)
        text_y = text_position.get("y", 0)
        text_label = text_elem.get("label", "")
      
        print(f"\nText {text_id} ('{text_label}') at position ({text_x}, {text_y})")
      
        best_player_id = None
        best_distance = float('inf')
        best_association_type = None
        for player in players:
            player_id = player.get("player_id")
            center = player.get("center", {"x": 0, "y": 0})
          
            if isinstance(center, dict):
                player_x = center.get("x", 0)
                player_y = center.get("y", 0)
            elif isinstance(center, (list, tuple)):
                player_x = center[0]
                player_y = center[1]
            else:
                continue
            distance_to_center = calculate_distance((text_x, text_y), (player_x, player_y))
            if player["type"] == "circle":
                player_bottom_y = player_y + CIRCLE_RADIUS + BORDER_THICKNESS
                distance_to_bottom = calculate_distance((text_x, text_y), (player_x, player_bottom_y))
                min_player_distance = min(distance_to_center, distance_to_bottom)
            else:
                min_player_distance = distance_to_center
            if min_player_distance < best_distance:
                best_distance = min_player_distance
                best_player_id = player_id
                best_association_type = "player"
            if player_id in player_solid_associations:
                for path_info in player_solid_associations[player_id]:
                    all_path_ids = [path_info["path_id"]] + path_info["continuation_chain"]
                  
                    for path_id in all_path_ids:
                        path = paths_dict.get(path_id)
                        if not path:
                            continue
                      
                        mask_points = path.get("mask_points", [])
                        for i in range(0, len(mask_points), 10):
                            point = mask_points[i]
                            distance_to_path = calculate_distance((text_x, text_y), (point[0], point[1]))
                          
                            if distance_to_path < best_distance:
                                best_distance = distance_to_path
                                best_player_id = player_id
                                best_association_type = "path"
      
        if best_player_id is not None and best_distance <= TEXT_TO_PLAYER_MAX_DISTANCE:
            text_to_player_map[text_id] = {
                "player_id": best_player_id,
                "distance": round(best_distance, 2),
                "association_type": best_association_type
            }
            print(f" ✓ Associated with Player {best_player_id} (distance: {best_distance:.1f}px, type: {best_association_type})")
        else:
            print(f" ✗ No close player found (closest: {best_distance:.1f}px)")
  
    print(f"\n{'='*70}")
    print(f"TEXT ASSOCIATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total text elements: {len(text_elements)}")
    print(f"Associated text elements: {len(text_to_player_map)}")
    print(f"Unassociated text elements: {len(text_elements) - len(text_to_player_map)}")
  
    return text_to_player_map

def create_script_json(player_json_path, sam3_json_path, text_json_path, player_solid_associations, player_dotted_associations, path_to_arrowhead_map, text_to_player_map, output_path, image_width, image_height, points_per_line=30):
    def format_points_compact_with_separators(all_path_points, points_per_line=30):
        if not all_path_points or not any(all_path_points):
            return "[]"
      
        result = "[\n"
      
        for path_idx, points in enumerate(all_path_points):
            if not points:
                continue
            for i in range(0, len(points), points_per_line):
                chunk = points[i:i + points_per_line]
                chunk_str = ','.join([f"[{x},{y}]" for x, y in chunk])
                result += f" {chunk_str}"
                is_last_chunk_of_path = (i + points_per_line >= len(points))
                is_last_path = (path_idx == len(all_path_points) - 1)
              
                if not (is_last_chunk_of_path and is_last_path):
                    result += ","
              
                result += "\n"
            if path_idx < len(all_path_points) - 1:
                result += "\n"
      
        result += " ]"
        return result
  
    print(f"\n{'='*70}")
    print(f"CREATING SCRIPT.JSON WITH TWO-PHASE PATH ASSOCIATION")
    print(f"{'='*70}")
    print(f"Image dimensions: {image_width}x{image_height}")
    print(f"Primary routes (solid lines) and secondary routes (dotted lines)")
  
    if not os.path.exists(player_json_path):
        print(f"Player JSON not found: {player_json_path}")
        return
  
    with open(player_json_path, 'r') as f:
        player_data = json.load(f)
    if not os.path.exists(sam3_json_path):
        print(f"SAM3 JSON not found: {sam3_json_path}")
        return
  
    with open(sam3_json_path, 'r') as f:
        sam3_data = json.load(f)
    text_elements_dict = {}
    if os.path.exists(text_json_path):
        with open(text_json_path, 'r') as f:
            text_data = json.load(f)
        text_elements_dict = {elem["text_id"]: elem for elem in text_data.get("text_elements", [])}
    paths_dict = {path["id"]: path for path in sam3_data.get("objects", [])}
    player_to_text_map = {}
    for text_id, association in text_to_player_map.items():
        player_id = association["player_id"]
        if player_id not in player_to_text_map:
            player_to_text_map[player_id] = []
        player_to_text_map[player_id].append({
            "text_id": text_id,
            "distance": association["distance"],
            "association_type": association["association_type"]
        })
    
    # Start JSON with image dimensions
    json_str = '{\n "image_dimensions": {\n'
    json_str += f'  "width": {image_width},\n'
    json_str += f'  "height": {image_height}\n'
    json_str += ' },\n "players": [\n'
  
    players = player_data.get("players", [])
    for player_idx, player in enumerate(players):
        player_id = player.get("player_id")
      
        json_str += ' {\n'
        json_str += f' "player_id": {player_id},\n'
        json_str += f' "type": "{player["type"]}",\n'
        bbox = player.get("bounding_box", {})
        json_str += f' "bounding_box": {{\n'
        json_str += f' "x1": {bbox.get("x1", 0)},\n'
        json_str += f' "y1": {bbox.get("y1", 0)},\n'
        json_str += f' "x2": {bbox.get("x2", 0)},\n'
        json_str += f' "y2": {bbox.get("y2", 0)}\n'
        json_str += f' }},\n'
        center = player.get("center", {})
        json_str += f' "center": {{\n'
        json_str += f' "x": {center.get("x", 0)},\n'
        json_str += f' "y": {center.get("y", 0)}\n'
        json_str += f' }},\n'
        if "cropped_image_path" in player:
            json_str += f' "cropped_image_path": "{player["cropped_image_path"]}",\n'
        alphabet = player.get("alphabet")
        if alphabet is not None:
            json_str += f' "alphabet": "{alphabet}",\n'
        else:
            json_str += f' "alphabet": null,\n'
      
        confidence = player.get("confidence")
        if confidence is not None:
            json_str += f' "confidence": {confidence},\n'
        else:
            json_str += f' "confidence": null,\n'
        
        # ============ PRIMARY ROUTES (SOLID LINES) ============
        if player_id in player_solid_associations:
            solid_associations = player_solid_associations[player_id]
          
            json_str += f' "has_primary_routes": true,\n'
            json_str += f' "primary_routes": [\n'
            for path_idx, path_info in enumerate(solid_associations):
                main_path_id = path_info["path_id"]
                connected_at = path_info["connected_at"]
                continuation_chain = path_info["continuation_chain"]
                all_path_ids = [main_path_id] + continuation_chain
                
                path_chain_key = f"{player_id}_{'-'.join(map(str, all_path_ids))}"
                
                main_path = paths_dict.get(main_path_id)
                if not main_path:
                    continue
              
                path_type = main_path.get("type", "unknown")
                path_color = main_path.get("color", [0, 0, 0])
                
                all_path_points = []
                main_mask_points = main_path.get("mask_points", [])
                if connected_at == "end":
                    main_mask_points = list(reversed(main_mask_points))
              
                all_path_points.append(main_mask_points)
                
                for cont_path_id in continuation_chain:
                    cont_path = paths_dict.get(cont_path_id)
                    if not cont_path:
                        continue
                  
                    cont_mask_points = cont_path.get("mask_points", [])
                    if all_path_points and all_path_points[-1]:
                        last_point = all_path_points[-1][-1]
                        dist_to_start = calculate_distance(
                            tuple(last_point),
                            tuple(cont_mask_points[0]) if cont_mask_points else (float('inf'), float('inf'))
                        )
                        dist_to_end = calculate_distance(
                            tuple(last_point),
                            tuple(cont_mask_points[-1]) if cont_mask_points else (float('inf'), float('inf'))
                        )
                        if dist_to_end < dist_to_start:
                            cont_mask_points = list(reversed(cont_mask_points))
                  
                    all_path_points.append(cont_mask_points)
                
                flat_points = []
                for segment in all_path_points:
                    flat_points.extend(segment)
                
                if path_chain_key in path_to_arrowhead_map:
                    arrowhead_data = path_to_arrowhead_map[path_chain_key]
                    arrowhead_centroid = arrowhead_data.get("arrowhead_centroid", [0, 0])
                    arrowhead_points = arrowhead_data.get("arrowhead_mask_points", [])
                    
                    original_point_count = len(flat_points)
                    
                    trimmed_points = trim_path_at_arrowhead(
                        flat_points, 
                        arrowhead_centroid,
                        arrowhead_points=arrowhead_points,
                        validate_ownership=True
                    )
                    
                    all_path_points = [trimmed_points]
                    
                    trimmed_count = len(trimmed_points)
                    print(f"Player {player_id}: Primary route {all_path_ids} - Trimmed from {original_point_count} to {trimmed_count} points using OWN Arrowhead {arrowhead_data['arrowhead_id']}")
                else:
                    all_path_points = all_path_points
                
                total_points = sum(len(points) for points in all_path_points)
                
                json_str += ' {\n'
                json_str += f' "path_id": {json.dumps(all_path_ids)},\n'
                json_str += f' "path_type": "{path_type}",\n'
                json_str += f' "color": {json.dumps(path_color)},\n'
                json_str += f' "mask_points": {format_points_compact_with_separators(all_path_points, points_per_line)},\n'
              
                arrowhead_data = path_to_arrowhead_map.get(path_chain_key)
                if arrowhead_data:
                    json_str += f' "has_arrowhead": true,\n'
                    json_str += f' "arrowhead": {{\n'
                    json_str += f' "arrowhead_id": {arrowhead_data["arrowhead_id"]},\n'
                    json_str += f' "type": "{arrowhead_data["arrowhead_type"]}",\n'
                    json_str += f' "color": {json.dumps(arrowhead_data["arrowhead_color"])},\n'
                    json_str += f' "mask_points": {json.dumps(arrowhead_data["arrowhead_mask_points"])},\n'
                    json_str += f' "centroid": {json.dumps(arrowhead_data["arrowhead_centroid"])},\n'
                    json_str += f' "total_points": {arrowhead_data["arrowhead_total_points"]},\n'
                    json_str += f' "sampled_points": {arrowhead_data["arrowhead_sampled_points"]},\n'
                    json_str += f' "distance_to_path": {arrowhead_data["distance_to_path"]}\n'
                    json_str += f' }}\n'
                    print(f"Player {player_id}: Primary route {all_path_ids} - Associated with Arrowhead {arrowhead_data['arrowhead_id']}")
                else:
                    json_str += f' "has_arrowhead": false\n'
              
                if path_idx < len(solid_associations) - 1:
                    json_str += ' },\n'
                else:
                    json_str += ' }\n'
              
                print(f"Player {player_id}: Primary route {all_path_ids} - {total_points} total points ({len(all_path_points)} segments)")
          
            json_str += ' ],\n'
        else:
            json_str += f' "has_primary_routes": false,\n'
            json_str += f' "primary_routes": [],\n'
            print(f"Player {player_id}: No primary routes")
        
        # ============ SECONDARY ROUTES (DOTTED LINES) ============
        if player_id in player_dotted_associations and player_dotted_associations[player_id]:
            dotted_associations = player_dotted_associations[player_id]
          
            json_str += f' "has_secondary_routes": true,\n'
            json_str += f' "secondary_routes": [\n'
            for dotted_idx, dotted_assoc in enumerate(dotted_associations):
                dotted_line_id = dotted_assoc["dotted_line_id"]
                primary_chain_index = dotted_assoc["primary_chain_index"]
                primary_chain_ids = dotted_assoc["primary_chain_ids"]
                branch_info = dotted_assoc["branch_info"]
                dotted_line_points = dotted_assoc["dotted_line_points"]
                dotted_line_color = dotted_assoc["dotted_line_color"]
                
                json_str += ' {\n'
                json_str += f' "path_id": [{dotted_line_id}],\n'
                json_str += f' "path_type": "dotted line",\n'
                json_str += f' "color": {json.dumps(dotted_line_color)},\n'
                json_str += f' "mask_points": {json.dumps(dotted_line_points)},\n'
                json_str += f' "branch_from_primary_index": {branch_info["index"]},\n'
                json_str += f' "branch_point": {json.dumps(branch_info["coordinates"])},\n'
                json_str += f' "branch_distance": {branch_info["distance"]},\n'
                json_str += f' "connected_primary_chain": {json.dumps(primary_chain_ids)},\n'
                json_str += f' "has_arrowhead": false\n'
                
                if dotted_idx < len(dotted_associations) - 1:
                    json_str += ' },\n'
                else:
                    json_str += ' }\n'
              
                print(f"Player {player_id}: Secondary route (Dotted Line {dotted_line_id}) - Branches from primary route {primary_chain_ids} at index {branch_info['index']}")
          
            json_str += ' ],\n'
        else:
            json_str += f' "has_secondary_routes": false,\n'
            json_str += f' "secondary_routes": [],\n'
            print(f"Player {player_id}: No secondary routes")
      
        # ============ TEXT ASSOCIATIONS ============
        if player_id in player_to_text_map:
            text_associations = player_to_text_map[player_id]
          
            json_str += f' "has_associated_text": true,\n'
            json_str += f' "associated_text": [\n'
          
            for text_idx, text_assoc in enumerate(text_associations):
                text_id = text_assoc["text_id"]
                text_elem = text_elements_dict.get(text_id)
              
                if not text_elem:
                    continue
              
                json_str += ' {\n'
                json_str += f' "text_id": {text_id},\n'
                json_str += f' "label": "{text_elem.get("label", "")}",\n'
                json_str += f' "confidence": {text_elem.get("confidence", 0)},\n'
              
                bbox = text_elem.get("bounding_box", {})
                json_str += f' "bounding_box": {{\n'
                json_str += f' "x_min": {bbox.get("x_min", 0)},\n'
                json_str += f' "y_min": {bbox.get("y_min", 0)},\n'
                json_str += f' "x_max": {bbox.get("x_max", 0)},\n'
                json_str += f' "y_max": {bbox.get("y_max", 0)}\n'
                json_str += f' }},\n'
              
                size = text_elem.get("size", {})
                json_str += f' "size": {{\n'
                json_str += f' "width": {size.get("width", 0)},\n'
                json_str += f' "height": {size.get("height", 0)}\n'
                json_str += f' }},\n'
              
                position = text_elem.get("position", {})
                json_str += f' "position": {{\n'
                json_str += f' "x": {position.get("x", 0)},\n'
                json_str += f' "y": {position.get("y", 0)}\n'
                json_str += f' }},\n'
              
                json_str += f' "association_distance": {text_assoc["distance"]},\n'
                json_str += f' "association_type": "{text_assoc["association_type"]}"\n'
              
                if text_idx < len(text_associations) - 1:
                    json_str += ' },\n'
                else:
                    json_str += ' }\n'
              
                print(f"Player {player_id}: Text '{text_elem.get('label', '')}' (distance: {text_assoc['distance']}px, type: {text_assoc['association_type']})")
          
            json_str += ' ]\n'
        else:
            json_str += f' "has_associated_text": false,\n'
            json_str += f' "associated_text": []\n'
      
        if player_idx < len(players) - 1:
            json_str += ' },\n'
        else:
            json_str += ' }\n'
  
    json_str += ' ],\n'
    
    all_arrowheads = [obj for obj in sam3_data.get("objects", []) if obj.get("type") == "arrowhead"]
    associated_arrowhead_ids = {v["arrowhead_id"] for v in path_to_arrowhead_map.values()}
    unassociated_arrowheads = [a for a in all_arrowheads if a["id"] not in associated_arrowhead_ids]
    
    json_str += ' "unassociated_arrowheads": [\n'
    
    for arrowhead_idx, arrowhead in enumerate(unassociated_arrowheads):
        json_str += ' {\n'
        json_str += f' "arrowhead_id": {arrowhead["id"]},\n'
        json_str += f' "type": "arrowhead",\n'
        json_str += f' "color": {json.dumps(arrowhead["color"])},\n'
        json_str += f' "mask_points": {json.dumps(arrowhead["mask_points"])},\n'
        json_str += f' "centroid": {json.dumps(arrowhead.get("centroid", [0, 0]))},\n'
        json_str += f' "total_points": {arrowhead["total_points"]},\n'
        json_str += f' "sampled_points": {arrowhead["sampled_points"]}\n'
        
        if arrowhead_idx < len(unassociated_arrowheads) - 1:
            json_str += ' },\n'
        else:
            json_str += ' }\n'
    
    json_str += ' ]\n}'
  
    with open(output_path, 'w') as f:
        f.write(json_str)
  
    print(f"\n✓ Script JSON saved to: {output_path}")
    print(f" Total players: {len(players)}")
    
    players_with_primary_routes = len([p for p in players if player_solid_associations.get(p.get("player_id"))])
    players_with_secondary_routes = len([p for p in players if player_dotted_associations.get(p.get("player_id")) and player_dotted_associations.get(p.get("player_id"))])
    
    total_primary_chains = sum(len(path_list) for path_list in player_solid_associations.values())
    total_secondary_routes = sum(len(dotted_list) for dotted_list in player_dotted_associations.values())
    players_with_text = len([p for p in players if player_to_text_map.get(p.get("player_id"))])
  
    print(f" Players with primary routes: {players_with_primary_routes}")
    print(f" Players with secondary routes: {players_with_secondary_routes}")
    print(f" Total primary route chains: {total_primary_chains}")
    print(f" Total secondary routes: {total_secondary_routes}")
    print(f" Total arrowheads: {len(all_arrowheads)}")
    print(f" Associated arrowheads: {len(associated_arrowhead_ids)}")
    print(f" Unassociated arrowheads: {len(unassociated_arrowheads)}")
    print(f" Players with associated text: {players_with_text}")

def draw_arrowhead(image, arrowhead_points, color=(0, 0, 0), fill=True):
    if not arrowhead_points or len(arrowhead_points) < 3:
        return image
    
    points = np.array(arrowhead_points, dtype=np.int32).reshape((-1, 1, 2))
    
    if fill:
        cv2.fillPoly(image, [points], color)
    else:
        cv2.polylines(image, [points], isClosed=True, color=color, thickness=2)
    
    return image

def draw_from_script_json(image, script_json_path, draw_mode="final", point_size=1, is_white_background=True):
    if not os.path.exists(script_json_path):
        print(f"Script JSON not found: {script_json_path}")
        return image
  
    with open(script_json_path, 'r') as f:
        script_data = json.load(f)
  
    players = script_data.get("players", [])
    unassociated_arrowheads = script_data.get("unassociated_arrowheads", [])
  
    print(f"\nDrawing {draw_mode} visualization from script.json...")
    print(f"Total players: {len(players)}")
    print(f"Total unassociated arrowheads: {len(unassociated_arrowheads)}")
  
    if draw_mode == "yolo":
        sam3_json_path = SAM3_RESULTS_JSON_PATH
        if os.path.exists(sam3_json_path):
            with open(sam3_json_path, 'r') as f:
                sam3_data = json.load(f)
            objects = sam3_data.get("objects", [])
            for obj in objects:
                mask_points = obj.get("mask_points", [])
                path_color = obj.get("color", [255, 0, 0])
                path_type = obj.get("type", "line")
                path_id = obj.get("id")
                draw_color = tuple(path_color)
                
                if path_type == "arrowhead":
                    image = draw_arrowhead(image, mask_points, draw_color, fill=True)
                else:
                    for point in mask_points:
                        x, y = point
                        cv2.circle(image, (int(x), int(y)), point_size, draw_color, -1)
                
                if len(mask_points) > 0:
                    points_array = np.array(mask_points)
                    centroid_x = int(np.mean(points_array[:, 0]))
                    centroid_y = int(np.mean(points_array[:, 1]))
                    label = f"{path_type.capitalize()}:{path_id}"
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.3,
                        1
                    )
                    padding = 2
                    cv2.rectangle(
                        image,
                        (centroid_x - padding, centroid_y - text_height - padding - baseline),
                        (centroid_x + text_width + padding, centroid_y + padding),
                        (255, 255, 255),
                        -1
                    )
                    cv2.putText(
                        image,
                        label,
                        (centroid_x, centroid_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.3,
                        draw_color,
                        1,
                        cv2.LINE_AA
                    )
    else:
        # Draw primary routes (solid lines)
        for player in players:
            if player.get("has_primary_routes", False):
                primary_routes = player.get("primary_routes", [])
                for route in primary_routes:
                    mask_points = route.get("mask_points", [])
                    if mask_points:
                        points_array = np.array(mask_points, dtype=np.int32)
                        if len(points_array) > 1:
                            cv2.polylines(image, [points_array], False, (0, 0, 0), 2)
                        
                        if route.get("has_arrowhead", False):
                            arrowhead = route.get("arrowhead", {})
                            arrowhead_points = arrowhead.get("mask_points", [])
                            if arrowhead_points:
                                image = draw_arrowhead(image, arrowhead_points, color=(0, 0, 0), fill=True)
        
        # Draw secondary routes (dotted lines)
        for player in players:
            if player.get("has_secondary_routes", False):
                secondary_routes = player.get("secondary_routes", [])
                for route in secondary_routes:
                    mask_points = route.get("mask_points", [])
                    if mask_points and len(mask_points) > 1:
                        for i in range(0, len(mask_points)-1, 3):
                            if i+1 < len(mask_points):
                                start_point = (int(mask_points[i][0]), int(mask_points[i][1]))
                                end_point = (int(mask_points[i+1][0]), int(mask_points[i+1][1]))
                                cv2.line(image, start_point, end_point, (100, 100, 100), 1, cv2.LINE_AA)
                        
                        branch_point = route.get("branch_point", [0, 0])
                        if branch_point:
                            cv2.circle(image, (int(branch_point[0]), int(branch_point[1])), 3, (255, 0, 0), -1)
        
        # Draw unassociated arrowheads
        for arrowhead in unassociated_arrowheads:
            mask_points = arrowhead.get("mask_points", [])
            if mask_points:
                if draw_mode == "white_shapes" or draw_mode == "final":
                    image = draw_arrowhead(image, mask_points, color=(0, 0, 0), fill=True)
                else:
                    arrowhead_color = arrowhead.get("color", [0, 0, 0])
                    image = draw_arrowhead(image, mask_points, color=tuple(arrowhead_color), fill=True)
  
    # Draw players and their alphabets
    for player in players:
        center = player.get("center", {"x": 0, "y": 0})
        cx = int(center.get("x", 0))
        cy = int(center.get("y", 0))
      
        if player["type"] == "circle":
            cv2.circle(image, (cx, cy), CIRCLE_RADIUS, (0, 0, 0), BORDER_THICKNESS)
          
            alphabet = player.get("alphabet")
            if alphabet:
                (text_width, text_height), baseline = cv2.getTextSize(
                    alphabet,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    FONT_SCALE,
                    FONT_THICKNESS
                )
                text_x = cx - text_width // 2
                text_y = cy + text_height // 2
              
                cv2.putText(
                    image,
                    alphabet,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    FONT_SCALE,
                    (0, 0, 0),
                    FONT_THICKNESS,
                    cv2.LINE_AA
                )
      
        elif player["type"] == "square":
            half = SQUARE_SIDE // 2
            cv2.rectangle(
                image,
                (cx - half, cy - half),
                (cx + half, cy + half),
                (0, 0, 0),
                BORDER_THICKNESS
            )
      
        if draw_mode == "yolo":
            bbox = player.get("bounding_box", {})
            x1 = bbox.get("x1", 0)
            y1 = bbox.get("y1", 0)
            x2 = bbox.get("x2", 0)
            y2 = bbox.get("y2", 0)
          
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
          
            if player["type"] == "circle":
                alphabet = player.get("alphabet")
                confidence = player.get("confidence")
                if alphabet and confidence:
                    label = f"{alphabet} ({confidence:.2f})"
                    cv2.putText(
                        image,
                        label,
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                        cv2.LINE_AA
                    )
  
    # Draw associated text
    for player in players:
        if player.get("has_associated_text", False):
            associated_text = player.get("associated_text", [])
          
            for text_elem in associated_text:
                label = text_elem.get("label", "")
                position = text_elem.get("position", {"x": 0, "y": 0})
              
                text_x = position.get("x", 0)
                text_y = position.get("y", 0)
              
                (text_width, text_height), baseline = cv2.getTextSize(
                    label,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    FONT_SCALE,
                    FONT_THICKNESS
                )
              
                text_x = text_x - text_width // 2
                text_y = text_y + text_height // 2
              
                if draw_mode == "yolo":
                    overlay = image.copy()
                    padding = 4
                    cv2.rectangle(
                        overlay,
                        (text_x - padding, text_y - text_height - padding),
                        (text_x + text_width + padding, text_y + padding),
                        (255, 0, 0),
                        -1
                    )
                    cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)
                  
                    cv2.putText(
                        image,
                        label,
                        (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        FONT_SCALE,
                        (255, 255, 255),
                        FONT_THICKNESS,
                        cv2.LINE_AA
                    )
                else:
                    cv2.putText(
                        image,
                        label,
                        (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        FONT_SCALE,
                        (0, 0, 0),
                        FONT_THICKNESS,
                        cv2.LINE_AA
                    )
  
    return image

def trim_path_at_arrowhead(path_points, arrowhead_centroid, arrowhead_points=None, validate_ownership=True):
    """
    Trim path at the point closest to its OWN arrowhead's centroid.
    """
    if not path_points or len(path_points) < 2:
        return path_points
    
    distances = []
    for point in path_points:
        dist = calculate_distance(point, arrowhead_centroid)
        distances.append(dist)
    
    min_index = distances.index(min(distances))
    min_distance = distances[min_index]
    
    if validate_ownership and arrowhead_points:
        path_length = calculate_distance(path_points[0], path_points[-1])
        if min_distance > path_length * 0.3:
            print(f"Warning: Arrowhead may not belong to this path (distance: {min_distance:.1f}px)")
    
    trimmed_points = path_points[:min_index + 1]
    
    print(f"    Trimmed at index {min_index}: Point {trimmed_points[-1]} (distance: {min_distance:.2f}px)")
    print(f"    Removed {len(path_points) - len(trimmed_points)} points after index {min_index}")
    
    return trimmed_points

def run_manim_animation(script_json_path=None, output_dir=None):
    """
    Run Manim animation for the given script.json and output directory.
    Returns the path to the rendered .mp4 file, or None on failure.

    When called from main() / server pipeline, script_json_path and output_dir
    are passed explicitly.  When called standalone (CLI --run-manim), they fall
    back to the module-level constants so nothing breaks.
    """
    # Resolve defaults
    if script_json_path is None:
        script_json_path = SCRIPT_JSON_PATH
    if output_dir is None:
        output_dir = OUTPUT_DIR

    print(f"\n{'='*70}")
    print("RUNNING MANIM ANIMATION")
    print(f"{'='*70}")
    print(f"JSON path : {script_json_path}")
    print(f"Output dir: {output_dir}")

    # manim.py lives in animators/ next to pipeline.py's parent (parsers/)
    script_dir   = os.path.dirname(os.path.abspath(__file__))          # parsers/
    backend_dir  = os.path.dirname(script_dir)                          # playbook-backend/
    manim_script = os.path.join(backend_dir, "animators", "manim.py")

    if not os.path.exists(manim_script):
        print(f"✗ manim.py not found at: {manim_script}")
        return None

    # Build env: inject the JSON path so manim.py picks it up via os.environ
    env = os.environ.copy()
    env["PLAYBOOK_JSON_PATH"] = script_json_path

    # Ask Manim to write media into <output_dir>/media
    media_dir = os.path.join(output_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    try:
        print(f"Running: manim -ql --media_dir {media_dir} --output_file output {manim_script} PlayerPlottingScene")

        result = subprocess.run(
            [
                "manim", "-ql",
                "--media_dir", media_dir,
                "--output_file", "output",
                manim_script,
                "PlayerPlottingScene",
            ],
            capture_output=True,
            text=True,
            cwd=output_dir,
            env=env,
            timeout=300,
        )

        if result.returncode != 0:
            print(f"✗ Manim failed (exit {result.returncode})")
            print(result.stderr[-3000:])
            return None

        print("✓ Manim animation completed successfully!")

        # Walk the media dir to find the rendered .mp4
        video_path = None
        for root, _, files in os.walk(media_dir):
            for f in files:
                if f.endswith(".mp4"):
                    video_path = os.path.join(root, f)
                    break
            if video_path:
                break

        if video_path:
            print(f"✓ Video file: {video_path}")
        else:
            print("✗ No .mp4 found after Manim render")

        return video_path

    except subprocess.TimeoutExpired:
        print("✗ Manim timed out (>5 min)")
        return None
    except FileNotFoundError:
        print("✗ 'manim' command not found. Install with: pip install manim")
        return None

def main():
    # ── Resolve paths: env vars injected by server.py take priority ──────────────
    image_path = os.environ.get("PIPELINE_IMAGE_PATH", _DEFAULT_IMAGE_PATH)
    output_dir = os.environ.get("PIPELINE_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)

    # Recompute all derived paths against the (possibly overridden) output_dir
    yolo_output_path       = os.path.join(output_dir, "yolo_output.png")
    white_shapes_path      = os.path.join(output_dir, "white_shapes.png")
    players_only_out_path  = os.path.join(output_dir, "final_output.png")
    cropped_dir            = os.path.join(output_dir, "circles")
    player_json_path       = os.path.join(output_dir, "player.json")
    text_json_path         = os.path.join(output_dir, "text.json")
    sam3_results_json_path = os.path.join(output_dir, "sam3_results.json")
    script_json_path       = os.path.join(output_dir, "script.json")

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(cropped_dir, exist_ok=True)

    print("="*70)
    print("PHASE 1: GENERATING ALL JSON FILES")
    print("="*70)
  
    print(f"\nLoading image: {image_path}")
    image = cv2.imread(image_path)
    h, w, _ = image.shape
    print(f"Image dimensions: {w}x{h}")
    
    print("\n" + "="*70)
    print("STEP 1: Running SAM3 segmentation and generating JSON")
    print("="*70)
  
    print("\nLoading SAM3 models...")
    sam3_model, sam3_processor, device, dtype = load_sam3_models(SAM3_MODEL_PATH)
  
    print("\nRunning SAM3 segmentation for 'line'...")
    line_objects_json = process_with_sam3(
        image_path, sam3_model, sam3_processor, device,
        text_prompt="line", line_type="line"
    )
  
    print("\nRunning SAM3 segmentation for 'dotted line'...")
    dotted_line_objects_json = process_with_sam3(
        image_path, sam3_model, sam3_processor, device,
        text_prompt="dotted line", line_type="dotted line"
    )
  
    print("\nRunning SAM3 segmentation for 'arrowhead'...")
    arrowhead_objects_json = process_with_sam3(
        image_path, sam3_model, sam3_processor, device,
        text_prompt="arrowhead", line_type="arrowhead"
    )
  
    all_sam3_objects = []
    all_sam3_objects.extend(line_objects_json)
  
    id_offset = len(line_objects_json)
    for obj in dotted_line_objects_json:
        obj["id"] = obj["id"] + id_offset
        all_sam3_objects.append(obj)
    
    id_offset = len(all_sam3_objects)
    for obj in arrowhead_objects_json:
        obj["id"] = obj["id"] + id_offset
        all_sam3_objects.append(obj)
  
    if all_sam3_objects:
        print(f"\n✓ Saving SAM3 JSON to: {sam3_results_json_path}")
        print(f" Total objects: {len(all_sam3_objects)}")
        print(f" - Solid lines: {len(line_objects_json)}")
        print(f" - Dotted lines: {len(dotted_line_objects_json)}")
        print(f" - Arrowheads: {len(arrowhead_objects_json)}")
        save_sam3_json_compact(sam3_results_json_path, all_sam3_objects, points_per_line=30)
    else:
        print("\n✗ No SAM3 objects detected")
  
    print("\n" + "="*70)
    print("STEP 2: Running YOLO detection and alphabet recognition")
    print("="*70)
  
    print("\nLoading YOLO models...")
    yolo_model = YOLO(YOLO_MODEL_PATH)
    alphabet_model = YOLO(YOLO_ALPHABET_MODEL_PATH)
  
    print("Running YOLO detection...")
    yolo_results = yolo_model(
        image_path,
        conf=0.25,
        iou=0.5,
        device="mps" if torch.backends.mps.is_available() else "cpu"
    )
  
    print("\nProcessing player detections and detecting alphabets...")
    circle_count = 0
    square_count = 0
    player_data = []
  
    for r in yolo_results:
        boxes = r.boxes
        names = r.names
      
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            cls_name = names[cls_id].lower()
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
          
            if cls_name == "circle":
                crop = image[y1:y2, x1:x2]
                crop_path = os.path.join(cropped_dir, f"circle_{circle_count}.png")
                cv2.imwrite(crop_path, crop)
              
                alphabet_detection = detect_alphabet_in_circle(crop, alphabet_model, circle_count)
              
                player_info = {
                    "player_id": circle_count,
                    "type": "circle",
                    "bounding_box": {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2
                    },
                    "center": {
                        "x": cx,
                        "y": cy
                    },
                    "cropped_image_path": crop_path
                }
              
                if alphabet_detection:
                    player_info["alphabet"] = alphabet_detection["class"]
                    player_info["confidence"] = round(alphabet_detection["confidence"], 4)
                else:
                    player_info["alphabet"] = None
                    player_info["confidence"] = None
              
                player_data.append(player_info)
                circle_count += 1
              
            elif cls_name == "square":
                player_info = {
                    "player_id": circle_count + square_count,
                    "type": "square",
                    "bounding_box": {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2
                    },
                    "center": {
                        "x": cx,
                        "y": cy
                    },
                    "alphabet": None,
                    "confidence": None
                }
                player_data.append(player_info)
                square_count += 1
  
    if player_data:
        with open(player_json_path, 'w') as f:
            json.dump({"players": player_data}, f, indent=2)
        print(f"\n✓ Player JSON saved to: {player_json_path}")
        print(f" Total players: {len(player_data)} (Circles: {circle_count}, Squares: {square_count})")
    else:
        print("\n✗ No players detected")
  
    print("\n" + "="*70)
    print("STEP 3: Running OCR and generating text JSON (with offensive line pattern filtering)")
    print("="*70)
  
    print("\nRunning EasyOCR...")
    reader = easyocr.Reader(['en'], gpu=True)
    ocr_results = reader.readtext(image_path)
  
    print(f"Found {len(ocr_results)} text elements with OCR")
    text_data = []
    filtered_count = 0
  
    for idx, (bbox, text, prob) in enumerate(ocr_results):
        if is_offensive_line_pattern(text):
            print(f" ✗ Filtered out offensive line pattern: '{text}'")
            filtered_count += 1
            continue
      
        bbox = np.array(bbox, dtype=np.int32)
        x_min, y_min = bbox[:, 0].min(), bbox[:, 1].min()
        x_max, y_max = bbox[:, 0].max(), bbox[:, 1].max()
      
        (text_width, text_height), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, FONT_THICKNESS
        )
      
        text_info = {
            "text_id": len(text_data),
            "label": text,
            "confidence": round(float(prob), 4),
            "bounding_box": {
                "x_min": int(x_min),
                "y_min": int(y_min),
                "x_max": int(x_max),
                "y_max": int(y_max)
            },
            "size": {
                "width": text_width,
                "height": text_height
            },
            "position": {
                "x": int((x_min + x_max) // 2),
                "y": int((y_min + y_max) // 2)
            }
        }
        text_data.append(text_info)
        print(f" ✓ Valid text: '{text}'")
  
    if text_data:
        with open(text_json_path, 'w') as f:
            json.dump({"text_elements": text_data}, f, indent=2)
        print(f"\n✓ Text JSON saved to: {text_json_path}")
        print(f" Total valid text elements: {len(text_data)}")
        print(f" Filtered offensive line patterns: {filtered_count}")
    else:
        print("\n✗ No valid text elements detected")
  
    print("\n" + "="*70)
    print("STEP 4: TWO-PHASE PATH ASSOCIATION")
    print("="*70)
    
    # ============ PHASE 1: SOLID LINE ASSOCIATION ============
    player_solid_associations = associate_solid_lines_to_players(
        player_json_path,
        sam3_results_json_path,
        max_distance=SOLID_LINE_ASSOCIATION_DISTANCE,
        check_points=PATH_CHECK_POINTS
    )
    
    # Build primary chains for dotted line association
    primary_chains_data = build_primary_chains(player_solid_associations, sam3_results_json_path)
    
    # ============ PHASE 2: DOTTED LINE ASSOCIATION ============
    player_dotted_associations = associate_dotted_lines_to_players(
        player_solid_associations,
        sam3_results_json_path,
        primary_chains_data,
        max_distance=DOTTED_LINE_ASSOCIATION_DISTANCE
    )
  
    print("\n" + "="*70)
    print("STEP 4.5: ASSOCIATING ARROWHEADS TO PRIMARY ROUTES")
    print("="*70)
  
    path_to_arrowhead_map = associate_arrowheads_to_paths(
        player_solid_associations,
        sam3_results_json_path,
        max_distance=ARROWHEAD_TO_PATH_MAX_DISTANCE,
        tail_percentage=PATH_TAIL_PERCENTAGE
    )
  
    print("\n" + "="*70)
    print("STEP 4.6: TRIMMING PATHS AT ARROWHEADS")
    print("="*70)
    print("Note: Primary routes will be trimmed at the point closest to the arrowhead centroid")
  
    print("\n" + "="*70)
    print("STEP 5: ASSOCIATING TEXT TO PLAYERS")
    print("="*70)
  
    text_to_player_map = associate_text_to_players(
        player_json_path,
        text_json_path,
        sam3_results_json_path,
        player_solid_associations
    )
  
    print("\n" + "="*70)
    print("STEP 6: CREATING SCRIPT.JSON WITH TWO-PHASE PATH ASSOCIATION")
    print("="*70)
  
    create_script_json(
        player_json_path,
        sam3_results_json_path,
        text_json_path,
        player_solid_associations,
        player_dotted_associations,
        path_to_arrowhead_map,
        text_to_player_map,
        script_json_path,
        w,
        h,
        points_per_line=30
    )
  
    print("\n" + "="*70)
    print("PHASE 2: DRAWING ALL OUTPUT IMAGES FROM SCRIPT.JSON")
    print("="*70)
  
    print("\n" + "-"*70)
    print("Creating YOLO Output Image (colored visualization from script.json)")
    print("-"*70)
  
    yolo_output_image = image.copy()
    yolo_output_image = draw_from_script_json(
        yolo_output_image,
        script_json_path,
        draw_mode="yolo",
        point_size=1,
        is_white_background=False
    )
  
    cv2.imwrite(yolo_output_path, yolo_output_image)
    print(f"\n✓ YOLO output image saved to: {yolo_output_path}")
  
    print("\n" + "-"*70)
    print("Creating White Shapes Image (clean diagram from script.json)")
    print("-"*70)
  
    white_image = np.ones((h, w, 3), dtype=np.uint8) * 255
    white_image = draw_from_script_json(
        white_image,
        script_json_path,
        draw_mode="white_shapes",
        point_size=1,
        is_white_background=True
    )
  
    cv2.imwrite(white_shapes_path, white_image)
    print(f"\n✓ White shapes image saved to: {white_shapes_path}")
  
    print("\n" + "-"*70)
    print("Creating Final Output Image (players with primary/secondary routes and text from script.json)")
    print("-"*70)
  
    final_output_image = np.ones((h, w, 3), dtype=np.uint8) * 255
    final_output_image = draw_from_script_json(
        final_output_image,
        script_json_path,
        draw_mode="final",
        point_size=1,
        is_white_background=True
    )
  
    cv2.imwrite(players_only_out_path, final_output_image)
    print(f"\n✓ Final output image saved to: {players_only_out_path}")
  
    print("\n" + "="*70)
    print("PROCESSING COMPLETE")
    print("="*70)
    print(f"\nJSON Files Generated:")
    print(f" 1. {sam3_results_json_path}")
    print(f" 2. {player_json_path}")
    print(f" 3. {text_json_path}")
    print(f" 4. {script_json_path}")
    print(f"\nOutput Images Generated (ALL FROM SCRIPT.JSON):")
    print(f" 1. {yolo_output_path}")
    print(f" 2. {white_shapes_path}")
    print(f" 3. {players_only_out_path}")
    print("="*70)

    # ── Always run Manim after a successful pipeline run ─────────────────────────
    # (server.py relies on the video being produced here so it can serve it back)
    video_path = run_manim_animation(
        script_json_path=script_json_path,
        output_dir=output_dir,
    )
    if video_path:
        print(f"\n✓ Animation video ready: {video_path}")
        # Write the video path to a known file so server.py can locate it
        # even if the walk order differs across platforms
        video_path_file = os.path.join(output_dir, "video_path.txt")
        with open(video_path_file, "w") as vf:
            vf.write(video_path)
        print(f"✓ Video path written to: {video_path_file}")
    else:
        print("\n✗ Manim animation failed or was skipped.")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run YOLO detection and optionally Manim animation')
    parser.add_argument('--run-manim', action='store_true', 
                       help='Automatically run Manim animation after processing')
    args = parser.parse_args()
    
    os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
    
    main()
    
    if args.run_manim:
        run_manim_animation()
    else:
        print("\nManim animation not run. Use --run-manim flag to execute it automatically.")
        print("Or run manually with: manim -pqh manim.py PlayerPlottingScene")