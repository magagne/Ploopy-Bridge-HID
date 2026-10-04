import argparse
import ctypes
import time
import threading
from datetime import datetime

import hid


USAGE_PAGE = 0xFF60
USAGE = 0x0061
REPORT_SIZE = 32
SCAN_INTERVAL = 1.0

DRAG_SCROLL_ON = 0x53
DRAG_SCROLL_OFF = 0x73

TEMPORARY_DPI_ON = 0x54
TEMPORARY_DPI_OFF = 0x74

AUTO_MOUSE_LAYER = 0x41
AUTO_MOUSE_LAYER_VERSION = 0x01


def info(message):
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


class PloopyOutput:
    """
    Sends drag-scroll commands to the Ploopy Nano 2 Raw HID interface.
    """

    def __init__(self):
        self.devices = {}

    def update_devices(self, devices):
        self.devices = devices

    def send_drag_scroll(self, enabled):
        command = DRAG_SCROLL_ON if enabled else DRAG_SCROLL_OFF
        report = [command] + [0] * (REPORT_SIZE - 1)

        for path, entry in list(self.devices.items()):
            if entry["role"] != "ploopy":
                continue

            name = entry["name"]

            try:
                written = entry["device"].write(b"\x00" + bytes(report))

                print(
                    f"TX [{name}]: "
                    + " ".join(f"{byte:02x}" for byte in report),
                    flush=True,
                )

                if written != REPORT_SIZE + 1:
                    print(
                        f"TX WARNING [{name}]: wrote {written} bytes",
                        flush=True,
                    )

            except OSError as error:
                print(
                    f"TX ERROR [{name}]: {error}",
                    flush=True,
                )



    def send_temporary_dpi(self, enabled):
        command = TEMPORARY_DPI_ON if enabled else TEMPORARY_DPI_OFF
        report = [command] + [0] * (REPORT_SIZE - 1)

        for path, entry in list(self.devices.items()):
            if entry["role"] != "ploopy":
                continue

            name = entry["name"]

            try:
                written = entry["device"].write(b"\x00" + bytes(report))

                print(
                    f"TX [{name}]: "
                    + " ".join(f"{byte:02x}" for byte in report),
                    flush=True,
                )

                if written != REPORT_SIZE + 1:
                    print(
                        f"TX WARNING [{name}]: wrote {written} bytes",
                        flush=True,
                    )

            except OSError as error:
                print(
                    f"TX ERROR [{name}]: {error}",
                    flush=True,
                )

class KeyboardOutput:
    """
    Sends AutoMouseLayer notifications to keyboard Raw HID interfaces.

    AutoMouseLayer forwarding is asynchronous so a slow Bluetooth HID write
    cannot block reading from the Ploopy. Multiple pending activity reports
    are coalesced into the newest report.
    """

    def __init__(self):
        self.devices = {}

        self._condition = threading.Condition()
        self._pending_report = None
        self._stopping = False

        self._worker = threading.Thread(
            target=self._writer_loop,
            name="AutoMouseLayerWriter",
            daemon=True,
        )
        self._worker.start()

    def update_devices(self, devices):
        with self._condition:
            self.devices = {
                path: entry
                for path, entry in devices.items()
                if entry["role"] == "keyboard"
            }
            self._condition.notify()

    def send_auto_mouse_layer(self, report):
        """
        Store only the newest AutoMouseLayer report.

        There is no reason to queue older A 01 packets because they all mean
        the same thing: "trackball activity occurred".
        """
        with self._condition:
            self._pending_report = bytes(report)
            self._condition.notify()

    def _writer_loop(self):
        while True:
            with self._condition:
                while (
                    self._pending_report is None
                    and not self._stopping
                ):
                    self._condition.wait()

                if self._stopping:
                    return

                report = self._pending_report
                self._pending_report = None

                devices = list(self.devices.values())

            for entry in devices:
                if entry["role"] != "keyboard":
                    continue

                device = entry["device"]
                name = entry["name"]

                try:
                    written = device.write(
                        b"\x00" + report
                    )

                    print(
                        f"TX [{name}]: "
                        + " ".join(
                            f"{byte:02x}"
                            for byte in report
                        ),
                        flush=True,
                    )

                    if written != REPORT_SIZE + 1:
                        print(
                            f"TX WARNING [{name}]: "
                            f"wrote {written} bytes",
                            flush=True,
                        )

                except OSError as error:
                    print(
                        f"TX ERROR [{name}]: {error}",
                        flush=True,
                    )

    def stop(self):
        with self._condition:
            self._stopping = True
            self._condition.notify()

        self._worker.join(timeout=1.0)


