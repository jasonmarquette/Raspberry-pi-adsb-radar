#!/usr/bin/env python3

import math
import time
import os
import requests
import configparser
import argparse
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# Plane Radar Pi - Proof of Concept
# Raspberry Pi 4B + GC9A01 240x240 + HDMI framebuffer display
# ============================================================


# -----------------------------
# USER CONFIG
# -----------------------------

# Config file path.
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.ini")


def parse_args():
    parser = argparse.ArgumentParser(description="Plane Radar Pi display")
    parser.add_argument(
        "--display",
        choices=["framebuffer", "hdmi", "preview"],
        default=None,
        help="Display output mode. framebuffer writes to /dev/fb0, hdmi opens a fullscreen HDMI window, preview only saves preview PNG.",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Use a normal resizable HDMI window instead of fullscreen. Only used with --display hdmi.",
    )
    return parser.parse_args()


def load_config():
    config = configparser.ConfigParser()

    radar_defaults = {
        "center_lat": "30.14705507846894",
        "center_lon": "-95.39204791784302",
        "range_mi": "10",
        "refresh_seconds": "5",
    }

    display_defaults = {
        # Framebuffer display settings.
        "device": "/dev/fb0",
        "write_framebuffer": "true",

        # Remote preview image settings.
        "save_preview": "false",
        "preview_file": "/tmp/plane-radar-preview.png",

        # Aircraft heading line settings.
        "show_heading_lines": "true",
        "heading_line_length": "26",
        "heading_line_gap": "7",
        "heading_line_width": "2",
    }

    config["radar"] = radar_defaults
    config["display"] = display_defaults

    config.read(CONFIG_PATH)

    radar_config = config["radar"]
    display_config = config["display"]

    return {
        "center_lat": radar_config.getfloat("center_lat"),
        "center_lon": radar_config.getfloat("center_lon"),
        "range_mi": radar_config.getfloat("range_mi"),
        "refresh_seconds": radar_config.getint("refresh_seconds"),

        "display_device": display_config.get("device"),
        "write_framebuffer": display_config.getboolean("write_framebuffer"),

        "save_preview": display_config.getboolean("save_preview"),
        "preview_file": display_config.get("preview_file"),

        "show_heading_lines": display_config.getboolean("show_heading_lines"),
        "heading_line_length": display_config.getint("heading_line_length"),
        "heading_line_gap": display_config.getint("heading_line_gap"),
        "heading_line_width": display_config.getint("heading_line_width"),
    }


APP_CONFIG = load_config()
ARGS = parse_args()

DISPLAY_MODE = ARGS.display
if DISPLAY_MODE is None:
    DISPLAY_MODE = "framebuffer" if APP_CONFIG["write_framebuffer"] else "preview"

# Your selected radar center.
CENTER_LAT = APP_CONFIG["center_lat"]
CENTER_LON = APP_CONFIG["center_lon"]

# Radar/API range in miles.
# Smaller range = fewer aircraft.
RANGE_MI = APP_CONFIG["range_mi"]

# Refresh rate in seconds.
REFRESH_SECONDS = APP_CONFIG["refresh_seconds"]

# Your GC9A01 display is exposed by the Pi overlay as /dev/fb0.
FRAMEBUFFER = APP_CONFIG["display_device"]
WRITE_FRAMEBUFFER = APP_CONFIG["write_framebuffer"] and DISPLAY_MODE == "framebuffer"

# Optional preview PNG for checking the radar image remotely.
SAVE_PREVIEW = APP_CONFIG["save_preview"]
PREVIEW_FILE = APP_CONFIG["preview_file"]

# Aircraft heading line options.
SHOW_HEADING_LINES = APP_CONFIG["show_heading_lines"]
HEADING_LINE_LENGTH = APP_CONFIG["heading_line_length"]
HEADING_LINE_GAP = APP_CONFIG["heading_line_gap"]
HEADING_LINE_WIDTH = APP_CONFIG["heading_line_width"]

