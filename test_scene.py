#!/usr/bin/env python3
"""Stdlib-only tests. Run with: python3 -m unittest -v"""
import contextlib
import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import gen_scene as g

OUTPUTS = ("sky.svg", "sky-night.svg", "garden-footer.svg", "garden-footer-night.svg")


def run(argv):
    """Invoke main() with its chatter swallowed, so test output stays readable."""
    with contextlib.redirect_stdout(io.StringIO()):
        g.main(argv)


def render(tmp, **kw):
    argv = ["--out-dir", str(tmp), "--state", str(tmp / "state"), "--force"]
    for k, v in kw.items():
        argv += [f"--{k}", str(v)]
    run(argv)
    return {name: (tmp / name).read_text() for name in OUTPUTS}


class EveryScene(unittest.TestCase):
    def test_all_combinations_render_valid_xml(self):
        for w in g.WEATHERS:
            for s in g.SEASONS:
                with self.subTest(weather=w, season=s), tempfile.TemporaryDirectory() as d:
                    for name, svg in render(Path(d), weather=w, season=s).items():
                        ET.fromstring(svg)  # raises if malformed
                        self.assertTrue(svg.startswith("<svg"), name)

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = render(Path(a), weather="snow", season="winter")
            second = render(Path(b), weather="snow", season="winter")
            self.assertEqual(first, second)

    def test_scenes_actually_differ(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            rain = render(Path(a), weather="rain", season="summer")
            snow = render(Path(b), weather="snow", season="summer")
            self.assertNotEqual(rain["sky.svg"], snow["sky.svg"])

    def test_night_variant_differs_from_day(self):
        with tempfile.TemporaryDirectory() as d:
            out = render(Path(d), weather="clear", season="spring")
            self.assertNotEqual(out["sky.svg"], out["sky-night.svg"])


class StateFile(unittest.TestCase):
    def test_unchanged_scene_leaves_files_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            render(tmp, weather="fog", season="autumn")
            before = (tmp / "sky.svg").stat().st_mtime_ns
            run(["--weather", "fog", "--season", "autumn",
                 "--out-dir", str(tmp), "--state", str(tmp / "state")])
            self.assertEqual(before, (tmp / "sky.svg").stat().st_mtime_ns)

    def test_state_records_the_scene(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            render(tmp, weather="storm", season="winter")
            self.assertEqual((tmp / "state").read_text().strip(), "storm-winter")


class Seasons(unittest.TestCase):
    def test_hemispheres_are_opposite(self):
        for tz in ("America/New_York", "Australia/Sydney", "UTC"):
            with self.subTest(tz=tz):
                north = g.current_season(tz, "north")
                south = g.current_season(tz, "south")
                opposite = {"spring": "autumn", "autumn": "spring",
                            "summer": "winter", "winter": "summer"}
                self.assertEqual(south, opposite[north])


class WeatherCodes(unittest.TestCase):
    def test_wmo_codes_map_to_expected_buckets(self):
        cases = {99: "storm", 95: "storm", 75: "snow", 86: "snow", 61: "rain",
                 82: "rain", 48: "fog", 45: "fog", 2: "clouds", 0: "clear"}
        for code, expected in cases.items():
            with self.subTest(code=code), mock.patch.object(
                g.urllib.request, "urlopen", return_value=FakeResponse(code)
            ):
                self.assertEqual(g.fetch_weather(0, 0), expected)

    def test_unreachable_api_falls_back_to_last_scene(self):
        args = g.parse_args([])
        with mock.patch.object(g.urllib.request, "urlopen",
                               side_effect=OSError("connection refused")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(g.resolve_weather(args, "snow-winter"), "snow")
                self.assertEqual(g.resolve_weather(args, ""), "clear")


class FakeResponse(io.BytesIO):
    def __init__(self, code):
        super().__init__(f'{{"current":{{"weather_code":{code}}}}}'.encode())


if __name__ == "__main__":
    unittest.main()
