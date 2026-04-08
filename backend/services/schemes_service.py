"""
schemes_service.py
──────────────────
Government agricultural scheme lookup service.

Returns applicable national + state-specific schemes for a given
crop and location.  No external API needed — purely rule-based.

Public API
──────────
  get_schemes(crop: str, location: str) -> list[dict]

  Each scheme dict:
    {
      "name":        str,
      "type":        str,    # "Cash Transfer" | "Insurance" | "Subsidy" | "Loan" | "Grant"
      "benefit":     str,
      "eligibility": str,
      "deadline":    str,
      "scope":       str,    # "National" | "State"
      "apply_url":   str,
    }
"""

from __future__ import annotations

# ── National schemes (applicable to every crop + state) ───────────────────────
_NATIONAL: list[dict] = [
    {
        "name":        "PM-KISAN (Pradhan Mantri Kisan Samman Nidhi)",
        "type":        "Cash Transfer",
        "benefit":     "₹6,000/year in 3 equal instalments directly to bank account",
        "eligibility": "Small & marginal farmers with cultivable land; Aadhaar required",
        "deadline":    "Rolling — register any time",
        "scope":       "National",
        "apply_url":   "https://pmkisan.gov.in/",
    },
    {
        "name":        "Pradhan Mantri Fasal Bima Yojana (PMFBY)",
        "type":        "Insurance",
        "benefit":     "Crop loss coverage at 2% premium (Kharif), 1.5% (Rabi)",
        "eligibility": "All farmers growing notified crops; loanee farmers auto-enrolled",
        "deadline":    "Before sowing; check state portal for dates",
        "scope":       "National",
        "apply_url":   "https://pmfby.gov.in/",
    },
    {
        "name":        "Kisan Credit Card (KCC) Scheme",
        "type":        "Loan",
        "benefit":     "Credit up to ₹3 lakh at 7% interest (4% effective with subvention)",
        "eligibility": "Farmers, tenant farmers, sharecroppers and SHGs",
        "deadline":    "Rolling — apply at nearest bank/cooperative",
        "scope":       "National",
        "apply_url":   "https://www.nabard.org/",
    },
    {
        "name":        "Soil Health Card Scheme",
        "type":        "Subsidy",
        "benefit":     "Free soil testing, nutrient report and crop-specific recommendations",
        "eligibility": "All farmers",
        "deadline":    "Rolling",
        "scope":       "National",
        "apply_url":   "https://soilhealth.dac.gov.in/",
    },
    {
        "name":        "Paramparagat Krishi Vikas Yojana (PKVY)",
        "type":        "Grant",
        "benefit":     "₹50,000/ha over 3 years for organic farming cluster",
        "eligibility": "Farmer groups (≥50 farmers, ≥50 ha) converting to organic",
        "deadline":    "Ongoing; apply via state agriculture department",
        "scope":       "National",
        "apply_url":   "https://pgsindia-ncof.gov.in/",
    },
    {
        "name":        "Agricultural Infrastructure Fund (AIF)",
        "type":        "Loan",
        "benefit":     "Loans up to ₹2 crore at 3% interest subvention for post-harvest infra",
        "eligibility": "Individual farmers, FPOs, cooperatives, agri-entrepreneurs",
        "deadline":    "Scheme valid till 2025-26",
        "scope":       "National",
        "apply_url":   "https://agriinfra.dac.gov.in/",
    },
]