def device_name(device):
    """
    Build a descriptive name without relying on VID/PID.
    """
    manufacturer = (
        device.get("manufacturer_string")
        or "Unknown manufacturer"
    )
    product = (
        device.get("product_string")
        or "Unknown product"
    )
    serial = device.get("serial_number") or ""

    if serial:
        return f"{manufacturer} / {product} / {serial}"

    return f"{manufacturer} / {product}"


def device_role(device):
    """
    Identify the bridge endpoints without hardcoding USB paths.
    """
    manufacturer = (
        device.get("manufacturer_string")
        or ""
    ).strip()

    product = (
        device.get("product_string")
        or ""
    ).strip()

    if (
        manufacturer == "Ploopy Corporation"
        and product == "Ploopy Nano 2 Trackball"
    ):
        return "ploopy"

    # Any non-Ploopy device exposing this bridge protocol is a keyboard
    # endpoint. Identification is based on the bridge HID interface, not on
    # a firmware name or a specific keyboard model.
    return "keyboard"


def find_raw_hid_devices():
    """
    Find all devices exposing the Raw HID interface used by the bridge.
    No VID/PID is used. Any compatible HID device using the required
    Usage Page and Usage is accepted.
    """
    devices = []

    for device in hid.enumerate():
        if (
            device.get("usage_page") == USAGE_PAGE
            and device.get("usage") == USAGE
        ):
            devices.append(device)

    return devices


def decode_event(data):
    if not data:
        return None

    command = data[0]

    if command == DRAG_SCROLL_ON:
        return ("drag_scroll", True)

    if command == DRAG_SCROLL_OFF:
        return ("drag_scroll", False)

    if command == TEMPORARY_DPI_ON:
        return ("temporary_dpi", True)

    if command == TEMPORARY_DPI_OFF:
        return ("temporary_dpi", False)


    if (
        command == AUTO_MOUSE_LAYER
        and len(data) >= 2
        and data[1] == AUTO_MOUSE_LAYER_VERSION
    ):
        return ("auto_mouse_layer", bytes(data))

    return None


def open_device(device_info, debug=False):
    name = device_name(device_info)

    if debug:
        print(
            "Opening:",
            name,
            device_info["path"],
        )

    device = hid.device()
    device.open_path(device_info["path"])

    return {
        "device": device,
        "name": name,
        "path": device_info["path"],
        "info": device_info,
    }


def close_device(entry, debug=False):
    if debug:
        print(
            "Closing:",
            entry["name"],
            entry["path"],
        )

    try:
        entry["device"].close()
    except Exception:
        pass


