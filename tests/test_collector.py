import hashlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.collector import choose_srcset, collect, same_site, slugify
from app.import_social_media import import_media
from PIL import Image


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class CollectorTests(unittest.TestCase):
    def test_utilities(self) -> None:
        self.assertEqual(choose_srcset("photo-300.jpg 300w, photo-900.jpg 900w"), "photo-900.jpg")
        self.assertTrue(same_site("https://www.example.com", "https://example.com/path"))
        self.assertEqual(slugify("Hello Dog & Cat!"), "hello-dog-cat")

    def test_website_collection_and_social_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = root / "public"
            web.mkdir()
            pic = Image.new("RGB", (320, 240), (220, 110, 105))
            mem = io.BytesIO()
            pic.save(mem, format="PNG")
            (web / "logo.png").write_bytes(mem.getvalue())
            (web / "photo.png").write_bytes(mem.getvalue())  # identical bytes -> de-dupe
            (web / "gallery.png").write_bytes(mem.getvalue())
            (web / "index.html").write_text(
                "<html><head><title>Pup Salon</title>"
                '<meta name="description" content="Grooming"></head>\n'
                "<body><h1>Welcome to Pup Salon</h1><p>Hand scissoring, trim and bath</p>\n"
                '<img src="/logo.png" alt="Pup Salon official logo"/>\n'
                '<img srcset="/photo.png 300w, /gallery.png 900w" alt="Groomed dog"/>\n'
                '<a href="/photo-gallery">Photo Gallery</a>\n'
                '<a href="https://www.instagram.com/pupsalon/">Instagram</a>\n'
                '<a href="https://www.facebook.com/pupsalon/">Facebook</a></body></html>',
                encoding="utf-8",
            )
            (web / "photo-gallery").mkdir()
            (web / "photo-gallery" / "index.html").write_text(
                '<html><body><h1>Photo Gallery</h1><img src="/gallery.png"/></body></html>',
                encoding="utf-8",
            )
            (web / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")

            class Handler(QuietHandler):
                def __init__(self, *args: object, **kwargs: object) -> None:
                    super().__init__(*args, directory=str(web), **kwargs)  # type: ignore[arg-type]

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                output = root / "projects"
                result = collect(
                    f"http://127.0.0.1:{port}/",
                    output,
                    max_pages=4,
                    allow_private=True,
                )
                self.assertEqual(result["pages_crawled"], 2)
                self.assertEqual(result["assets_saved"], 1)
                self.assertGreaterEqual(result["asset_duplicates"], 1)
                folder = Path(str(result["project_folder"]))
                pages = json.loads((folder / "research/pages.json").read_text(encoding="utf-8"))
                self.assertIn("Hand scissoring", pages[0]["text"])
                for page in pages:
                    self.assertIn("url", page)
                    self.assertIn("sha256", page)
                    self.assertIn("fetched_at", page)
                    self.assertEqual(page["status_code"], 200)
                    snap = folder / "research" / "snapshots" / f"{page['sha256']}.html"
                    self.assertTrue(snap.is_file())
                    self.assertEqual(
                        hashlib.sha256(snap.read_bytes()).hexdigest(),
                        page["sha256"],
                    )
                assets = json.loads(
                    (folder / "research/asset-manifest.json").read_text(encoding="utf-8")
                )
                self.assertGreaterEqual(len(assets), 2)
                for row in assets:
                    self.assertIn("captured_at", row)
                    parsed_dt = datetime.fromisoformat(row["captured_at"])
                    self.assertIsNotNone(parsed_dt.tzinfo)
                    self.assertIs(row["rights_confirmed_for_preview"], False)
                social = json.loads(
                    (folder / "research/social-sources.json").read_text(encoding="utf-8")
                )
                self.assertTrue(social["instagram"])
                self.assertTrue(social["facebook"])
                imported = import_media(
                    folder,
                    "instagram",
                    "https://instagram.com/p/TEST/",
                    [web / "photo.png"],
                )
                self.assertEqual(len(imported), 1)
                self.assertTrue((folder / str(imported[0]["file"])).exists())
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()

