#!/usr/bin/env python3
"""RK R75PRO V2 Fn+Enter battery key fix: Fn+Enter battery display broken after remapping keys in the web driver.

Root cause (see fix.md / api.md): the Fn+Enter battery function lives in the Enter
slot of the WIN/FN1 key matrix layer, that is column-major index 81
(= row3 + 6*col13), encoded as special-function key 0x07000024. The web driver's
built-in WIN/FN1 layout table has NONE in that slot, so editing any key of the
Windows layout rewrites the whole layer and overwrites the battery key with 0.
The Mac layout is unaffected.

This script reads WIN/FN1, writes 0x07000024 to index 81, writes the layer back
and reads it back to verify. The R75PRO V2 firmware interprets every key matrix
u32 as big-endian, so the data is byte-reversed per u32 in both directions.

Usage:
  sudo python3 rkfix.py /dev/hidraw3            # USB wired, feature report
  sudo python3 rkfix.py /dev/hidraw5 --dongle   # 2.4G receiver, output/input report

"""

import argparse
import fcntl
import os
import select
import sys
import time

# Protocol constants (api.md sections 3, 4, 5, 9).
RID_DONGLE = 19         # 2.4G: reportId of both the output and the input report
RID_USB = 6             # USB wired: reportId of the feature report (R75PRO V2 pid 0x02C2)

FRAME_LEN = 19          # dongle frame length, reportId excluded
MAX_CHUNK = 14          # max payload bytes per dongle packet
CRC_INIT = 19           # dongle CRC seed
FRAME519_LEN = 519      # USB frame length, reportId excluded
FEATURE_BUF = 520       # feature report buffer: reportId + 519-byte frame

MATRIX_LEN = 504        # 126 keys x 4 bytes
LAYER_FN1, TABLE_WIN = 1, 0
ENTER_INDEX = 81        # column-major index, i = row + 6*col
BATTERY_KEY = 0x07000024  # special function (type 7) + id 0x24, measured on factory data

CMD_DONGLE_GET, CMD_DONGLE_SET = 65, 1    # same function, different cmdId per channel
CMD_USB_GET, CMD_USB_SET = 131, 3

# msf-style console output: bold coloured [*]/[+]/[-]/[!] tag, plain message.
_COLOR = {"*": 34, "+": 32, "-": 31, "!": 33}   # info/good/error/warning
_VERBOSE = False        # --verbose: one line per packet instead of 25% milestones


def progress(done, total, state, msg):
    # Packet-loop progress: a line per quarter of the transfer by default, a
    # line per packet under --verbose. state is a one-element list holding the
    # last quarter index, so the caller keeps the counter across iterations.
    mark = done * 4 // total
    if mark == state[0] and not _VERBOSE:
        return
    state[0] = mark
    log("*", f"{msg} {done}/{total} ({done * 100 // total}%)")


def log(sym, msg, stream=None):
    # Colors only on a terminal, so piped output stays clean.
    stream = sys.stdout if stream is None else stream
    tag = f"[{sym}]"
    if stream.isatty():
        tag = f"\033[1m\033[{_COLOR[sym]}m{tag}\033[0m"
    print(f"{tag} {msg}", file=stream)


def die(msg, hint=None):
    log("-", msg, sys.stderr)
    if hint:
        log("*", hint, sys.stderr)
    sys.exit(1)


def _ioc(nr, size):
    # Linux hidraw request number: _IOC(_IOC_READ | _IOC_WRITE, 'H', nr, size).
    # nr 0x06 = set feature report, nr 0x07 = get feature report.
    return 0xC0000000 | (size << 16) | (ord("H") << 8) | nr


def frame19(cmd, payload=b"", index=0, count=1, layer=0, table=0):
    # 19-byte dongle frame without reportId: byte1 = packet count,
    # byte2 = packet index | (table << 7), byte3 = payload length | (layer << 4)
    # (board is always 0), byte4..17 = payload, byte18 = (19 + sum(byte0..17)) & 0xFF.
    f = bytearray(FRAME_LEN)
    f[0] = cmd
    f[1] = count & 0x7F
    f[2] = (index & 0x7F) | (table << 7)
    f[3] = (len(payload) & 0x0F) | (layer << 4)
    f[4:4 + len(payload)] = payload
    f[18] = (CRC_INIT + sum(f[:18])) & 0xFF
    return bytes(f)


def swap32(data):
    # Reverse every 4-byte group: the R75PRO V2 firmware reads each key matrix
    # u32 as big-endian, and factory data is stored byte-reversed.
    out = bytearray(data)
    for i in range(0, len(out), 4):
        out[i:i + 4] = out[i:i + 4][::-1]
    return bytes(out)


