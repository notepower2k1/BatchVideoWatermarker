import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import threading
import subprocess
import os
import time
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import imageio_ffmpeg
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import tempfile
import fractions

class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Batch Video Watermarker")
        if os.name == 'nt':
            self.root.state('zoomed')
        else:
            self.root.attributes('-zoomed', True)
        
        self.root.resizable(False, False) # Disable resizing

        # Set window icon
        if os.path.exists("logo.png"):
            try:
                self.icon_img = ImageTk.PhotoImage(file="logo.png")
                self.root.iconphoto(False, self.icon_img)
            except:
                pass
        
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
        self.orig_vol_var = tk.DoubleVar(value=100)
        self.bgm_vol_var = tk.DoubleVar(value=100)
        self.v_fade_var = tk.StringVar(value="None")
        self.wm_effect_var = tk.StringVar(value="None")
        self.wm_start_time_var = tk.StringVar(value="0")
        self.wm_end_time_var = tk.StringVar(value="")
        self.text_color_var = tk.StringVar(value="#FFFFFF")
        self.text_size_var = tk.IntVar(value=80)
        self.font_var = tk.StringVar(value="Arial")
        self.rotate_var = tk.DoubleVar(value=0)
        self.preview_bg_img = None
        self.process_selected_var = tk.BooleanVar(value=False)
        self.parallel_videos_var = tk.StringVar()
        self.encoder_var = tk.StringVar(value="Auto (Recommended)")
        self.encode_speed_var = tk.StringVar(value="Very Fast (Recommended)")
        self._ffmpeg_encoder_cache = {}
        self._video_metadata_cache = {}
        
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        self.history_wm = []
        
        # Registration for numeric validation
        self._vcmd = (self.root.register(self.validate_numeric), '%P')

        # UI Elements
        self.setup_ui()
        self.update_wm_ui_state()
        self.load_config()
        
    def validate_numeric(self, P):
        if P == "" or P == ".":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    def get_auto_parallel_count(self):
        cpu_count = os.cpu_count() or 2
        return max(1, min(4, cpu_count // 2))

    def get_auto_parallel_label(self):
        count = self.get_auto_parallel_count()
        suffix = "video" if count == 1 else "videos"
        return f"Auto ({count} {suffix})"

    def get_auto_parallel_label_for_cfg(self, cfg):
        count = self.get_auto_parallel_count_for_cfg(cfg)
        suffix = "video" if count == 1 else "videos"
        return f"Auto ({count} {suffix})"

    def refresh_parallel_videos_ui(self, *_):
        if not hasattr(self, "parallel_videos_cb"):
            return
        auto_label = self.get_auto_parallel_label_for_cfg({
            "exe": imageio_ffmpeg.get_ffmpeg_exe(),
            "encoder": self.encoder_var.get()
        })
        self.parallel_videos_cb.configure(values=[auto_label, "1", "2", "3", "4"])
        if str(self.parallel_videos_var.get()).startswith("Auto"):
            self.parallel_videos_var.set(auto_label)

    def should_use_nvenc(self, exe, encoder_pref):
        nvenc_supported = self.has_ffmpeg_encoder(exe, "h264_nvenc")
        return nvenc_supported and encoder_pref in [
            "Auto (Recommended)",
            "Auto",
            "NVIDIA GPU (Fastest, if supported)",
            "NVIDIA NVENC"
        ]

    def get_auto_parallel_count_for_cfg(self, cfg):
        cpu_count = os.cpu_count() or 2
        exe = cfg.get("exe", imageio_ffmpeg.get_ffmpeg_exe())
        encoder_pref = cfg.get("encoder", "Auto (Recommended)")
        if self.should_use_nvenc(exe, encoder_pref):
            return max(1, min(4, cpu_count))
        return max(1, min(4, cpu_count // 2))

    def get_ffmpeg_thread_count(self, cfg, max_parallel):
        cpu_count = os.cpu_count() or 2
        exe = cfg.get("exe", imageio_ffmpeg.get_ffmpeg_exe())
        encoder_pref = cfg.get("encoder", "Auto (Recommended)")
        if self.should_use_nvenc(exe, encoder_pref):
            return max(1, min(4, cpu_count // max(1, max_parallel)))
        return max(1, cpu_count // max(1, max_parallel))

    def has_ffmpeg_encoder(self, exe, encoder_name):
        cache_key = (exe, encoder_name)
        if cache_key in self._ffmpeg_encoder_cache:
            return self._ffmpeg_encoder_cache[cache_key]

        try:
            res = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding='utf-8', errors='replace')
            text = f"{res.stdout}\n{res.stderr}"
            supported = encoder_name in text
        except Exception:
            supported = False

        self._ffmpeg_encoder_cache[cache_key] = supported
        return supported

    def get_ffprobe_exe(self, ffmpeg_exe):
        ffprobe_exe = ffmpeg_exe.replace("ffmpeg", "ffprobe")
        return ffprobe_exe if os.path.exists(ffprobe_exe) else ""

    def probe_video_metadata(self, path, ffmpeg_exe=None):
        cache_key = (path, ffmpeg_exe or "")
        if cache_key in self._video_metadata_cache:
            return dict(self._video_metadata_cache[cache_key])

        meta = {"fps": 30.0, "duration": 1.0, "has_audio": False}
        ffprobe_exe = self.get_ffprobe_exe(ffmpeg_exe) if ffmpeg_exe else ""

        if ffprobe_exe:
            try:
                cmd = [
                    ffprobe_exe,
                    "-v", "error",
                    "-print_format", "json",
                    "-show_streams",
                    "-show_format",
                    path
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    streams = data.get("streams", [])
                    format_info = data.get("format", {})
                    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
                    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

                    if video_stream:
                        fps_raw = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
                        try:
                            fps_val = float(fractions.Fraction(fps_raw))
                            if fps_val > 0:
                                meta["fps"] = fps_val
                        except Exception:
                            pass

                        dur_candidates = [
                            video_stream.get("duration"),
                            format_info.get("duration")
                        ]
                        for dur in dur_candidates:
                            try:
                                dur_val = float(dur)
                                if dur_val > 0:
                                    meta["duration"] = dur_val
                                    break
                            except Exception:
                                pass

                    meta["has_audio"] = audio_stream is not None
                    self._video_metadata_cache[cache_key] = dict(meta)
                    return dict(meta)
            except Exception:
                pass

        cap = cv2.VideoCapture(path)
        fps_v = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps_v > 0:
            meta["fps"] = fps_v
        if fps_v > 0 and frame_count > 0:
            meta["duration"] = frame_count / fps_v

        if ffmpeg_exe:
            meta["has_audio"] = self.check_has_audio(path, ffmpeg_exe)
        else:
            meta["has_audio"] = self.check_has_audio(path)

        self._video_metadata_cache[cache_key] = dict(meta)
        return dict(meta)

    def build_video_codec_args(self, exe, cfg, crf, preview_mode=False):
        encoder_pref = cfg.get("encoder", "Auto (Recommended)")
        speed_pref = cfg.get("encode_speed", "Very Fast (Recommended)")

        cpu_preset_map = {
            "Fast (better quality)": "fast",
            "Very Fast (Recommended)": "veryfast",
            "Super Fast (faster, larger file)": "superfast",
            "Ultra Fast (fastest, lower quality)": "ultrafast",
            "Fast": "fast",
            "Very Fast": "veryfast",
            "Super Fast": "superfast",
            "Ultra Fast": "ultrafast",
        }
        nvenc_preset_map = {
            "Fast (better quality)": "p4",
            "Very Fast (Recommended)": "p3",
            "Super Fast (faster, larger file)": "p2",
            "Ultra Fast (fastest, lower quality)": "p1",
            "Fast": "p4",
            "Very Fast": "p3",
            "Super Fast": "p2",
            "Ultra Fast": "p1",
        }

        use_nvenc = self.should_use_nvenc(exe, encoder_pref)
        if use_nvenc:
            nvenc_preset = nvenc_preset_map.get(speed_pref, "p3")
            return ["-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-cq", crf, "-preset", nvenc_preset]

        cpu_preset = "ultrafast" if preview_mode else cpu_preset_map.get(speed_pref, "veryfast")
        return ["-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", crf, "-preset", cpu_preset]

    def can_copy_audio(self, cfg, has_audio):
        if not has_audio:
            return False
        if cfg.get("bgm_file"):
            return False
        if cfg.get("mute"):
            return False
        if abs(float(cfg.get("spd", 1.0)) - 1.0) > 0.0001:
            return False
        if abs(float(cfg.get("orig_vol", 100)) - 100.0) > 0.0001:
            return False
        return True

    def needs_video_filter(self, cfg):
        if cfg.get("watermark_file"):
            return True
        if abs(float(cfg.get("spd", 1.0)) - 1.0) > 0.0001:
            return True
        return cfg.get("v_fade", "None") not in ["None", "", None]

    def setup_ui(self):
        style = ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
            
        self.main_container = tk.Frame(self.root, padx=10, pady=10)
        self.main_container.pack(fill="both", expand=True)

        # ---------------- SIDEBAR (Left Column) with Scrollbar ---------------- #
        self.sidebar_outer = tk.Frame(self.main_container, width=420)
        self.sidebar_outer.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar_outer.pack_propagate(False)

        self.sidebar_canvas = tk.Canvas(self.sidebar_outer, borderwidth=0, highlightthickness=0)
        self.sidebar_scrollbar = ttk.Scrollbar(self.sidebar_outer, orient="vertical", command=self.sidebar_canvas.yview)
        # Increase width slightly to account for scrollbar visibility and padding
        self.sidebar_frame = tk.Frame(self.sidebar_canvas)

        self.sidebar_frame.bind("<Configure>", lambda e: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.create_window((0, 0), window=self.sidebar_frame, anchor="nw", width=390)
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scrollbar.set)

        self.sidebar_canvas.pack(side="left", fill="both", expand=True)
        self.sidebar_scrollbar.pack(side="right", fill="y")
        
        # Mousewheel support for sidebar
        def _on_mousewheel(event): self.sidebar_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.sidebar_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 1. VIDEO SETTINGS BLOCK
        frame_video_group = tk.LabelFrame(self.sidebar_frame, text="VIDEO SETTINGS", padx=10, pady=10, fg="blue", font=("Arial", 10, "bold"))
        frame_video_group.pack(fill="x", pady=(0, 10))

        # List & Add/Remove
        frame_list = tk.Frame(frame_video_group)
        frame_list.pack(fill="x", pady=(0, 5))
        
        l_box_frame = tk.Frame(frame_list)
        l_box_frame.pack(fill="x", expand=True)
        self.listbox_videos = tk.Listbox(l_box_frame, selectmode=tk.EXTENDED, height=4, exportselection=False)
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
        frame_v_cfg.columnconfigure(1, weight=1)
        
        ttk.Label(frame_v_cfg, text="Format:").grid(row=0, column=0, sticky="w", pady=2)
        self.format_var = tk.StringVar(value="Original")
        ttk.Combobox(frame_v_cfg, textvariable=self.format_var, values=["Original", "MP4", "MKV", "AVI", "MOV"], state="readonly").grid(row=0, column=1, sticky="ew", padx=10)
        
        ttk.Label(frame_v_cfg, text="Quality:").grid(row=1, column=0, sticky="w", pady=2)
        self.quality_var = tk.StringVar(value="Medium (Balanced)")
        ttk.Combobox(frame_v_cfg, textvariable=self.quality_var, values=["High (Lossless)", "Medium (Balanced)", "Low (Smaller File)"], state="readonly").grid(row=1, column=1, sticky="ew", padx=10)

        ttk.Label(frame_v_cfg, text="Timelapse:").grid(row=2, column=0, sticky="w", pady=2)
        self.speed_var = tk.StringVar(value="1x (Normal)")
        ttk.Combobox(frame_v_cfg, textvariable=self.speed_var, values=["1x (Normal)", "2x", "4x", "8x", "16x", "0.5x (Slow)"], state="readonly").grid(row=2, column=1, sticky="ew", padx=10)

        ttk.Label(frame_v_cfg, text="Fade:").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Combobox(frame_v_cfg, textvariable=self.v_fade_var, values=["None", "Fade In", "Fade Out", "Both"], state="readonly").grid(row=3, column=1, sticky="ew", padx=10)

        ttk.Label(frame_v_cfg, text="Encoder:").grid(row=4, column=0, sticky="w", pady=2)
        self.encoder_cb = ttk.Combobox(frame_v_cfg, textvariable=self.encoder_var, values=["Auto (Recommended)", "CPU Only (More compatible)", "NVIDIA GPU (Fastest, if supported)"], state="readonly")
        self.encoder_cb.grid(row=4, column=1, sticky="ew", padx=10)
        self.encoder_cb.bind("<<ComboboxSelected>>", self.refresh_parallel_videos_ui)

        ttk.Label(frame_v_cfg, text="Encode Speed:").grid(row=5, column=0, sticky="w", pady=2)
        ttk.Combobox(frame_v_cfg, textvariable=self.encode_speed_var, values=["Fast (better quality)", "Very Fast (Recommended)", "Super Fast (faster, larger file)", "Ultra Fast (fastest, lower quality)"], state="readonly").grid(row=5, column=1, sticky="ew", padx=10)

        frame_out = tk.Frame(frame_video_group, pady=5)
        frame_out.pack(fill="x")
        self.lbl_output = tk.Label(frame_out, text="Output: Not Set", fg="gray", anchor="w", font=("Arial", 8), wraplength=300)
        self.lbl_output.pack(fill="x")
        out_btns = tk.Frame(frame_out)
        out_btns.pack(fill="x")
        ttk.Button(out_btns, text="Set Folder", command=self.select_output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(out_btns, text="Open Folder", command=self.open_output_dir).pack(side="left", padx=2)

        # 2. WATERMARK SETTINGS BLOCK
        frame_wm_group = tk.LabelFrame(self.sidebar_frame, text="WATERMARK SETTINGS", padx=10, pady=10, fg="darkgreen", font=("Arial", 10, "bold"))
        frame_wm_group.pack(fill="x", pady=(0, 10))

        # Preview Logo
        wm_info2 = tk.Frame(frame_wm_group)
        wm_info2.pack(fill="x", pady=(0, 5))
        # Fixed size container to prevent UI layout shifts
        self.wm_preview_container = tk.Frame(wm_info2, width=80, height=80, bg="lightgray")
        self.wm_preview_container.pack(side="left", padx=(0, 10))
        self.wm_preview_container.pack_propagate(False)
        self.lbl_wm_preview = tk.Label(self.wm_preview_container, bg="lightgray")
        self.lbl_wm_preview.pack(fill="both", expand=True)
        
        self.lbl_watermark = tk.Label(wm_info2, text="No mark selected", fg="gray", anchor="w", font=("Arial", 8), wraplength=130)
        self.lbl_watermark.pack(side="left", fill="x", expand=True)

        # Notebook tabs
        self.wm_notebook = ttk.Notebook(frame_wm_group)
        self.wm_notebook.pack(fill="x", pady=5)
        style.configure("TNotebook", padding=1)
        self.wm_notebook.bind("<<NotebookTabChanged>>", self.on_wm_tab_changed)
        
        self.tab_image = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_image, text="Image")
        self.btn_select_img_wm = ttk.Button(self.tab_image, text="Browse Image", command=self.select_watermark)
        self.btn_select_img_wm.pack(fill="x", padx=5, pady=5)
        
        self.tab_text = ttk.Frame(self.wm_notebook)
        self.wm_notebook.add(self.tab_text, text="Text")
        t_box = tk.Frame(self.tab_text, pady=5)
        t_box.pack(fill="x")
        t_box.columnconfigure(1, weight=1)
        ttk.Label(t_box, text="Text:").grid(row=0, column=0, padx=2)
        self.text_var = tk.StringVar(value="Sample")
        ttk.Entry(t_box, textvariable=self.text_var).grid(row=0, column=1, sticky="ew")
        
        c_box = tk.Frame(self.tab_text)
        c_box.pack(fill="x", padx=5)
        ttk.Label(c_box, text="Size:").pack(side="left")
        ttk.Entry(c_box, textvariable=self.text_size_var, width=5).pack(side="left", padx=2)
        ttk.Button(c_box, text="Pick Color", command=self.pick_color).pack(side="left", padx=2)
        # Visual color preview box
        self.lbl_color_box = tk.Label(c_box, width=3, height=1, relief="raised", bg=self.text_color_var.get())
        self.lbl_color_box.pack(side="left", padx=5)
        ttk.Label(c_box, textvariable=self.text_color_var).pack(side="left")

        f_box = tk.Frame(self.tab_text, pady=2)
        f_box.pack(fill="x", padx=5)
        ttk.Label(f_box, text="Font:").pack(side="left")
        try:
            import tkinter.font as tkfont
            all_fonts = sorted(list(set(tkfont.families())))
            priority = ["Arial", "Preuksa", "Montserrat", "Roboto", "Calibri", "Segoe UI", "Tahoma", "Times New Roman"]
            # Force add requested fonts to list even if not in system fonts for Pillow to find
            avail = [f for f in priority if f in all_fonts] + [f for f in ["Preuksa", "Montserrat", "Roboto"] if f not in all_fonts] + sorted([f for f in all_fonts if f not in priority])
        except: avail = ["Arial", "Preuksa", "Montserrat", "Roboto", "Courier", "Times"]
        
        self.font_cb = ttk.Combobox(f_box, textvariable=self.font_var, values=avail[:150], state="readonly", width=20)
        self.font_cb.pack(side="left", fill="x", expand=True, padx=2)
        self.font_cb.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        self.btn_apply_text_wm = ttk.Button(self.tab_text, text="Apply Text Logo", command=self.generate_text_watermark)
        self.btn_apply_text_wm.pack(fill="x", padx=5, pady=5)
        
        # Recent History
        h_frame = tk.Frame(frame_wm_group)
        h_frame.pack(fill="x", pady=5)
        ttk.Label(h_frame, text="Recent:").pack(side="left")
        self.cb_history = ttk.Combobox(h_frame, state="readonly", width=30)
        self.cb_history.pack(side="left", fill="x", expand=True, padx=5)
        self.cb_history.bind("<<ComboboxSelected>>", self.on_history_selected)
        
        self.btn_clear_wm = ttk.Button(frame_wm_group, text="X Clear Watermark", command=self.clear_watermark_selection)
        self.btn_clear_wm.pack(fill="x", pady=2)

        # Detailed Params
        frame_wm_det = tk.Frame(frame_wm_group)
        frame_wm_det.pack(fill="x", pady=5)
        frame_wm_det.columnconfigure(1, weight=1)
        
        ttk.Label(frame_wm_det, text="Pos:").grid(row=0, column=0, sticky="w")
        self.position_var = tk.StringVar(value="Bottom Right")
        dp = ttk.Combobox(frame_wm_det, textvariable=self.position_var, values=["Top Left", "Top Right", "Bottom Left", "Bottom Right", "Center", "Custom (Drag)"], state="readonly")
        dp.grid(row=0, column=1, sticky="ew", padx=10, pady=2)
        dp.bind("<<ComboboxSelected>>", self.on_position_changed)
        
        ttk.Label(frame_wm_det, text="Scale:").grid(row=1, column=0, sticky="w")
        self.scale_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_wm_det, from_=10, to=300, orient="horizontal", variable=self.scale_var, command=self.on_transform_changed).grid(row=1, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="Opacity:").grid(row=2, column=0, sticky="w")
        self.opacity_var = tk.DoubleVar(value=100)
        ttk.Scale(frame_wm_det, from_=0, to=100, orient="horizontal", variable=self.opacity_var, command=self.on_transform_changed).grid(row=2, column=1, sticky="ew", padx=10, pady=2)
        
        ttk.Label(frame_wm_det, text="Rotate:").grid(row=3, column=0, sticky="w")
        ttk.Scale(frame_wm_det, from_=0, to=360, orient="horizontal", variable=self.rotate_var, command=self.on_transform_changed).grid(row=3, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="Start(s):").grid(row=4, column=0, sticky="w")
        tk.Entry(frame_wm_det, textvariable=self.wm_start_time_var, validate='key', validatecommand=self._vcmd).grid(row=4, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="End(s):").grid(row=5, column=0, sticky="w")
        tk.Entry(frame_wm_det, textvariable=self.wm_end_time_var, validate='key', validatecommand=self._vcmd).grid(row=5, column=1, sticky="ew", padx=10, pady=2)

        ttk.Label(frame_wm_det, text="Effect:").grid(row=6, column=0, sticky="w")
        ttk.Combobox(frame_wm_det, textvariable=self.wm_effect_var, values=["None", "Fade", "Fly In (L)", "Fly In (R)"], state="readonly").grid(row=6, column=1, sticky="ew", padx=10, pady=2)

        # 3. AUDIO (Inside or below)
        frame_audio = tk.Frame(frame_wm_group, pady=5)
        frame_audio.pack(fill="x")
        ttk.Separator(frame_audio, orient='horizontal').pack(fill='x', pady=5)
        self.lbl_bgm = tk.Label(frame_audio, text="Audio: Original", fg="gray", font=("Arial", 8))
        self.lbl_bgm.pack(fill="x")
        
        a_btns = tk.Frame(frame_audio)
        a_btns.pack(fill="x")
        self.btn_select_bgm = ttk.Button(a_btns, text="Set Music", command=self.select_bgm)
        self.btn_select_bgm.pack(side="left", fill="x", expand=True)
        self.btn_clear_bgm = ttk.Button(a_btns, text="X", command=self.clear_bgm, width=3)
        self.btn_clear_bgm.pack(side="left", padx=2)
        
        v_box = tk.Frame(frame_audio, pady=5)
        v_box.pack(fill="x")
        ttk.Label(v_box, text="Orig Vol:", width=8).grid(row=0, column=0, sticky="w")
        ttk.Scale(v_box, from_=0, to=200, orient="horizontal", variable=self.orig_vol_var).grid(row=0, column=1, sticky="ew", padx=5)
        
        ttk.Label(v_box, text="BGM Vol:", width=8).grid(row=1, column=0, sticky="w")
        ttk.Scale(v_box, from_=0, to=200, orient="horizontal", variable=self.bgm_vol_var).grid(row=1, column=1, sticky="ew", padx=5)
        v_box.columnconfigure(1, weight=1)

        tk.Checkbutton(frame_audio, text="Mute Original", variable=self.mute_var).pack(anchor="w")

        # Action block
        frame_actions = tk.Frame(self.sidebar_frame, pady=5)
        frame_actions.pack(side="bottom", fill="x")
        self.lbl_status = tk.Label(frame_actions, text="Ready", fg="blue", anchor="w")
        self.lbl_status.pack(fill="x")
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_actions, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=5)
        
        tk.Checkbutton(frame_actions, text="Process Selected Only", variable=self.process_selected_var).pack(anchor="w")
        parallel_box = tk.Frame(frame_actions)
        parallel_box.pack(fill="x", pady=(0, 5))
        ttk.Label(parallel_box, text="Parallel Videos:").pack(side="left")
        self.parallel_videos_cb = ttk.Combobox(parallel_box, textvariable=self.parallel_videos_var, values=[self.get_auto_parallel_label_for_cfg({"exe": imageio_ffmpeg.get_ffmpeg_exe(), "encoder": self.encoder_var.get()}), "1", "2", "3", "4"], state="readonly", width=16)
        self.parallel_videos_cb.pack(side="right")
        self.parallel_videos_var.set(self.get_auto_parallel_label_for_cfg({"exe": imageio_ffmpeg.get_ffmpeg_exe(), "encoder": self.encoder_var.get()}))

        self.btn_start = ttk.Button(frame_actions, text="🚀 START PROCESS", command=self.start_processing)
        self.btn_start.pack(fill="x", ipady=10)
        
        ttk.Button(frame_actions, text="Reset All Settings", command=self.reset_settings).pack(fill="x", pady=(5,0))

        # ---------------- PLAYER PREVIEW (Right) ---------------- #
        frame_preview = tk.LabelFrame(self.main_container, text="Video Preview (Drag logo to position)", padx=5, pady=5)
        frame_preview.pack(side="right", fill="both", expand=True)
        
        self.canvas_preview = tk.Canvas(frame_preview, bg="black", highlightthickness=0, borderwidth=0)
        self.canvas_preview.pack(fill="both", expand=True, pady=(0, 5))
        self.canvas_preview.tag_bind("watermark", "<ButtonPress-1>", self.on_drag_start)
        self.canvas_preview.tag_bind("watermark", "<B1-Motion>", self.on_drag_motion)
        
        ctrls = tk.Frame(frame_preview)
        ctrls.pack(side="bottom", fill="x", pady=5)
        
        self.btn_play_pause = ttk.Button(ctrls, text="▶ Play", command=self.toggle_play, width=10)
        self.btn_play_pause.pack(side="left")
        
        self.btn_stop = ttk.Button(ctrls, text="⏹ Stop", command=self.stop_playback, width=8)
        self.btn_stop.pack(side="left", padx=5)
        self.btn_audio_preview = ttk.Button(ctrls, text="🔊 Play with Audio", command=self.preview_with_audio, width=18)
        self.btn_audio_preview.pack(side="left", padx=5)
        
        self.seek_var = tk.DoubleVar()
        self.seek_slider = ttk.Scale(ctrls, from_=0, to=100, orient="horizontal", variable=self.seek_var, command=self.seek_video)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        self.lbl_time = ttk.Label(ctrls, text="00:00 / 00:00")
        self.lbl_time.pack(side="left", padx=(0, 5))

    def add_videos(self):
        files = filedialog.askopenfilenames(title="Select Videos", filetypes=(("Video", "*.mp4 *.avi *.mov *.mkv"), ("All", "*.*")))
        if not files: return
        is_first = len(self.video_files) == 0
        invalid = []
        for f in files:
            if f in self.video_files: continue
            
            cap = cv2.VideoCapture(f)
            if not cap.isOpened():
                invalid.append(f"{os.path.basename(f)} (Readable error)")
                continue
            cap.release()

            self.video_files.append(f)
            self.listbox_videos.insert(tk.END, os.path.basename(f))
            
        if invalid:
            msg = "Some files could not be opened and were rejected:\n\n" + "\n".join(invalid)
            messagebox.showwarning("Invalid Format", msg)

        if is_first and len(self.video_files) > 0:
            self.listbox_videos.select_set(0)
            self.show_preview(None)
        self.update_wm_ui_state()

    def remove_videos(self):
        selected = self.listbox_videos.curselection()
        if not selected: return
        # Remove from bottom to top to keep indices valid
        for idx in reversed(selected):
            self.listbox_videos.delete(idx)
            del self.video_files[idx]
        
        if len(self.video_files) > 0:
            new_idx = min(selected[0], len(self.video_files)-1)
            self.listbox_videos.select_set(new_idx)
            self.show_preview(None)
        else:
            if self.video_cap: self.video_cap.release()
            self.video_cap = None
            self.clear_preview("Select a video\nto preview")
            self.lbl_time.config(text="00:00 / 00:00")
            self.wm_start_time_var.set("0")
            self.wm_end_time_var.set("")
        self.update_wm_ui_state()

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
            # Use actual frame dimensions as source of truth
            h, w = frame.shape[:2]
            v_w = w
            self.orig_v_width = v_w
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
        if not self.preview_bg_img: return
        self.canvas_preview.delete("all")
        c_w = max(1, self.canvas_preview.winfo_width())
        c_h = max(1, self.canvas_preview.winfo_height())
        # Use rounding for stable coordinate offsets across UI changes
        ox = int(round((c_w - self.bg_width) / 2.0))
        oy = int(round((c_h - self.bg_height) / 2.0))
        self.canvas_preview.create_image(ox, oy, image=self.preview_bg_img, anchor="nw", tags="bg")
        visible = True
        try:
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30
            cur = self.video_cap.get(cv2.CAP_PROP_POS_FRAMES)/fps
            st_pre = float(self.wm_start_time_var.get() or 0)
            end_val = self.wm_end_time_var.get().strip()
            end = float(end_val) if end_val else 999999
            if (cur < st_pre) or (cur > end): visible = False
        except: pass
        if path and os.path.exists(path) and visible:
            try:
                wm = Image.open(path).convert("RGBA")
                usc = self.scale_var.get()/100.0
                if usc != 1.0: wm = wm.resize((max(1,int(wm.size[0]*usc)), max(1,int(wm.size[1]*usc))), Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS)
                
                rot = self.rotate_var.get()
                if rot != 0: wm = wm.rotate(-rot, expand=True, resample=Image.Resampling.BICUBIC)
                opa_base = self.opacity_var.get()/100.0
                wm_eff = self.wm_effect_var.get()
                opa = opa_base
                eff_dur = 0.5
                if wm_eff == "Fade":
                    if cur < st_pre + eff_dur: opa = opa_base * ((cur-st_pre)/eff_dur)
                    elif cur > end - eff_dur: opa = opa_base * ((end-cur)/eff_dur)
                if opa < 1.0:
                    r,g,b,a = wm.split()
                    wm = Image.merge("RGBA", (r,g,b,a.point(lambda p: int(p*max(0,min(1,opa))))))
                # Always scale relative to current actual background image size for pixel stability
                vsc = self.bg_width / v_w if v_w > 0 else 1.0
                ww, wh = wm.size[0]*vsc, wm.size[1]*vsc
                if ww>0 and wh>0:
                    wm_resized = wm.resize((int(ww), int(wh)), Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS)
                    self.preview_wm_img = ImageTk.PhotoImage(wm_resized)
                    pad = 10.0 * vsc
                    px, py = pad, pad
                    if pos == "Top Right": px = self.bg_width-ww-pad
                    elif pos == "Bottom Left": py = self.bg_height-wh-pad
                    elif pos == "Bottom Right": px, py = self.bg_width-ww-pad, self.bg_height-wh-pad
                    elif pos == "Center": px, py = (self.bg_width-ww)/2, (self.bg_height-wh)/2
                    elif pos == "Custom (Drag)": px, py = self.custom_x_ratio*self.bg_width, self.custom_y_ratio*self.bg_height
                    
                    if wm_eff == "Fly In (L)" and cur < st_pre + eff_dur:
                        px = px - (px + ww) * (1 - max(0, (cur-st_pre)/eff_dur))
                    elif wm_eff == "Fly In (R)" and cur < st_pre + eff_dur:
                        px = px + (self.bg_width - px) * (1 - max(0, (cur-st_pre)/eff_dur))
                        
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
            # Match the stable offset logic for synchronization
            c_w, c_h = max(1, self.canvas_preview.winfo_width()), max(1, self.canvas_preview.winfo_height())
            ox = int(round((c_w - self.bg_width) / 2.0))
            oy = int(round((c_h - self.bg_height) / 2.0))
            self.custom_x_ratio = (coords[0]-ox)/self.bg_width
            self.custom_y_ratio = (coords[1]-oy)/self.bg_height
            if self.position_var.get() != "Custom (Drag)": self.position_var.set("Custom (Drag)")

    def update_wm_preview(self):
        if self.watermark_file:
            try:
                img = Image.open(self.watermark_file).copy(); img.thumbnail((80,80), Image.Resampling.LANCZOS)
                self.wm_preview_img = ImageTk.PhotoImage(img)
                self.lbl_wm_preview.config(image=self.wm_preview_img, text="")
            except: self.lbl_wm_preview.config(image='', text="Error")

    def select_watermark(self):
        if not self.video_files: return
        f = filedialog.askopenfilename(title="Watermark", filetypes=(("Image","*.png *.jpg *.jpeg"),("All","*.*")))
        if f: 
            self.watermark_file=f
            self.lbl_watermark.config(text=os.path.basename(f), fg="black")
            self.update_wm_preview()
            self.update_history(f)
            self.refresh_preview()

    def on_wm_tab_changed(self, e): pass
    def clear_watermark_selection(self):
        self.watermark_file = ""; self.lbl_watermark.config(text="No image", fg="gray"); self.wm_preview_img=None; self.lbl_wm_preview.config(image='', text="None"); self.refresh_preview()

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
        tmp = os.path.join(tempfile.gettempdir(), "video_watermarker_previews")
        if not os.path.exists(tmp): os.makedirs(tmp)
        out = os.path.join(tmp, "preview_sample.mp4")

        meta = self.probe_video_metadata(path, exe)
        fps = meta["fps"] or 30
        spd = float(self.speed_var.get().split('x')[0])
        raw_dur = meta["duration"] if meta["duration"] > 0 else 10
        
        # In preview we only render 10s. If original is longer, fade out won't show unless we cap it.
        dur_v = min(10.0, raw_dur / spd)
        
        has_audio = meta["has_audio"]
        v_f, a_f = self.get_ffmpeg_complex_filter_str(dur_v, has_audio=has_audio)
        cmd = [exe, "-y", "-i", path]
        if self.watermark_file:
            ext_wm = os.path.splitext(self.watermark_file)[1].lower()
            if ext_wm in ['.png', '.jpg', '.jpeg']:
                cmd.extend(["-loop", "1", "-i", self.watermark_file])
            else:
                cmd.extend(["-i", self.watermark_file])
        if self.bgm_file: cmd.extend(["-stream_loop", "-1", "-i", self.bgm_file])
        preview_cfg = {"encoder": self.encoder_var.get(), "encode_speed": "Ultra Fast (fastest, lower quality)"}
        cmd.extend(["-filter_complex", f"{v_f};{a_f}", "-map", "[v]", "-map", "[a]", "-t", "10", "-shortest"])
        cmd.extend(self.build_video_codec_args(exe, preview_cfg, "28", preview_mode=True))
        cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "44100", out])
        si = subprocess.STARTUPINFO() if os.name=='nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            subprocess.run(cmd, startupinfo=si, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if os.name=='nt': os.startfile(out)
            else: subprocess.run(["open" if sys.platform=="darwin" else "xdg-open", out])
        except Exception as e: self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally: self.root.after(0, lambda: (self.btn_audio_preview.config(state="normal"), self.lbl_status.config(text="Ready", fg="blue")))

    def on_position_changed(self, e=None): self.refresh_preview()
    def on_transform_changed(self, e=None): self.refresh_preview()
    def refresh_preview(self): 
        if self.video_cap and self.preview_bg_img: self.draw_preview_canvas(self.watermark_file, self.position_var.get(), self.orig_v_width)

    def open_output_dir(self):
        if self.output_dir: os.startfile(self.output_dir) if os.name=='nt' else subprocess.call(['xdg-open', self.output_dir])

    def get_ffmpeg_complex_filter_str(self, vid_dur=0, has_audio=True, cfg=None):
        if cfg is None:
            cfg = {
                "position": self.position_var.get(),
                "custom_x_ratio": self.custom_x_ratio,
                "custom_y_ratio": self.custom_y_ratio,
                "scale": self.scale_var.get(),
                "rotate": self.rotate_var.get(),
                "wm_start_time": self.wm_start_time_var.get(),
                "wm_end_time": self.wm_end_time_var.get(),
                "wm_effect": self.wm_effect_var.get(),
                "opacity": self.opacity_var.get(),
                "spd": float(self.speed_var.get().split('x')[0]),
                "v_fade": self.v_fade_var.get(),
                "orig_vol": self.orig_vol_var.get(),
                "bgm_vol": self.bgm_vol_var.get(),
                "watermark_file": self.watermark_file,
                "bgm_file": self.bgm_file,
                "mute": self.mute_var.get()
            }

        p, pad = cfg["position"], 10
        target_x = {"Top Left": f"{pad}", "Top Right": f"W-w-{pad}", "Bottom Left": f"{pad}", "Bottom Right": f"W-w-{pad}", "Center": "(W-w)/2"}.get(p, f"W*{cfg['custom_x_ratio']:.6f}")
        target_y = {"Top Left": f"{pad}", "Top Right": f"{pad}", "Bottom Left": f"H-h-{pad}", "Bottom Right": f"H-h-{pad}", "Center": "(H-h)/2"}.get(p, f"H*{cfg['custom_y_ratio']:.6f}")
        
        flt = ["format=rgba"]
        usc = cfg["scale"]/100.0
        if usc != 1.0: 
            # Force even dimensions for hardware compatibility (iPhone/Android)
            flt.append(f"scale=trunc(iw*{usc}/2)*2:trunc(ih*{usc}/2)*2")
        
        rot = cfg["rotate"]
        if rot != 0:
            rad = f"({rot}*PI/180)"
            flt.append(f"rotate={rad}:c=none:ow='iw*abs(cos({rad}))+ih*abs(sin({rad}))':oh='iw*abs(sin({rad}))+ih*abs(cos({rad}))'")

        st, ed = 0, 999999
        try:
            st = float(cfg["wm_start_time"] or 0)
            ed_val = cfg["wm_end_time"].strip()
            if ed_val: ed = float(ed_val)
        except: pass

        wm_eff = cfg["wm_effect"]
        if wm_eff == "Fade":
            flt.append(f"fade=t=in:st={st}:d=0.5:alpha=1")
            if ed < 999998: flt.append(f"fade=t=out:st={ed-0.5}:d=0.5:alpha=1")
        
        opa = cfg["opacity"]/100.0
        if opa < 1.0: flt.append(f"colorchannelmixer=aa={opa}")
            
        en = f"enable='between(t,{st},{ed})'"
        wm_x = f"'{target_x}'"
        wm_y = f"'{target_y}'"
        d = 0.5
        
        if wm_eff == "Fly In (L)":
            wm_x = f"'if(lt(t,{st}+{d}), -w+(t-{st})/{d}*({target_x}+w), {target_x})'"
        elif wm_eff == "Fly In (R)":
            wm_x = f"'if(lt(t,{st}+{d}), W+(t-{st})/{d}*({target_x}-W), {target_x})'"

        spd = cfg["spd"]
        # Force constant 30 FPS to avoid "strange FPS" issues on iPhone/Android
        v_flt_base = f"setpts={1/spd}*PTS"
        
        v_eff = cfg["v_fade"]
        if v_eff == "Fade In" or v_eff == "Both": v_flt_base += ",fade=t=in:st=0:d=1"
        if (v_eff == "Fade Out" or v_eff == "Both") and vid_dur > 0: v_flt_base += f",fade=t=out:st={vid_dur-1}:d=1"

        v_orig, v_bgm = cfg["orig_vol"]/100.0, cfg["bgm_vol"]/100.0
        
        tmp_s = spd
        tempo_f = []
        while tmp_s>2.0: tempo_f.append("atempo=2.0"); tmp_s/=2.0
        while tmp_s<0.5: tempo_f.append("atempo=0.5"); tmp_s*=2.0
        if tmp_s!=1.0: tempo_f.append(f"atempo={tmp_s}")
        a_s = ",".join(tempo_f) if tempo_f else "anull"

        wm_i = 1 if cfg["watermark_file"] else -1
        bg_i = (wm_i+1) if cfg["bgm_file"] and wm_i!=-1 else (1 if cfg["bgm_file"] else -1)
        
        if wm_i != -1:
            overlay_str = f"overlay=x={wm_x}:y={wm_y}:{en}"
            v_res = f"[{wm_i}:v]{','.join(flt)}[wm];[0:v]{v_flt_base}[vs];[vs][wm]{overlay_str}[v]"
        else: v_res = f"[0:v]{v_flt_base}[v]"
            
        a_parts, mix_inputs = [], []
        if has_audio:
            # Use a tiny volume instead of absolute 0 to trick the AAC encoder 
            # into maintaining a high bitrate (prevents the 2kb/s issue).
            v_actual = 0.00001 if cfg["mute"] else v_orig
            a_parts.append(f"[0:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={v_actual},{a_s}[a_orig]")
            mix_inputs.append("[a_orig]")
            
        if bg_i != -1:
            a_parts.append(f"[{bg_i}:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={v_bgm}[a_bgm]")
            mix_inputs.append("[a_bgm]")
            
        if len(mix_inputs) == 2:
            a_res = f"{';'.join(a_parts)};{''.join(mix_inputs)}amix=inputs=2:duration=first:dropout_transition=0[a]"
        elif len(mix_inputs) == 1:
            a_res = f"{a_parts[0]};{mix_inputs[0]}anull[a]"
        else:
            # Explicitly set duration and format to avoid 2kb/s issues on iPhone
            dur_a = vid_dur if vid_dur > 0 else 1
            a_res = f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={dur_a},aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a]"
            
        return v_res, a_res

    def pick_color(self):
        c = colorchooser.askcolor(title="Color", initialcolor=self.text_color_var.get())
        if c and c[1]: 
            self.text_color_var.set(c[1])
            self.lbl_color_box.config(bg=c[1])

    def generate_text_watermark(self):
        if not self.video_files: return
        txt = self.text_var.get()
        if not txt: return
        f_name = self.font_var.get()
        try:
            try: font = ImageFont.truetype(f_name, self.text_size_var.get())
            except: 
                f_map = {"Arial": "arial.ttf", "Times New Roman": "times.ttf", "Courier New": "cour.ttf"}
                font = ImageFont.truetype(f_map.get(f_name, "arial.ttf"), self.text_size_var.get())
        except: font = ImageFont.load_default()
        
        dr = ImageDraw.Draw(Image.new("RGBA", (1,1)))
        try: bb = dr.textbbox((0,0), txt, font=font); w, h = bb[2]-bb[0], bb[3]-bb[1]
        except: w, h = dr.textsize(txt, font=font)
        img = Image.new("RGBA", (w+20, h+20), (255,255,255,0))
        ImageDraw.Draw(img).text((10,10), txt, fill=self.text_color_var.get(), font=font)
        p = os.path.join(tempfile.gettempdir(), "watermark_app_temp_text.png")
        img.save(p)
        self.watermark_file=p
        self.lbl_watermark.config(text=f"Text: {txt[:15]}...", fg="black")
        self.update_wm_preview()
        self.update_history(f"TEXT:{txt}")
        self.refresh_preview()

    def update_history(self, item):
        if item in self.history_wm: self.history_wm.remove(item)
        self.history_wm.insert(0, item)
        self.history_wm = self.history_wm[:10]
        self.cb_history['values'] = [os.path.basename(i) if not i.startswith("TEXT:") else i for i in self.history_wm]
        self.save_config()

    def on_history_selected(self, e):
        if not self.video_files: return
        idx = self.cb_history.current()
        if idx == -1: return
        item = self.history_wm[idx]
        if item.startswith("TEXT:"):
            txt = item[5:]
            self.text_var.set(txt)
            self.generate_text_watermark()
        else:
            if os.path.exists(item):
                self.watermark_file = item
                self.lbl_watermark.config(text=os.path.basename(item), fg="black")
                self.update_wm_preview()
                self.refresh_preview()
            else:
                messagebox.showerror("Error", "File no longer exists.")
                # Remove from history and update UI
                if item in self.history_wm: self.history_wm.remove(item)
                self.cb_history['values'] = [os.path.basename(i) if not i.startswith("TEXT:") else i for i in self.history_wm]
                self.save_config()

    def select_output_dir(self):
        d = filedialog.askdirectory(title="Output")
        if d: 
            self.output_dir=d
            self.lbl_output.config(text=d, fg="black")
            self.save_config()
    def check_has_audio(self, path, exe=None):
        exe = exe or imageio_ffmpeg.get_ffmpeg_exe()
        # Fast probe using ffmpeg
        cmd = [exe, "-hide_banner", "-i", path]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            return "Audio:" in res.stderr
        except: return False


    def start_processing(self):
        missing = []
        if not self.video_files: missing.append("- Videos input")
        if not self.output_dir: missing.append("- Output folder (Set Folder)")
        
        if missing:
            messagebox.showerror("Error", "Please provide:\n" + "\n".join(missing))
            return
            
        settings = {
            "exe": imageio_ffmpeg.get_ffmpeg_exe(),
            "spd": float(self.speed_var.get().split('x')[0]),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "output_dir": self.output_dir,
            "watermark_file": self.watermark_file,
            "bgm_file": self.bgm_file,
            "encoder": self.encoder_var.get(),
            "encode_speed": self.encode_speed_var.get(),
            "process_selected": self.process_selected_var.get(),
            "position": self.position_var.get(),
            "custom_x_ratio": self.custom_x_ratio,
            "custom_y_ratio": self.custom_y_ratio,
            "scale": self.scale_var.get(),
            "rotate": self.rotate_var.get(),
            "wm_start_time": self.wm_start_time_var.get(),
            "wm_end_time": self.wm_end_time_var.get(),
            "wm_effect": self.wm_effect_var.get(),
            "opacity": self.opacity_var.get(),
            "v_fade": self.v_fade_var.get(),
            "orig_vol": self.orig_vol_var.get(),
            "bgm_vol": self.bgm_vol_var.get(),
            "mute": self.mute_var.get(),
            "parallel_videos": self.parallel_videos_var.get()
        }
        settings["auto_parallel_count"] = self.get_auto_parallel_count_for_cfg(settings)
        
        if settings["process_selected"]:
            sel = self.listbox_videos.curselection()
            settings["files"] = [self.video_files[i] for i in sel]
        else:
            settings["files"] = list(self.video_files)

        if not settings["files"]:
            messagebox.showwarning("Warning", "No videos to process!")
            return

        self.btn_start.config(state="disabled"); self.progress_var.set(0)
        threading.Thread(target=self.process_videos, args=(settings,), daemon=True).start()

    def process_single_video(self, cfg, path):
        exe = cfg["exe"]
        spd = cfg["spd"]
        fname = os.path.basename(path)
        ffmpeg_threads = max(1, int(cfg.get("ffmpeg_threads", 1)))

        meta = self.probe_video_metadata(path, exe)
        dur_raw = meta["duration"] if meta["duration"] > 0 else 1
        has_audio = meta["has_audio"]
        copy_audio = self.can_copy_audio(cfg, has_audio)
        needs_video_filter = self.needs_video_filter(cfg)
        f_v, f_a = self.get_ffmpeg_complex_filter_str(dur_raw/spd, has_audio=(has_audio and not copy_audio), cfg=cfg)

        name, ext = os.path.splitext(fname)
        out_ext = ext if cfg["format"] == "Original" else f".{cfg['format'].lower()}"
        out = os.path.join(cfg["output_dir"], f"watermarked_{name}{out_ext}")
        crf = {"Low (Smaller File)": "28", "Medium (Balanced)": "23"}.get(cfg["quality"], "18")

        cmd = [exe, "-y", "-threads", str(ffmpeg_threads), "-i", path]
        if cfg["watermark_file"]:
            ext_wm = os.path.splitext(cfg["watermark_file"])[1].lower()
            if ext_wm in ['.png', '.jpg', '.jpeg']:
                cmd.extend(["-loop", "1", "-framerate", "30", "-i", cfg["watermark_file"]])
            else:
                cmd.extend(["-i", cfg["watermark_file"]])

        if cfg["bgm_file"]:
            cmd.extend(["-stream_loop", "-1", "-i", cfg["bgm_file"]])

        target_dur = dur_raw / spd
        filter_parts = []
        if needs_video_filter:
            filter_parts.append(f_v)
        if not copy_audio:
            filter_parts.append(f_a)
        if filter_parts:
            cmd.extend(["-filter_complex", ";".join(filter_parts)])

        if needs_video_filter:
            cmd.extend(["-map", "[v]"])
        else:
            cmd.extend(["-map", "0:v:0"])
        if copy_audio:
            cmd.extend(["-map", "0:a?"])
        else:
            cmd.extend(["-map", "[a]"])
        cmd.extend(["-t", f"{target_dur}"])
        cmd.extend(self.build_video_codec_args(exe, cfg, crf))
        if copy_audio:
            cmd.extend(["-c:a", "copy", out])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "44100", out])

        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(cmd, startupinfo=si, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            raise Exception(result.stderr)

        return fname

    def process_videos(self, cfg):
        total = len(cfg["files"])
        selected_parallel = str(cfg.get("parallel_videos", self.get_auto_parallel_label()))
        if selected_parallel.startswith("Auto"):
            max_workers = min(total, int(cfg.get("auto_parallel_count", self.get_auto_parallel_count_for_cfg(cfg))))
        else:
            max_workers = min(total, max(1, int(selected_parallel)))
        cfg = dict(cfg)
        cfg["ffmpeg_threads"] = self.get_ffmpeg_thread_count(cfg, max_workers)
        completed = 0
        failed = []

        self.root.after(0, lambda: self.lbl_status.config(text=f"Processing {total} video(s), up to {max_workers} videos in parallel...", fg="orange"))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(self.process_single_video, cfg, path): path for path in cfg["files"]}

            for future in as_completed(future_map):
                path = future_map[future]
                fname = os.path.basename(path)
                try:
                    future.result()
                except Exception as e:
                    failed.append((fname, str(e)))

                completed += 1
                progress = (completed / total) * 100
                self.root.after(0, lambda p=progress, done=completed, n=total, name=fname: (
                    self.progress_var.set(p),
                    self.lbl_status.config(text=f"Completed {done}/{n}: {name}", fg="orange")
                ))

        def finish():
            self.btn_start.config(state="normal")
            if failed:
                self.lbl_status.config(text=f"Completed with errors ({total-len(failed)}/{total})", fg="red")
                err_list = "\n\n".join(f"{name}\n{err}" for name, err in failed)
                messagebox.showerror("Processing Error", f"Some videos failed:\n\n{err_list}")
            else:
                self.lbl_status.config(text="Completed!", fg="green")
                self.open_output_dir()
                messagebox.showinfo("Success", "Batch processing finished. Output folder opened.")

        self.root.after(0, finish)

    def fmt_time(self, s): mins, secs = int(max(0,s)//60), int(max(0,s)%60); return f"{mins:02d}:{secs:02d}"

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.output_dir = data.get("output_dir", "")
                    if self.output_dir: self.lbl_output.config(text=self.output_dir, fg="black")
                    self.history_wm = data.get("history_wm", [])
                    self.cb_history['values'] = [os.path.basename(i) if not i.startswith("TEXT:") else i for i in self.history_wm]
                    last_f = data.get("font_family", "Arial")
                    if last_f: self.font_var.set(last_f)
                    tc = data.get("text_color", "#FFFFFF")
                    self.text_color_var.set(tc)
                    encoder_val = data.get("encoder", "Auto (Recommended)")
                    speed_val = data.get("encode_speed", "Very Fast (Recommended)")
                    if encoder_val == "Auto":
                        encoder_val = "Auto (Recommended)"
                    elif encoder_val == "CPU (libx264)":
                        encoder_val = "CPU Only (More compatible)"
                    elif encoder_val == "NVIDIA NVENC":
                        encoder_val = "NVIDIA GPU (Fastest, if supported)"
                    if speed_val == "Fast":
                        speed_val = "Fast (better quality)"
                    elif speed_val == "Very Fast":
                        speed_val = "Very Fast (Recommended)"
                    elif speed_val == "Super Fast":
                        speed_val = "Super Fast (faster, larger file)"
                    elif speed_val == "Ultra Fast":
                        speed_val = "Ultra Fast (fastest, lower quality)"
                    self.encoder_var.set(encoder_val)
                    self.encode_speed_var.set(speed_val)
                    self.refresh_parallel_videos_ui()
                    try: self.lbl_color_box.config(bg=tc)
                    except: pass
            except: pass

    def save_config(self):
        data = {
            "output_dir": self.output_dir,
            "history_wm": self.history_wm,
            "font_family": self.font_var.get(),
            "text_color": self.text_color_var.get(),
            "encoder": self.encoder_var.get(),
            "encode_speed": self.encode_speed_var.get()
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except: pass

    def reset_settings(self):
        if not messagebox.askyesno("Reset", "Clear all settings and files?"): return
        self.video_files = []
        self.listbox_videos.delete(0, tk.END)
        self.clear_watermark_selection()
        self.clear_bgm()
        self.format_var.set("Original")
        self.quality_var.set("Medium (Balanced)")
        self.speed_var.set("1x (Normal)")
        self.encoder_var.set("Auto (Recommended)")
        self.encode_speed_var.set("Very Fast (Recommended)")
        self.v_fade_var.set("None")
        self.position_var.set("Bottom Right")
        self.scale_var.set(100)
        self.opacity_var.set(100)
        self.orig_vol_var.set(100)
        self.bgm_vol_var.set(100)
        self.wm_effect_var.set("None")
        self.wm_start_time_var.set("0")
        self.wm_end_time_var.set("")
        self.rotate_var.set(0)
        self.text_var.set("Sample")
        self.text_size_var.set(80)
        self.text_color_var.set("#FFFFFF")
        try: self.lbl_color_box.config(bg="#FFFFFF")
        except: pass
        self.font_var.set("Arial")
        self.mute_var.set(False)
        self.refresh_parallel_videos_ui()
        self.lbl_status.config(text="Ready", fg="blue")
        self.progress_var.set(0)
        if self.video_cap: self.video_cap.release(); self.video_cap = None
        self.clear_preview("Select a video\nto preview")
        self.update_wm_ui_state()
        messagebox.showinfo("Reset", "Settings wiped.")

    def update_wm_ui_state(self):
        state = "normal" if len(self.video_files) > 0 else "disabled"
        try:
            self.btn_select_img_wm.config(state=state)
            self.btn_apply_text_wm.config(state=state)
            self.btn_clear_wm.config(state=state)
            self.cb_history.config(state="readonly" if state=="normal" else "disabled")
            self.btn_play_pause.config(state=state)
            self.btn_stop.config(state=state)
            self.btn_audio_preview.config(state=state)
            self.seek_slider.config(state=state)
            self.btn_start.config(state=state)
            self.btn_select_bgm.config(state=state)
            self.btn_clear_bgm.config(state=state)
        except: pass

if __name__ == "__main__":
    root = tk.Tk(); app = WatermarkApp(root); root.mainloop()
