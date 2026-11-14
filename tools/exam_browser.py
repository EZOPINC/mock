"""Small dependency-free CDP client for the opt-in local Edge UI check."""
import base64
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen


class ExamBrowser:
    def __init__(self):
        self.profile = tempfile.TemporaryDirectory(prefix="exam-ui-edge-")
        executable = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
        self.process = subprocess.Popen([
            str(executable), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--remote-debugging-port=0",
            "--remote-allow-origins=http://localhost", "--user-data-dir=" + self.profile.name,
            "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        port_file = Path(self.profile.name) / "DevToolsActivePort"
        for _ in range(100):
            if port_file.exists():
                break
            time.sleep(.1)
        port = port_file.read_text().splitlines()[0]
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as response:
            tab = next(tab for tab in json.load(response) if tab["type"] == "page")
        url = urlparse(tab["webSocketDebuggerUrl"])
        self.socket = socket.create_connection((url.hostname, url.port), timeout=15)
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f"GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            header += self.socket.recv(1)
        if b"101" not in header.splitlines()[0]:
            raise RuntimeError("Edge debugger handshake failed")
        self.sequence = 0
        self.call("Page.enable")

    def read(self, size):
        data = b""
        while len(data) < size:
            part = self.socket.recv(size - len(data))
            if not part:
                raise RuntimeError("Edge debugger disconnected")
            data += part
        return data

    def call(self, method, **params):
        self.sequence += 1
        data = json.dumps(dict(id=self.sequence, method=method, params=params)).encode()
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x81, 0x80 | size]) if size < 126 else bytes([0x81, 0xfe]) + struct.pack("!H", size)
        self.socket.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)))
        message = b""
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            frame_mask = self.read(4) if second & 128 else None
            payload = self.read(size)
            if frame_mask:
                payload = bytes(byte ^ frame_mask[i % 4] for i, byte in enumerate(payload))
            message += payload
            if not first & 128:
                continue
            result = json.loads(message)
            message = b""
            if result.get("id") == self.sequence:
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(.1)
        raise AssertionError(f"Browser condition timed out: {expression}")

    def navigate(self, url):
        self.call("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def viewport(self, width, height=1000):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        self.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    def screenshot(self, path, selector=None):
        params = {"format": "png"}
        if selector:
            # Isolated whole-question captures omit sticky chrome; the ordinary
            # viewport screenshots above them retain it exactly as students see it.
            self.evaluate("document.querySelectorAll('.ui-header,.mock-toolbar,.mock-action-bar').forEach(e => {e.dataset.captureVisibility=e.style.visibility; e.style.visibility='hidden';})")
            params["clip"] = self.evaluate(f"(() => {{ const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return {{x:0,y:r.top+scrollY,width:innerWidth,height:r.height,scale:1}}; }})()")
            params["captureBeyondViewport"] = True
        try:
            Path(path).write_bytes(base64.b64decode(self.call("Page.captureScreenshot", **params)["data"]))
        finally:
            if selector:
                self.evaluate("document.querySelectorAll('[data-capture-visibility]').forEach(e => {e.style.visibility=e.dataset.captureVisibility; delete e.dataset.captureVisibility;})")

    def key(self, key, code, virtual):
        self.call("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=virtual)
        self.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=virtual)

    def close(self):
        self.socket.close()
        self.process.terminate()
        self.process.wait(timeout=10)
        # Edge helpers may finish after the parent; temp files are outside the repo.
        try:
            self.profile.cleanup()
        except PermissionError:
            pass
