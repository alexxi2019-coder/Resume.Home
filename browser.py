"""Open Resume.Home in the default browser using the desktop library."""

import os
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import Store, make_handler


def main():
    data_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Resume.Home'
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / 'resume.sqlite3')
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(store))
    url = f'http://127.0.0.1:{server.server_port}/#library'
    print(f'Resume.Home is running at {url}', flush=True)
    print('Keep this window open while using the site. Press Ctrl+C to stop.', flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
