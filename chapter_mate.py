import os
import json
import datetime
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, simpledialog
import fitz  # PyMuPDF
import sys
import ollama # The AI Connector

# --- CONFIGURATION ---
def get_data_path(filename):
    if getattr(sys, 'frozen', False):
        app_data = os.path.join(os.environ['APPDATA'], 'ChapterMate')
        if not os.path.exists(app_data): os.makedirs(app_data)
        return os.path.join(app_data, filename)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

STATE_FILE = get_data_path("reading_library.json")
DEFAULT_PAGES = 10 
AI_MODEL = "llama3.2" 

# --- THEME ---
THEME = {
    "bg_main":       "#121212",  
    "bg_text_area":  "#1E1E1E",  
    "bg_card":       "#2C2C2C",
    "bg_popup":      "#252526",  
    "fg_text":       "#E0E0E0",  
    "fg_accent":     "#BB86FC",  
    "fg_progress":   "#03DAC6", 
    "fg_warn":       "#CF6679",
    "font_header":   ("Segoe UI", 16, "bold"),
    "font_body":     ("Georgia", 13),      
    "font_ui":       ("Segoe UI", 10),      
}

def load_library_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f: return json.load(f)
        except: pass
    return {"active_book": None, "library": {}}

def save_library_state(state):
    try:
        with open(STATE_FILE, "w") as f: json.dump(state, f)
    except: pass

# --- FIXED PDF EXTRACTOR ---
def get_pdf_text(filepath, start_page, num_pages):
    try:
        doc = fitz.open(filepath)
        total_pages = doc.page_count
        end_page = min(start_page + num_pages, total_pages)
        text = ""
        
        # Try to read page by page, skipping broken ones
        for i in range(start_page, end_page):
            try:
                page_text = doc.load_page(i).get_text("text")
                text += page_text + " "
            except Exception as e:
                print(f"⚠️ Warning: Skipping Page {i} due to PDF error: {e}")
                continue # Skip bad page, keep going
                
        doc.close()
        
        # If we got NO text, the whole file might be unreadable
        if not text.strip():
            return "Error: This PDF contains no readable text (it might be an image scan).", end_page, False, total_pages
            
        return text, end_page, (end_page >= total_pages), total_pages
    except Exception as e:
        print(f"❌ CRITICAL PDF ERROR: {e}")
        return "", start_page, False, 0