# Temporary image path used by older display methods.
IMAGE_PATH = "/tmp/plane-radar.png"


# -----------------------------
# DISPLAY LAYOUT
# -----------------------------

WIDTH = 240
HEIGHT = 240
DRAW_SCALE = 1.0

# Move radar slightly up to avoid bottom clipping on the round SPI display.
CENTER_X = WIDTH // 2
CENTER_Y = (HEIGHT // 2) - 4

# Smaller radar circle to fit safely on round display.
RADAR_RADIUS = 112

# Colors
COLOR_BG = (2, 8, 20)
COLOR_RING_MAJOR = (0, 180, 90)
COLOR_RING_MINOR = (0, 80, 60)
COLOR_TEXT = (220, 220, 220)
COLOR_TEXT_DIM = (160, 210, 170)
COLOR_OWN_SHIP = (255, 255, 255)
COLOR_AIRCRAFT = (255, 70, 70)
COLOR_HEADING_LINE = (180, 80, 255)
COLOR_LABEL = (235, 235, 235)
COLOR_TYPE = (255, 190, 80)
COLOR_ALTITUDE = (80, 200, 255)
COLOR_WARN = (255, 190, 80)


# -----------------------------
# FONT HELPERS
# -----------------------------

def load_font(size, bold=False):
    paths = []

    if bold:
        paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

    paths.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ])

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


# Font objects are initialized by configure_layout().
FONT_TINY = load_font(10)
FONT_SMALL = load_font(10)
FONT_MED = load_font(12)
FONT_BOLD = load_font(12, bold=True)


def scaled(value, minimum=1):
    return max(minimum, int(round(value * DRAW_SCALE)))


def configure_layout(width=240, height=240, mode="framebuffer"):
    """
    Configure drawing size.

    Framebuffer mode renders the original 240x240 image for the GC9A01.
    HDMI mode renders at the HDMI window/screen size instead of drawing 240x240
    and scaling it up. This removes the pixelated look.
    """
    global WIDTH, HEIGHT, DRAW_SCALE, CENTER_X, CENTER_Y, RADAR_RADIUS
    global FONT_TINY, FONT_SMALL, FONT_MED, FONT_BOLD

    WIDTH = int(width)
    HEIGHT = int(height)
    DRAW_SCALE = min(WIDTH, HEIGHT) / 240.0

    CENTER_X = WIDTH // 2

    if mode == "framebuffer":
        CENTER_Y = (HEIGHT // 2) - scaled(4, 0)
        RADAR_RADIUS = min(WIDTH, HEIGHT) // 2 - scaled(8)
    else:
        CENTER_Y = HEIGHT // 2
        RADAR_RADIUS = min(WIDTH, HEIGHT) // 2 - scaled(36)

    # Scale fonts for HDMI so text is sharp instead of enlarged from 240px.
    FONT_TINY = load_font(scaled(10, 8))
    FONT_SMALL = load_font(scaled(10, 8))
    FONT_MED = load_font(scaled(12, 9))
    FONT_BOLD = load_font(scaled(12, 9), bold=True)


# -----------------------------
# GEO MATH
# -----------------------------

def haversine_mi(lat1, lon1, lat2, lon2):
    """
    Distance between two lat/lon points in statute miles.
    """
    earth_radius_mi = 3958.8

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_mi * c


def bearing_deg(lat1, lon1, lat2, lon2):
    """
    Bearing from point 1 to point 2.
    0 degrees = north, 90 = east.
    """
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)

    y = math.sin(dl) * math.cos(p2)
    x = (
        math.cos(p1) * math.sin(p2)
        - math.sin(p1) * math.cos(p2) * math.cos(dl)
    )

    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360


