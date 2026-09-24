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


class HeaderMode(unittest.TestCase):
    BANNER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300"><title>t</title>'
              '<!--WEATHER--><!--/WEATHER--><circle r="4" fill="#E8603C"/></svg>')

    def paint(self, tmp, banner=BANNER, **kw):
        header = tmp / "header.svg"
        header.write_text(banner)
        argv = ["--out-dir", str(tmp), "--state", str(tmp / "state"), "--header", str(header), "--skip-sky",
                "--weather", kw.get("weather", "rain"), "--season", kw.get("season", "autumn")]
        run(argv)
        return header.read_text(), (tmp / "header-night.svg").read_text()

    def test_weather_is_painted_between_the_markers(self):
        with tempfile.TemporaryDirectory() as d:
            day, night = self.paint(Path(d))
            self.assertIn("<!--WEATHER rain-autumn day-->", day)
            self.assertIn("<!--WEATHER rain-autumn night-->", night)
            self.assertIn("wx-fade", day)  # rain drops are masked
            for svg in (day, night):
                ET.fromstring(svg)
                self.assertIn('<circle r="4"', svg)  # the rest of the banner survives

    def test_night_maps_the_palette(self):
        with tempfile.TemporaryDirectory() as d:
            day, night = self.paint(Path(d))
            self.assertIn("#E8603C", day)
            self.assertIn(g.NIGHT_MAP["#E8603C"], night)
            self.assertIn("nightmoon", self.paint(Path(d), weather="clear")[1])

    def test_repaint_replaces_rather_than_appends(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            day, _ = self.paint(tmp)
            day2, _ = self.paint(tmp, banner=day, weather="snow")
            self.assertEqual(day2.count("<!--WEATHER"), 1)
            self.assertIn("<!--WEATHER snow-autumn day-->", day2)
            self.assertNotIn("wx-fade", day2)

    def test_stale_header_is_repainted_even_when_state_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "state").write_text("rain-autumn\n")  # scene already recorded...
            day, _ = self.paint(tmp)                      # ...but the banner has empty markers
            self.assertIn("<!--WEATHER rain-autumn day-->", day)

    def test_other_canvas_sizes_are_scaled(self):
        banner = self.BANNER.replace('viewBox="0 0 900 300"', 'viewBox="0 0 1800 300"')
        with tempfile.TemporaryDirectory() as d:
            day, _ = self.paint(Path(d), banner=banner)
            self.assertIn('scale(2.0000,1.0000)', day)

    def test_banner_without_markers_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                self.paint(Path(d), banner='<svg xmlns="http://www.w3.org/2000/svg"/>')

    def test_skip_sky_writes_no_strip(self):
        with tempfile.TemporaryDirectory() as d:
            self.paint(Path(d))
            self.assertFalse((Path(d) / "sky.svg").exists())
            self.assertTrue((Path(d) / "garden-footer.svg").exists())


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
                self.assertEqual(g.fetch_weather(0, 0)[0], expected)

    def test_unreachable_api_falls_back_to_last_scene(self):
        args = g.parse_args([])
        with mock.patch.object(g.urllib.request, "urlopen",
                               side_effect=OSError("connection refused")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(g.resolve_weather(args, "snow-winter"), ("snow", None))
                self.assertEqual(g.resolve_weather(args, ""), ("clear", None))


class RainIntensity(unittest.TestCase):
    def test_wmo_intensity(self):
        for code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            with self.subTest(code=code), mock.patch.object(
                g.urllib.request, "urlopen", return_value=FakeResponse(code)
            ):
                self.assertEqual(g.fetch_weather(0, 0),
                                 ("rain", "light" if code <= 61 else "heavy"))

    def test_drops_are_fewer_and_thinner_in_both_themes(self):
        ns = {"s": "http://www.w3.org/2000/svg"}
        for generate in (lambda intensity: g.gen_sky("rain", "summer", intensity),
                         lambda intensity: g.paint_header(HeaderMode.BANNER, "rain", "summer", intensity)):
            light, heavy = generate("light"), generate("heavy")
            self.assertEqual(light, generate("light"))
            self.assertEqual(heavy, generate("heavy"))
            for a, b in zip(light, heavy):
                def drops(svg):
                    return [float(e.attrib["stroke-width"]) for e in ET.fromstring(svg).findall(".//s:line", ns)
                            if "stroke-width" in e.attrib]
                small, large = drops(a), drops(b)
                self.assertLess(len(small), len(large))
                self.assertLess(max(small), max(large))

    def test_intensity_changes_repaint_without_changing_public_state(self):
        for header_mode in (False, True):
            with self.subTest(header=header_mode), tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                argv = ["--season", "summer", "--out-dir", d, "--state", str(tmp / "state")]
                target = tmp / "sky.svg"
                if header_mode:
                    target = tmp / "header.svg"
                    target.write_text(HeaderMode.BANNER)
                    argv += ["--header", str(target), "--skip-sky"]
                for code, intensity in ((51, "light"), (65, "heavy"), (51, "light")):
                    with mock.patch.object(g.urllib.request, "urlopen", return_value=FakeResponse(code)):
                        run(argv)
                    self.assertIn(f"<!--RAIN {intensity}-->", target.read_text())
                    self.assertEqual((tmp / "state").read_text(), "rain-summer\n")
                    before = target.stat().st_mtime_ns
                    with mock.patch.object(g.urllib.request, "urlopen", return_value=FakeResponse(code)):
                        run(argv)
                    self.assertEqual(target.stat().st_mtime_ns, before)
                # Failed lookup retains drizzle instead of silently switching to heavy rain.
                with mock.patch.object(g.urllib.request, "urlopen", side_effect=OSError("offline")):
                    run(argv)
                self.assertEqual(target.stat().st_mtime_ns, before)
                run(argv + ["--weather", "rain"])
                self.assertIn("<!--RAIN heavy-->", target.read_text())


class FakeResponse(io.BytesIO):
    def __init__(self, code):
        super().__init__(f'{{"current":{{"weather_code":{code}}}}}'.encode())


if __name__ == "__main__":
    unittest.main()
