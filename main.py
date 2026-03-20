"""
main.py - 财经新闻 Job 管理器
Windows GUI application for managing the daily financial news collection job.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import os
import datetime
import time
import logging
import queue
import sys

import schedule

from job_runner import load_config, run_job

# ──────────────────────────────────────────────────────────────
# Logging setup — pipe to queue for GUI display
# ──────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_queue: queue.Queue = queue.Queue()


class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(self.format(record))


root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
queue_handler = QueueHandler()
queue_handler.setFormatter(logging.Formatter("%(message)s"))
root_logger.addHandler(queue_handler)

# File handler
file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, f"job_{datetime.date.today().strftime('%Y%m%d')}.log"),
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Constants / colors
# ──────────────────────────────────────────────────────────────
BG = "#1e1e2e"
SURFACE = "#2a2a3e"
ACCENT = "#7c3aed"
ACCENT_HOVER = "#6d28d9"
SUCCESS = "#22c55e"
ERROR = "#ef4444"
WARNING = "#f59e0b"
TEXT = "#e2e8f0"
TEXT_DIM = "#94a3b8"
BORDER = "#3f3f5f"

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")


# ──────────────────────────────────────────────────────────────
# State persistence
# ──────────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_run": None, "last_result": None, "run_count": 0}


def save_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_data = load_config(CONFIG_PATH)
        self.state = load_state()

        self._job_running = False
        self._scheduler_running = False
        self._scheduler_thread: threading.Thread | None = None
        self._job_thread: threading.Thread | None = None

        self._setup_window()
        self._build_ui()
        self._refresh_status()
        self._poll_log_queue()

        if self.config_data.get("schedule_enabled", True):
            self._start_scheduler()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Window ──────────────────────────────────────────────
    def _setup_window(self):
        self.title("📰 财经新闻 Job 管理器")
        self.geometry("780x620")
        self.minsize(680, 520)
        self.configure(bg=BG)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass
        # Center on screen
        self.update_idletasks()
        w, h = 780, 620
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── UI ──────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ─────────────────────────
        hdr = tk.Frame(self, bg=ACCENT, height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="📰  财经新闻 Job 管理器",
            bg=ACCENT, fg="white",
            font=("Microsoft YaHei", 15, "bold"),
        ).pack(side=tk.LEFT, padx=20, pady=10)
        tk.Label(
            hdr, text="每日自动收集 Top 10 财经新闻 → 飞书",
            bg=ACCENT, fg="#c4b5fd",
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT, padx=0, pady=14)

        # ── Body ───────────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        # ── Status card ─────────────────────
        self._build_status_card(body)

        # ── Settings card ────────────────────
        self._build_settings_card(body)

        # ── Button row ──────────────────────
        self._build_buttons(body)

        # ── Log area ────────────────────────
        self._build_log_area(body)

    def _card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=SURFACE, bd=0, highlightthickness=1,
                         highlightbackground=BORDER)
        outer.pack(fill=tk.X, pady=(0, 10))
        tk.Label(outer, text=f"  {title}", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 8, "bold")).pack(anchor=tk.W, pady=(6, 2))
        inner = tk.Frame(outer, bg=SURFACE)
        inner.pack(fill=tk.X, padx=12, pady=(0, 10))
        return inner

    def _build_status_card(self, parent):
        frame = self._card(parent, "▸ 任务状态")

        # Row 1
        r1 = tk.Frame(frame, bg=SURFACE)
        r1.pack(fill=tk.X, pady=2)
        tk.Label(r1, text="调度状态：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
        self._lbl_sched_status = tk.Label(r1, text="—", bg=SURFACE, fg=TEXT,
                                          font=("Microsoft YaHei", 9, "bold"))
        self._lbl_sched_status.pack(side=tk.LEFT)

        tk.Label(r1, text="     任务状态：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        self._lbl_job_status = tk.Label(r1, text="空闲", bg=SURFACE, fg=SUCCESS,
                                        font=("Microsoft YaHei", 9, "bold"))
        self._lbl_job_status.pack(side=tk.LEFT)

        # Row 2
        r2 = tk.Frame(frame, bg=SURFACE)
        r2.pack(fill=tk.X, pady=2)
        tk.Label(r2, text="下次执行：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
        self._lbl_next_run = tk.Label(r2, text="—", bg=SURFACE, fg=TEXT,
                                      font=("Microsoft YaHei", 9))
        self._lbl_next_run.pack(side=tk.LEFT)

        # Row 3
        r3 = tk.Frame(frame, bg=SURFACE)
        r3.pack(fill=tk.X, pady=2)
        tk.Label(r3, text="上次执行：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
        self._lbl_last_run = tk.Label(r3, text="—", bg=SURFACE, fg=TEXT,
                                      font=("Microsoft YaHei", 9))
        self._lbl_last_run.pack(side=tk.LEFT)
        self._lbl_last_result = tk.Label(r3, text="", bg=SURFACE, fg=SUCCESS,
                                         font=("Microsoft YaHei", 9, "bold"))
        self._lbl_last_result.pack(side=tk.LEFT, padx=(12, 0))

        tk.Label(r3, text="   累计运行：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        self._lbl_run_count = tk.Label(r3, text="0 次", bg=SURFACE, fg=TEXT,
                                       font=("Microsoft YaHei", 9))
        self._lbl_run_count.pack(side=tk.LEFT)

    def _build_settings_card(self, parent):
        frame = self._card(parent, "▸ 设置")

        r1 = tk.Frame(frame, bg=SURFACE)
        r1.pack(fill=tk.X, pady=2)

        tk.Label(r1, text="执行时间：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)

        self._hour_var = tk.StringVar()
        self._min_var = tk.StringVar()
        sched_time = self.config_data.get("schedule_time", "08:00")
        h, m = sched_time.split(":")
        self._hour_var.set(h)
        self._min_var.set(m)

        hour_spin = tk.Spinbox(r1, from_=0, to=23, width=3, textvariable=self._hour_var,
                               format="%02.0f", bg=SURFACE, fg=TEXT,
                               buttonbackground=BORDER, insertbackground=TEXT,
                               font=("Consolas", 10))
        hour_spin.pack(side=tk.LEFT)
        tk.Label(r1, text=" : ", bg=SURFACE, fg=TEXT,
                 font=("Consolas", 10)).pack(side=tk.LEFT)
        min_spin = tk.Spinbox(r1, from_=0, to=59, width=3, textvariable=self._min_var,
                              format="%02.0f", bg=SURFACE, fg=TEXT,
                              buttonbackground=BORDER, insertbackground=TEXT,
                              font=("Consolas", 10))
        min_spin.pack(side=tk.LEFT)

        tk.Label(r1, text="   飞书 Chat ID：", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        self._chat_id_var = tk.StringVar(value=self.config_data.get("feishu_chat_id", ""))
        chat_entry = tk.Entry(r1, textvariable=self._chat_id_var, width=36,
                              bg="#1a1a2e", fg=TEXT, insertbackground=TEXT,
                              font=("Consolas", 9), relief=tk.FLAT,
                              highlightthickness=1, highlightbackground=BORDER)
        chat_entry.pack(side=tk.LEFT, padx=(4, 0))

        r2 = tk.Frame(frame, bg=SURFACE)
        r2.pack(fill=tk.X, pady=(4, 0))
        save_btn = self._mk_btn(r2, "保存设置", self._save_settings,
                                bg="#374151", hover="#4b5563", width=10)
        save_btn.pack(side=tk.LEFT)

    def _build_buttons(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill=tk.X, pady=(0, 8))

        self._run_btn = self._mk_btn(row, "▶  立即运行", self._manual_run,
                                     bg=ACCENT, hover=ACCENT_HOVER, width=14)
        self._run_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._toggle_btn = self._mk_btn(row, "⏸  暂停定时", self._toggle_scheduler,
                                        bg="#1d4ed8", hover="#1e40af", width=12)
        self._toggle_btn.pack(side=tk.LEFT, padx=(0, 8))

        clear_btn = self._mk_btn(row, "🗑  清除日志", self._clear_log,
                                 bg="#374151", hover="#4b5563", width=12)
        clear_btn.pack(side=tk.LEFT)

    def _build_log_area(self, parent):
        log_frame = tk.Frame(parent, bg=SURFACE, bd=0, highlightthickness=1,
                             highlightbackground=BORDER)
        log_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(log_frame, text="  ▸ 执行日志", bg=SURFACE, fg=TEXT_DIM,
                 font=("Microsoft YaHei", 8, "bold")).pack(anchor=tk.W, pady=(6, 2))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, bg="#0f0f1a", fg="#a8b2c1",
            font=("Consolas", 9), relief=tk.FLAT,
            insertbackground=TEXT, state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._log_text.tag_config("success", foreground=SUCCESS)
        self._log_text.tag_config("error", foreground=ERROR)
        self._log_text.tag_config("warn", foreground=WARNING)
        self._log_text.tag_config("dim", foreground=TEXT_DIM)

    def _mk_btn(self, parent, text: str, cmd, bg: str, hover: str, width: int = 12):
        btn = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg="white", activebackground=hover, activeforeground="white",
            font=("Microsoft YaHei", 9, "bold"),
            relief=tk.FLAT, cursor="hand2",
            width=width, height=1, padx=8, pady=6,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    # ── Status refresh ──────────────────────────────────────
    def _refresh_status(self):
        # Scheduler status
        if self._scheduler_running:
            sched_time = self.config_data.get("schedule_time", "08:00")
            self._lbl_sched_status.config(text=f"● 运行中 (每天 {sched_time})", fg=SUCCESS)
            self._toggle_btn.config(text="⏸  暂停定时")
            # Next run
            next_jobs = schedule.get_jobs()
            if next_jobs:
                next_run = min(j.next_run for j in next_jobs)
                self._lbl_next_run.config(text=next_run.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                self._lbl_next_run.config(text="—")
        else:
            self._lbl_sched_status.config(text="○ 已暂停", fg=TEXT_DIM)
            self._toggle_btn.config(text="▶  开启定时")
            self._lbl_next_run.config(text="—")

        # Job status
        if self._job_running:
            self._lbl_job_status.config(text="● 执行中...", fg=WARNING)
            self._run_btn.config(state=tk.DISABLED, text="⏳ 执行中...")
        else:
            self._lbl_job_status.config(text="空闲", fg=SUCCESS)
            self._run_btn.config(state=tk.NORMAL, text="▶  立即运行")

        # Last run
        last_run = self.state.get("last_run")
        if last_run:
            self._lbl_last_run.config(text=last_run)
            result = self.state.get("last_result")
            if result == "success":
                self._lbl_last_result.config(text="✓ 成功", fg=SUCCESS)
            elif result == "failed":
                self._lbl_last_result.config(text="✗ 失败", fg=ERROR)
        else:
            self._lbl_last_run.config(text="从未运行")

        self._lbl_run_count.config(text=f"{self.state.get('run_count', 0)} 次")

        self.after(2000, self._refresh_status)

    # ── Log ─────────────────────────────────────────────────
    def _poll_log_queue(self):
        max_batch = 30
        try:
            for _ in range(max_batch):
                msg = log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(200, self._poll_log_queue)

    def _append_log(self, msg: str):
        self._log_text.config(state=tk.NORMAL)
        tag = None
        if "✓" in msg or "成功" in msg:
            tag = "success"
        elif "✗" in msg or "失败" in msg or "错误" in msg or "Error" in msg.lower():
            tag = "error"
        elif "警告" in msg or "超时" in msg:
            tag = "warn"
        elif msg.startswith("---"):
            tag = "dim"
        if tag:
            self._log_text.insert(tk.END, msg + "\n", tag)
        else:
            self._log_text.insert(tk.END, msg + "\n")

        # Trim log
        max_lines = self.config_data.get("log_max_lines", 1000)
        lines = int(self._log_text.index(tk.END).split(".")[0])
        if lines > max_lines + 50:
            self._log_text.delete("1.0", f"{lines - max_lines}.0")

        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _clear_log(self):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ── Job execution ────────────────────────────────────────
    def _manual_run(self):
        if self._job_running:
            messagebox.showwarning("提示", "任务正在执行中，请稍候...")
            return
        self._start_job()

    def _start_job(self):
        if self._job_running:
            return
        self._job_running = True
        self._job_thread = threading.Thread(target=self._run_job_thread, daemon=True)
        self._job_thread.start()

    def _run_job_thread(self):
        config = load_config(CONFIG_PATH)

        def log_cb(msg: str):
            log_queue.put(msg)

        result = run_job(config, log_callback=log_cb)

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state["last_run"] = now
        self.state["last_result"] = "success" if result["success"] else "failed"
        self.state["run_count"] = self.state.get("run_count", 0) + 1
        save_state(self.state)

        self._job_running = False

    # ── Scheduler ────────────────────────────────────────────
    def _start_scheduler(self):
        if self._scheduler_running:
            return
        schedule.clear()
        sched_time = self.config_data.get("schedule_time", "08:00")
        schedule.every().day.at(sched_time).do(self._start_job)
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True, name="SchedulerThread"
        )
        self._scheduler_thread.start()
        logger.info(f"[调度器] 已启动，将在每天 {sched_time} 执行任务")

    def _stop_scheduler(self):
        self._scheduler_running = False
        schedule.clear()
        logger.info("[调度器] 已暂停")

    def _scheduler_loop(self):
        while self._scheduler_running:
            schedule.run_pending()
            time.sleep(10)

    def _toggle_scheduler(self):
        if self._scheduler_running:
            self._stop_scheduler()
            self.config_data["schedule_enabled"] = False
        else:
            self._start_scheduler()
            self.config_data["schedule_enabled"] = True
        self._save_config()

    # ── Settings ─────────────────────────────────────────────
    def _save_settings(self):
        try:
            h = int(self._hour_var.get())
            m = int(self._min_var.get())
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "请输入有效的时间 (小时 0-23, 分钟 0-59)")
            return

        new_time = f"{h:02d}:{m:02d}"
        self.config_data["schedule_time"] = new_time
        self.config_data["feishu_chat_id"] = self._chat_id_var.get().strip()
        self._save_config()

        # Restart scheduler with new time
        if self._scheduler_running:
            self._stop_scheduler()
            self._start_scheduler()

        logger.info(f"[设置] 已保存：执行时间={new_time}, chat_id={self.config_data['feishu_chat_id']}")
        messagebox.showinfo("成功", f"设置已保存！\n定时任务将在每天 {new_time} 执行。")

    def _save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, ensure_ascii=False, indent=2)

    # ── Close ────────────────────────────────────────────────
    def _on_close(self):
        if self._job_running:
            if not messagebox.askyesno("确认", "任务正在执行中，确定要退出吗？"):
                return
        self._scheduler_running = False
        self.destroy()


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
