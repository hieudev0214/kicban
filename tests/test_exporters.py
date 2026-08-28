from app.exporters import to_srt, to_txt
from app.transcribe import Segment


def test_to_txt_strips_and_appends_newline():
    assert to_txt("  hello world  ") == "hello world\n"


def test_to_srt_formats_timestamps_and_index():
    segments = [
        Segment(start=0.0, end=1.5, text="Hello"),
        Segment(start=1.5, end=63.25, text="world"),
    ]
    srt = to_srt(segments)
    expected = (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "Hello\n"
        "\n"
        "2\n"
        "00:00:01,500 --> 00:01:03,250\n"
        "world\n"
        ""
    )
    assert srt == expected


def test_to_srt_empty_segments():
    assert to_srt([]) == ""
