import base64
import hashlib
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from scripts import generate_brand_icons


@unittest.skipUnless(shutil.which("rsvg-convert"), "requires librsvg")
class BrandIconExportsTests(unittest.TestCase):
    def test_exports_preserve_the_circle_and_fill_the_square_corners(self):
        source = generate_brand_icons.SOURCE
        original = source.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with Image.open(source) as image:
                width = image.width
            generate_brand_icons.generate(source, output, size=width)

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((output / "pod-god-circle.png").read_bytes(), original)
            text = (output / "pod-god-circle.svg").read_text()
            self.assertIn(digest, text)
            root = ET.fromstring(text)
            embedded = root.find("{http://www.w3.org/2000/svg}image")
            self.assertEqual(base64.b64decode(embedded.attrib["href"].split(",", 1)[1]), original)

            with Image.open(source) as image:
                circle = image.convert("RGBA")
            with Image.open(output / "pod-god-square.png") as image:
                self.assertEqual(image.mode, "RGBA")
                square = image.convert("RGBA")
            self.assertEqual(square.size, circle.size)
            self.assertEqual(square.getchannel("A").getextrema(), (255, 255))
            for point in ((0, 0), (width - 1, 0), (0, width - 1), (width - 1, width - 1)):
                self.assertLess(min(square.getpixel(point)[:3]), 160)
            # The original white stroke centers retain their positions.
            for y in range(width):
                for x in range(width):
                    red, green, blue, alpha = circle.getpixel((x, y))
                    if alpha == 255 and min(red, green, blue) > 245:
                        self.assertGreater(min(square.getpixel((x, y))[:3]), 240)


if __name__ == "__main__":
    unittest.main()
