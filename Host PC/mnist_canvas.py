"""
Edge AI Transmitter — MNIST Digit Drawer
------------------------------------------------
Draw a digit, watch it get down-sampled to the exact 28x28 tensor your
FPGA/ESP32 pipeline will see, and fire it over UART. Optionally listens
for a prediction + per-class confidence reply from the ESP32 and plots it.

Requires: pillow, pyserial
    pip install pillow pyserial
"""

import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageDraw, ImageOps, ImageTk
import serial
import serial.tools.list_ports
import threading
import queue
import time
import re
import numpy as np

# --- Configuration ---
BAUD_RATE = 115200
CANVAS_SIZE = 300          # drawing canvas, px
MODEL_SIZE = 28            # network input size
PREVIEW_SCALE = 7          # 28 * 7 = 196px preview
SYNC = bytes([0xA5, 0x5A])          # ESP32 firmware waits for these 2 bytes, then 784 pixels
REPLY_RE = re.compile(rb"Prediction Result:\s*(\d+)")

# Palette
BG = "#12141A"
PANEL = "#1B1E27"
PANEL_BORDER = "#2A2E3A"
ACCENT = "#4FA3FF"
ACCENT_DIM = "#2D6FBF"
GOOD = "#3DD68C"
BAD = "#FF5C5C"
WARN = "#F5B942"
TEXT = "#E8EAF0"
SUBTEXT = "#8890A3"


class SerialWorker(threading.Thread):
    """Owns the serial port on its own thread so the GUI never blocks."""

    def __init__(self, out_queue: queue.Queue):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.ser: serial.Serial | None = None
        self._halt = threading.Event()

    def connect(self, port, baud):
        self.disconnect()
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = port, baud, 0.2
            ser.dtr = False          # do not reset the ESP32 when the port opens
            ser.rts = False
            ser.open()
            self.ser = ser
            time.sleep(0.3)
            self.out_queue.put(("status", "connected", port))
            return True
        except serial.SerialException as e:
            self.ser = None
            self.out_queue.put(("status", "error", str(e)))
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def send_frame(self, byte_array: bytearray):
        if not self.is_connected():
            self.out_queue.put(("send_result", "offline", None))
            return
        try:
            t0 = time.time()
            self.ser.reset_input_buffer()
            self.ser.write(SYNC + bytes(byte_array))
            self.ser.flush()

            # ESP32 prints a log line:  ">> FPGA Prediction Result: N <<"
            buf, digit = b"", None
            while time.time() - t0 < 5.0:
                buf += self.ser.read(256)
                m = REPLY_RE.search(buf)
                if m:
                    digit = int(m.group(1))
                    break
            elapsed_ms = (time.time() - t0) * 1000

            if digit is not None:
                self.out_queue.put(("send_result", "ok_with_prediction",
                                     (digit, [], elapsed_ms)))
            else:
                self.out_queue.put(("send_result", "ok_no_reply", elapsed_ms))
        except Exception as e:
            self.out_queue.put(("send_result", "error", str(e)))

    def run(self):
        # Thread just waits to be torn down; sends happen via send_frame()
        # called from the GUI thread's button handler (pyserial calls are
        # quick fire-and-wait, but we still keep the object thread-owned
        # so future streaming/async reads can hook in here).
        while not self._halt.is_set():
            time.sleep(0.2)

    def stop(self):
        self._halt.set()
        self.disconnect()


