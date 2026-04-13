"""Desktop Pet with HTTP Toast — ~90 lines"""
import tkinter as tk, threading, random, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 51983
GIF = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'pet.gif')

class Pet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes('-topmost', True)
        self.root.wm_attributes('-transparentcolor', '#01FF01')
        self.root.config(bg='#01FF01')
        self.root.after(50, lambda: self.root.geometry('+300+500'))
        # load GIF frames
        self.frames, i = [], 0
        while True:
            try: self.frames.append(tk.PhotoImage(file=GIF, format=f'gif -index {i}')); i += 1
            except: break
        if not self.frames: raise FileNotFoundError(f'No GIF: {GIF}')
        self.idx = 0
        self.label = tk.Label(self.root, image=self.frames[0], bg='#01FF01', bd=0)
        self.label.pack()
        # drag
        self.label.bind('<Button-1>', lambda e: setattr(self, '_d', (e.x, e.y)))
        self.label.bind('<B1-Motion>', self._drag)
        self.label.bind('<Double-1>', lambda e: (self.root.destroy(), os._exit(0)))
        # start loops
        self._animate()
        self._wander()
        self._start_server()
        self.root.mainloop()

    def _drag(self, e):
        x, y = self.root.winfo_x() + e.x - self._d[0], self.root.winfo_y() + e.y - self._d[1]
        self.root.geometry(f'+{x}+{y}')

    def _animate(self):
        self.idx = (self.idx + 1) % len(self.frames)
        self.label.config(image=self.frames[self.idx])
        self.root.after(150, self._animate)

    def _wander(self):
        if random.random() < 0.25:
            x = self.root.winfo_x() + random.randint(-15, 15)
            y = self.root.winfo_y() + random.randint(-5, 5)
            self.root.geometry(f'+{x}+{y}')
        self.root.after(4000, self._wander)

    def show_toast(self, msg):
        """Show a speech bubble near the pet that auto-dismisses."""
        tw = tk.Toplevel(self.root)
        tw.overrideredirect(True)
        tw.wm_attributes('-topmost', True)
        tw.config(bg='#FFFDE7')
        px, py = self.root.winfo_x(), self.root.winfo_y()
        tw.geometry(f'+{px + 30}+{py - 50}')
        # bubble content
        f = tk.Frame(tw, bg='#FFFDE7', highlightbackground='#888', highlightthickness=1, padx=8, pady=4)
        f.pack()
        tk.Label(f, text=msg, bg='#FFFDE7', fg='#333', font=('Segoe UI', 10), wraplength=220, justify='left').pack()
        # auto dismiss
        tw.after(3000, tw.destroy)

    def _start_server(self):
        pet = self
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                qs = parse_qs(urlparse(self.path).query)
                msg = qs.get('msg', [''])[0]
                if msg:
                    pet.root.after(0, pet.show_toast, msg)
                    self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
                else:
                    self.send_response(400); self.end_headers(); self.wfile.write(b'?msg=xxx')
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
                if body:
                    pet.root.after(0, pet.show_toast, body)
                    self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
                else:
                    self.send_response(400); self.end_headers(); self.wfile.write(b'empty body')
            def log_message(self, *a): pass
        HTTPServer.allow_reuse_address = False
        srv = HTTPServer(('127.0.0.1', PORT), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        print(f'Toast server: http://127.0.0.1:{PORT}/?msg=hello')

if __name__ == '__main__':
    Pet()