def polar_to_screen(distance_mi, bearing, max_range_mi):
    """
    Convert distance/bearing into x/y screen position.
    """
    scale = min(distance_mi / max_range_mi, 1.0)
    radius = scale * RADAR_RADIUS

    angle = math.radians(bearing)

    x = CENTER_X + math.sin(angle) * radius
    y = CENTER_Y - math.cos(angle) * radius

    return int(x), int(y)


# -----------------------------
# ADS-B DATA
# -----------------------------

def fetch_aircraft():
    """
    Fetch aircraft near the configured location.

    opendata.adsb.fi returns aircraft in the top-level "ac" array.

    Returns:
        list[dict] on success.
        None on temporary failure, such as HTTP 429 rate limiting.

    Returning None lets the main loop keep showing the last good
    aircraft list instead of blanking the radar screen.
    """
    url = (
        f"https://opendata.adsb.fi/api/v3/lat/{CENTER_LAT}/"
        f"lon/{CENTER_LON}/dist/{RANGE_MI}"
    )

    try:
        response = requests.get(url, timeout=8)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")

            if retry_after:
                print(
                    "ADS-B fetch rate limited: 429 Too Many Requests "
                    f"| Retry-After: {retry_after}s | keeping last good data"
                )
            else:
                print(
                    "ADS-B fetch rate limited: 429 Too Many Requests "
                    "| keeping last good data"
                )

            return None

        response.raise_for_status()
        data = response.json()

        aircraft = data.get("ac", [])

        print(
            f"API aircraft: {len(aircraft)} | "
            f"API total: {data.get('total', 'n/a')}"
        )

        return aircraft

    except Exception as e:
        print(f"ADS-B fetch failed: {e} | keeping last good data")
        return None


# -----------------------------
# AIRCRAFT FIELD HELPERS
# -----------------------------

def format_altitude(ac):
    """
    Format altitude in feet.

    Example:
    2500 ft -> 2500 ft
    """
    alt = ac.get("alt_baro")

    if alt is None or alt == "ground":
        alt = ac.get("alt_geom")

    if alt == "ground":
        return "GND"

    if isinstance(alt, int) or isinstance(alt, float):
        return f"{int(round(alt))} ft"

    return ""


def get_callsign(ac):
    callsign = (
        ac.get("flight")
        or ac.get("r")
        or ac.get("hex")
        or ""
    )

    return str(callsign).strip()


def get_aircraft_type(ac):
    """
    Return aircraft type/designator if available.
    Examples: A319, B738, BCS3, P28A
    """
    aircraft_type = (
        ac.get("t")
        or ac.get("type")
        or ac.get("desc")
        or ""
    )

    return str(aircraft_type).strip()


def get_aircraft_heading(ac):
    """
    Try common ADS-B heading/track fields.
    Returns heading in degrees, or None if unavailable.

    For this display, track is usually the best field because it shows
    where the aircraft is moving over the ground.
    """
    for key in ("track", "true_track", "heading", "mag_heading", "nav_heading"):
        value = ac.get(key)

        if value is None:
            continue

        try:
            return float(value) % 360
        except (TypeError, ValueError):
            continue

    return None


# -----------------------------
# DRAWING HELPERS
# -----------------------------

def draw_centered_text(draw, text, center_x, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, y), text, font=font, fill=fill)


def draw_heading_line(draw, x, y, heading_deg):
    """
    Draw a heading line in front of the aircraft symbol.

    heading_deg is degrees clockwise from north:
    0 = north/up, 90 = east/right, 180 = south/down, 270 = west/left.
    """
    if not SHOW_HEADING_LINES:
        return

    if heading_deg is None:
        return

    try:
        heading_deg = float(heading_deg)
    except (TypeError, ValueError):
        return

    radians = math.radians(heading_deg)

    dx = math.sin(radians)
    dy = -math.cos(radians)

    gap = scaled(HEADING_LINE_GAP)
    length = scaled(HEADING_LINE_LENGTH)

    start_x = x + dx * gap
    start_y = y + dy * gap

    end_x = x + dx * length
    end_y = y + dy * length

    draw.line(
        [(start_x, start_y), (end_x, end_y)],
        fill=COLOR_HEADING_LINE,
        width=scaled(HEADING_LINE_WIDTH),
    )