def enable_shared_hid_access():
    lib = ctypes.CDLL(hid.__file__)
    func = lib.hid_darwin_set_open_exclusive
    func.argtypes = [ctypes.c_int]
    func.restype = None
    func(0)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable diagnostic output",
    )

    args = parser.parse_args()

    enable_shared_hid_access()

    ploopy = PloopyOutput()
    keyboard = KeyboardOutput()
    devices = {}

    last_scan = 0.0
    running_logged = False

    info("HID bridge started.")

    if args.debug:
        print(
            f"Looking for Usage Page 0x{USAGE_PAGE:04x}, "
            f"Usage 0x{USAGE:04x}"
        )

    try:
        while True:
            now = time.monotonic()

            if now - last_scan >= SCAN_INTERVAL:
                last_scan = now

                discovered = find_raw_hid_devices()

                discovered_paths = {
                    info["path"]
                    for info in discovered
                }

                # Remove disconnected devices.
                for path in list(devices):
                    if path not in discovered_paths:
                        entry = devices.pop(path)

                        info(
                            f"Device disconnected: {entry['name']}"
                        )

                        close_device(
                            entry,
                            args.debug,
                        )

                # Open newly connected devices.
                for device_info in discovered:
                    path = device_info["path"]

                    if path in devices:
                        continue

                    try:
                        role = device_role(device_info)

                        if role is None:
                            continue

                        entry = open_device(
                            device_info,
                            args.debug,
                        )

                        entry["role"] = role
                        devices[path] = entry

                        info(
                            f"Device connected: "
                            f"{entry['name']} [{role}]"
                        )

                    except OSError as error:
                        if args.debug:
                            print(
                                "Could not open:",
                                device_name(device_info),
                                error,
                            )

                if not running_logged:
                    info("HID bridge running.")
                    running_logged = True

                if args.debug:
                    if devices:
                        print(
                            "Listening on:",
                            ", ".join(
                                entry["name"]
                                for entry in devices.values()
                            ),
                        )
                    else:
                        print(
                            "No compatible HID devices connected."
                        )

            # Read every connected device without blocking.
            for path, entry in list(devices.items()):
                device = entry["device"]
                name = entry["name"]

                try:
                    data = device.read(
                        REPORT_SIZE,
                        timeout_ms=1,
                    )

                except OSError as error:
                    if args.debug:
                        print(
                            "Read error:",
                            name,
                            error,
                        )

                    close_device(
                        entry,
                        args.debug,
                    )

                    devices.pop(path, None)
                    continue

                if not data:
                    continue

                if args.debug:
                    print(
                        f"RX [{name}]:",
                        " ".join(
                            f"{byte:02x}"
                            for byte in data
                        ),
                    )

                event = decode_event(data)

                if event is None:
                    if args.debug:
                        print(
                            f"EVENT [{name}]: "
                            f"UNKNOWN 0x{data[0]:02x}"
                        )

                    continue

                event_type, event_value = event

                if event_type == "drag_scroll":
                    # Keyboard -> bridge -> Ploopy
                    if entry["role"] != "keyboard":
                        if args.debug:
                            print(
                                f"EVENT [{name}]: "
                                "ignored drag-scroll from non-keyboard"
                            )
                        continue

                    if args.debug:
                        print(
                            f"EVENT [{name}]:",
                            "DRAG_SCROLL_ON"
                            if event_value
                            else "DRAG_SCROLL_OFF",
                        )

                    ploopy.update_devices(devices)
                    ploopy.send_drag_scroll(event_value)

                elif event_type == "temporary_dpi":
                    # Keyboard -> bridge -> Ploopy
                    if entry["role"] != "keyboard":
                        continue

                    ploopy.update_devices(devices)
                    ploopy.send_temporary_dpi(event_value)

                elif event_type == "auto_mouse_layer":
                    # Ploopy -> bridge -> keyboard
                    if entry["role"] != "ploopy":
                        if args.debug:
                            print(
                                f"EVENT [{name}]: "
                                "ignored AutoMouseLayer from non-Ploopy"
                            )
                        continue

                    if args.debug:
                        print(
                            f"EVENT [{name}]: "
                            "AUTO_MOUSE_LAYER A 01"
                        )

                    keyboard.update_devices(devices)
                    keyboard.send_auto_mouse_layer(event_value)

            time.sleep(0.001)

    except KeyboardInterrupt:
        print()
        info("Stopping HID bridge...")

    finally:
        keyboard.stop()

        for entry in list(devices.values()):
            close_device(
                entry,
                args.debug,
            )

        devices.clear()
        info("Bridge stopped.")


if __name__ == "__main__":
    main()
