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
        self.orig_v_width = 1.0 # Default non-zero
        self._drag_data = {"x": 0, "y": 0}
        
        self.video_cap = None
        self.is_playing = False
        self.play_job = None
        
        self.mute_var = tk.BooleanVar(value=False)
        self.opacity_var = tk.DoubleVar(value=100)
        
        # UI Elements
        self.setup_ui()
        
    def setup_ui(self):
        # Apply a simple built-in theme
        style = ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
            
        # Main layout wrapper
        self.main_container = tk.Frame(self.root, padx=10, pady=10)
        self.main_container.pack(fill="both", expand=True)

        # ---------------- SIDEBAR (Left Column) ---------------- #
        self.sidebar_frame = tk.Frame(self.main_container, width=350)
        self.sidebar_frame.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar_frame.pack_propagate(False) # lock width
        
        # 1. Videos
        frame_videos = tk.LabelFrame(self.sidebar_frame, text="1. Select Videos", padx=10, pady=10)
        frame_videos.pack(fill="x", pady=(0, 10))
        
        list_frame = tk.Frame(frame_videos)
        list_frame.pack(fill="x", expand=True)
        self.listbox_videos = tk.Listbox(list_frame, selectmode=tk.BROWSE, height=6, exportselection=False)
        self.listbox_videos.pack(side="left", fill="x", expand=True)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox_videos.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox_videos.config(yscrollcommand=scrollbar.set)
        self.listbox_videos.bind('<<ListboxSelect>>', self.show_preview)
        
        btn_frame = tk.Frame(frame_videos)
        btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_frame, text="Add Videos", command=self.add_videos).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame, text="Remove", command=self.remove_videos).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # 2. Watermark
        frame_watermark = tk.LabelFrame(self.sidebar_frame, text="2. Select Watermark", padx=5, pady=5)
        frame_watermark.pack(fill="x", pady=(0, 10))
        
        wm_top = tk.Frame(frame_watermark)
        wm_top.pack(fill="x", pady=(0, 5))
        self.lbl_wm_preview = tk.Label(wm_top, text="None", bg="lightgray", width=6, height=3)
        self.lbl_wm_preview.pack(side="left", padx=(5, 10))
        
        self.lbl_watermark = tk.Label(wm_top, text="No image", fg="gray", anchor="w", justify="left", wraplength=130)
        self.lbl_watermark.pack(side="left", fill="x", expand=True)
        
        self.wm_notebook = ttk.Notebook(frame_watermark)
        self.wm_notebook.pack(fill="x", expand=True)
        self.wm_notebook.bind("<<NotebookTabChanged>>", self.on_wm_tab_changed)
        
        # Tab 1: Image
        self.tab_image = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_image, text="Image")
        ttk.Button(self.tab_image, text="Browse Image", command=self.select_watermark).pack(fill="x", padx=5, pady=(5, 5))
        
        # Tab 2: Text
        self.tab_text = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_text, text="Text")
        
        text_frame = tk.Frame(self.tab_text, pady=5)
        text_frame.pack(fill="x")
        
        ttk.Label(text_frame, text="Text:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.text_var = tk.StringVar(value="Sample Text")
        ttk.Entry(text_frame, textvariable=self.text_var).grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        
        ttk.Label(text_frame, text="Font:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.font_var = tk.StringVar(value="arial.ttf")
        fonts = ["arial.ttf", "times.ttf", "calibri.ttf", "montserrat.ttf", "roboto.ttf", "preuksa.ttf", "comic.ttf", "impact.ttf", "tahoma.ttf", "verdana.ttf", "georgia.ttf"]
        ttk.Combobox(text_frame, textvariable=self.font_var, values=fonts, state="readonly").grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        
        ttk.Label(text_frame, text="Color:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.text_color_var = tk.StringVar(value="white")
        
        color_frame = tk.Frame(text_frame)
        color_frame.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        self.btn_color = tk.Button(color_frame, text="Pick Color", bg="white", command=self.pick_color, relief="groove")
        self.btn_color.pack(fill="x", expand=True)
        
        text_frame.columnconfigure(1, weight=1)
        ttk.Button(self.tab_text, text="Apply Text Watermark", command=self.generate_text_watermark).pack(fill="x", padx=5, pady=(5, 5))
        
        # Clear Watermark Button
        ttk.Button(frame_watermark, text="X Clear Watermark", command=self.clear_watermark_selection).pack(fill="x", padx=5, pady=(5, 0))

        # 3. Audio Settings
        frame_audio = tk.LabelFrame(self.sidebar_frame, text="3. Audio (Optional)", padx=10, pady=10)
        frame_audio.pack(fill="x", pady=(0, 10))
        
        self.lbl_bgm = tk.Label(frame_audio, text="Original audio will be kept", fg="gray", anchor="w", wraplength=300, justify="left")
        self.lbl_bgm.pack(fill="x", pady=(0, 5))
        
        btn_frame_bgm = tk.Frame(frame_audio)
        btn_frame_bgm.pack(fill="x")
        ttk.Button(btn_frame_bgm, text="Browse Music", command=self.select_bgm).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame_bgm, text="X Clear", command=self.clear_bgm, width=8).pack(side="left", padx=(2, 0))

        tk.Checkbutton(frame_audio, text="Mute Original Audio", variable=self.mute_var).pack(anchor="w", pady=(5, 0))

        # 4. Processing Settings
        frame_settings = tk.LabelFrame(self.sidebar_frame, text="4. Processing Settings", padx=10, pady=10)
        frame_settings.pack(fill="x", pady=(0, 10))
        
        # Grid layout for settings
        ttk.Label(frame_settings, text="Position:").grid(row=0, column=0, sticky="w", pady=2)
        self.position_var = tk.StringVar(value="Bottom Right")
        positions = ["Top Left", "Top Right", "Bottom Left", "Bottom Right", "Center", "Custom (Drag)"]
        dropdown = ttk.Combobox(frame_settings, textvariable=self.position_var, values=positions, state="readonly", width=14)
        dropdown.grid(row=0, column=1, sticky="ew", padx=(5,0), pady=2)
        dropdown.bind("<<ComboboxSelected>>", self.on_position_changed)
        
        row_idx = 1
        
        ttk.Label(frame_settings, text="Scale (%):").grid(row=row_idx, column=0, sticky="w", pady=2)
        self.scale_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_settings, from_=10, to=300, orient="horizontal", variable=self.scale_var, command=self.on_transform_changed).grid(row=row_idx, column=1, sticky="ew", padx=(5,0), pady=2)
        row_idx += 1

        ttk.Label(frame_settings, text="Opacity (%):").grid(row=row_idx, column=0, sticky="w", pady=2)
        self.opacity_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_settings, from_=0, to=100, orient="horizontal", variable=self.opacity_var, command=self.on_transform_changed).grid(row=row_idx, column=1, sticky="ew", padx=(5,0), pady=2)
        row_idx += 1
        
        ttk.Label(frame_settings, text="Format:").grid(row=row_idx, column=0, sticky="w", pady=2)
        self.format_var = tk.StringVar(value="Original")
        formats = ["Original", "MP4", "MKV", "AVI", "MOV"]
        ttk.Combobox(frame_settings, textvariable=self.format_var, values=formats, state="readonly", width=14).grid(row=row_idx, column=1, sticky="ew", padx=(5,0), pady=2)
        row_idx += 1
        
        ttk.Label(frame_settings, text="Quality:").grid(row=row_idx, column=0, sticky="w", pady=2)
        self.quality_var = tk.StringVar(value="High (Lossless)")
        qualities = ["High (Lossless)", "Medium (Balanced)", "Low (Smaller File)"]
        ttk.Combobox(frame_settings, textvariable=self.quality_var, values=qualities, state="readonly", width=14).grid(row=row_idx, column=1, sticky="ew", padx=(5,0), pady=2)
        row_idx += 1

        ttk.Label(frame_settings, text="Timelapse:").grid(row=row_idx, column=0, sticky="w", pady=2)
        self.speed_var = tk.StringVar(value="1x (Normal)")
        speeds = ["1x (Normal)", "2x", "4x", "8x", "16x", "0.5x (Slow)"]
        ttk.Combobox(frame_settings, textvariable=self.speed_var, values=speeds, state="readonly", width=14).grid(row=row_idx, column=1, sticky="ew", padx=(5,0), pady=2)

        # 5. Output
        frame_output = tk.LabelFrame(self.sidebar_frame, text="5. Output Directory", padx=10, pady=10)

        frame_output.pack(fill="x", pady=(0, 10))
        self.lbl_output = tk.Label(frame_output, text="No directory selected", fg="gray", anchor="w")
        self.lbl_output.pack(fill="x", pady=(0, 5))
        
        btn_frame_out = tk.Frame(frame_output)
        btn_frame_out.pack(fill="x")
        ttk.Button(btn_frame_out, text="Browse Folder", command=self.select_output_dir).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame_out, text="Open Folder", command=self.open_output_dir).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # Start block
        frame_action = tk.Frame(self.sidebar_frame, pady=5)
        frame_action.pack(side="bottom", fill="x")
        self.lbl_status = tk.Label(frame_action, text="Ready", fg="blue", anchor="w")
        self.lbl_status.pack(fill="x", pady=(0, 5))
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_action, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.btn_start = ttk.Button(frame_action, text="Start Batch Watermarking", command=self.start_processing)
        self.btn_start.pack(fill="x", ipady=5)

        # ---------------- PREVIEW AREA (Right Column) ---------------- #
        frame_preview = tk.LabelFrame(self.main_container, text="Video Player Preview (Drag logo to adjust position)", padx=5, pady=5)
        frame_preview.pack(side="right", fill="both", expand=True)
        
        self.canvas_preview = tk.Canvas(frame_preview, bg="black")
        self.canvas_preview.pack(fill="both", expand=True, pady=(0, 5))
        self.canvas_preview.tag_bind("watermark", "<ButtonPress-1>", self.on_drag_start)
        self.canvas_preview.tag_bind("watermark", "<B1-Motion>", self.on_drag_motion)
        
        self.controls_frame = tk.Frame(frame_preview)
        self.controls_frame.pack(side="bottom", fill="x", pady=5)
        
        self.btn_play_pause = ttk.Button(self.controls_frame, text="▶ Play", command=self.toggle_play, width=10)
        self.btn_play_pause.pack(side="left")
        
        self.btn_stop = ttk.Button(self.controls_frame, text="⏹ Stop", command=self.stop_playback, width=8)
        self.btn_stop.pack(side="left", padx=5)
        
        self.btn_audio_preview = ttk.Button(self.controls_frame, text="🔊 Play with Audio", command=self.preview_with_audio, width=18)
        self.btn_audio_preview.pack(side="left", padx=5)
        
        self.seek_var = tk.DoubleVar()
        self.seek_slider = ttk.Scale(self.controls_frame, from_=0, to=100, orient="horizontal", variable=self.seek_var, command=self.seek_video)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=(5,5))
        
        self.lbl_time = ttk.Label(self.controls_frame, text="00:00 / 00:00")
        self.lbl_time.pack(side="left", padx=(0, 5))

    def add_videos(self):
        files = filedialog.askopenfilenames(
            title="Select Videos",
            filetypes=(("Video files", "*.mp4 *.avi *.mov *.mkv"), ("All files", "*.*"))
        )
        for f in files:
            if f not in self.video_files:
                self.video_files.append(f)
                self.listbox_videos.insert(tk.END, os.path.basename(f))

    def remove_videos(self):
        selected = self.listbox_videos.curselection()
        for index in reversed(selected):
            self.listbox_videos.delete(index)
            del self.video_files[index]
            
        if not self.listbox_videos.curselection():
            self.clear_preview("Select a video\nto preview")

    def show_preview(self, event):
        selected = self.listbox_videos.curselection()
        if not selected:
            return
        index = selected[-1]
        video_path = self.video_files[index]
        
        if self.video_cap:
            self.video_cap.release()
            
        self.video_cap = cv2.VideoCapture(video_path)
        self.is_playing = False
        self.btn_play_pause.config(text="▶ Play")
        if self.play_job:
            self.root.after_cancel(self.play_job)
            self.play_job = None
            
        self.update_video_frame(initial_load=True)

    def on_position_changed(self, event=None):
        if self.orig_v_width > 0:
            self.draw_preview_canvas(self.watermark_file, self.position_var.get(), self.orig_v_width)

    def on_transform_changed(self, event=None):
        if self.orig_v_width > 0:
            self.draw_preview_canvas(self.watermark_file, self.position_var.get(), self.orig_v_width)

    def toggle_play(self):
        if not self.video_cap or not self.video_cap.isOpened():
            return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.btn_play_pause.config(text="⏸ Pause")
            self.update_video_frame()
        else:
            self.btn_play_pause.config(text="▶ Play")
            if self.play_job:
                self.root.after_cancel(self.play_job)

    def stop_playback(self):
        self.is_playing = False
        self.btn_play_pause.config(text="▶ Play")
        if self.play_job:
            self.root.after_cancel(self.play_job)
            self.play_job = None
        if self.video_cap and self.video_cap.isOpened():
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.seek_var.set(0)
            self.lbl_time.config(text="00:00 / 00:00")
            self.update_video_frame(initial_load=True)

    def fmt_time(self, seconds):
        if seconds < 0: seconds = 0
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def seek_video(self, val):
        if not self.video_cap or not self.video_cap.isOpened():
            return
        total_frames = max(1, self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target = int((float(val) / 100.0) * total_frames)
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        if not self.is_playing:
            self.update_video_frame(initial_load=True)

    def update_video_frame(self, initial_load=False):
        if not self.video_cap or not self.video_cap.isOpened():
            return
            
        if not self.is_playing and not initial_load:
            return
            
        t_start = time.time()
        ret, frame = self.video_cap.read()
        if ret:
            c_w = max(10, self.canvas_preview.winfo_width())
            c_h = max(10, self.canvas_preview.winfo_height())
            
            v_width = self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            self.orig_v_width = v_width
            
            # Fast cv2 resize
            h, w = frame.shape[:2]
            scale = min(c_w/w, c_h/h)
            new_w, new_h = int(w * scale), int(h * scale)
            if new_w > 0 and new_h > 0:
                # INTER_AREA is better for shrinking, INTER_LINEAR/CUBIC for upscaling.
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                
            cv2_im = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2_im)
            self.bg_width, self.bg_height = img.size
            self.preview_bg_img = ImageTk.PhotoImage(img) # persist reference
            
            self.draw_preview_canvas(self.watermark_file, self.position_var.get(), v_width, fast_mode=self.is_playing)
            
            total_frames = max(1, self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            current = self.video_cap.get(cv2.CAP_PROP_POS_FRAMES)
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30
            if fps <= 0: fps = 30
            
            cur_time_str = self.fmt_time(current / fps)
            tot_time_str = self.fmt_time(total_frames / fps)
            self.lbl_time.config(text=f"{cur_time_str} / {tot_time_str}")
            
            if total_frames > 0:
                self.seek_var.set((current / total_frames) * 100)
            
            if self.is_playing:
                t_elapsed = (time.time() - t_start) * 1000
                delay = int(max(1, (1000 / fps) - t_elapsed))
                self.play_job = self.root.after(delay, self.update_video_frame)
        else:
            self.stop_playback()

    def draw_preview_canvas(self, watermark_path, position, orig_v_width, fast_mode=False):
        self.canvas_preview.delete("all")
        
        c_w = self.canvas_preview.winfo_width()
        c_h = self.canvas_preview.winfo_height()
        offset_x = (c_w - self.bg_width) // 2
        offset_y = (c_h - self.bg_height) // 2
        
        self.canvas_preview.create_image(offset_x, offset_y, image=self.preview_bg_img, anchor="nw", tags="bg")
        
        if watermark_path and os.path.exists(watermark_path):
            try:
                with Image.open(watermark_path) as orig_wm:
                    wm = orig_wm.convert("RGBA")
                
                user_scale = self.scale_var.get() / 100.0
                
                # Apply user transforms
                resample_method = Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS
                if user_scale != 1.0:
                    new_w = max(1, int(wm.size[0] * user_scale))
                    new_h = max(1, int(wm.size[1] * user_scale))
                    wm = wm.resize((new_w, new_h), resample_method)

                # Apply opacity
                opacity = self.opacity_var.get() / 100.0
                if opacity < 1.0:
                    r, g, b, a = wm.split()
                    a = a.point(lambda p: int(p * opacity))
                    wm = Image.merge("RGBA", (r, g, b, a))

                scale_view = self.bg_width / orig_v_width if orig_v_width > 0 else 1.0
                wm_w, wm_h = int(wm.size[0] * scale_view), int(wm.size[1] * scale_view)
                
                if wm_w > 0 and wm_h > 0:
                    wm = wm.resize((wm_w, wm_h), resample_method)
                    self.preview_wm_img = ImageTk.PhotoImage(wm)
                    
                    padding = 10 * scale_view
                    x, y = 10 * scale_view, 10 * scale_view
                    
                    if position == "Top Right":
                        x = self.bg_width - wm_w - padding
                    elif position == "Bottom Left":
                        y = self.bg_height - wm_h - padding
                    elif position == "Bottom Right":
                        x = self.bg_width - wm_w - padding
                        y = self.bg_height - wm_h - padding
                    elif position == "Center":
                        x = (self.bg_width - wm_w) / 2
                        y = (self.bg_height - wm_h) / 2
                    elif position == "Custom (Drag)":
                        x = self.custom_x_ratio * self.bg_width
                        y = self.custom_y_ratio * self.bg_height
                        
                    self.canvas_preview.create_image(offset_x + x, offset_y + y, image=self.preview_wm_img, anchor="nw", tags="watermark")
            except Exception as e:
                print("Watermark preview error:", e)

    def clear_preview(self, text):
        self.canvas_preview.delete("all")
        c_w = self.canvas_preview.winfo_width()
        c_h = self.canvas_preview.winfo_height()
        if c_w < 10: c_w = 400
        if c_h < 10: c_h = 400
        self.canvas_preview.create_text(c_w//2, c_h//2, text=text, fill="white")

    def on_drag_start(self, event):
        self._drag_data = {'x': event.x, 'y': event.y}
        
    def on_drag_motion(self, event):
        dx = event.x - self._drag_data['x']
        dy = event.y - self._drag_data['y']
        
        self.canvas_preview.move("watermark", dx, dy)
        self._drag_data['x'] = event.x
        self._drag_data['y'] = event.y
        
        coords = self.canvas_preview.coords("watermark")
        if coords:
            c_w = self.canvas_preview.winfo_width()
            c_h = self.canvas_preview.winfo_height()
            offset_x = (c_w - self.bg_width) // 2
            offset_y = (c_h - self.bg_height) // 2
            
            x = coords[0] - offset_x
            y = coords[1] - offset_y
            
            self.custom_x_ratio = max(0.0, min(1.0, x / self.bg_width))
            self.custom_y_ratio = max(0.0, min(1.0, y / self.bg_height))
            
            if self.position_var.get() != "Custom (Drag)":
                self.position_var.set("Custom (Drag)")

    def update_wm_preview(self):
        if self.watermark_file:
            try:
                with Image.open(self.watermark_file) as orig_img:
                    img = orig_img.copy()
                img.thumbnail((80, 80), Image.Resampling.LANCZOS)
                self.wm_preview_img = ImageTk.PhotoImage(img)
                self.lbl_wm_preview.config(image=self.wm_preview_img, text="", width=0, height=0)
            except Exception:
                self.lbl_wm_preview.config(image='', text="Error", width=6, height=3)

    def select_watermark(self):
        file = filedialog.askopenfilename(
            title="Select Watermark Image",
            filetypes=(("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*"))
        )
        if file:
            self.watermark_file = file
            self.lbl_watermark.config(text=os.path.basename(file), fg="black")
            self.update_wm_preview()
            self.refresh_preview()

    def on_wm_tab_changed(self, event):
        self.clear_watermark_selection()
        
    def clear_watermark_selection(self):
        if hasattr(self, 'watermark_file') and self.watermark_file:
            self.watermark_file = ""
            self.lbl_watermark.config(text="No image", fg="gray")
            self.wm_preview_img = None
            self.lbl_wm_preview.config(image='', text="None", width=6, height=3)
            self.refresh_preview()

    def select_bgm(self):
        file = filedialog.askopenfilename(
            title="Select Background Music",
            filetypes=(("Audio files", "*.mp3 *.wav *.m4a *.aac"), ("All files", "*.*"))
        )
        if file:
            self.bgm_file = file
            self.lbl_bgm.config(text=f"Replace with: {os.path.basename(file)}", fg="blue")

    def clear_bgm(self):
        self.bgm_file = ""
        self.lbl_bgm.config(text="Original audio will be kept", fg="gray")

    def preview_with_audio(self):
        selected = self.listbox_videos.curselection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a video from the list first.")
            return
        
        index = selected[-1]
        video_path = self.video_files[index]

        # Disable button during small render
        self.btn_audio_preview.config(state="disabled")
        self.lbl_status.config(text="Generating audio preview (10s)...", fg="orange")
        
        threading.Thread(target=self._run_audio_preview_render, args=(video_path,), daemon=True).start()

    def _run_audio_preview_render(self, video_path):
        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path: return
        
        temp_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "temp_previews")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        out_path = os.path.join(temp_dir, "preview_sample.mp4")
        filter_complex_str = self.get_ffmpeg_complex_filter_str()
        v_filter, a_full_filter = filter_complex_str
        
        cmd = [
            ffmpeg_path, "-y",
            "-i", video_path,
        ]
        if self.watermark_file:
            cmd.extend(["-i", self.watermark_file])
            
        if self.bgm_file:
            cmd.extend(["-stream_loop", "-1", "-i", self.bgm_file])
            
        cmd.extend([
            "-filter_complex", f"{v_filter};{a_full_filter}",
            "-map", "[v]", "-map", "[a]",
            "-t", "10",        # Only 10 seconds for speed
            "-preset", "ultrafast", # Fastest encoding for preview
            "-crf", "28",      # Lower quality for speed
            out_path
        ])
        
        # Hide console
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            subprocess.run(cmd, startupinfo=startupinfo, check=True)
            # Open with default player
            if os.name == 'nt':
                os.startfile(out_path)
            elif os.name == 'posix':
                subprocess.run(["open", out_path] if sys.platform == "darwin" else ["xdg-open", out_path])
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Preview Error", f"Failed to generate preview: {e}"))
        finally:
            self.root.after(0, lambda: self.btn_audio_preview.config(state="normal"))
            self.root.after(0, lambda: self.lbl_status.config(text="Ready", fg="blue"))

    def refresh_preview(self):
        if hasattr(self, 'orig_v_width') and self.orig_v_width > 0:
            self.draw_preview_canvas(self.watermark_file, self.position_var.get(), self.orig_v_width)
        else:
            self.show_preview(None)

    def pick_color(self):
        color_code = colorchooser.askcolor(title="Choose color", initialcolor=self.text_color_var.get())
        if color_code and color_code[1]:
            self.text_color_var.set(color_code[1])
            self.btn_color.config(bg=color_code[1])

    def generate_text_watermark(self):
        text = self.text_var.get()
        if not text:
            return
            
        color = self.text_color_var.get()
        font_name = self.font_var.get()
        try:
            # Using basic default size mapping (size 80 standardizing to Windows view height)
            font = ImageFont.truetype(font_name, 80)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 80)
            except Exception:
                font = ImageFont.load_default()
            
        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except AttributeError:
            w, h = draw.textsize(text, font=font)
            
        img = Image.new("RGBA", (w + 20, h + 20), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), text, fill=color, font=font)
        
        temp_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "watermark_app_temp_text.png")
        img.save(temp_path)
        
        self.watermark_file = temp_path
        self.lbl_watermark.config(text=f"Text: {text[:15]}...", fg="black")
        self.update_wm_preview()
        self.refresh_preview()

    def select_output_dir(self):
        dir_name = filedialog.askdirectory(title="Select Output Directory")
        if dir_name:
            self.output_dir = dir_name
            self.lbl_output.config(text=dir_name, fg="black")

    def open_output_dir(self):
        if self.output_dir and os.path.exists(self.output_dir):
            if os.name == 'nt':
                os.startfile(self.output_dir)
            else:
                subprocess.call(['xdg-open', self.output_dir])
        else:
            messagebox.showinfo("Info", "Output directory has not been selected yet or does not exist.")

    def get_ffmpeg_path(self):
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def get_ffmpeg_complex_filter_str(self):
        pos = self.position_var.get()
        padding = 10
        if pos == "Top Left":
            over_pos = f"{padding}:{padding}"
        elif pos == "Top Right":
            over_pos = f"W-w-{padding}:{padding}"
        elif pos == "Bottom Left":
            over_pos = f"{padding}:H-h-{padding}"
        elif pos == "Bottom Right":
            over_pos = f"W-w-{padding}:H-h-{padding}"
        elif pos == "Center":
            over_pos = "(W-w)/2:(H-h)/2"
        elif pos == "Custom (Drag)":
            over_pos = f"W*{self.custom_x_ratio}:H*{self.custom_y_ratio}"
        else:
            over_pos = "10:10"
            
        user_scale = self.scale_var.get() / 100.0
        
        filters = []
        if user_scale != 1.0:
            filters.append("format=rgba")
            filters.append(f"scale=iw*{user_scale}:ih*{user_scale}")
            
        opacity_val = self.opacity_var.get() / 100.0
        if opacity_val < 1.0:
            if "format=rgba" not in filters:
                filters.append("format=rgba")
            filters.append(f"colorchannelmixer=aa={opacity_val}")

        # 1. Video Speed (Timelapse)
        speed_val = self.speed_var.get().split('x')[0]
        try:
            speed_factor = float(speed_val)
        except:
            speed_factor = 1.0
        v_speed_filter = f"setpts={1/speed_factor}*PTS"
        
        # 2. Audio Speed (needs multiple atempo filters for > 2x)
        a_speed_filters = []
        temp_speed = speed_factor
        while temp_speed > 2.0:
            a_speed_filters.append("atempo=2.0")
            temp_speed /= 2.0
        while temp_speed < 0.5:
            a_speed_filters.append("atempo=0.5")
            temp_speed *= 2.0
        if temp_speed != 1.0:
            a_speed_filters.append(f"atempo={temp_speed}")
        
        a_filter_str = ",".join(a_speed_filters) if a_speed_filters else "anull"

        # Determine indices
        wm_idx = 1 if self.watermark_file else -1
        bgm_idx = (wm_idx + 1) if self.bgm_file and wm_idx != -1 else (1 if self.bgm_file else -1)
                
        if wm_idx != -1 and filters:
            wm_filter = ",".join(filters)
            v_filter = f"[{wm_idx}:v]{wm_filter}[wm];[0:v]{v_speed_filter}[vspeed];[vspeed][wm]overlay={over_pos}[v]"
        elif wm_idx != -1:
            v_filter = f"[0:v]{v_speed_filter}[vspeed];[vspeed][{wm_idx}:v]overlay={over_pos}[v]"
        else:
            # No watermark
            v_filter = f"[0:v]{v_speed_filter}[v]"
            
        # Audio selection logic for complex filter
        if bgm_idx != -1:
            # For BGM
            full_a_filter = f"[{bgm_idx}:a]anull[a]"
        elif self.mute_var.get():
            # For Mute (generate silence)
            full_a_filter = "anullsrc=r=44100:cl=stereo[a]"
        else:
            # For original audio
            full_a_filter = f"[0:a]{a_filter_str}[a]"
            
        return v_filter, full_a_filter

    def start_processing(self):
        if not self.video_files:
            messagebox.showerror("Error", "Please select at least one video.")
            return
        if not self.watermark_file:
            messagebox.showerror("Error", "Please select a watermark image.")
            return
        if not self.output_dir:
            messagebox.showerror("Error", "Please select an output directory.")
            return

        self.btn_start.config(state="disabled")
        self.progress_var.set(0)
        
        # Start processing in a separate thread so GUI doesn't freeze
        threading.Thread(target=self.process_videos, daemon=True).start()

    def process_videos(self):
        total = len(self.video_files)
        filter_complex_str = self.get_ffmpeg_complex_filter_str()

        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path:
            self.root.after(0, lambda: messagebox.showerror("FFmpeg Not Found", "Failed to find any FFmpeg binary (local or integrated)."))
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            self.root.after(0, lambda: self.lbl_status.config(text="FFmpeg not found."))
            return

        for i, video_path in enumerate(self.video_files):
            filename = os.path.basename(video_path)
            self.root.after(0, lambda f=filename, idx=i+1, t=total: self.lbl_status.config(text=f"Processing {idx}/{t}: {f}..."))
            
            sel_format = self.format_var.get()
            name, ext = os.path.splitext(filename)
            out_ext = ext if sel_format == "Original" else f".{sel_format.lower()}"
            out_path = os.path.join(self.output_dir, f"watermarked_{name}{out_ext}")
            
            sel_quality = self.quality_var.get()
            crf_val = "18"
            if sel_quality == "Low (Smaller File)":
                crf_val = "28"
            elif sel_quality == "Medium (Balanced)":
                crf_val = "23"
            
            # Use strict subprocess creation flags to hide console window on windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            v_filter, a_full_filter = filter_complex_str

            cmd = [
                ffmpeg_path, 
                "-y",                    # overwrite output
                "-i", video_path,        # input 0: video
            ]
            
            if self.watermark_file:
                cmd.extend(["-i", self.watermark_file]) # input 1: watermark
            
            if self.bgm_file:
                # input 2: BGM (looped)
                cmd.extend(["-stream_loop", "-1", "-i", self.bgm_file])
                
            # Add filter_complex
            if self.mute_var.get() and not self.bgm_file:
                # If mute is requested and no BGM, we can either use anullsrc or just skip mapping audio.
                # Using anullsrc in filter_complex is safer for format consistency.
                cmd.extend(["-filter_complex", f"{v_filter};{a_full_filter}"])
            else:
                cmd.extend(["-filter_complex", f"{v_filter};{a_full_filter}"])

            cmd.extend([
                "-map", "[v]",           # Map final video
                "-map", "[a]",           # Map final audio
                "-shortest",             # Ensure output duration matches video
                "-c:v", "libx264",       
                "-crf", crf_val,         
                "-preset", "fast",       
                "-c:a", "aac",           # Re-encode audio to support atempo/silence
                out_path
            ])
            
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, check=True)
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode("utf-8", errors="ignore").strip()
                lines = [line for line in err_msg.split('\n') if line.strip()]
                compact_err = "\n".join(lines[-3:]) if lines else "Unknown error"
                self.root.after(0, lambda f=filename, err=compact_err: messagebox.showerror("Error", f"Failed to process {f}.\n\nError details:\n{err}"))
                continue
            
            progress = ((i + 1) / total) * 100
            self.root.after(0, lambda p=progress: self.progress_var.set(p))

        self.root.after(0, lambda: self.lbl_status.config(text="Batch processing completed!", fg="green"))
        self.root.after(0, lambda: self.btn_start.config(state="normal"))
        self.root.after(0, lambda: messagebox.showinfo("Success", "All videos processed successfully."))

if __name__ == "__main__":
    root = tk.Tk()
    app = WatermarkApp(root)
    root.mainloop()