def draw_aircraft_symbol(draw, x, y, track):
    """
    Draw a small aircraft triangle. If no track is available, draw a dot.
    """
    dot_radius = scaled(3)

    if track is None:
        draw.ellipse((x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius), fill=COLOR_AIRCRAFT)
        return

    try:
        track = float(track)
    except (TypeError, ValueError):
        draw.ellipse((x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius), fill=COLOR_AIRCRAFT)
        return

    # Draw the heading line first so the aircraft triangle appears on top of it.
    draw_heading_line(draw, x, y, track)

    heading = math.radians(track)
    size = scaled(7)

    nose = (
        int(x + math.sin(heading) * size),
        int(y - math.cos(heading) * size),
    )

    left = (
        int(x + math.sin(heading + 2.4) * size),
        int(y - math.cos(heading + 2.4) * size),
    )

    right = (
        int(x + math.sin(heading - 2.4) * size),
        int(y - math.cos(heading - 2.4) * size),
    )

    draw.polygon([nose, left, right], fill=COLOR_AIRCRAFT)


def draw_aircraft_label(draw, x, y, callsign, aircraft_type, altitude, label_index):
    """
    Draw:
    line 1 = callsign in white
    line 2 = aircraft type in orange
    line 3 = altitude in blue
    """
    callsign = str(callsign).strip()[:8] if callsign else ""
    aircraft_type = str(aircraft_type).strip()[:8] if aircraft_type else ""
    altitude = str(altitude).strip() if altitude else ""

    lines = []

    if callsign:
        lines.append((callsign, COLOR_LABEL))

    if aircraft_type:
        lines.append((aircraft_type, COLOR_TYPE))

    if altitude:
        lines.append((altitude, COLOR_ALTITUDE))

    if not lines:
        return

    line_gap = scaled(1)
    line_height = scaled(11)

    text_width = 0

    for line_text, _ in lines:
        bbox = draw.textbbox((0, 0), line_text, font=FONT_TINY)
        text_width = max(text_width, bbox[2] - bbox[0])

    text_height = len(lines) * line_height + (len(lines) - 1) * line_gap

    # Default: place label to right of aircraft.
    tx = x + scaled(7)
    ty = y - scaled(10)

    # If near right edge, place label to left.
    if tx + text_width > WIDTH - scaled(4):
        tx = x - text_width - scaled(7)

    # Keep inside top/bottom safe area.
    if ty < scaled(4):
        ty = y + scaled(7)

    if ty + text_height > HEIGHT - scaled(6):
        ty = HEIGHT - scaled(6) - text_height

    # Slight alternating offset to reduce overlap.
    if label_index % 2 == 1:
        ty += scaled(5)

    for i, (line_text, line_color) in enumerate(lines):
        draw.text(
            (tx, ty + i * (line_height + line_gap)),
            line_text,
            fill=line_color,
            font=FONT_TINY,
        )


# -----------------------------
# RADAR DRAWING
# -----------------------------

