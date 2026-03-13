import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import threading
import subprocess
import os
import time
import sys
import imageio_ffmpeg
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np

class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Batch Video Watermarker")
        if os.name == 'nt':
            self.root.state('zoomed')
        else:
            self.root.attributes('-zoomed', True)
        
        self.video_files = []
        self.watermark_file = ""
        self.bgm_file = ""
        self.output_dir = ""
        self.custom_x_ratio = 0.0
        self.custom_y_ratio = 0.0
        self.bg_width = 1
        self.bg_height = 1
        self.orig_v_width = 1.0 
        self._drag_data = {"x": 0, "y": 0}
        
        self.video_cap = None
        self.is_playing = False
        self.play_job = None
        
        self.mute_var = tk.BooleanVar(value=False)
        self.opacity_var = tk.DoubleVar(value=100)
        self.wm_start_time_var = tk.StringVar(value="0")
        self.wm_end_time_var = tk.StringVar(value="")
        
        # Registration for numeric validation
        self._vcmd = (self.root.register(self.validate_numeric), '%P')

        # UI Elements
        self.setup_ui()
        
    def validate_numeric(self, P):
        if P == "" or P == ".":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    def setup_ui(self):
        style = ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
            
        self.main_container = tk.Frame(self.root, padx=10, pady=10)
        self.main_container.pack(fill="both", expand=True)

        # ---------------- SIDEBAR (Left Column) ---------------- #
        self.sidebar_frame = tk.Frame(self.main_container, width=380)
        self.sidebar_frame.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar_frame.pack_propagate(False)

        # 1. VIDEO SETTINGS BLOCK
        frame_video_group = tk.LabelFrame(self.sidebar_frame, text="VIDEO SETTINGS", padx=10, pady=10, fg="blue", font=("Arial", 10, "bold"))
        frame_video_group.pack(fill="x", pady=(0, 10))

        # List & Add/Remove
        frame_list = tk.Frame(frame_video_group)
        frame_list.pack(fill="x", pady=(0, 5))
        
        l_box_frame = tk.Frame(frame_list)
        l_box_frame.pack(fill="x", expand=True)
        self.listbox_videos = tk.Listbox(l_box_frame, selectmode=tk.BROWSE, height=4, exportselection=False)
        self.listbox_videos.pack(side="left", fill="x", expand=True)
        scrollbar = tk.Scrollbar(l_box_frame, orient="vertical", command=self.listbox_videos.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox_videos.config(yscrollcommand=scrollbar.set)
        self.listbox_videos.bind('<<ListboxSelect>>', self.show_preview)
        
        btn_list = tk.Frame(frame_list)
        btn_list.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_list, text="Add Videos", command=self.add_videos).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_list, text="Remove", command=self.remove_videos).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # Global Config (Format, Quality, Speed)
        frame_v_cfg = tk.Frame(frame_video_group)
        frame_v_cfg.pack(fill="x", pady=5)
        
        ttk.Label(frame_v_cfg, text="Format:").grid(row=0, column=0, sticky="w", pady=2)
        self.format_var = tk.StringVar(value="Original")
        ttk.Combobox(frame_v_cfg, textvariable=self.format_var, values=["Original", "MP4", "MKV", "AVI", "MOV"], state="readonly", width=12).grid(row=0, column=1, sticky="ew", padx=10)
        
        ttk.Label(frame_v_cfg, text="Quality:").grid(row=1, column=0, sticky="w", pady=2)
        self.quality_var = tk.StringVar(value="Medium (Balanced)")
        ttk.Combobox(frame_v_cfg, textvariable=self.quality_var, values=["High (Lossless)", "Medium (Balanced)", "Low (Smaller File)"], state="readonly", width=12).grid(row=1, column=1, sticky="ew", padx=10)

        ttk.Label(frame_v_cfg, text="Timelapse:").grid(row=2, column=0, sticky="w", pady=2)
        self.speed_var = tk.StringVar(value="1x (Normal)")
        ttk.Combobox(frame_v_cfg, textvariable=self.speed_var, values=["1x (Normal)", "2x", "4x", "8x", "16x", "0.5x (Slow)"], state="readonly", width=12).grid(row=2, column=1, sticky="ew", padx=10)

        # Output
        frame_out = tk.Frame(frame_video_group, pady=5)
        frame_out.pack(fill="x")
        self.lbl_output = tk.Label(frame_out, text="Output: Not Set", fg="gray", anchor="w", font=("Arial", 8), wraplength=300)
        self.lbl_output.pack(fill="x")
        ttk.Button(frame_out, text="Set Output Folder", command=self.select_output_dir).pack(fill="x")

        # 2. WATERMARK SETTINGS BLOCK
        frame_wm_group = tk.LabelFrame(self.sidebar_frame, text="WATERMARK SETTINGS", padx=10, pady=10, fg="darkgreen", font=("Arial", 10, "bold"))
        frame_wm_group.pack(fill="x", pady=(0, 10))

        # Preview Logo
        wm_info = tk.Frame(frame_wm_group)
        wm_info.pack(fill="x", pady=(0, 5))
        self.lbl_wm_preview = tk.Label(wm_info, text="None", bg="lightgray", width=6, height=3)
        self.lbl_wm_preview.pack(side="left", padx=(0, 10))
        self.lbl_watermark = tk.Label(wm_info, text="No mark selected", fg="gray", anchor="w", font=("Arial", 8), wraplength=130)
        self.lbl_watermark.pack(side="left", fill="x", expand=True)

        # Notebook tabs
        self.wm_notebook = ttk.Notebook(frame_wm_group)
        self.wm_notebook.pack(fill="x", pady=5)
        style.configure("TNotebook", padding=1)
        self.wm_notebook.bind("<<NotebookTabChanged>>", self.on_wm_tab_changed)
        
        self.tab_image = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_image, text="Image")
        ttk.Button(self.tab_image, text="Browse Image", command=self.select_watermark).pack(fill="x", padx=5, pady=5)
        
        self.tab_text = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_text, text="Text")
        t_box = tk.Frame(self.tab_text, pady=5)
        t_box.pack(fill="x")
        ttk.Label(t_box, text="Text:").grid(row=0, column=0, padx=2)
        self.text_var = tk.StringVar(value="Sample")
        ttk.Entry(t_box, textvariable=self.text_var, width=12).grid(row=0, column=1, sticky="ew")
        ttk.Button(self.tab_text, text="Apply Text Logo", command=self.generate_text_watermark).pack(fill="x", padx=5, pady=2)
        
        ttk.Button(frame_wm_group, text="X Clear Watermark", command=self.clear_watermark_selection).pack(fill="x", pady=2)

        # Detailed Params
        frame_wm_det = tk.Frame(frame_wm_group)
        frame_wm_det.pack(fill="x", pady=5)
        
        ttk.Label(frame_wm_det, text="Pos:").grid(row=0, column=0, sticky="w")
        self.position_var = tk.StringVar(value="Bottom Right")
        dp = ttk.Combobox(frame_wm_det, textvariable=self.position_var, values=["Top Left", "Top Right", "Bottom Left", "Bottom Right", "Center", "Custom (Drag)"], state="readonly", width=12)
        dp.grid(row=0, column=1, sticky="ew", padx=10, pady=2)
        dp.bind("<<ComboboxSelected>>", self.on_position_changed)
        
        ttk.Label(frame_wm_det, text="Scale:").grid(row=1, column=0, sticky="w")
        self.scale_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_wm_det, from_=10, to=300, orient="horizontal", variable=self.scale_var, command=self.on_transform_changed).grid(row=1, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="Opacity:").grid(row=2, column=0, sticky="w")
        self.opacity_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_wm_det, from_=0, to=100, orient="horizontal", variable=self.opacity_var, command=self.on_transform_changed).grid(row=2, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="Start(s):").grid(row=3, column=0, sticky="w")
        tk.Entry(frame_wm_det, textvariable=self.wm_start_time_var, width=12, validate='key', validatecommand=self._vcmd).grid(row=3, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="End(s):").grid(row=4, column=0, sticky="w")
        tk.Entry(frame_wm_det, textvariable=self.wm_end_time_var, width=12, validate='key', validatecommand=self._vcmd).grid(row=4, column=1, sticky="ew", padx=10, pady=2)

        # 3. AUDIO (Inside or below)
        frame_audio = tk.Frame(frame_wm_group, pady=5)
        frame_audio.pack(fill="x")
        ttk.Separator(frame_audio, orient='horizontal').pack(fill='x', pady=5)
        self.lbl_bgm = tk.Label(frame_audio, text="Audio: Original", fg="gray", font=("Arial", 8))
        self.lbl_bgm.pack(fill="x")
        
        a_btns = tk.Frame(frame_audio)
        a_btns.pack(fill="x")
        ttk.Button(a_btns, text="Set Music", command=self.select_bgm).pack(side="left", fill="x", expand=True)
        ttk.Button(a_btns, text="X", command=self.clear_bgm, width=3).pack(side="left", padx=2)
        tk.Checkbutton(frame_audio, text="Mute Original", variable=self.mute_var).pack(anchor="w")

        # Action block
        frame_actions = tk.Frame(self.sidebar_frame, pady=5)
        frame_actions.pack(side="bottom", fill="x")
        self.lbl_status = tk.Label(frame_actions, text="Ready", fg="blue", anchor="w")
        self.lbl_status.pack(fill="x")
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_actions, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=5)
        self.btn_start = ttk.Button(frame_actions, text="🚀 START PROCESS", command=self.start_processing)
        self.btn_start.pack(fill="x", ipady=10)

        # ---------------- PLAYER PREVIEW (Right) ---------------- #
        frame_preview = tk.LabelFrame(self.main_container, text="Video Preview (Drag logo to position)", padx=5, pady=5)
        frame_preview.pack(side="right", fill="both", expand=True)
        
        self.canvas_preview = tk.Canvas(frame_preview, bg="black")
        self.canvas_preview.pack(fill="both", expand=True, pady=(0, 5))
        self.canvas_preview.tag_bind("watermark", "<ButtonPress-1>", self.on_drag_start)
        self.canvas_preview.tag_bind("watermark", "<B1-Motion>", self.on_drag_motion)
        
        ctrls = tk.Frame(frame_preview)
        ctrls.pack(side="bottom", fill="x", pady=5)
        
        self.btn_play_pause = ttk.Button(ctrls, text="▶ Play", command=self.toggle_play, width=10)
        self.btn_play_pause.pack(side="left")
        
        ttk.Button(ctrls, text="⏹ Stop", command=self.stop_playback, width=8).pack(side="left", padx=5)
        self.btn_audio_preview = ttk.Button(ctrls, text="🔊 Play with Audio", command=self.preview_with_audio, width=18)
        self.btn_audio_preview.pack(side="left", padx=5)
        
        self.seek_var = tk.DoubleVar()
        self.seek_slider = ttk.Scale(ctrls, from_=0, to=100, orient="horizontal", variable=self.seek_var, command=self.seek_video)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        self.lbl_time = ttk.Label(ctrls, text="00:00 / 00:00")
        self.lbl_time.pack(side="left", padx=(0, 5))

    def add_videos(self):
        files = filedialog.askopenfilenames(title="Select Videos", filetypes=(("Video", "*.mp4 *.avi *.mov *.mkv"), ("All", "*.*")))
        for f in files:
            if f not in self.video_files:
                self.video_files.append(f)
                self.listbox_videos.insert(tk.END, os.path.basename(f))

    def remove_videos(self):
        selected = self.listbox_videos.curselection()
        if not selected: return
        idx = selected[0]
        self.listbox_videos.delete(idx)
        del self.video_files[idx]
        if len(self.video_files) > 0:
            new_idx = min(idx, len(self.video_files)-1)
            self.listbox_videos.select_set(new_idx)
            self.show_preview(None)
        else:
            if self.video_cap: self.video_cap.release()
            self.video_cap = None
            self.clear_preview("Select a video\nto preview")
            self.lbl_time.config(text="00:00 / 00:00")
            self.wm_start_time_var.set("0")
            self.wm_end_time_var.set("")

    def show_preview(self, event):
        selected = self.listbox_videos.curselection()
        if not selected: return
        video_path = self.video_files[selected[-1]]
        if self.video_cap: self.video_cap.release()
        self.video_cap = cv2.VideoCapture(video_path)
        fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30
        frames = self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = frames / fps if fps > 0 else 0
        self.wm_start_time_var.set("0")
        self.wm_end_time_var.set(f"{duration:.1f}")
        self.is_playing = False
        self.btn_play_pause.config(text="▶ Play")
        if self.play_job: self.root.after_cancel(self.play_job); self.play_job = None
        self.update_video_frame(initial_load=True)

    def toggle_play(self):
        if not self.video_cap or not self.video_cap.isOpened(): return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.btn_play_pause.config(text="⏸ Pause")
            self.update_video_frame()
        else:
            self.btn_play_pause.config(text="▶ Play")
            if self.play_job: self.root.after_cancel(self.play_job)

    def stop_playback(self):
        self.is_playing = False
        self.btn_play_pause.config(text="▶ Play")
        if self.play_job: self.root.after_cancel(self.play_job); self.play_job = None
        if self.video_cap and self.video_cap.isOpened():
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.seek_var.set(0)
            self.update_video_frame(initial_load=True)

    def seek_video(self, val):
        if not self.video_cap or not self.video_cap.isOpened(): return
        total = max(1, self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, int((float(val)/100.0)*total))
        if not self.is_playing: self.update_video_frame(initial_load=True)

    def update_video_frame(self, initial_load=False):
        if not self.video_cap or (not self.is_playing and not initial_load): return
        t_start = time.time()
        ret, frame = self.video_cap.read()
        if ret:
            c_w, c_h = max(10, self.canvas_preview.winfo_width()), max(10, self.canvas_preview.winfo_height())
            v_w = self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            self.orig_v_width = v_w
            h, w = frame.shape[:2]
            sc = min(c_w/w, c_h/h)
            new_w, new_h = int(w*sc), int(h*sc)
            if new_w > 0 and new_h > 0:
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self.bg_width, self.bg_height = img.size
            self.preview_bg_img = ImageTk.PhotoImage(img)
            self.draw_preview_canvas(self.watermark_file, self.position_var.get(), v_w, fast_mode=self.is_playing)
            cur = self.video_cap.get(cv2.CAP_PROP_POS_FRAMES)
            tot = max(1, self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30
            self.lbl_time.config(text=f"{self.fmt_time(cur/fps)} / {self.fmt_time(tot/fps)}")
            self.seek_var.set((cur/tot)*100)
            if self.is_playing:
                delay = int(max(1, (1000/fps) - (time.time()-t_start)*1000))
                self.play_job = self.root.after(delay, self.update_video_frame)
        else: self.stop_playback()

    def draw_preview_canvas(self, path, pos, v_w, fast_mode=False):
        self.canvas_preview.delete("all")
        c_w, c_h = self.canvas_preview.winfo_width(), self.canvas_preview.winfo_height()
        ox, oy = (c_w-self.bg_width)//2, (c_h-self.bg_height)//2
        self.canvas_preview.create_image(ox, oy, image=self.preview_bg_img, anchor="nw", tags="bg")
        visible = True
        try:
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30
            cur = self.video_cap.get(cv2.CAP_PROP_POS_FRAMES)/fps
            start = float(self.wm_start_time_var.get() or 0)
            end = self.wm_end_time_var.get().strip()
            if (cur < start) or (end and cur > float(end)): visible = False
        except: pass
        if path and os.path.exists(path) and visible:
            try:
                wm = Image.open(path).convert("RGBA")
                usc = self.scale_var.get()/100.0
                if usc != 1.0: wm = wm.resize((max(1,int(wm.size[0]*usc)), max(1,int(wm.size[1]*usc))), Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS)
                opa = self.opacity_var.get()/100.0
                if opa < 1.0:
                    r,g,b,a = wm.split()
                    wm = Image.merge("RGBA", (r,g,b,a.point(lambda p: int(p*opa))))
                vsc = self.bg_width / v_w if v_w > 0 else 1.0
                ww, wh = int(wm.size[0]*vsc), int(wm.size[1]*vsc)
                if ww>0 and wh>0:
                    wm = wm.resize((ww, wh), Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS)
                    self.preview_wm_img = ImageTk.PhotoImage(wm)
                    pad = 10*vsc
                    px, py = pad, pad
                    if pos == "Top Right": px = self.bg_width-ww-pad
                    elif pos == "Bottom Left": py = self.bg_height-wh-pad
                    elif pos == "Bottom Right": px, py = self.bg_width-ww-pad, self.bg_height-wh-pad
                    elif pos == "Center": px, py = (self.bg_width-ww)/2, (self.bg_height-wh)/2
                    elif pos == "Custom (Drag)": px, py = self.custom_x_ratio*self.bg_width, self.custom_y_ratio*self.bg_height
                    self.canvas_preview.create_image(ox+px, oy+py, image=self.preview_wm_img, anchor="nw", tags="watermark")
            except: pass

    def clear_preview(self, text):
        self.canvas_preview.delete("all")
        w, h = self.canvas_preview.winfo_width(), self.canvas_preview.winfo_height()
        self.canvas_preview.create_text(max(w,400)//2, max(h,400)//2, text=text, fill="white")

    def on_drag_start(self, e): self._drag_data = {'x':e.x, 'y':e.y}
    def on_drag_motion(self, e):
        dx, dy = e.x-self._drag_data['x'], e.y-self._drag_data['y']
        self.canvas_preview.move("watermark", dx, dy)
        self._drag_data = {'x':e.x, 'y':e.y}
        coords = self.canvas_preview.coords("watermark")
        if coords:
            ox, oy = (self.canvas_preview.winfo_width()-self.bg_width)//2, (self.canvas_preview.winfo_height()-self.bg_height)//2
            self.custom_x_ratio = max(0.0, min(1.0, (coords[0]-ox)/self.bg_width))
            self.custom_y_ratio = max(0.0, min(1.0, (coords[1]-oy)/self.bg_height))
            if self.position_var.get() != "Custom (Drag)": self.position_var.set("Custom (Drag)")

    def update_wm_preview(self):
        if self.watermark_file:
            try:
                img = Image.open(self.watermark_file).copy(); img.thumbnail((80,80), Image.Resampling.LANCZOS)
                self.wm_preview_img = ImageTk.PhotoImage(img)
                self.lbl_wm_preview.config(image=self.wm_preview_img, text="", width=0, height=0)
            except: self.lbl_wm_preview.config(image='', text="Error", width=6, height=3)

    def select_watermark(self):
        f = filedialog.askopenfilename(title="Watermark", filetypes=(("Image","*.png *.jpg *.jpeg"),("All","*.*")))
        if f: self.watermark_file=f; self.lbl_watermark.config(text=os.path.basename(f), fg="black"); self.update_wm_preview(); self.refresh_preview()

    def on_wm_tab_changed(self, e): self.clear_watermark_selection()
    def clear_watermark_selection(self):
        self.watermark_file = ""; self.lbl_watermark.config(text="No image", fg="gray"); self.wm_preview_img=None; self.lbl_wm_preview.config(image='', text="None", width=6, height=3); self.refresh_preview()

    def select_bgm(self):
        f = filedialog.askopenfilename(title="Music", filetypes=(("Audio","*.mp3 *.wav *.m4a *.aac"),("All","*.*")))
        if f: self.bgm_file=f; self.lbl_bgm.config(text=f"Replace with: {os.path.basename(f)}", fg="blue")
    def clear_bgm(self): self.bgm_file=""; self.lbl_bgm.config(text="Audio: Original", fg="gray")

    def preview_with_audio(self):
        sel = self.listbox_videos.curselection()
        if not sel: messagebox.showwarning("Warning", "Select a video first."); return
        self.btn_audio_preview.config(state="disabled")
        self.lbl_status.config(text="Generating audio preview (10s)...", fg="orange")
        threading.Thread(target=self._run_audio_preview_render, args=(self.video_files[sel[-1]],), daemon=True).start()

    def _run_audio_preview_render(self, path):
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        tmp = os.path.join(os.path.dirname(__file__), "temp_previews")
        if not os.path.exists(tmp): os.makedirs(tmp)
        out = os.path.join(tmp, "preview_sample.mp4")
        v_f, a_f = self.get_ffmpeg_complex_filter_str()
        cmd = [exe, "-y", "-i", path]
        if self.watermark_file: cmd.extend(["-i", self.watermark_file])
        if self.bgm_file: cmd.extend(["-stream_loop", "-1", "-i", self.bgm_file])
        cmd.extend(["-filter_complex", f"{v_f};{a_f}", "-map", "[v]", "-map", "[a]", "-t", "10", "-preset", "ultrafast", out])
        si = subprocess.STARTUPINFO() if os.name=='nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            subprocess.run(cmd, startupinfo=si, check=True)
            if os.name=='nt': os.startfile(out)
            else: subprocess.run(["open" if sys.platform=="darwin" else "xdg-open", out])
        except Exception as e: self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally: self.root.after(0, lambda: (self.btn_audio_preview.config(state="normal"), self.lbl_status.config(text="Ready", fg="blue")))

    def on_position_changed(self, e=None): self.refresh_preview()
    def on_transform_changed(self, e=None): self.refresh_preview()
    def refresh_preview(self): 
        if self.orig_v_width > 0: self.draw_preview_canvas(self.watermark_file, self.position_var.get(), self.orig_v_width)

    def pick_color(self):
        c = colorchooser.askcolor(title="Color", initialcolor=self.text_color_var.get())
        if c and c[1]: self.text_color_var.set(c[1])

    def generate_text_watermark(self):
        txt = self.text_var.get()
        if not txt: return
        try: font = ImageFont.truetype("arial.ttf", 80)
        except: font = ImageFont.load_default()
        dr = ImageDraw.Draw(Image.new("RGBA", (1,1)))
        try: bb = dr.textbbox((0,0), txt, font=font); w, h = bb[2]-bb[0], bb[3]-bb[1]
        except: w, h = dr.textsize(txt, font=font)
        img = Image.new("RGBA", (w+20, h+20), (255,255,255,0))
        ImageDraw.Draw(img).text((10,10), txt, fill="white", font=font)
        p = os.path.join(os.path.dirname(__file__), "watermark_app_temp_text.png")
        img.save(p); self.watermark_file=p; self.lbl_watermark.config(text=f"Text: {txt[:15]}...", fg="black"); self.update_wm_preview(); self.refresh_preview()

    def select_output_dir(self):
        d = filedialog.askdirectory(title="Output")
        if d: self.output_dir=d; self.lbl_output.config(text=d, fg="black")
    def open_output_dir(self):
        if self.output_dir: os.startfile(self.output_dir) if os.name=='nt' else subprocess.call(['xdg-open', self.output_dir])

    def get_ffmpeg_complex_filter_str(self):
        p, pad = self.position_var.get(), 10
        pos = {"Top Left":f"{pad}:{pad}", "Top Right":f"W-w-{pad}:{pad}", "Bottom Left":f"{pad}:H-h-{pad}", "Bottom Right":f"W-w-{pad}:H-h-{pad}", "Center":"(W-w)/2:(H-h)/2"}.get(p, f"W*{self.custom_x_ratio}:H*{self.custom_y_ratio}")
        flt = ["format=rgba"]
        usc = self.scale_var.get()/100.0
        if usc != 1.0: flt.append(f"scale=iw*{usc}:ih*{usc}")
        opa = self.opacity_var.get()/100.0
        if opa < 1.0: flt.append(f"colorchannelmixer=aa={opa}")
        en = ""
        try:
            st = float(self.wm_start_time_var.get() or 0)
            ed = self.wm_end_time_var.get().strip()
            en = f":enable='between(t,{st},{ed})'" if ed else (f":enable='gte(t,{st})'" if st>0 else "")
        except: pass
        spd = float(self.speed_var.get().split('x')[0])
        v_spd = f"setpts={1/spd}*PTS"
        a_f = []
        tmp_s = spd
        while tmp_s>2.0: a_f.append("atempo=2.0"); tmp_s/=2.0
        while tmp_s<0.5: a_f.append("atempo=0.5"); tmp_s*=2.0
        if tmp_s!=1.0: a_f.append(f"atempo={tmp_s}")
        a_s = ",".join(a_f) if a_f else "anull"
        wm_i = 1 if self.watermark_file else -1
        bg_i = (wm_i+1) if self.bgm_file and wm_i!=-1 else (1 if self.bgm_file else -1)
        v_res = f"[{wm_i}:v]{','.join(flt)}[wm];[0:v]{v_spd}[vs];[vs][wm]overlay={pos}{en}[v]" if wm_i!=-1 else f"[0:v]{v_spd}[v]"
        a_res = f"[{bg_i}:a]anull[a]" if bg_i!=-1 else (f"anullsrc=r=44100:cl=stereo[a]" if self.mute_var.get() else f"[0:a]{a_s}[a]")
        return v_res, a_res

    def start_processing(self):
        if not self.video_files or not self.watermark_file or not self.output_dir: messagebox.showerror("Error", "Missing input/output/watermark."); return
        self.btn_start.config(state="disabled"); self.progress_var.set(0)
        threading.Thread(target=self.process_videos, daemon=True).start()

    def process_videos(self):
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        f_v, f_a = self.get_ffmpeg_complex_filter_str()
        for i, path in enumerate(self.video_files):
            name, ext = os.path.splitext(os.path.basename(path))
            out_ext = ext if self.format_var.get()=="Original" else f".{self.format_var.get().lower()}"
            out = os.path.join(self.output_dir, f"watermarked_{name}{out_ext}")
            crf = {"Low (Smaller File)":"28", "Medium (Balanced)":"23"}.get(self.quality_var.get(), "18")
            cmd = [exe, "-y", "-i", path]
            if self.watermark_file: cmd.extend(["-i", self.watermark_file])
            if self.bgm_file: cmd.extend(["-stream_loop", "-1", "-i", self.bgm_file])
            cmd.extend(["-filter_complex", f"{f_v};{f_a}", "-map", "[v]", "-map", "[a]", "-shortest", "-c:v", "libx264", "-crf", crf, "-preset", "fast", "-c:a", "aac", out])
            si = subprocess.STARTUPINFO() if os.name=='nt' else None
            if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try: subprocess.run(cmd, startupinfo=si, check=True)
            except Exception as e: self.root.after(0, lambda: messagebox.showerror("Error", str(e))); continue
            self.root.after(0, lambda p=((i+1)/len(self.video_files))*100: self.progress_var.set(p))
        self.root.after(0, lambda: (self.lbl_status.config(text="Completed!", fg="green"), self.btn_start.config(state="normal"), messagebox.showinfo("Success", "Done.")))

    def fmt_time(self, s): mins, secs = int(max(0,s)//60), int(max(0,s)%60); return f"{mins:02d}:{secs:02d}"

if __name__ == "__main__":
    root = tk.Tk(); app = WatermarkApp(root); root.mainloop()