class ChapterMate:
    def __init__(self, root):
        self.root = root
        self.root.title("ChapterMate AI - Offline Intelligence")
        self.root.geometry("1000x850")
        self.root.configure(bg=THEME["bg_main"])
        
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Horizontal.TProgressbar", background=THEME["fg_progress"], troughcolor=THEME["bg_card"], borderwidth=0)
        
        self.state = load_library_state()
        self.today = str(datetime.date.today())
        self.is_processing = False 
        self.setup_ui()

    def setup_ui(self):
        # Header
        header = tk.Frame(self.root, bg=THEME["bg_main"])
        header.pack(fill=tk.X, padx=40, pady=(20, 10))
        self.lbl_book = tk.Label(header, text="ChapterMate AI", font=THEME["font_header"], bg=THEME["bg_main"], fg="white", anchor="w")
        self.lbl_book.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Progress
        self.progress_var = tk.DoubleVar()
        self.pbar = ttk.Progressbar(self.root, style="Horizontal.TProgressbar", variable=self.progress_var, maximum=100)
        self.pbar.pack(fill=tk.X, padx=40, pady=(0, 15))

        # Main Text Area
        self.txt_summary = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=THEME["font_body"], bg=THEME["bg_text_area"], fg=THEME["fg_text"], insertbackground="white", relief="flat", padx=40, pady=20)
        self.txt_summary.pack(fill=tk.BOTH, expand=True, padx=20)
        self.txt_summary.tag_configure("h1", font=("Segoe UI", 14, "bold"), foreground=THEME["fg_accent"], spacing3=10)

        # Buttons
        btn_box = tk.Frame(self.root, bg=THEME["bg_main"], pady=20)
        btn_box.pack(fill=tk.X)
        
        def make_btn(text, cmd, color):
            tk.Button(btn_box, text=text, command=cmd, bg=color, font=THEME["font_ui"], relief="flat", padx=15, pady=8).pack(side=tk.LEFT, padx=10)

        make_btn("📚 LIBRARY", self.open_library, "#E0E0E0")
        make_btn("📂 NEW BOOK", self.upload_book, "#A0A0A0")
        make_btn("📖 NEXT CHUNK", self.go_next, THEME["fg_progress"])
        make_btn("🔥 RESET", self.factory_reset, THEME["fg_warn"])
        
        self.load_daily_content()

    # --- THE AI ENGINE ---
    def load_daily_content(self):
        if self.is_processing: return
        
        self.txt_summary.config(state=tk.NORMAL)
        self.txt_summary.delete(1.0, tk.END)
        
        if not self.state["active_book"]:
            self.txt_summary.insert(tk.END, "\n\nWelcome to ChapterMate AI.\nPlease load a book to begin.")
            self.txt_summary.config(state=tk.DISABLED)
            return

        path = self.state["active_book"]
        entry = self.state["library"][path]
        self.lbl_book.config(text=f"Reading: {entry['title']}")
        
        # Get raw text
        raw_text, _, _, total = get_pdf_text(path, entry["page"], DEFAULT_PAGES)
        
        if "Error:" in raw_text:
            self.txt_summary.insert(tk.END, f"\n{raw_text}\n\nTry a different PDF file.")
            self.txt_summary.config(state=tk.DISABLED)
            return

        # Update Progress Bar
        self.progress_var.set((entry["page"] / total) * 100)

        # Start AI in a separate thread
        self.is_processing = True
        self.txt_summary.insert(tk.END, "🧠 AI is reading and analyzing your chapters...\n\n(This may take 10-20 seconds depending on your computer speed)")
        threading.Thread(target=self.run_ai_analysis, args=(raw_text,)).start()

    def run_ai_analysis(self, text):
        try:
            prompt =f"Summarize the following book text into 5 clear bullet points and a 'Practical Application' section:\n\n{text[:8000]}"
            
            response = ollama.chat(model=AI_MODEL, messages=[{'role': 'user', 'content': prompt}])
            ai_reply = response['message']['content']
            
            self.root.after(0, self.update_ui_with_summary, ai_reply)
            
        except Exception as e:
            self.root.after(0, self.update_ui_with_summary, f"Error: Ensure Ollama is running.\n\nDetails: {e}")

    def update_ui_with_summary(self, text):
        self.txt_summary.delete(1.0, tk.END)
        self.txt_summary.insert(tk.END, f"AI SUMMARY: {self.today}\n\n", "h1")
        self.txt_summary.insert(tk.END, text)
        self.txt_summary.config(state=tk.DISABLED)
        self.is_processing = False

    # --- STANDARD FUNCTIONS ---
    def open_library(self):
        lib_win = tk.Toplevel(self.root)
        lib_win.title("Library")
        lib_win.geometry("400x400")
        for path, data in self.state["library"].items():
            tk.Button(lib_win, text=data['title'], command=lambda p=path: self.resume_book(p, lib_win)).pack(fill=tk.X)

    def resume_book(self, path, win):
        self.state["active_book"] = path
        save_library_state(self.state)
        win.destroy()
        self.load_daily_content()

    def upload_book(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if path:
            start = simpledialog.askinteger("Start", "Start Page:", minvalue=0) or 0
            doc = fitz.open(path)
            self.state["active_book"] = path
            self.state["library"][path] = {"title": os.path.basename(path), "page": start}
            save_library_state(self.state)
            self.load_daily_content()

    def go_next(self):
        if self.state["active_book"] and not self.is_processing:
            path = self.state["active_book"]
            self.state["library"][path]["page"] += DEFAULT_PAGES
            save_library_state(self.state)
            self.load_daily_content()

    def factory_reset(self):
        if messagebox.askyesno("Reset", "Clear all data?"):
            if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
            self.state = {"active_book": None, "library": {}}
            self.load_daily_content()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChapterMate(root)
    root.mainloop()