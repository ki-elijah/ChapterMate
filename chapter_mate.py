import os
import json
import datetime
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, simpledialog
import fitz  # PyMuPDF
import re

# --- UX / UI DESIGN SYSTEM ---
THEME = {
    "bg_main":       "#121212",  
    "bg_text_area":  "#1E1E1E",  
    "bg_card":       "#2C2C2C",
    "bg_popup":      "#252526",  
    "fg_text":       "#E0E0E0",  
    "fg_dim":        "#A0A0A0",  
    "fg_accent":     "#BB86FC",  
    "fg_progress":   "#03DAC6", 
    "fg_warn":       "#CF6679",
    "font_header":   ("Segoe UI", 18, "bold"),
    "font_body":     ("Georgia", 13),      
    "font_ui":       ("Segoe UI", 10),      
    "font_emoji":    ("Segoe UI Emoji", 14) 
}

STATE_FILE = "reading_library.json"
CACHE_FILE = "offline_cache.json"
DEFAULT_PAGES = 10

def load_library_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f: return json.load(f)
        except: pass
    return {"active_book": None, "library": {}, "last_run_date": None}

def save_library_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f)

def get_pdf_text(filepath, start_page, num_pages):
    try:
        doc = fitz.open(filepath)
        total_pages = doc.page_count
        if start_page >= total_pages:
            doc.close()
            return "", start_page, True, total_pages
        end_page = min(start_page + num_pages, total_pages)
        text = ""
        for i in range(start_page, end_page):
            text += doc.load_page(i).get_text("text") + " "
        doc.close()
        return text, end_page, (end_page >= total_pages), total_pages
    except: return "", start_page, False, 0

def generate_summary_points(text):
    lines = text.replace('\n', ' ').split('. ')
    valid_lines = [line.strip() for line in lines if len(line) > 25]
    points = [f"{line}." for line in valid_lines]
    return points[:50] if len(points) <= 50 else points[::2]

