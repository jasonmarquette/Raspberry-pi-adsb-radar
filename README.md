# Plane Radar Pi

A Raspberry Pi 4B proof-of-concept port of an ESP32 live ADS-B plane radar project. This version uses a 1.28 inch round GC9A01 240×240 SPI TFT display connected to a Raspberry Pi and shows nearby aircraft on a circular radar-style screen.

The display is driven through the Raspberry Pi Linux framebuffer using the built-in GC9A01 device tree overlay. Aircraft data is fetched from the public ADS-B API at opendata.adsb.fi.

## Project Overview

This project displays nearby aircraft on a small round TFT screen.

It shows:

* aircraft position relative to a fixed center point
* aircraft heading as a small triangle
* callsign or registration
* altitude on a second line under the callsign
* radar range rings
* north/south/east/west markers
* live aircraft count
* configurable radar range
* configurable radar center latitude and longitude

The current setup was built and tested on:

* Raspberry Pi 4B
* Raspberry Pi OS
* GC9A01 1.28 inch round SPI display
* Python virtual environment
* Linux framebuffer `/dev/fb0`

## Hardware Used

* Raspberry Pi 4B
* 1.28 inch round TFT LCD display

  * 240×240 resolution
  * GC9A01 driver
  * SPI interface
  * 3.3V/5V compatible module
* Jumper wires
* MicroSD card with Raspberry Pi OS
* Internet connection

## Display Wiring

| GC9A01 Display Pin | Raspberry Pi 4B Pin            |
| ------------------ | ------------------------------ |
| VCC                | 3.3V, physical pin 1 or 17     |
| GND                | GND, physical pin 6            |
| SCL / CLK          | GPIO11 / SCLK, physical pin 23 |
| SDA / DIN / MOSI   | GPIO10 / MOSI, physical pin 19 |
| CS                 | GPIO8 / CE0, physical pin 24   |
| DC                 | GPIO25, physical pin 22        |
| RST / RES          | GPIO27, physical pin 13        |
| BL / LED           | 3.3V, physical pin 17          |

Important: power off the Raspberry Pi before wiring the display.

Even if the display module says 3V–5V compatible, use 3.3V with the Raspberry Pi first. Raspberry Pi GPIO pins are not 5V tolerant.

## Enable SPI and GC9A01 Overlay

Edit the Raspberry Pi boot config:

```bash
sudo nano /boot/firmware/config.txt
```

Make sure SPI is enabled:

```ini
dtparam=spi=on
```

Add the GC9A01 overlay:

```ini
dtoverlay=gc9a01,width=240,height=240,rotate=0
```

Reboot:

```bash
sudo reboot
```

After reboot, check for the framebuffer:

```bash
ls -l /dev/fb*
```

On this project, the display appeared as:

```text
/dev/fb0
```

Also check SPI:

```bash
ls -l /dev/spidev*
```

With the overlay using CE0, it is normal to see only:

```text
/dev/spidev0.1
```

## Test the Display

Install test tools:

```bash
sudo apt update
sudo apt install -y fbi imagemagick
```

Create a test image:

```bash
convert -size 240x240 xc:black \
  -fill none -stroke lime -strokewidth 5 -draw "circle 120,120 120,10" \
  -fill white -pointsize 24 -gravity center -annotate 0 "RADAR" \
  /tmp/radar-test.png
```

Show it on the display:

```bash
sudo timeout 5 fbi -T 1 -d /dev/fb0 -noverbose -a /tmp/radar-test.png
```

If the test image appears, the display is working.

## Project Setup

Create the project folder:

```bash
mkdir -p ~/plane-radar-pi
cd ~/plane-radar-pi
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install pillow requests numpy
```

The project intentionally does not use a Python GC9A01 driver. The display is handled by the Raspberry Pi framebuffer and `fbi`.

## Main Script

The main script is:

```text
~/plane-radar-pi/radar.py
```

Run it manually with:

```bash
cd ~/plane-radar-pi
source .venv/bin/activate
python radar.py
```

Stop it with:

```text
Ctrl+C
```

## Configuration

Radar settings are controlled by a local `config.ini` file in the project directory.

Create a file named:

```text
config.ini
```

Example:

```ini
[radar]
center_lat = 30.14705507846894
center_lon = -95.39204791784302
range_mi = 10
refresh_seconds = 5
```

### Config Options

| Setting           | Description                                   |
| ----------------- | --------------------------------------------- |
| `center_lat`      | Latitude for the center of the radar display  |
| `center_lon`      | Longitude for the center of the radar display |
| `range_mi`        | Radar/API range in statute miles              |
| `refresh_seconds` | Number of seconds between radar refreshes     |

### Radar Center

The radar center is the fixed latitude/longitude used as the middle of the display.

Example:

```ini
center_lat = 30.14705507846894
center_lon = -95.39204791784302
```

To center the radar somewhere else, update those two values in `config.ini`.

### Radar Range

The radar range controls how far out aircraft are fetched and displayed.

Example:

```ini
range_mi = 10
```

Smaller values show fewer aircraft. Larger values show more aircraft but may make the screen busier.

Common values:

```ini
range_mi = 5
range_mi = 10
range_mi = 25
```

### Refresh Rate

The refresh rate controls how often the radar fetches new aircraft data.

Example:

```ini
refresh_seconds = 5
```

A lower value refreshes more often. A higher value reduces API requests and screen updates.

## Display Position and Size

The green radar circle can be adjusted in `radar.py`:

```python
CENTER_X = WIDTH // 2
CENTER_Y = (HEIGHT // 2) - 4
RADAR_RADIUS = 112
```

Larger `RADAR_RADIUS` uses more of the round display. Smaller `RADAR_RADIUS` prevents clipping around the edges.

## ADS-B API

Aircraft data is fetched from:

```text
https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{range}
```

Example test:

```bash
curl "https://opendata.adsb.fi/api/v3/lat/30.14705507846894/lon/-95.39204791784302/dist/10" | head
```

The API returns aircraft in the top-level JSON field:

```json
"ac": []
```

The script parses that field and plots aircraft that include latitude and longitude.

## Auto-Start on Boot

A systemd service can be used to start the radar automatically when the Pi boots.

Create a startup script:

```bash
nano ~/plane-radar-pi/start-radar.sh
```

Contents:

```bash
#!/bin/bash

cd /home/jason/plane-radar-pi
source /home/jason/plane-radar-pi/.venv/bin/activate

exec python /home/jason/plane-radar-pi/radar.py
```

Make it executable:

```bash
chmod +x ~/plane-radar-pi/start-radar.sh
```

Create the service:

```bash
sudo nano /etc/systemd/system/plane-radar.service
```

Service file:

```ini
[Unit]
Description=Plane Radar Pi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/jason/plane-radar-pi
ExecStart=/home/jason/plane-radar-pi/.venv/bin/python /home/jason/plane-radar-pi/radar.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the service at boot:

```bash
sudo systemctl enable plane-radar.service
```

Start it now:

```bash
sudo systemctl start plane-radar.service
```

Check status:

```bash
sudo systemctl status plane-radar.service --no-pager
```

Verify it is enabled:

```bash
sudo systemctl is-enabled plane-radar.service
```

Expected output:

```text
enabled
```

## Service Commands

Start:

```bash
sudo systemctl start plane-radar.service
```

Stop:

```bash
sudo systemctl stop plane-radar.service
```

Restart:

```bash
sudo systemctl restart plane-radar.service
```

Check status:

```bash
sudo systemctl status plane-radar.service --no-pager
```

View logs:

```bash
journalctl -u plane-radar.service -f
```

Disable auto-start:

```bash
sudo systemctl disable plane-radar.service
```

## Troubleshooting

### Display does not show up

Check framebuffer devices:

```bash
ls -l /dev/fb*
```

Check for the GC9A01 overlay:

```bash
ls /boot/firmware/overlays | grep -i gc9
```

Check boot config:

```bash
grep -E "spi|gc9|dtoverlay" /boot/firmware/config.txt
```

Expected lines include:

```ini
dtparam=spi=on
dtoverlay=gc9a01,width=240,height=240,rotate=0
```

### Display works, but no aircraft appear

Test the API manually:

```bash
curl "https://opendata.adsb.fi/api/v3/lat/30.14705507846894/lon/-95.39204791784302/dist/10" | head
```

If the API returns aircraft but the screen does not show them, check that the script parses:

```python
data.get("ac", [])
```

not:

```python
data.get("aircraft", [])
```

Also check your `config.ini` values:

```bash
cat config.ini
```

Make sure `center_lat`, `center_lon`, and `range_mi` are correct.

### Service does not auto-start after reboot

Check status:

```bash
sudo systemctl status plane-radar.service --no-pager
```

Check if enabled:

```bash
sudo systemctl is-enabled plane-radar.service
```

If it says disabled, enable it:

```bash
sudo systemctl enable plane-radar.service
```

Then reboot again:

```bash
sudo reboot
```

### View service logs

```bash
journalctl -u plane-radar.service -n 80 --no-pager
```

## Current Limitations

This is a proof of concept.

Known limitations:

* Uses `fbi` to push images to the framebuffer.
* Refreshing may flicker slightly.
* Labels can overlap when several aircraft are close together.
* The display layout is currently designed for a 240×240 round screen.
* It depends on internet access and the public ADS-B API.

## Future Improvements

Possible next steps:

* write directly to the framebuffer instead of launching `fbi`
* add physical buttons for range selection
* add command-line display modes such as `--display tft` and `--display hdmi`
* add HDMI/TV output mode
* improve label collision handling
* add aircraft speed and heading
* add an airport/runway overlay
* add Wi-Fi status indicator
* add graceful “no aircraft found” screen
* design a 3D printed enclosure for the Pi and round display

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Credits

Inspired by the ESP32 Plane Radar concept originally designed for an ESP32-C3 and GC9A01 round display.

This Raspberry Pi version was built as a proof-of-concept port using:

* Raspberry Pi 4B
* GC9A01 SPI display
* Python
* Pillow
* fbi
* Raspberry Pi framebuffer overlay
* opendata.adsb.fi ADS-B data

