"""Tiny LG webOS (SSAP) client, standard library only: pair once, then read the power state or turn the TV off."""
import base64, json, os, socket, ssl, struct

KEY = os.path.expanduser("~/.config/ps5-play/lgtv-key")
MANIFEST = {"manifestVersion": 1, "appId": "com.smithy.ps5play", "vendorId": "smithy", "localizedAppNames": {"": "ps5-play"},
            "permissions": ["READ_POWER_STATE", "CONTROL_POWER", "READ_RUNNING_APPS", "READ_CURRENT_CHANNEL"],
            "signed": {"appId": "com.smithy.ps5play", "created": "20261027", "vendorId": "smithy", "permissions": ["READ_POWER_STATE"]},
            "signatures": [{"signatureVersion": 1, "signature": ""}]}


class TV:
    def __init__(self, host, timeout=4):
        raw = socket.create_connection((host, 3001), timeout)
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        self.s = ctx.wrap_socket(raw, server_hostname=host)
        k = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f"GET / HTTP/1.1\r\nHost: {host}:3001\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {k}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf: buf += self.s.recv(1024)
        if b" 101 " not in buf.split(b"\r\n")[0]: raise OSError("no websocket")
        self.n = 0

    def send(self, obj):
        p = json.dumps(obj).encode(); m = os.urandom(4)
        h = bytes([0x81]) + (bytes([0x80 | len(p)]) if len(p) < 126 else bytes([0xFE]) + struct.pack(">H", len(p)))
        self.s.sendall(h + m + bytes(b ^ m[i % 4] for i, b in enumerate(p)))

    def recv(self):
        def n(k):
            b = b""
            while len(b) < k: b += self.s.recv(k - len(b))
            return b
        while True:
            a, l = n(2); op = a & 0x0F; l &= 0x7F
            if l == 126: l = struct.unpack(">H", n(2))[0]
            elif l == 127: l = struct.unpack(">Q", n(8))[0]
            b = n(l)
            if op == 8: raise OSError("the TV closed the connection: " + b[2:].decode(errors="replace"))   # e.g. asleep: "Try Again Later"
            if op == 9:                               # ping: answer pong, or the TV hangs up while the Allow prompt waits
                m = os.urandom(4); self.s.sendall(bytes([0x8A, 0x80 | len(b)]) + m + bytes(x ^ m[i % 4] for i, x in enumerate(b))); continue
            if op == 1: return json.loads(b)          # text; other frames are skipped

    def register(self, prompt=False):
        msg = {"type": "register", "id": "reg", "payload": {"pairingType": "PROMPT", "manifest": MANIFEST}}
        if os.path.exists(KEY): msg["payload"]["client-key"] = open(KEY).read().strip()
        elif not prompt: return False
        self.send(msg)
        while True:
            r = self.recv()
            if r.get("type") == "registered":
                os.makedirs(os.path.dirname(KEY), exist_ok=True)
                with open(os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: f.write(r["payload"]["client-key"])
                return True
            if r.get("type") == "error": return False

    def call(self, uri, payload=None):
        self.n += 1; i = f"q{self.n}"
        self.send({"type": "request", "id": i, "uri": uri, **({"payload": payload} if payload else {})})
        while True:
            r = self.recv()
            if r.get("id") == i: return r.get("payload") or {}


def state(host):
    """'off' (no answer), 'standby', 'on', or 'on:<app>'; 'unpaired' if the TV hasn't been paired yet."""
    try: tv = TV(host, 2)
    except OSError: return "off"
    try:
        if not tv.register(): return "unpaired"
        p = tv.call("ssap://com.webos.service.tvpower/power/getPowerState").get("state", "Active")
        if p != "Active": return "standby"
        app = tv.call("ssap://com.webos.applicationManager/getForegroundAppInfo").get("appId", "")
        return "on:" + app if app else "on"
    except (OSError, ValueError, KeyError): return "off"
    finally: tv.s.close()


def wake(mac="ac:b6:87:35:ad:4a"):
    """Wake-on-LAN: the TV turns on if 'Turn on via Wi-Fi/LAN' is on in its settings."""
    m = bytes.fromhex(mac.replace(":", "")); s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for port in (9, 7): s.sendto(b"\xff" * 6 + m * 16, ("255.255.255.255", port))


def off(host):
    tv = TV(host); tv.register(); tv.call("ssap://system/turnOff"); tv.s.close()