# ── Crop-specific national schemes ────────────────────────────────────────────
_CROP_SCHEMES: dict[str, list[dict]] = {
    "rice": [
        {
            "name":        "National Food Security Mission — Rice",
            "type":        "Subsidy",
            "benefit":     "Subsidised HYV seeds, nutrients, IPM inputs & farm machinery",
            "eligibility": "Rice farmers in targeted districts",
            "deadline":    "Before Kharif season",
            "scope":       "National",
            "apply_url":   "https://nfsm.gov.in/",
        },
    ],
    "wheat": [
        {
            "name":        "National Food Security Mission — Wheat",
            "type":        "Subsidy",
            "benefit":     "Subsidised certified seeds and micro-nutrient kits",
            "eligibility": "Wheat farmers in targeted districts",
            "deadline":    "Before Rabi season",
            "scope":       "National",
            "apply_url":   "https://nfsm.gov.in/",
        },
    ],
    "oilseeds": [
        {
            "name":        "National Mission on Edible Oils — Oil Palm",
            "type":        "Subsidy",
            "benefit":     "₹29,000/ha planting material + ₹12,000/ha maintenance for 4 years",
            "eligibility": "Farmers in North-East, Andaman & other states",
            "deadline":    "Check state portal",
            "scope":       "National",
            "apply_url":   "https://nmeo.dac.gov.in/",
        },
    ],
    "cotton": [
        {
            "name":        "Technology Mission on Cotton",
            "type":        "Subsidy",
            "benefit":     "Subsidised Bt cotton seeds and micro-irrigation support",
            "eligibility": "Cotton farmers in 9 major states",
            "deadline":    "Before Kharif",
            "scope":       "National",
            "apply_url":   "https://dac.gov.in/",
        },
    ],
    "coconut": [
        {
            "name":        "Coconut Development Board Scheme",
            "type":        "Subsidy",
            "benefit":     "₹75/seedling subsidy + technology support for coconut farms",
            "eligibility": "Coconut farmers registered with CDB",
            "deadline":    "Rolling",
            "scope":       "National",
            "apply_url":   "https://coconutboard.gov.in/",
        },
    ],
    "arecanut": [
        {
            "name":        "Arecanut Replanting Aid",
            "type":        "Subsidy",
            "benefit":     "₹40/seedling for replanting + disease management support",
            "eligibility": "Registered arecanut farmers",
            "deadline":    "Check state horticulture dept",
            "scope":       "National",
            "apply_url":   "https://nhb.gov.in/",
        },
    ],
    "coffee": [
        {
            "name":        "Coffee Board Development Scheme",
            "type":        "Subsidy",
            "benefit":     "Post-harvest processing subsidies + quality improvement grants",
            "eligibility": "Registered coffee growers",
            "deadline":    "Rolling",
            "scope":       "National",
            "apply_url":   "https://indiacoffee.org/",
        },
    ],
    "pepper": [
        {
            "name":        "Spices Board Development Scheme",
            "type":        "Subsidy",
            "benefit":     "50% subsidy on planting material and quality certification",
            "eligibility": "Pepper farmers registered with Spices Board",
            "deadline":    "Rolling",
            "scope":       "National",
            "apply_url":   "https://indianspices.com/",
        },
    ],
    "turmeric": [
        {
            "name":        "Spices Board — Turmeric Development",
            "type":        "Grant",
            "benefit":     "₹10,000/ha for improved variety cultivation and processing",
            "eligibility": "Spices Board-registered turmeric farmers",
            "deadline":    "Before planting season",
            "scope":       "National",
            "apply_url":   "https://indianspices.com/",
        },
    ],
}

# ── State-specific schemes ─────────────────────────────────────────────────────
_STATE_SCHEMES: dict[str, list[dict]] = {
    "karnataka": [
        {
            "name":        "Raitha Siri (Karnataka)",
            "type":        "Cash Transfer",
            "benefit":     "₹2,000/acre input subsidy for small farmers",
            "eligibility": "Karnataka farmers with <5 acres; registered with Raitha Seva Kendra",
            "deadline":    "Annual — before Kharif",
            "scope":       "State",
            "apply_url":   "https://raitamitra.karnataka.gov.in/",
        },
        {
            "name":        "Krishi Bhagya Scheme (Karnataka)",
            "type":        "Subsidy",
            "benefit":     "90% subsidy on farm pond construction + micro-irrigation set",
            "eligibility": "Dryland farmers in 10 vulnerable districts",
            "deadline":    "Before monsoon; apply at taluk agriculture office",
            "scope":       "State",
            "apply_url":   "https://raitamitra.karnataka.gov.in/",
        },
    ],
    "maharashtra": [
        {
            "name":        "Magel Tyala Shet Tale (Maharashtra)",
            "type":        "Subsidy",
            "benefit":     "50% subsidy on farm pond construction (max ₹50,000)",
            "eligibility": "Farmers in rain-shadow districts of Maharashtra",
            "deadline":    "Before monsoon",
            "scope":       "State",
            "apply_url":   "https://agri.maharashtra.gov.in/",
        },
        {
            "name":        "Nanaji Deshmukh Krishi Sanjivani",
            "type":        "Grant",
            "benefit":     "Climate-resilient agriculture inputs and capacity building",
            "eligibility": "Farmers in 15 drought-prone districts",
            "deadline":    "Ongoing",
            "scope":       "State",
            "apply_url":   "https://agri.maharashtra.gov.in/",
        },
    ],
    "punjab": [
        {
            "name":        "Pani Bachao Paisa Kamao (Punjab)",
            "type":        "Cash Transfer",
            "benefit":     "₹7,000/ha incentive for direct seeded rice & water saving",
            "eligibility": "Punjab farmers who shift from transplanted to direct seeded rice",
            "deadline":    "Before Kharif",
            "scope":       "State",
            "apply_url":   "https://agripb.gov.in/",
        },
    ],
    "haryana": [
        {
            "name":        "Meri Fasal Mera Byora (Haryana)",
            "type":        "Subsidy",
            "benefit":     "MSP support + input subsidy after crop registration",
            "eligibility": "All Haryana farmers registering crops on portal",
            "deadline":    "Before sowing; check portal dates",
            "scope":       "State",
            "apply_url":   "https://fasal.haryana.gov.in/",
        },
    ],
    "madhya-pradesh": [
        {
            "name":        "Mukhyamantri Krishak Udyami Yojana (MP)",
            "type":        "Loan",
            "benefit":     "Loan ₹10L–2Cr at 5% interest for agro-processing businesses",
            "eligibility": "MP farmers' children aged 18-40 for agri-enterprises",
            "deadline":    "Rolling",
            "scope":       "State",
            "apply_url":   "https://mpagri.gov.in/",
        },
    ],
    "kerala": [
        {
            "name":        "Karshaka Sreyas (Kerala)",
            "type":        "Insurance",
            "benefit":     "Comprehensive crop + livestock insurance at subsidised premium",
            "eligibility": "All Kerala farmers registered on eKarshaka portal",
            "deadline":    "Before crop season",
            "scope":       "State",
            "apply_url":   "https://keralaagriculture.gov.in/",
        },
    ],
    "andhra-pradesh": [
        {
            "name":        "YSR Rythu Bharosa (AP)",
            "type":        "Cash Transfer",
            "benefit":     "₹13,500/year — ₹7,500 state + ₹6,000 PM-KISAN",
            "eligibility": "AP farmers with cultivable land",
            "deadline":    "Enrolled automatically if on PM-KISAN",
            "scope":       "State",
            "apply_url":   "https://apagrisnet.gov.in/",
        },
    ],
    "telangana": [
        {
            "name":        "Rythu Bandhu (Telangana)",
            "type":        "Cash Transfer",
            "benefit":     "₹10,000/acre per season for all farmers",
            "eligibility": "All Telangana farmers owning agricultural land",
            "deadline":    "Before each crop season",
            "scope":       "State",
            "apply_url":   "https://rythubandhu.telangana.gov.in/",
        },
    ],
    "uttar-pradesh": [
        {
            "name":        "UP Kisan Karj Rahat Yojana",
            "type":        "Loan",
            "benefit":     "Farm loan waiver up to ₹1 lakh for small and marginal farmers",
            "eligibility": "UP farmers with outstanding farm loans",
            "deadline":    "Rolling — check portal",
            "scope":       "State",
            "apply_url":   "https://upagripardarshi.gov.in/",
        },
    ],
    "gujarat": [
        {
            "name":        "Mukhyamantri Bagayat Vikas Mission (Gujarat)",
            "type":        "Subsidy",
            "benefit":     "50-75% subsidy on drip/sprinkler irrigation for horticultural crops",
            "eligibility": "Gujarat farmers growing fruits/vegetables",
            "deadline":    "Rolling",
            "scope":       "State",
            "apply_url":   "https://agri.gujarat.gov.in/",
        },
    ],
}