def draw_radar(aircraft):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Main radar circle.
    draw.ellipse(
        (
            CENTER_X - RADAR_RADIUS,
            CENTER_Y - RADAR_RADIUS,
            CENTER_X + RADAR_RADIUS,
            CENTER_Y + RADAR_RADIUS,
        ),
        outline=COLOR_RING_MAJOR,
        width=scaled(2),
    )

    # Range rings.
    ring_fracs = [0.50, 0.75]

    for frac in ring_fracs:
        rr = int(RADAR_RADIUS * frac)
        ring_range = int(RANGE_MI * frac)

        draw.ellipse(
            (CENTER_X - rr, CENTER_Y - rr, CENTER_X + rr, CENTER_Y + rr),
            outline=COLOR_RING_MINOR,
            width=scaled(1),
        )

       
    # Crosshairs.
    draw.line(
        (CENTER_X, CENTER_Y - RADAR_RADIUS, CENTER_X, CENTER_Y + RADAR_RADIUS),
        fill=COLOR_RING_MINOR,
    )
    draw.line(
        (CENTER_X - RADAR_RADIUS, CENTER_Y, CENTER_X + RADAR_RADIUS, CENTER_Y),
        fill=COLOR_RING_MINOR,
    )

    # Cardinal direction labels.
    draw_centered_text(draw, "N", CENTER_X, scaled(4), FONT_BOLD, COLOR_TEXT)
    draw_centered_text(draw, "S", CENTER_X, HEIGHT - scaled(29), FONT_MED, COLOR_TEXT)
    draw.text((WIDTH - scaled(18), CENTER_Y - scaled(7)), "E", fill=COLOR_TEXT, font=FONT_MED)
    draw.text((scaled(7), CENTER_Y - scaled(7)), "W", fill=COLOR_TEXT, font=FONT_MED)

    # Radar range label.
    draw.text(
        (scaled(8), HEIGHT - scaled(17)),
        f"Range: {RANGE_MI:g} mi",
        fill=COLOR_TEXT_DIM,
        font=FONT_SMALL,
    )
    
    # Own location / center dot.
    draw.ellipse(
        (CENTER_X - scaled(3), CENTER_Y - scaled(3), CENTER_X + scaled(3), CENTER_Y + scaled(3)),
        fill=COLOR_OWN_SHIP,
    )

    

    plotted = 0
    labeled = 0

    for ac in aircraft:
        lat = ac.get("lat")
        lon = ac.get("lon")

        if lat is None or lon is None:
            continue

        # For testing, do not hide ground aircraft.
        # Uncomment later if you want to hide them.
        # if ac.get("gnd") is True:
        #     continue

        distance = haversine_mi(CENTER_LAT, CENTER_LON, lat, lon)

        if distance > RANGE_MI:
            continue

        bearing = bearing_deg(CENTER_LAT, CENTER_LON, lat, lon)
        x, y = polar_to_screen(distance, bearing, RANGE_MI)

        track = get_aircraft_heading(ac)
        draw_aircraft_symbol(draw, x, y, track)

        callsign = get_callsign(ac)
        aircraft_type = get_aircraft_type(ac)
        altitude = format_altitude(ac)

        # Label only first several targets to avoid clutter.
        if labeled < 8:
            draw_aircraft_label(draw, x, y, callsign, aircraft_type, altitude, labeled)
            labeled += 1

        plotted += 1

    return img, plotted


# -----------------------------
# DISPLAY OUTPUT
# -----------------------------

def init_hdmi_display():
    """
    Open the active HDMI desktop display using pygame.
    This is only used when launched with --display hdmi.
    """
    if DISPLAY_MODE != "hdmi":
        return None

    try:
        import pygame
    except ImportError as exc:
        raise SystemExit(
            "pygame is required for HDMI mode. Install it with: sudo apt install python3-pygame"
        ) from exc

    pygame.init()
    pygame.display.set_caption("Plane Radar Pi")
    pygame.mouse.set_visible(False)

    if ARGS.windowed:
        screen = pygame.display.set_mode((960, 960), pygame.RESIZABLE)
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    return pygame, screen


def show_on_hdmi(img, hdmi):
    """
    Show the Pillow radar image on the HDMI desktop.
    Show the radar at native HDMI resolution.
    If the image already matches the target square, no scaling is done.
    """
    if DISPLAY_MODE != "hdmi" or hdmi is None:
        return False

    pygame, screen = hdmi

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            raise KeyboardInterrupt
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
            raise KeyboardInterrupt

    screen_width, screen_height = screen.get_size()
    scale_size = min(screen_width, screen_height)

    surface = pygame.image.fromstring(img.convert("RGB").tobytes(), img.size, "RGB")
    if img.size != (scale_size, scale_size):
        surface = pygame.transform.smoothscale(surface, (scale_size, scale_size))

    screen.fill(COLOR_BG)
    x = (screen_width - scale_size) // 2
    y = (screen_height - scale_size) // 2
    screen.blit(surface, (x, y))
    pygame.display.flip()

    return True


