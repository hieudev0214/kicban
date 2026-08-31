"""Tiered pricing by media duration, replacing a single flat price per job.

Whisper actually costs about $0.006 per minute of audio (~150 VND at typical
exchange rates) regardless of how long the video is. Charging one flat price
for every job either overcharges short clips or - worse - loses money on
long ones (a 2-hour video costs ~18,000 VND to transcribe but a flat 5,000
VND charge would only recover a fraction of that). Each tier below prices in
its worst case (the video is exactly as long as the tier's upper bound) at
well under a third of the sale price, so no tier can lose money.
"""

# (upper_bound_seconds, price_vnd) - a duration is priced by the first tier
# whose upper bound it reaches. The last tier's bound matches
# MAX_DURATION_SECONDS in config.py; a longer video is rejected before it
# ever reaches pricing.
TIERS: list[tuple[int, int]] = [
    (2 * 60, 2_000),
    (5 * 60, 4_000),
    (8 * 60, 6_000),
    (15 * 60, 10_000),
    (30 * 60, 18_000),
    (60 * 60, 28_000),
    (120 * 60, 50_000),
]

# The first transcription job on a new account is free, to let people try
# the product with no wallet top-up. Capped to short videos only so this
# can't be abused to get a long (and therefore costly to us) job for free.
FREE_TRIAL_MAX_SECONDS = 10 * 60


def price_for_duration_seconds(duration: float | None) -> int:
    """Price for a media of the given duration. `duration=None` (unknown at
    charge time - e.g. a yt-dlp metadata probe failed for a URL job) is
    priced at the highest tier: charging a safe upper bound up front and
    refunding the difference once the real duration is known (see jobs.py's
    price reconciliation) is simpler and safer than trying to charge more
    mid-job if a low estimate turns out to be wrong."""
    if duration is None:
        return TIERS[-1][1]
    for upper_bound, price in TIERS:
        if duration <= upper_bound:
            return price
    return TIERS[-1][1]


def is_free_trial_eligible(duration: float | None) -> bool:
    return duration is not None and duration <= FREE_TRIAL_MAX_SECONDS


def tier_display() -> list[tuple[str, int]]:
    """Human-readable (label, price_vnd) pairs for showing the tier table in
    the UI, e.g. [("≤ 2 phút", 3000), ("2–5 phút", 6000), ...]."""
    display = []
    prev_minutes = 0
    for upper_seconds, price in TIERS:
        minutes = upper_seconds // 60
        label = f"≤ {minutes} phút" if prev_minutes == 0 else f"{prev_minutes}–{minutes} phút"
        display.append((label, price))
        prev_minutes = minutes
    return display