# ── Normalise state key ───────────────────────────────────────────────────────
_STATE_ALIASES: dict[str, str] = {
    "karnataka":        "karnataka",
    "maharashtra":      "maharashtra",
    "punjab":           "punjab",
    "haryana":          "haryana",
    "madhya-pradesh":   "madhya-pradesh",
    "mp":               "madhya-pradesh",
    "uttar-pradesh":    "uttar-pradesh",
    "up":               "uttar-pradesh",
    "gujarat":          "gujarat",
    "andhra-pradesh":   "andhra-pradesh",
    "ap":               "andhra-pradesh",
    "telangana":        "telangana",
    "tamil-nadu":       "tamil-nadu",
    "kerala":           "kerala",
    "west-bengal":      "west-bengal",
    "rajasthan":        "rajasthan",
    "bihar":            "bihar",
    "odisha":           "odisha",
}


def get_schemes(crop: str, location: str) -> list[dict]:
    """
    Return a list of applicable government schemes for a crop + location.
    Always returns a non-empty list — never raises.
    """
    try:
        crop     = (crop or "").strip().lower()
        location = (location or "").strip().lower()

        # Resolve state key
        state_key = _STATE_ALIASES.get(location, location)

        schemes: list[dict] = list(_NATIONAL)   # always include national schemes

        # Crop-specific national schemes
        for key, crop_list in _CROP_SCHEMES.items():
            if key in crop:
                schemes.extend(crop_list)
                break
        # Oilseed crops catch-all
        if any(c in crop for c in ("soybean", "groundnut", "sunflower", "mustard")):
            schemes.extend(_CROP_SCHEMES.get("oilseeds", []))

        # State-specific schemes
        schemes.extend(_STATE_SCHEMES.get(state_key, []))

        # Deduplicate by name (preserve order)
        seen: set[str] = set()
        result: list[dict] = []
        for s in schemes:
            if s["name"] not in seen:
                seen.add(s["name"])
                result.append(s)

        return result

    except Exception as exc:
        print(f"[SchemesService] Error: {exc}")
        # Hard fallback
        return [
            {
                "name":        "PM-KISAN",
                "type":        "Cash Transfer",
                "benefit":     "₹6,000/year income support",
                "eligibility": "All Indian farmers",
                "deadline":    "Rolling",
                "scope":       "National",
                "apply_url":   "https://pmkisan.gov.in/",
            }
        ]