class ChapterMate:
    def __init__(self, root):
        self.root = root
        self.root.title("ChapterMate - Library Edition")
        self.root.geometry("1000x850")
        self.root.configure(bg=THEME["bg_main"])
        
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Horizontal.TProgressbar", background=THEME["fg_progress"], troughcolor=THEME["bg_card"], borderwidth=0)
        
        self.state = load_library_state()
        self.today = str(datetime.date.today())
        self.setup_ui()

    def setup_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg=THEME["bg_main"])
        header.pack(fill=tk.X, padx=40, pady=(30, 20))
        self.lbl_book = tk.Label(header, text="No Active Book", font=THEME["font_header"], bg=THEME["bg_main"], fg="white", anchor="w")
        self.lbl_book.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 2. Progress
        meta = tk.Frame(self.root, bg=THEME["bg_main"])
        meta.pack(fill=tk.X, padx=40, pady=(0, 20))
        self.progress_var = tk.DoubleVar()
        self.pbar = ttk.Progressbar(meta, style="Horizontal.TProgressbar", variable=self.progress_var, maximum=100, length=200)
        self.pbar.pack(side=tk.RIGHT)
        self.lbl_percent = tk.Label(meta, text="0%", font=("Segoe UI", 9, "bold"), bg=THEME["bg_main"], fg=THEME["fg_progress"])
        self.lbl_percent.pack(side=tk.RIGHT, padx=10)

        # 3. Reading Area
        self.txt_summary = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, height=10, font=THEME["font_body"], bg=THEME["bg_text_area"], fg=THEME["fg_text"], insertbackground="white", relief="flat", padx=40, pady=20)
        self.txt_summary.pack(fill=tk.BOTH, expand=True)
        self.txt_summary.tag_configure("card", background=THEME["bg_card"], lmargin1=30, lmargin2=70, rmargin=30, spacing1=25, spacing3=25, spacing2=8)
        self.txt_summary.tag_configure("date_header", font=("Segoe UI", 12, "bold"), foreground=THEME["fg_accent"], justify="center")

        # 4. Footer Buttons
        footer = tk.Frame(self.root, bg=THEME["bg_main"])
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=25)
        btn_container = tk.Frame(footer, bg=THEME["bg_main"])
        btn_container.pack()

        def make_btn(text, cmd, color):
            return tk.Button(btn_container, text=text, command=cmd, bg=color, font=THEME["font_ui"], relief="flat", padx=15, pady=8, cursor="hand2")

        make_btn("📚 LIBRARY", self.open_library, "#E0E0E0").pack(side=tk.LEFT, padx=5)
        make_btn("📂 NEW", self.upload_book, "#A0A0A0").pack(side=tk.LEFT, padx=5)
        make_btn("⬅ PREV", self.go_prev, "#FFB74D").pack(side=tk.LEFT, padx=5)
        make_btn("📖 NEXT", self.go_next, THEME["fg_progress"]).pack(side=tk.LEFT, padx=5)
        make_btn("✅ DONE", self.root.destroy, "#4CAF50").pack(side=tk.LEFT, padx=5)
        
        # --- NEW RESET BUTTON ---
        make_btn("🔥 RESET ALL", self.factory_reset, THEME["fg_warn"]).pack(side=tk.LEFT, padx=5)
        
        self.load_daily_content()

    def factory_reset(self):
        """Wipes the library state and cache files entirely."""
        confirm = messagebox.askyesno("Factory Reset", "This will PERMANENTLY delete all your books, progress, and cache. Are you sure you want to start from scratch?")
        if confirm:
            if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
            if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
            messagebox.showinfo("Reset Complete", "All data cleared. The application will now restart.")
            self.root.destroy()
            # Restart logic is handled by Windows automation (batch file)

    def open_library(self):
        lib_win = tk.Toplevel(self.root)
        lib_win.title("Library")
        lib_win.geometry("500x500")
        lib_win.configure(bg=THEME["bg_popup"])
        for path, data in self.state["library"].items():
            btn = tk.Button(lib_win, text=f"{data['title']} ({int(data['page']/data['total']*100)}%)", 
                            command=lambda p=path: self.resume_book(p, lib_win), bg=THEME["bg_card"], fg="white", pady=10)
            btn.pack(fill=tk.X, padx=10, pady=5)

    def resume_book(self, path, win):
        self.state["active_book"] = path
        save_library_state(self.state)
        win.destroy()
        self.load_daily_content()

    def upload_book(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if path:
            start = simpledialog.askinteger("Skip Intro", "Start page:", minvalue=0) or 0
            doc = fitz.open(path)
            self.state["active_book"] = path
            self.state["library"][path] = {"title": os.path.basename(path), "page": start, "total": doc.page_count, "status": "reading"}
            doc.close()
            save_library_state(self.state)
            self.load_daily_content()

    def load_daily_content(self):
        self.txt_summary.config(state=tk.NORMAL)
        self.txt_summary.delete(1.0, tk.END)
        if not self.state["active_book"]:
            self.txt_summary.insert(tk.END, "\n\n      Welcome. Use NEW to upload a book.\n      (Previous data cleared)", "date_header")
            self.lbl_book.config(text="No Active Book")
            self.progress_var.set(0)
            self.lbl_percent.config(text="0%")
        else:
            path = self.state["active_book"]
            entry = self.state["library"][path]
            self.lbl_book.config(text=entry["title"])
            pct = (entry["page"] / entry["total"]) * 100
            self.progress_var.set(pct)
            self.lbl_percent.config(text=f"{int(pct)}%")
            text, _, _, _ = get_pdf_text(path, entry["page"], DEFAULT_PAGES)
            points = generate_summary_points(text)
            self.txt_summary.insert(tk.END, f"\n{self.today.upper()}\n", "date_header")
            for p in points:
                self.txt_summary.insert(tk.END, f"💡   {p}\n", "card")
        self.txt_summary.config(state=tk.DISABLED)

    def go_next(self):
        if self.state["active_book"]:
            path = self.state["active_book"]
            self.state["library"][path]["page"] += DEFAULT_PAGES
            save_library_state(self.state)
            self.load_daily_content()

    def go_prev(self):
        if self.state["active_book"]:
            path = self.state["active_book"]
            self.state["library"][path]["page"] = max(0, self.state["library"][path]["page"] - DEFAULT_PAGES)
            save_library_state(self.state)
            self.load_daily_content()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChapterMate(root)
    root.mainloop()