class Hidraw:
    # Raw hidraw node. Every buffer carries the reportId as its first byte,
    # for output reports and feature reports alike.

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)

    def write(self, buf):
        os.write(self.fd, buf)

    def read(self, timeout):
        # os.read offers no timeout, so wait for readability first.
        # Returns the report as bytes, reportId first, or None on timeout.
        if not select.select([self.fd], [], [], timeout)[0]:
            return None
        return os.read(self.fd, 64)

    def feature_get(self):
        # Returns the 520-byte buffer, buf[0] = reportId.
        buf = bytearray(FEATURE_BUF)
        buf[0] = RID_USB
        fcntl.ioctl(self.fd, _ioc(0x07, FEATURE_BUF), buf, True)
        return bytes(buf)

    def feature_set(self, buf):
        fcntl.ioctl(self.fd, _ioc(0x06, FEATURE_BUF), buf, True)

    def close(self):
        os.close(self.fd)


def dongle_read_frame(dev, cmd, timeout):
    # Returns the 19-byte response frame without its reportId, or None on
    # timeout. Unrelated reports (e.g. actively-reported cmd 10) are skipped.
    end = time.monotonic() + timeout
    while True:
        r = dev.read(max(end - time.monotonic(), 0.001))
        if r is None:
            return None
        if len(r) == FRAME_LEN + 1 and r[0] == RID_DONGLE and r[1] == cmd:
            return r[1:]
        if _VERBOSE:
            log("*", f"ignoring unrelated report: {len(r)} bytes, "
                     f"rid={r[0]}, cmd={r[1] if len(r) > 1 else '-'}")


def dongle_get(dev, cmd, expect, layer=0, table=0, timeout=8.0):
    # GET has no separate ACK: send one zero-payload request, then keep reading
    # response packets until expect bytes are assembled.
    req = bytes([RID_DONGLE]) + frame19(cmd, b"", 0, 1, layer, table)
    log("*", f"cmd={cmd}: request sent, waiting for {expect} bytes")
    dev.write(req)
    buf = bytearray()
    end = time.monotonic() + timeout
    state = [0]              # quarter 0 is already covered by the request log
    while len(buf) < expect:
        resp = dongle_read_frame(dev, cmd, max(end - time.monotonic(), 0.001))
        if resp is None:
            raise TimeoutError(f"cmd={cmd}: read timed out, got {len(buf)}/{expect} bytes")
        if resp[1] & 0x80:              # byte1 bit7=1: device asks for a resend
            log("!", f"cmd={cmd}: device asked for a resend at {len(buf)}/{expect} bytes")
            dev.write(req)
            continue
        buf += resp[4:4 + (resp[3] & 0x0F)]
        progress(len(buf), expect, state, f"cmd={cmd}: received")
    log("+", f"cmd={cmd}: read complete, {len(buf)} bytes")
    return bytes(buf[:expect])


def dongle_set(dev, cmd, data, layer=0, table=0, retries=10, timeout=3.0):
    # SET: push 14-byte packets one by one, waiting for an ACK after each.
    # byte1 bit7=1 in the response means the packet was rejected, resend it.
    chunks = [data[i:i + MAX_CHUNK] for i in range(0, len(data), MAX_CHUNK)]
    log("*", f"cmd={cmd}: writing {len(data)} bytes in {len(chunks)} packets")
    state = [0]             # quarter 0 is already covered by the write log
    for i, c in enumerate(chunks):
        f = bytes([RID_DONGLE]) + frame19(cmd, c, i, len(chunks), layer, table)
        for attempt in range(1, retries + 1):
            dev.write(f)
            resp = dongle_read_frame(dev, cmd, timeout)
            if resp is not None and not resp[1] & 0x80:
                break
            log("!", f"packet {i + 1}/{len(chunks)}: no ACK, resending "
                     f"(attempt {attempt}/{retries})")
        else:
            raise TimeoutError(f"cmd={cmd}: no ACK for packet {i + 1}/{len(chunks)}")
        if attempt > 1:
            log("!", f"packet {i + 1}/{len(chunks)} acked after {attempt} attempts")
        progress(i + 1, len(chunks), state, f"cmd={cmd}: acked")
    log("+", f"cmd={cmd}: write complete, {len(chunks)} packets acknowledged")