class MNISTCanvas:
    def __init__(self, root):
        self.root = root
        self.root.title("Edge AI Transmitter")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self.msg_queue = queue.Queue()
        self.worker = SerialWorker(self.msg_queue)
        self.worker.start()

        self.brush_size = tk.IntVar(value=14)
        self.show_grid = tk.BooleanVar(value=True)
        self.strokes = []          # for undo: list of PIL image snapshots
        self.connected = False

        self._build_style()
        self._build_layout()
        self._refresh_ports()
        self._poll_queue()

        self.root.bind("<c>", lambda e: self.clear_canvas())
        self.root.bind("<C>", lambda e: self.clear_canvas())
        self.root.bind("<Return>", lambda e: self.process_and_send())
        self.root.bind("<Control-z>", lambda e: self.undo())

    # ---------------------------------------------------------------- UI --
    def _build_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                         foreground=TEXT, arrowcolor=TEXT, borderwidth=0)
        style.configure("Accent.TButton", padding=(14, 9), relief="flat",
                         background=ACCENT, foreground="#0A0C10",
                         font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DIM),
                                                  ("disabled", "#3A3F4C")])

        style.configure("Ghost.TButton", padding=(12, 9), relief="flat",
                         background=PANEL_BORDER, foreground=TEXT,
                         font=("Segoe UI", 10), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#343948")])

        style.configure("TScale", background=BG, troughcolor=PANEL_BORDER)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                         font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", PANEL)])

    def _card(self, parent, **kw):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=PANEL_BORDER,
                     highlightthickness=1, **kw)
        return f

    def _build_layout(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(padx=18, pady=16)

        # ---- Header -----------------------------------------------------
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 14))

        tk.Label(header, text="Edge AI Transmitter", font=("Segoe UI", 19, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(header, text="Draw → 28×28 tensor → ESP32 → Tang Nano 20K",
                 font=("Segoe UI", 9), bg=BG, fg=SUBTEXT).pack(anchor="w")

        # ---- Body: canvas card | side panel -----------------------------
        body = tk.Frame(outer, bg=BG)
        body.pack()

        # Canvas card
        canvas_card = self._card(body)
        canvas_card.grid(row=0, column=0, sticky="n", padx=(0, 14))

        tk.Label(canvas_card, text="DRAW HERE", font=("Segoe UI", 8, "bold"),
                 bg=PANEL, fg=SUBTEXT).pack(pady=(10, 4))

        self.canvas = tk.Canvas(canvas_card, width=CANVAS_SIZE, height=CANVAS_SIZE,
                                 bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=12, pady=(0, 6))
        self.canvas.bind("<B1-Motion>", self.paint)
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self._draw_grid_lines()

        # brush + grid controls under canvas
        ctrl_row = tk.Frame(canvas_card, bg=PANEL)
        ctrl_row.pack(fill="x", padx=12, pady=(0, 12))

        tk.Label(ctrl_row, text="Brush", font=("Segoe UI", 8), bg=PANEL,
                 fg=SUBTEXT).grid(row=0, column=0, sticky="w")
        brush_scale = ttk.Scale(ctrl_row, from_=4, to=28, variable=self.brush_size,
                                 orient="horizontal", length=140)
        brush_scale.grid(row=0, column=1, padx=8)

        grid_chk = ttk.Checkbutton(ctrl_row, text="grid", variable=self.show_grid,
                                    command=self._draw_grid_lines)
        grid_chk.grid(row=0, column=2, padx=(8, 0))

        btn_row = tk.Frame(canvas_card, bg=PANEL)
        btn_row.pack(fill="x", padx=12, pady=(0, 14))
        ttk.Button(btn_row, text="Undo", style="Ghost.TButton",
                   command=self.undo).pack(side="left")
        ttk.Button(btn_row, text="Clear", style="Ghost.TButton",
                   command=self.clear_canvas).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Send to ESP32  ⏎", style="Accent.TButton",
                   command=self.process_and_send).pack(side="right")

        # Side panel
        side = tk.Frame(body, bg=BG)
        side.grid(row=0, column=1, sticky="n")
        side2 = tk.Frame(body, bg=BG)
        side2.grid(row=0, column=2, sticky="n", padx=(14, 0))

        # -- connection card
        conn_card = self._card(side)
        conn_card.pack(fill="x", pady=(0, 12))
        tk.Label(conn_card, text="CONNECTION", font=("Segoe UI", 8, "bold"),
                 bg=PANEL, fg=SUBTEXT).pack(anchor="w", padx=12, pady=(10, 6))

        port_row = tk.Frame(conn_card, bg=PANEL)
        port_row.pack(fill="x", padx=12)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_row, textvariable=self.port_var,
                                        width=16, state="readonly")
        self.port_combo.pack(side="left")
        ttk.Button(port_row, text="⟳", style="Ghost.TButton", width=2,
                   command=self._refresh_ports).pack(side="left", padx=4)

        self.connect_btn = ttk.Button(conn_card, text="Connect",
                                       style="Accent.TButton",
                                       command=self.toggle_connection)
        self.connect_btn.pack(fill="x", padx=12, pady=10)

        status_row = tk.Frame(conn_card, bg=PANEL)
        status_row.pack(fill="x", padx=12, pady=(0, 12))
        self.status_dot = tk.Canvas(status_row, width=10, height=10, bg=PANEL,
                                     highlightthickness=0)
        self.status_dot.pack(side="left")
        self._dot = self.status_dot.create_oval(1, 1, 9, 9, fill=BAD, outline="")
        self.status_lbl = tk.Label(status_row, text="Disconnected",
                                    font=("Segoe UI", 9), bg=PANEL, fg=SUBTEXT)
        self.status_lbl.pack(side="left", padx=6)

        # -- preview card (live 28x28 tensor)
        prev_card = self._card(side2)
        prev_card.pack(fill="x", pady=(0, 12))
        tk.Label(prev_card, text="MODEL INPUT (28×28)", font=("Segoe UI", 8, "bold"),
                 bg=PANEL, fg=SUBTEXT).pack(anchor="w", padx=12, pady=(10, 6))
        self.preview_canvas = tk.Canvas(
            prev_card, width=MODEL_SIZE * PREVIEW_SCALE,
            height=MODEL_SIZE * PREVIEW_SCALE, bg="black", highlightthickness=0)
        self.preview_canvas.pack(padx=12, pady=(0, 6))
        self.preview_img_id = None
        self.byte_count_lbl = tk.Label(prev_card, text="784 bytes ready",
                                        font=("Segoe UI", 8), bg=PANEL, fg=SUBTEXT)
        self.byte_count_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        # -- prediction card
        pred_card = self._card(side)
        pred_card.pack(fill="x")
        tk.Label(pred_card, text="ESP32 REPLY", font=("Segoe UI", 8, "bold"),
                 bg=PANEL, fg=SUBTEXT).pack(anchor="w", padx=12, pady=(10, 6))

        self.pred_digit_lbl = tk.Label(pred_card, text="—", font=("Segoe UI", 34, "bold"),
                                        bg=PANEL, fg=ACCENT)
        self.pred_digit_lbl.pack(pady=(0, 4))

        self.bars_frame = tk.Frame(pred_card, bg=PANEL)
        self.bars_frame.pack(padx=12, pady=(0, 6))
        self.digit_boxes = []
        for i in range(10):
            lb = tk.Label(self.bars_frame, text=str(i), width=2, font=("Segoe UI", 10, "bold"),
                          bg="#0E1016", fg=SUBTEXT)
            lb.grid(row=i // 5, column=i % 5, padx=2, pady=2)
            self.digit_boxes.append(lb)

        self.latency_lbl = tk.Label(pred_card, text="", font=("Segoe UI", 8),
                                     bg=PANEL, fg=SUBTEXT)
        self.latency_lbl.pack(anchor="w", padx=12, pady=(0, 12))

        # ---- Footer status bar -------------------------------------------
        self.footer_var = tk.StringVar(value="Ready. Draw a digit, then Send.")
        footer = tk.Label(self.root, textvariable=self.footer_var, bg="#0E1016",
                           fg=SUBTEXT, font=("Segoe UI", 9), anchor="w", padx=14, pady=6)
        footer.pack(side="bottom", fill="x")

        # image buffer backing the canvas
        self.image = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), "black")
        self.draw = ImageDraw.Draw(self.image)
        self._update_preview()

    # ------------------------------------------------------------ drawing --
    def _draw_grid_lines(self):
        self.canvas.delete("grid")
        if not self.show_grid.get():
            return
        step = CANVAS_SIZE // 7
        for i in range(1, 7):
            self.canvas.create_line(i * step, 0, i * step, CANVAS_SIZE,
                                     fill="#242832", tags="grid")
            self.canvas.create_line(0, i * step, CANVAS_SIZE, i * step,
                                     fill="#242832", tags="grid")
        self.canvas.tag_lower("grid")

    def on_press(self, event):
        self.strokes.append(self.image.copy())
        if len(self.strokes) > 20:
            self.strokes.pop(0)
        self.paint(event)

    def on_release(self, event):
        self._update_preview()

    def paint(self, event):
        r = self.brush_size.get()
        x1, y1, x2, y2 = event.x - r, event.y - r, event.x + r, event.y + r
        self.canvas.create_oval(x1, y1, x2, y2, fill="white", outline="white",
                                 tags="ink")
        self.draw.ellipse([x1, y1, x2, y2], fill="white")
        self._update_preview()

    def undo(self):
        if not self.strokes:
            return
        self.image = self.strokes.pop()
        self.draw = ImageDraw.Draw(self.image)
        self.canvas.delete("ink")
        self.canvas.tag_raise("grid")
        # redraw from buffer since individual ovals aren't tracked separately
        tmp = self.image.point(lambda p: p)
        self._redraw_canvas_from_image(tmp)
        self._update_preview()
        self.footer_var.set("Undid last stroke.")

    def _redraw_canvas_from_image(self, img):
        # Cheap redraw: blit the PIL buffer back onto the tk canvas as an image
        self._backdrop = ImageTk.PhotoImage(img.convert("RGB"))
        if hasattr(self, "_backdrop_id") and self._backdrop_id:
            self.canvas.delete(self._backdrop_id)
        self._backdrop_id = self.canvas.create_image(0, 0, anchor="nw",
                                                       image=self._backdrop)
        self.canvas.tag_lower(self._backdrop_id)
        self._draw_grid_lines()

    def clear_canvas(self):
        self.canvas.delete("ink")
        if hasattr(self, "_backdrop_id") and self._backdrop_id:
            self.canvas.delete(self._backdrop_id)
            self._backdrop_id = None
        self.strokes.clear()
        self.image = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), "black")
        self.draw = ImageDraw.Draw(self.image)
        self._update_preview()
        self._clear_prediction()
        self.footer_var.set("Canvas cleared. Ready to draw.")

    def _preprocess(self):
        """Crop to the digit, scale longest side to 20 px, centre by centre of mass in 28x28.
        Returns uint8 array 28x28 with values 0..127 (what the model was trained on)."""
        a = np.array(self.image, dtype=np.float32)
        ys, xs = np.where(a > 30)
        if len(xs) == 0:
            return np.zeros((MODEL_SIZE, MODEL_SIZE), dtype=np.uint8)
        a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h, w = a.shape
        k = 20.0 / max(h, w)
        a = np.array(Image.fromarray(a.astype(np.uint8)).resize(
            (max(1, round(w * k)), max(1, round(h * k))), Image.Resampling.LANCZOS),
            dtype=np.float32)
        tot = a.sum()
        cy = (a.sum(axis=1) * np.arange(a.shape[0])).sum() / tot
        cx = (a.sum(axis=0) * np.arange(a.shape[1])).sum() / tot
        oy = min(max(int(round(14 - cy)), 0), MODEL_SIZE - a.shape[0])
        ox = min(max(int(round(14 - cx)), 0), MODEL_SIZE - a.shape[1])
        out = np.zeros((MODEL_SIZE, MODEL_SIZE), dtype=np.float32)
        out[oy:oy + a.shape[0], ox:ox + a.shape[1]] = a
        return (out * 127.0 / 255.0).round().astype(np.uint8)

    def _update_preview(self):
        self._last_bytes = self._preprocess()
        resized = Image.fromarray((self._last_bytes.astype(np.float32) * 255 / 127).astype(np.uint8))
        self._last_tensor_img = resized
        big = resized.resize((MODEL_SIZE * PREVIEW_SCALE, MODEL_SIZE * PREVIEW_SCALE),
                              Image.Resampling.NEAREST)
        self._preview_tk = ImageTk.PhotoImage(big)
        if self.preview_img_id is None:
            self.preview_img_id = self.preview_canvas.create_image(
                0, 0, anchor="nw", image=self._preview_tk)
        else:
            self.preview_canvas.itemconfig(self.preview_img_id, image=self._preview_tk)

    # --------------------------------------------------------- connection --
    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])
        elif not ports:
            self.port_var.set("")

    def toggle_connection(self):
        if self.connected:
            self.worker.disconnect()
            self.connected = False
            self._set_status(False, "Disconnected")
            self.connect_btn.config(text="Connect")
        else:
            port = self.port_var.get()
            if not port:
                messagebox.showwarning("No port selected",
                                        "Pick a COM/serial port first, or plug in the ESP32.")
                return
            self.footer_var.set(f"Connecting to {port} @ {BAUD_RATE}...")
            threading.Thread(target=self.worker.connect, args=(port, BAUD_RATE),
                              daemon=True).start()

    def _set_status(self, ok, text):
        self.status_dot.itemconfig(self._dot, fill=GOOD if ok else BAD)
        self.status_lbl.config(text=text)

    # --------------------------------------------------------------- send --
    def process_and_send(self):
        byte_array = bytearray(self._last_bytes.flatten().tobytes())
        self.byte_count_lbl.config(text=f"{len(byte_array)} bytes ready")

        if not self.connected:
            self.footer_var.set("Offline — 784 bytes generated but not sent "
                                 "(connect to an ESP32 first).")
            return

        self.footer_var.set("Sending 784 bytes over UART...")
        self._clear_prediction()
        threading.Thread(target=self.worker.send_frame, args=(byte_array,),
                          daemon=True).start()

    def _clear_prediction(self):
        self.pred_digit_lbl.config(text="—")
        self.latency_lbl.config(text="")
        for lb in self.digit_boxes:
            lb.config(bg="#0E1016", fg=SUBTEXT)

    def _show_prediction(self, digit, confs, elapsed_ms):
        self.pred_digit_lbl.config(text=str(digit))
        for i, lb in enumerate(self.digit_boxes):
            lb.config(bg=GOOD if i == digit else "#0E1016",
                      fg="#0A0C10" if i == digit else SUBTEXT)
        self.latency_lbl.config(text=f"Round-trip: {elapsed_ms:.1f} ms")

    # ------------------------------------------------------------- queue --
    def _poll_queue(self):
        try:
            while True:
                kind, status, payload = self.msg_queue.get_nowait()
                if kind == "status":
                    if status == "connected":
                        self.connected = True
                        self._set_status(True, f"Connected · {payload}")
                        self.connect_btn.config(text="Disconnect")
                        self.footer_var.set(f"Connected to {payload} @ {BAUD_RATE} baud.")
                    elif status == "error":
                        self.connected = False
                        self._set_status(False, "Connection failed")
                        self.connect_btn.config(text="Connect")
                        self.footer_var.set(f"Could not open port: {payload}")
                elif kind == "send_result":
                    if status == "ok_with_prediction":
                        digit, confs, elapsed_ms = payload
                        self._show_prediction(digit, confs, elapsed_ms)
                        self.footer_var.set(
                            f"Sent 784 bytes · ESP32 replied digit={digit} "
                            f"in {elapsed_ms:.1f} ms.")
                    elif status == "ok_no_reply":
                        elapsed_ms = payload
                        self.footer_var.set(
                            f"Sent 784 bytes · no reply protocol detected "
                            f"({elapsed_ms:.1f} ms).")
                    elif status == "offline":
                        self.footer_var.set("Not connected — nothing sent.")
                    elif status == "error":
                        self.footer_var.set(f"Serial error: {payload}")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def on_close(self):
        self.worker.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MNISTCanvas(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()