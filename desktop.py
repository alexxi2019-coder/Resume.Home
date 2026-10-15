"""Standalone Windows launcher and isolated document worker."""
import sys

if '--resume-worker' in sys.argv:
    import json
    from resume_parser import extract_preview
    try:
        print(json.dumps(extract_preview(json.load(sys.stdin))))
    except Exception:
        print(json.dumps({'error': 'Document extraction failed. Try a plain DOCX or paste text.'}))
    raise SystemExit

import os
import sqlite3
import threading
import webview
from pathlib import Path
from http.server import ThreadingHTTPServer
from app import Store, make_handler

def main():
    if getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Resume.Home'
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / 'resume.sqlite3'
    # An optional personal database beside the launcher is imported only once.
    seed = Path(sys.executable).parent / 'library.sqlite3'
    if not database.exists() and seed.exists():
        with sqlite3.connect(seed) as source, sqlite3.connect(database) as target:
            source.backup(target)
    store = Store(database)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(store))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    class DesktopAPI:
        def save_pdf(self, data):
            import re
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(data.get('application_name','Application'))).rstrip('. ') or 'Application'
            pdf = store.export_pdf(data)
            path = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name+'.pdf', file_types=('PDF files (*.pdf)',))
            if not path:
                return {'saved': False}
            if isinstance(path, (tuple, list)):
                path = path[0]
            Path(path).write_bytes(pdf)
            return {'saved': True}
    window = webview.create_window('Resume.Home', 'http://127.0.0.1:'+str(server.server_port)+'/#library', js_api=DesktopAPI(), width=1280, height=900, min_size=(850,600))
    webview.settings['ALLOW_DOWNLOADS'] = True
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(folder/'webview'))
    finally:
        server.shutdown()
        server.server_close()

if __name__ == '__main__':
    main()