def usb_feature(dev, cmd, data=b"", length=None, layer=0, table=0):
    # 519-byte feature frame: byte1 = table/layer, byte3 = 1, byte5/6 = data
    # length, byte7.. = payload.
    f = bytearray(FRAME519_LEN)
    n = len(data) if length is None else length
    f[0] = cmd
    f[1] = (table << 2) | layer
    f[3] = 1
    f[5], f[6] = n & 0xFF, n >> 8
    f[7:7 + len(data)] = data
    dev.feature_set(bytes([RID_USB]) + bytes(f))


def usb_get(dev, cmd, expect, layer=0, table=0):
    # Single request, single response; the response payload starts at resp[8].
    usb_feature(dev, cmd, length=expect, layer=layer, table=table)
    time.sleep(0.06)            # let the firmware answer, otherwise the old frame is read
    return dev.feature_get()[8:8 + expect]


def main():
    ap = argparse.ArgumentParser(
        description="RK R75PRO V2 Fn+Enter battery key fix")
    ap.add_argument("path", help="hidraw node, e.g. /dev/hidraw3")
    ap.add_argument("--dongle", action="store_true",
                    help="2.4G receiver channel (default: USB wired feature reports)")
    ap.add_argument("--value", type=lambda s: int(s, 0), default=BATTERY_KEY,
                    help=f"value to write at index {ENTER_INDEX}, default 0x{BATTERY_KEY:08X}")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="log every packet, not just quarterly progress")
    args = ap.parse_args()

    global _VERBOSE
    _VERBOSE = args.verbose
    kind = "dongle" if args.dongle else "usb"
    channel = "2.4G dongle (output/input report 19)" if args.dongle \
        else "USB wired (feature report 6)"
    log("*", f"RK R75PRO V2 Fn+Enter battery fix, channel: {channel}")
    log("*", f"opening {args.path}")
    try:
        dev = Hidraw(args.path)
    except OSError as e:
        die(f"cannot open {args.path}: {e}",
            "Run as root, or grant write access to that node (udev rule).")

    off = ENTER_INDEX * 4
    try:
        def read_win_fn1(step):
            log("*", f"{step}: reading WIN/FN1 layer "
                     f"({MATRIX_LEN} bytes, layer {LAYER_FN1} table {TABLE_WIN})")
            if kind == "dongle":
                return dongle_get(dev, CMD_DONGLE_GET, MATRIX_LEN, LAYER_FN1, TABLE_WIN)
            return usb_get(dev, CMD_USB_GET, MATRIX_LEN, LAYER_FN1, TABLE_WIN)

        win = bytearray(swap32(read_win_fn1("initial read")))
        before = int.from_bytes(win[off:off + 4], "little")
        if before == args.value:
            log("!", f"index {ENTER_INDEX} (row {ENTER_INDEX % 6}, col {ENTER_INDEX // 6}) "
                     f"already holds 0x{args.value:08X}, writing it again anyway")
        else:
            log("*", f"index {ENTER_INDEX} (row {ENTER_INDEX % 6}, col {ENTER_INDEX // 6}) "
                     f"holds 0x{before:08X}, patching to 0x{args.value:08X}")

        win[off:off + 4] = args.value.to_bytes(4, "little")
        data = swap32(bytes(win))
        if kind == "dongle":
            dongle_set(dev, CMD_DONGLE_SET, data, LAYER_FN1, TABLE_WIN)
        else:
            log("*", f"writing WIN/FN1 layer ({len(data)} bytes) via feature report {RID_USB}")
            usb_feature(dev, CMD_USB_SET, data, layer=LAYER_FN1, table=TABLE_WIN)
            time.sleep(0.05)
            log("+", f"cmd={CMD_USB_SET}: write complete, {len(data)} bytes sent")

        back = int.from_bytes(swap32(read_win_fn1("verify"))[off:off + 4], "little")
        if back != args.value:
            die(f"read back 0x{back:08X}, expected 0x{args.value:08X}: "
                "the key matrix write did not take effect.")
        if before != back:
            log("+", f"index {ENTER_INDEX} changed 0x{before:08X} -> 0x{back:08X}")
        else:
            log("+", f"index {ENTER_INDEX} reads back 0x{back:08X}")
        log("+", "done: Fn+Enter should show the battery level again on the Windows layout when not in wired mode.")
    except TimeoutError as e:
        die(f"{e}",
            "The device stopped answering. Replug it, then retry with the same channel: "
            "USB wired takes no --dongle, the 2.4G receiver needs --dongle.")
    except OSError as e:
        die(f"hidraw I/O failed: {e}",
            f"Check that {args.path} is the protocol interface (usage page 0xFF02) "
            f"and that the channel is right: USB wired takes no --dongle, "
            f"the 2.4G receiver needs --dongle.")
    finally:
        try:
            dev.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
