# Ploopy-Bridge-HID

Ploopy-Bridge-HID is a small macOS host-side Raw HID transport bridge
connecting a Ploopy pointing device and a compatible keyboard firmware.

It provides two independent communication paths:

- **DragScroll-HID** — keyboard → Ploopy
- **AutoMouseLayer-HID** — Ploopy → keyboard

The bridge transports these protocols between the two devices. It does not
implement pointing behavior, scrolling behavior, or keyboard layer policy.

## Architecture

    Keyboard endpoint
         │
         │ Raw HID
         ▼
    Ploopy-Bridge-HID
         │
         │ Raw HID
         ▼
    Ploopy Nano 2

The two protocol directions are:

    keyboard ── S / s ──────────────► Ploopy
           DragScroll-HID

    Ploopy ── A 01 ──────────────► keyboard
           AutoMouseLayer-HID

The bridge runs on macOS and forwards the Raw HID packets without changing
their protocol payload.

## Raw HID Interface

The bridge discovers Raw HID interfaces using:

    Usage Page : 0xFF60
    Usage      : 0x0061

The bridge identifies the Ploopy Nano 2 explicitly. Other devices exposing
the same bridge HID interface are treated as keyboard endpoints.

No keyboard VID, PID, firmware name, or keyboard model is required.

The bridge uses a Raw HID report-ID prefix of `0x00` when writing to these
HIDAPI interfaces.

## DragScroll-HID

The keyboard sends one of two one-byte commands:

    'S'  → DragScroll ON
    's'  → DragScroll OFF

The bridge forwards the command unchanged to the Ploopy.

The Ploopy firmware applies the command to its existing DragScroll behavior.

The bridge does not decide when DragScroll should be enabled or disabled.

`DragScroll-HID` is the macOS Raw HID transport. Windows uses the separate
`DragScroll-LED` transport and does not require this bridge.

## AutoMouseLayer-HID

The Ploopy firmware sends a 32-byte Raw HID notification when physical
trackball movement is detected.

The packet begins with:

    0x41 0x01

or:

    'A'  0x01

The remaining bytes are currently zero.

The bridge forwards this packet unchanged to the keyboard.

The first physical movement is reported immediately. Subsequent notifications
are rate-limited by the Ploopy firmware.

The notification is independent of:

- pointer rotation
- DragScroll
- Vertical Scrolling Only

The bridge only transports the notification. The keyboard firmware decides
which Mouse layer to activate and how long it remains active.

## AutoMouseLayer-LED

`AutoMouseLayer-LED` is the Windows transport for the same AutoMouseLayer
feature.

It does **not** use this bridge.

On Windows:

    Ploopy
       │
       │ Caps Lock keyboard event
       ▼
    Windows
       │
       │ Caps Lock LED state
       ▼
    Keyboard

The keyboard firmware consumes the current Caps Lock LED state as its
AutoMouseLayer signal:

- Caps Lock ON → Windows Mouse layer ON
- Caps Lock OFF → Windows Mouse layer OFF

The Windows path is state-based and does not use the macOS Raw HID
AutoMouseLayer timeout.

This is separate from DragScroll:

- **ScrollLock** remains the DragScroll LED signal.
- **Caps Lock** is the AutoMouseLayer LED signal.

## Direction Summary

    keyboard ── S / s ──────────────► Ploopy
           DragScroll-HID

    Ploopy ── A 01 ──────────────► keyboard
           AutoMouseLayer-HID

These are separate protocols and do not share state.

## Keyboard Firmware

The keyboard-side implementation is maintained separately.

The bridge supports any compatible keyboard Raw HID endpoint exposing usage
page `0xFF60` / usage `0x0061`.

The keyboard firmware is responsible for:

- handling the DragScroll command
- handling the AutoMouseLayer signal
- selecting the appropriate Mouse layer
- managing AutoMouseLayer ownership
- applying the Raw HID/macOS AutoMouseLayer timeout
- consuming the Windows Caps Lock LED state

Ploopy-Bridge-HID only transports the corresponding Raw HID messages.

## Ploopy Firmware

The enhanced Nano-2 firmware is maintained separately in the
`Ploopy-Nano2-Enhanced` project.

The Ploopy firmware is responsible for:

- normal pointing-device HID behavior
- DragScroll behavior
- generating AutoMouseLayer-HID notifications
- generating the Caps Lock signal used by AutoMouseLayer-LED

No Ploopy mouse HID behavior is implemented by this host bridge.

## macOS

The bridge can run continuously as a macOS LaunchAgent.

The LaunchAgent:

- starts the bridge at login
- keeps the bridge running
- writes standard output and error logs
- uses the project's Python virtual environment

See `platform/mac/README.md` for installation and troubleshooting.

## Debugging

From the project directory:

    .venv/bin/python -u src/ploopy_bridge_hid.py --debug

Debug output can be used to verify:

- Raw HID device discovery
- keyboard and Ploopy device identification
- received Raw HID packets
- decoded events
- forwarded packets

For LaunchAgent troubleshooting, see `platform/mac/README.md`.

## Design Goals

Ploopy-Bridge-HID is intentionally small.

    Keyboard firmware
          │
          │ protocol decisions
          ▼
    Ploopy-Bridge-HID
          │
          │ Raw HID transport
          ▼
    Ploopy firmware

The bridge should not contain policy that belongs in either endpoint.

In particular, it does not:

- monitor macOS mouse events
- emulate mouse input through CoreGraphics
- modify normal Ploopy HID reports
- implement DragScroll itself
- implement keyboard-layer policy
- infer keyboard operating-system layers

Its role is to transport the defined Raw HID messages between the supported
devices.
