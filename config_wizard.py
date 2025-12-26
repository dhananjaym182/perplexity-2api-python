import json
import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


class ConfigWizard:
    def __init__(self, root):
        self.root = root
        self.root.title("Perplexity-2API Smart Config Wizard v4.0 (All-in-One)")
        self.root.geometry("800x650")

        # Style settings
        style = ttk.Style()
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TLabel", font=("Segoe UI", 10))

        # --- Header area ---
        header_frame = ttk.Frame(root, padding="20 20 10 10")
        header_frame.pack(fill=tk.X)
        ttk.Label(header_frame, text="🔧 Perplexity-2API Config Console", style="Header.TLabel").pack(anchor=tk.W)

        # --- Info area ---
        info_frame = ttk.LabelFrame(root, text="ℹ️ Supported Data Formats", padding="15")
        info_frame.pack(fill=tk.X, padx=20, pady=5)

        info_text = (
            "This tool can extract credentials from any of the following formats:\n"
            "1. HAR file (JSON)\n"
            "2. PowerShell script (Invoke-WebRequest)\n"
            "3. cURL command\n"
            "4. Any text snippet that contains Cookie"
        )
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT).pack(anchor=tk.W)

        # --- Tabs area ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Tab 1: Paste text (recommended)
        self.tab_paste = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_paste, text="📋 Paste Any Content (Recommended)")
        self.setup_paste_tab()

        # Tab 2: Import file
        self.tab_file = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_file, text="📂 Import HAR File")
        self.setup_file_tab()

        # --- Bottom status area ---
        self.status_frame = ttk.Frame(root, padding="20")
        self.status_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(self.status_frame, text="Ready", foreground="#888")
        self.status_label.pack(side=tk.LEFT)

        self.write_btn = ttk.Button(self.status_frame, text="Write config to .env", command=self.write_to_env, state=tk.DISABLED)
        self.write_btn.pack(side=tk.RIGHT)

        # Data storage
        self.extracted_cookie = None
        self.extracted_ua = None

        # .env path
        self.env_path = ".env"

    def setup_file_tab(self):
        frame = ttk.Frame(self.tab_file)
        frame.pack(fill=tk.X, pady=10)

        ttk.Label(frame, text="Select HAR file:").pack(side=tk.LEFT, padx=(0, 10))
        self.har_path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.har_path_var, width=50).pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        ttk.Button(frame, text="Browse...", command=self.browse_har).pack(side=tk.LEFT)

    def setup_paste_tab(self):
        ttk.Label(self.tab_paste, text="Paste content here (Ctrl+V):").pack(anchor=tk.W, pady=(0, 5))
        self.paste_text = scrolledtext.ScrolledText(self.tab_paste, height=10, font=("Consolas", 9))
        self.paste_text.pack(fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(self.tab_paste)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Smart Parse", command=self.parse_paste_content).pack(side=tk.RIGHT)

    def browse_har(self):
        filename = filedialog.askopenfilename(title="Select HAR file", filetypes=[("HTTP Archive", "*.har"), ("All Files", "*.*")])
        if filename:
            self.har_path_var.set(filename)
            try:
                with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()  # Read as text directly
                self.process_text_content(content)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read file: {str(e)}")

    def parse_paste_content(self):
        content = self.paste_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Notice", "Please paste some content first")
            return
        self.process_text_content(content)

    def process_text_content(self, content: str):
        """
        All-in-one parsing logic: try JSON parsing first, then fall back to regex extraction
        """
        self.status_label.config(text="Analyzing...", foreground="blue")
        self.root.update()

        cookie = None
        ua = None

        # 1. Try to parse as JSON (HAR format)
        try:
            data = json.loads(content)
            cookie, ua = self.extract_from_json(data)
        except Exception:
            pass  # Not JSON, continue with other methods

        # 2. If JSON did not yield anything, try PowerShell format
        if not cookie:
            cookie, ua = self.extract_from_powershell(content)

        # 3. If still nothing, try generic regex (key=value format)
        if not cookie:
            cookie = self.extract_from_regex(content)

        # 4. Extract UA (if still missing)
        if not ua:
            ua = self.extract_ua_regex(content)

        # 5. Result handling
        if cookie:
            # Clean up
            cookie = cookie.strip().strip('"').strip("'")
            ua = (ua or "").strip().strip('"').strip("'")

            self.extracted_cookie = cookie
            self.extracted_ua = ua

            preview = cookie[:40] + "..." + cookie[-40:] if len(cookie) > 80 else cookie
            self.status_label.config(text=f"✅ Extraction successful! (length: {len(cookie)})", foreground="green")

            msg = (
                f"Credentials extracted successfully!\n\n"
                f"User-Agent: {ua[:30]}...\n"
                f"Cookie: {preview}\n\n"
                f"Click [Write Config] to save."
            )
            messagebox.showinfo("Parse Successful", msg)
            self.write_btn.config(state=tk.NORMAL)
        else:
            self.status_label.config(text="❌ Failed to detect valid credentials", foreground="red")
            messagebox.showerror(
                "Parse Failed",
                "Could not extract a valid Perplexity Cookie from the text.\n"
                "Please make sure the content contains 'pplx.visitor-id' or 'session-token'."
            )

    def extract_from_json(self, data):
        """Recursively traverse JSON to find Cookie"""
        candidates = []
        ua_candidates = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key_lower = str(k).lower()
                    if isinstance(v, str):
                        if 'cookie' in key_lower and 'pplx.visitor-id' in v:
                            candidates.append(v)
                        if 'user-agent' in key_lower:
                            ua_candidates.append(v)
                    elif isinstance(v, (dict, list)):
                        walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)

        # Choose best Cookie
        best_cookie = ""
        for c in candidates:
            if len(c) > len(best_cookie):
                best_cookie = c

        ua = ua_candidates[0] if ua_candidates else None
        return best_cookie or None, ua

    def extract_from_powershell(self, text):
        """Extract Cookie from PowerShell script"""
        # Match $session.Cookies.Add((New-Object System.Net.Cookie("KEY", "VALUE", ...))
        pattern = r'New-Object System\.Net\.Cookie\("([^"]+)",\s*"([^"]+)"'
        matches = re.findall(pattern, text)
        if not matches:
            return None, None

        cookie_parts = []
        for key, value in matches:
            cookie_parts.append(f"{key}={value}")
        cookie = "; ".join(cookie_parts)

        ua = self.extract_ua_regex(text)
        return cookie, ua

    def extract_from_regex(self, text):
        """Generic regex extraction"""
        # Try to match the entire Cookie string (usually in cURL or raw header)
        # Look for a long string that contains pplx.visitor-id
        lines = text.splitlines()
        for line in lines:
            if "pplx.visitor-id" in line and "=" in line:
                # Try to extract key=value; key=value format
                # Simple heuristic: if the line has a Cookie: prefix, strip it
                if "Cookie:" in line:
                    return line.split("Cookie:", 1)[1].strip()
                # Otherwise, if the line looks like a cookie string
                if ";" in line and "=" in line:
                    return line.strip()
        return None

    def extract_ua_regex(self, text):
        """Extract User-Agent"""
        # Match User-Agent: ...
        match = re.search(r'User-Agent["\']?\s*[:=]\s*["\']?([^"\']+)["\']?', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Match PowerShell $session.UserAgent = "..."
        match = re.search(r'\$session\.UserAgent\s*=\s*"([^"]+)"', text)
        if match:
            return match.group(1).strip()
        return None

    def write_to_env(self):
        if not self.extracted_cookie:
            messagebox.showwarning("Notice", "No Cookie has been extracted yet")
            return

        cookie = self.extracted_cookie
        ua = self.extracted_ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.147 Safari/537.36"

        try:
            if os.path.exists(self.env_path):
                with open(self.env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            else:
                lines = []

            new_lines = []
            has_cookie = False
            has_ua = False

            for line in lines:
                if line.startswith("PPLX_COOKIE="):
                    new_lines.append(f'PPLX_COOKIE="{cookie}"\n')
                    has_cookie = True
                elif line.startswith("PPLX_USER_AGENT="):
                    new_lines.append(f'PPLX_USER_AGENT="{ua}"\n')
                    has_ua = True
                else:
                    new_lines.append(line)

            if not has_cookie:
                new_lines.append(f'PPLX_COOKIE="{cookie}"\n')
            if not has_ua:
                new_lines.append(f'PPLX_USER_AGENT="{ua}"\n')

            with open(self.env_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            messagebox.showinfo("Write Successful", "✅ Config has been updated!\n\nPlease run the following command to restart the service:\n\ndocker-compose restart app")
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("Write Failed", f"Unable to write .env file: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ConfigWizard(root)
    root.mainloop()
