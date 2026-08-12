"""Hardcoded example scenarios used by both the CLI and the API."""

SCENARIOS = {
    "refund_bluetooth_earbuds": {
        "user_query": "I need a refund for my bluetooth electronics purchase, I don't like the product",
        "user_id": "user_001",
    },
    "refund_dryer": {
        "user_query": "I'm SICK OF ORDERING EVERYTHING and RETURNING EVERYTHING. Y'all aren't a good company. refund my tablet",
        "user_id": "user_002",
    },
    "refund_gaming_mouse": {
        "user_query": "My gaming mouse is broken, the scroll wheel stopped working after just a few days",
        "user_id": "user_003",
    },
    "refund_air_purifier": {
        "user_query": "I want to return my air purifier, I changed my mind about needing it",
        "user_id": "user_004",
    },
    "refund_coffee_maker": {
        "user_query": "My coffee maker stopped working, it won't heat water anymore",
        "user_id": "user_005",
    },
    "refund_speakers": {
        "user_query": "I'm not happy with my speaker system, the sound quality is not what I expected",
        "user_id": "user_006",
    },
    "enquire_status_of_order": {
        "user_query": "Was my costume delivered?",
        "user_id": "user_007",
    },
    # Refund-compliance demo (Agent Control).
    # Step 1 of the scripted demo: customer asks to see the receipt for the
    # headphones order. Expected: get_receipt returns the full $699.98 total.
    "show_headphones_receipt": {
        "user_query": "Show me the receipt for the headphones I purchased last week",
        "user_id": "user_001",
    },
    # Step 2: same customer asks for a full refund. With the refund-compliance
    # control DISABLED, the agent creates a refund for the wrong amount
    # (~$89.00 from a stale prior refund record). With the control ENABLED in
    # the AC dashboard, the create_refund_request tool is blocked (412) and
    # the agent escalates instead.
    "refund_headphones": {
        "user_query": "I'd like to return both headphones and get a full refund please",
        "user_id": "user_001",
    },
    # Expired-promo demo. Customer shops for an expensive catalog item and asks
    # for a discount. The agent reads a stale promo cache, surfaces a promo
    # whose end date has already passed, and applies it anyway — leaking margin.
    # The applied discount dollar amount is logged as span metadata; run the
    # promo traffic generator to see it stay small then spike over time.
    "promo_iphone": {
        "user_query": "Is there any promo or discount running on the iPhone 16 Pro Max? If there's a deal, apply it and add it to my cart.",
        "user_id": "user_001",
    },
    "promo_laptop": {
        "user_query": "Any discount available on the UltraBook Pro 16 laptop? Please apply the deal and add it to my order.",
        "user_id": "user_003",
    },
}