def image_to_rgb565_bytes(img):
    """
    Convert a Pillow RGB image to RGB565 little-endian bytes.

    Most small SPI framebuffer displays on Raspberry Pi use RGB565.
    """
    img = img.convert("RGB")
    rgb = img.tobytes()

    output = bytearray()

    for i in range(0, len(rgb), 3):
        r = rgb[i]
        g = rgb[i + 1]
        b = rgb[i + 2]

        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

        # Little-endian RGB565
        output.append(value & 0xFF)
        output.append((value >> 8) & 0xFF)

    return bytes(output)

def save_preview_image(img):
    """
    Save a PNG copy of the radar image so it can be copied to another computer.
    """
    if not SAVE_PREVIEW:
        return

    preview_dir = os.path.dirname(PREVIEW_FILE)

    if preview_dir:
        os.makedirs(preview_dir, exist_ok=True)

    img.save(PREVIEW_FILE)


def show_on_display(img):
    """
    Write the radar image directly to the Linux framebuffer.

    This avoids the flicker caused by repeatedly launching fbi.
    """
    if not WRITE_FRAMEBUFFER:
        return

    frame = image_to_rgb565_bytes(img)

    with open(FRAMEBUFFER, "wb", buffering=0) as fb:
        fb.write(frame)


# -----------------------------
# MAIN LOOP
# -----------------------------

def main():
    print("Starting Plane Radar Pi...")
    print(f"Center: {CENTER_LAT}, {CENTER_LON}")
    print(f"Range: {RANGE_MI} mi")
    print(f"Display mode: {DISPLAY_MODE}")
    print(f"Framebuffer device: {FRAMEBUFFER}")
    print(f"Write framebuffer: {WRITE_FRAMEBUFFER}")
    print(f"Save preview: {SAVE_PREVIEW}")
    if SAVE_PREVIEW:
        print(f"Preview file: {PREVIEW_FILE}")
    print(f"Heading lines: {SHOW_HEADING_LINES}")
    print("Press Ctrl+C to stop. Press Esc or q to quit HDMI mode.")

    hdmi = init_hdmi_display()

    if DISPLAY_MODE == "hdmi" and hdmi is not None:
        _, screen = hdmi
        screen_width, screen_height = screen.get_size()
        radar_size = min(screen_width, screen_height)
        configure_layout(radar_size, radar_size, mode="hdmi")
        print(f"HDMI screen: {screen_width}x{screen_height}")
        print(f"HDMI radar render size: {WIDTH}x{HEIGHT}")
    else:
        configure_layout(240, 240, mode="framebuffer")

    last_good_aircraft = []
    last_good_fetch_time = None

    while True:
        fetched_aircraft = fetch_aircraft()

        if fetched_aircraft is not None:
            last_good_aircraft = fetched_aircraft
            last_good_fetch_time = time.time()
            aircraft = fetched_aircraft
            using_cached_data = False
        else:
            aircraft = last_good_aircraft
            using_cached_data = True

        img, plotted = draw_radar(aircraft)

        save_preview_image(img)
        show_on_hdmi(img, hdmi)
        show_on_display(img)

        if using_cached_data:
            if last_good_fetch_time is None:
                print(f"Plotted targets: {plotted} using cached data: no successful fetch yet")
            else:
                cache_age = int(time.time() - last_good_fetch_time)
                print(f"Plotted targets: {plotted} using cached data: {cache_age}s old")
        else:
            print(f"Plotted targets: {plotted}")

        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
