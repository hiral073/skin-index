"""Every piece of fixed guidance text on the Today page, with its source.

These texts are quoted from the sources named beside them and are shown with those sources.
They are general information, not the app's own claims. Do not add or reword a tip without
the person who owns the content agreeing to it, and never add a tip without a source (the
four "also worth remembering" reminders are the only unattributed lines, as supplied).
Thresholds that decide which group shows live in database/services.py (TODAY_CONFIG).
"""

AAD = "American Academy of Dermatology"
WHO = "World Health Organization"
JHM = "Johns Hopkins Medicine"

# ---------------------------------------------------------------- "Sun protection today" card

SUN_PROTECTION = {
    "title": "Sun protection today",
    "text": ("Dermatologists recommend broad-spectrum, SPF 30 or higher, water-resistant sunscreen on skin "
             "not covered by clothing, reapplied about every two hours when outdoors and after swimming or sweating."),
    "source": AAD,
}

# Extra steps by UV level (the level is today's peak UV, see TODAY_CONFIG); none at UV 0 to 2
EXTRA_STEPS = {
    "moderate_to_high": {  # UV 3 to 7
        "text": "Seek shade during midday hours, cover up with clothing, wear a hat and use sunscreen.",
        "source": WHO,
    },
    "very_high": {         # UV 8 and above
        "text": ("Avoid being outside during midday hours where possible. "
                 "Seek shade, and wear a shirt, a hat and sunscreen."),
        "source": WHO,
    },
}

# Today's maximum UV below 3 (but 1 or more): this one line is the whole UV card, so the sunscreen
# advice appears once on the page. Below 1 the card says only that UV is very low.
UV_LOW = {
    "text": ("UV is low right now. Dermatologists still recommend daily sunscreen on exposed skin "
             "when you're outdoors."),
    "source": AAD,
}
UV_VERY_LOW = "UV is very low today."

# Timeline sentences (UV 3 or higher only); {ranges} is like "10:00 to 16:00" or "10:00 to 12:00 and 14:00 to 16:00"
TIMELINE = {
    "title": "UV today",
    "reaches": "UV is {level} or higher from {ranges}.",
    "peak": "Peak hour: {span}, UV {uv} (hourly average).",
    "unavailable": "The hourly UV timeline isn't available right now.",
    "no_uv": "The UV index isn't available right now.",
}

REMINDERS = {
    "title": "Also worth remembering",
    "tips": [
        "Sunscreen should not be used to extend the time you spend in the sun.",
        "Shade and clothing protect best.",
        "Reapply sunscreen even on cloudy days.",
        "Bright surfaces such as water and sand reflect UV.",
    ],
}

SUNSCREEN_LINK = {"label": "Browse sunscreens", "note": "Check for SPF and broad-spectrum on the label."}

# ---------------------------------------------------------------- "Skin-care tips" card

TIPS_CARD_TITLE = "Skin-care tips for today's weather"
SOURCES_NOTE = "General information from the sources named. Not medical advice."   # small note at the bottom

# The weather tips card only shows when the weather fits a group; there are no every-day tips.
# The headline names the conditions that triggered the group, never a season
HEADLINES = {
    "cool_dry": "Cool, dry air today",
    "cool": "Cool air today",
    "dry": "Dry air today",
    "hot_humid": "Hot and humid today",
}

COOL_DRY_TIPS = [
    {"text": "Apply moisturizer right after washing to help trap moisture.", "source": AAD},
    {"text": "Creams and ointments are usually more effective and less irritating than lotions for dry skin.",
     "source": AAD},
    {"text": "Use warm, not hot, water for baths and showers.", "source": AAD},
    {"text": "Gentle, fragrance-free skin care products tend to suit dry, sensitive skin.", "source": AAD},
    {"text": "A cool-mist humidifier in the bedroom can help with indoor dryness.", "source": AAD},
]

HOT_HUMID_TIPS = [
    {"text": "Blot sweat with a clean towel; wiping it off can irritate skin and lead to a breakout.", "source": AAD},
    {"text": "Wash sweaty clothes, headbands, towels and hats before wearing them again.", "source": AAD},
    {"text": ("Shower, cool down and dry off when you are hot and sweaty; use a mild cleanser daily "
              "and avoid heavy makeup."), "source": JHM},
    {"text": "Humid air can still leave skin dry and irritated, especially after sun, pools and air-conditioning.",
     "source": AAD},
]

# group -> tips; the links go to the Products page filtered by a compare group (the "category" filter)
TIP_GROUPS = {"cool_dry": COOL_DRY_TIPS, "hot_humid": HOT_HUMID_TIPS}
TIP_LINKS = {
    "cool_dry": [{"label": "Browse moisturizers with 'cream' in the name",
                  "category": "Moisturizers", "q": "cream"}],
    "hot_humid": [{"label": "Browse cleansers", "category": "Face Wash & Cleansers"},
                  {"label": "Browse moisturizers", "category": "Moisturizers"}],
}
