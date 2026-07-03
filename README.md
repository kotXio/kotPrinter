# Yet Another Cat Printer

![A small Bluetooth cat printer](assets/cat_printer.jpg)

A small Python CLI for printing text and images on a cheap Bluetooth thermal
cat printer without the vendor mobile app.

I bought this printer cheaply. It came with Android and iOS apps, but the app
experience was, gently speaking, not great. I also wanted to use the printer in
custom workflows, and being tied to a phone app was getting in the way.

Before writing this tool I tried the available scripts and applications I could
find, but none of them worked with my printer. I ended up capturing the
Bluetooth traffic between the mobile app and the printer, then reverse
engineering enough of the exchange to print from a Raspberry Pi.

The funny part: this printer does not seem to support many normal POS commands.
In practice, the reliable path is to render everything into a 384-dot-wide
1-bit image and send it as raster data over Bluetooth RFCOMM.

That is what this CLI does.

## Supported Printer

Tested with a `YHK-D0D0` style Bluetooth cat printer.

Known hardware details:

- Bluetooth thermal printer
- 384-dot print width
- Internal `18650` battery
- USB-C charging
- One physical button
- Long button press turns the printer on or off
- Double button press prints the printer self-test and MAC address

This project may work with similar cat printers, but the Bluetooth MAC address,
RFCOMM channel, print width, and protocol quirks may differ.

## What It Can Do

- Print Unicode text by rendering it to an image first
- Print PNG/JPEG/etc. images supported by Pillow
- Preview the generated print raster as `debug.png`
- Control text size, alignment, padding, line spacing, and text density
- Adjust image preprocessing with brightness, contrast, gamma, and dithering
- Query printer voltage, DPI, battery estimate, and serial number
- Reconnect/rebind `/dev/rfcomm0` before jobs when the printer is asleep or the
  RFCOMM device is stale

The tool talks directly to `/dev/rfcomm0`. It is not a CUPS driver and does not
run a print server.

## Project Files

- `print.py` - main CLI tool
- `systemd/rfcomm-printer.service` - optional RFCOMM bind unit
- `assets/cat_printer.jpg` - project photo used in this README
- `LICENSE` - MIT license

## Requirements

System packages on Debian or Raspberry Pi OS:

```sh
sudo apt update
sudo apt install python3 python3-pip fonts-dejavu-core bluez
```

Python packages:

```text
Pillow>=9.4
pyserial>=3.5
```

Install them with pip:

```sh
python3 -m pip install "Pillow>=9.4" "pyserial>=3.5"
```

Or use distro packages:

```sh
sudo apt install python3-pil python3-serial
```

The default font is:

```text
/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf
```

It is provided by the `fonts-dejavu-core` package. Other useful fonts from the
same package usually include:

```text
DejaVuSans-Bold.ttf
DejaVuSansMono-Bold.ttf
DejaVuSansMono.ttf
DejaVuSans.ttf
DejaVuSerif-Bold.ttf
DejaVuSerif.ttf
```

To use another font, change `FONT_PATH` in `print.py`.

## Installation

Clone the repository:

```sh
git clone https://github.com/kotXio/kotPrinter.git
cd catPrinter
```

Install dependencies:

```sh
sudo apt update
sudo apt install python3 python3-pip fonts-dejavu-core bluez
python3 -m pip install "Pillow>=9.4" "pyserial>=3.5"
```

Make sure your user can access serial devices:

```sh
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing groups.

## Bluetooth Setup

Turn on the printer first. If you do not know its MAC address, double press the
printer button to print the self-test page, or scan for it:

```sh
bluetoothctl
scan on
```

Pair and trust the printer:

```sh
bluetoothctl
scan on
pair D6:85:FD:2C:D0:D0
trust D6:85:FD:2C:D0:D0
quit
```

Replace `D6:85:FD:2C:D0:D0` with your printer MAC address.

## RFCOMM Setup

The CLI expects the printer at:

```text
/dev/rfcomm0
```

Manual bind:

```sh
sudo rfcomm release /dev/rfcomm0
sudo rfcomm bind /dev/rfcomm0 D6:85:FD:2C:D0:D0 2
ls -l /dev/rfcomm0
```

The tested printer uses RFCOMM channel `2`.

Optional systemd unit:

```sh
sudo install -m 0644 systemd/rfcomm-printer.service /etc/systemd/system/rfcomm-printer.service
sudo systemctl daemon-reload
sudo systemctl enable --now rfcomm-printer.service
```

Before installing the unit for your own printer, edit:

```text
systemd/rfcomm-printer.service
```

and replace the MAC address in:

```ini
ExecStart=/usr/bin/rfcomm bind /dev/rfcomm0 D6:85:FD:2C:D0:D0 2
```

The unit is a one-shot bind. It creates `/dev/rfcomm0`, but it is not a
long-running print daemon.

## Quick Start

Show printer info:

```sh
python3 print.py info
```

Print text:

```sh
python3 print.py text 'hello cat printer'
```

Print multiple lines:

```sh
python3 print.py text 'hello\nworld'
```

Print centered larger text:

```sh
python3 print.py text 'CENTER' --align center --size 28
```

Print lighter or darker text:

```sh
python3 print.py text 'quiet label' --text-density light
python3 print.py text 'bold label' --text-density dark
```

Print an image:

```sh
python3 print.py img ./picture.png
```

Save a preview instead of printing:

```sh
python3 print.py text 'preview only' --preview
python3 print.py img ./picture.png --preview
```

Preview output is written to `debug.png` in the current working directory.

## CLI Reference

Top-level commands:

```sh
python3 print.py info
python3 print.py text TEXT [options]
python3 print.py img PATH [options]
```

### `info`

Queries the printer and prints voltage, DPI, battery estimate, serial number,
and current default settings.

```sh
python3 print.py info
```

### `text`

Renders text into a 384-dot-wide raster image, then prints it.

```sh
python3 print.py text 'hello'
```

Text-specific options:

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `-s`, `--size` | integer `> 0` | `20` | Font size in pixels. |
| `-a`, `--align` | `left`, `center`, `right` | `left` | Horizontal text alignment. |
| `-p`, `--pad_y` | integer `>= 0` | `6` | Top and bottom padding in pixels. |
| `-l`, `--line_spacing` | float `>= 0` | `0.5` | Extra line spacing as a multiplier of font size. |
| `--text-density` | `light`, `normal`, `dark` | `normal` | Text-specific density control. |

`--text-density normal` matches the original/default text rendering. `light`
removes a small regular pattern of black text pixels. `dark` expands black text
pixels to make letters bolder.

Examples:

```sh
python3 print.py text 'left aligned'
python3 print.py text 'centered' --align center
python3 print.py text 'large' --size 32
python3 print.py text 'A\n\nB' --line_spacing 1.0
python3 print.py text 'light' --text-density light
python3 print.py text 'dark' --text-density dark
```

### `img`

Loads an image with Pillow, preprocesses it, resizes or centers it to the
printer width, then prints it as raster data.

```sh
python3 print.py img ./picture.png
```

Image files can be any format supported by Pillow, for example PNG or JPEG.

Examples:

```sh
python3 print.py img ./label.png
python3 print.py img ./photo.jpg --method fs
python3 print.py img ./photo.jpg --brightness 1.2 --contrast 1.4 --gamma 1.2
python3 print.py img ./label.png --repeat 2
```

### Shared Render Options

These options are available for both `text` and `img`:

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `-m`, `--method` | `fs`, `ordered`, `th` | `fs` | Raster conversion method. `fs` uses Floyd-Steinberg dithering, `ordered` uses a simple ordered conversion, and `th` uses hard thresholding. |
| `-b`, `--brightness` | float `> 0` | `1.0` | Brightness multiplier before 1-bit conversion. |
| `-c`, `--contrast` | float `> 0` | `1.0` | Contrast multiplier before 1-bit conversion. |
| `-g`, `--gamma` | float `> 0` | `1.0` | Gamma correction before 1-bit conversion. |

For normal text darkness control, prefer `--text-density`. Extreme
brightness/contrast/gamma values can turn text into a blank raster or a solid
black stripe.

### Shared Print Options

These options are available for both `text` and `img`:

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `--feed` | integer `>= 0` | `5` | Number of newline feed lines after printing. |
| `--repeat` | integer `> 0` | `1` | Send the same raster payload multiple times. |
| `--preview` | flag | off | Save `debug.png` instead of opening the printer. |

## How It Works

The printer protocol used here is intentionally simple:

1. Open `/dev/rfcomm0` at `115200`.
2. Send a short wake/info handshake.
3. Render text or image input into a 384-dot-wide 1-bit image.
4. Pack image rows into ESC/POS-style raster bytes.
5. Send the raster payload to the printer.
6. Feed paper by sending newline characters.

The CLI retries the wake handshake and can restart `rfcomm-printer.service`
before a job if `/dev/rfcomm0` is missing, closed, or stale. It does not retry
after a payload write failure because the printer may already have produced a
partial print.

## Troubleshooting

### `/dev/rfcomm0` exists, but the printer does not answer

`/dev/rfcomm0` existing does not prove the printer is awake or connected. The
printer may be off, asleep, out of range, already busy, or the RFCOMM bind may
be stale.

Try:

```sh
python3 print.py info
sudo systemctl restart rfcomm-printer.service
python3 print.py info
```

If that still fails, power-cycle the printer and retry.

### The printer goes away after sitting idle

This printer runs on battery and may power off or sleep by itself. Turn it on
again before printing. A long button press toggles power.

### Text density looks wrong

Use:

```sh
python3 print.py text 'sample' --text-density light
python3 print.py text 'sample' --text-density normal
python3 print.py text 'sample' --text-density dark
```

Avoid using extreme `--brightness`, `--contrast`, or `--gamma` values for text.
Those options are generic raster preprocessing controls and can overdrive text
into an empty or fully black raster.

### Image output is too dark or too light

Try preview first:

```sh
python3 print.py img ./photo.jpg --preview
```

Then adjust:

```sh
python3 print.py img ./photo.jpg --brightness 1.2 --contrast 1.3 --gamma 1.1
python3 print.py img ./photo.jpg --method th
```

### Desktop Bluetooth widgets

On Raspberry Pi desktop systems, a panel Bluetooth widget can register its own
BlueZ agent and may interfere with command-line pairing or recovery. During
setup, keep the GUI Bluetooth menu closed and use `bluetoothctl` consistently.

### Useful Checks

```sh
systemctl status bluetooth.service --no-pager
systemctl status rfcomm-printer.service --no-pager
journalctl -u rfcomm-printer.service -n 50 --no-pager
rfcomm -a
ls -l /dev/rfcomm0
bluetoothctl show
bluetoothctl devices
python3 print.py info
```

## Known Limitations

- Tested with one printer model, currently identified as `YHK-D0D0`.
- The systemd unit contains a hardcoded MAC address and RFCOMM channel.
- The tool prints raster images; many normal POS text commands are ignored by
  this printer.
- No queue or print server mode is implemented yet.
- No CUPS integration is provided.

## Author

Kostiantyn Andriiuk

## License

MIT. See [LICENSE](LICENSE).
