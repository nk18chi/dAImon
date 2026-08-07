import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import schedule_fmt  # noqa: E402


class ScheduleFmtTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(schedule_fmt.parse("20m"), {"interval": 1200})
        self.assertEqual(schedule_fmt.parse(":8,38"), {"minutes": [8, 38]})
        self.assertEqual(schedule_fmt.parse("09:02"), {"daily": "09:02"})

    def test_parse_bad(self):
        with self.assertRaises(ValueError):
            schedule_fmt.parse("whenever")

    def test_display_roundtrips(self):
        for text in ("1200s", ":8,38", "09:02"):
            self.assertEqual(schedule_fmt.display(schedule_fmt.parse(text)), text)

    def test_descriptor(self):
        self.assertEqual(schedule_fmt.descriptor({"interval": 1200}), "interval 1200")
        self.assertEqual(schedule_fmt.descriptor({"minutes": [17, 47]}), "minutes 17 47")
        self.assertEqual(
            schedule_fmt.descriptor({"daily": "13:02", "tz": "UTC"}), "daily 13:02 UTC"
        )

    def test_to_plist(self):
        self.assertIn("StartInterval", schedule_fmt.to_plist({"interval": 1200}))
        self.assertIn("StartCalendarInterval", schedule_fmt.to_plist({"minutes": [8]}))
        self.assertIn(
            "<key>Hour</key><integer>13</integer>", schedule_fmt.to_plist({"daily": "13:02"})
        )

    # --- day filtering on the "minutes" shape ---------------------------------

    def test_parse_minutes_with_days(self):
        self.assertEqual(
            schedule_fmt.parse(":11,26,41,56 mon-fri"),
            {"minutes": [11, 26, 41, 56], "days": "mon-fri"},
        )
        # "all" is the absence of a filter, so it is not stored — an unfiltered
        # schedule keeps the exact shape existing configs already have.
        self.assertEqual(schedule_fmt.parse(":8,38"), {"minutes": [8, 38]})

    def test_parse_minutes_bad_day_set(self):
        with self.assertRaises(ValueError):
            schedule_fmt.parse(":8,38 mon-weds")

    def test_display_roundtrips_minutes_with_days(self):
        for text in (":11,26,41,56 mon-fri", ":8,38"):
            self.assertEqual(schedule_fmt.display(schedule_fmt.parse(text)), text)

    def test_descriptor_minutes_with_days(self):
        self.assertEqual(
            schedule_fmt.descriptor({"minutes": [17, 47], "days": "mon-fri"}),
            "minutes 17 47 days mon-fri",
        )
        # Unfiltered stays byte-identical — schedule.sh parses this string.
        self.assertEqual(schedule_fmt.descriptor({"minutes": [17, 47]}), "minutes 17 47")

    def test_to_plist_minutes_weekdays(self):
        xml = schedule_fmt.to_plist({"minutes": [11, 26, 41, 56], "days": "mon-fri"})
        # One dict per (minute, weekday): 4 minutes x 5 weekdays.
        self.assertEqual(xml.count("<dict>"), 20)
        self.assertEqual(xml.count("<key>Weekday</key>"), 20)
        self.assertIn("<key>Minute</key><integer>26</integer>", xml)
        for d in range(1, 6):
            self.assertIn(f"<key>Weekday</key><integer>{d}</integer>", xml)
        self.assertNotIn("<integer>0</integer></dict>", xml)  # no Sunday

    def test_to_plist_minutes_defaults_to_all_days(self):
        xml = schedule_fmt.to_plist({"minutes": [8, 38]})
        self.assertEqual(xml.count("<dict>"), 2)
        self.assertNotIn("Weekday", xml)

    # --- the "at" shape: several times a day, optionally weekdays only ---------

    def test_parse_at(self):
        self.assertEqual(
            schedule_fmt.parse("09:00,16:00 mon-fri"),
            {"at": ["09:00", "16:00"], "days": "mon-fri"},
        )
        self.assertEqual(
            schedule_fmt.parse("09:00,16:00"), {"at": ["09:00", "16:00"], "days": "all"}
        )
        # A single time WITH a day filter must not be mistaken for `daily`, which
        # has nowhere to put the filter.
        self.assertEqual(schedule_fmt.parse("09:00 mon-fri"), {"at": ["09:00"], "days": "mon-fri"})

    def test_parse_at_bad_day_set(self):
        with self.assertRaises(ValueError):
            schedule_fmt.parse("09:00,16:00 mon-weds")

    def test_display_roundtrips_at(self):
        for text in ("09:00,16:00 mon-fri", "09:00,16:00"):
            self.assertEqual(schedule_fmt.display(schedule_fmt.parse(text)), text)

    def test_descriptor_at(self):
        self.assertEqual(
            schedule_fmt.descriptor({"at": ["09:00", "16:00"], "days": "mon-fri"}),
            "at 09:00 16:00 days mon-fri",
        )
        self.assertEqual(schedule_fmt.descriptor({"at": ["09:00"]}), "at 09:00 days all")

    def test_to_plist_at_weekdays(self):
        xml = schedule_fmt.to_plist({"at": ["09:00", "16:00"], "days": "mon-fri"})
        # launchd needs one dict per (time, weekday): 2 times x 5 weekdays.
        self.assertEqual(xml.count("<dict>"), 10)
        self.assertEqual(xml.count("<key>Weekday</key>"), 10)
        self.assertIn("<key>Hour</key><integer>9</integer>", xml)
        self.assertIn("<key>Hour</key><integer>16</integer>", xml)
        for d in range(1, 6):
            self.assertIn(f"<key>Weekday</key><integer>{d}</integer>", xml)
        self.assertNotIn("<integer>0</integer></dict>", xml)  # no Sunday

    def test_to_plist_at_all_days_omits_weekday(self):
        xml = schedule_fmt.to_plist({"at": ["09:00", "16:00"], "days": "all"})
        self.assertEqual(xml.count("<dict>"), 2)
        self.assertNotIn("Weekday", xml)

    def test_to_plist_at_defaults_to_all_days(self):
        self.assertNotIn("Weekday", schedule_fmt.to_plist({"at": ["09:00"]}))


if __name__ == "__main__":
    unittest.main()
