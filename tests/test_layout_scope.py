"""Check optional layout selectors without a private homepage fixture."""
from pathlib import Path
import re
import unittest


class LayoutScopeTests(unittest.TestCase):
    def test_layout_rules_stay_inside_opt_in_wrapper(self):
        css = (Path(__file__).resolve().parents[1] / 'pinuke/static/pip-zone.css').read_text()
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        for selector in re.findall(r'([^{}]+)\{', css):
            if not selector.strip().startswith('@container'):
                self.assertTrue(selector.strip().startswith('[data-pinuke-zone]'), selector)
        self.assertNotIn('#pip-fullscreen', css)
        self.assertNotIn('.pip-artwork', css)
