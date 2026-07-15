"""City/state -> MSA (metropolitan statistical area) assignment.

The research manual organizes companies by MSA. This is a pragmatic
keyword map of major metros (extend freely); anything unmatched falls
back to the manual's "<STATE> (Other)" convention.
"""

from __future__ import annotations

# state -> [(MSA name, (city keywords...)), ...]  matched case-insensitively
MSA_MAP: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "NY": [
        ("New York-Newark-Jersey City", ("new york", "brooklyn", "bronx", "queens", "staten island", "manhattan", "yonkers", "white plains", "new rochelle", "hempstead", "hicksville", "long island", "melville", "hauppauge", "farmingdale", "westbury", "mount vernon")),
        ("Buffalo-Cheektowaga", ("buffalo", "cheektowaga", "tonawanda")),
        ("Rochester", ("rochester",)),
        ("Albany-Schenectady-Troy", ("albany", "schenectady", "troy")),
        ("Syracuse", ("syracuse",)),
    ],
    "NJ": [
        ("New York-Newark-Jersey City", ("newark", "jersey city", "paterson", "elizabeth", "edison", "new brunswick", "hackensack", "clifton", "union", "wayne", "parsippany", "secaucus", "hoboken")),
        ("Philadelphia-Camden-Wilmington", ("camden", "cherry hill", "vineland", "mount laurel")),
        ("Trenton-Princeton", ("trenton", "princeton")),
        ("Atlantic City-Hammonton", ("atlantic city", "hammonton")),
    ],
    "CT": [
        ("Bridgeport-Stamford-Norwalk", ("bridgeport", "stamford", "norwalk", "greenwich", "danbury", "fairfield", "shelton")),
        ("Hartford-East Hartford", ("hartford", "east hartford", "new britain", "manchester")),
        ("New Haven-Milford", ("new haven", "milford", "waterbury", "meriden")),
    ],
    "PA": [
        ("Philadelphia-Camden-Wilmington", ("philadelphia", "king of prussia", "norristown", "chester", "media", "conshohocken", "bensalem")),
        ("Pittsburgh", ("pittsburgh",)),
        ("Allentown-Bethlehem-Easton", ("allentown", "bethlehem", "easton")),
        ("Harrisburg-Carlisle", ("harrisburg", "carlisle")),
        ("Scranton–Wilkes-Barre", ("scranton", "wilkes-barre")),
    ],
    "MA": [
        ("Boston-Cambridge-Newton", ("boston", "cambridge", "newton", "quincy", "waltham", "woburn", "framingham", "braintree", "somerville", "peabody")),
        ("Worcester", ("worcester",)),
        ("Springfield", ("springfield",)),
    ],
    "FL": [
        ("Miami-Fort Lauderdale-West Palm Beach", ("miami", "fort lauderdale", "west palm beach", "hialeah", "pompano", "boca raton", "hollywood", "doral", "coral springs")),
        ("Tampa-St. Petersburg-Clearwater", ("tampa", "st. petersburg", "saint petersburg", "clearwater", "brandon")),
        ("Orlando-Kissimmee-Sanford", ("orlando", "kissimmee", "sanford")),
        ("Jacksonville", ("jacksonville",)),
        ("Cape Coral-Fort Myers", ("cape coral", "fort myers")),
        ("North Port-Sarasota-Bradenton", ("sarasota", "bradenton", "north port")),
    ],
    "TX": [
        ("Dallas-Fort Worth-Arlington", ("dallas", "fort worth", "arlington", "plano", "irving", "garland", "frisco", "carrollton", "richardson", "grand prairie")),
        ("Houston-The Woodlands-Sugar Land", ("houston", "the woodlands", "sugar land", "pasadena", "katy", "spring")),
        ("San Antonio-New Braunfels", ("san antonio", "new braunfels")),
        ("Austin-Round Rock", ("austin", "round rock", "cedar park")),
        ("El Paso", ("el paso",)),
    ],
    "CA": [
        ("Los Angeles-Long Beach-Anaheim", ("los angeles", "long beach", "anaheim", "santa ana", "irvine", "glendale", "burbank", "torrance", "pasadena", "van nuys", "orange", "fullerton")),
        ("San Francisco-Oakland-Berkeley", ("san francisco", "oakland", "berkeley", "hayward", "concord", "san rafael")),
        ("San Jose-Sunnyvale-Santa Clara", ("san jose", "sunnyvale", "santa clara", "milpitas")),
        ("San Diego-Chula Vista-Carlsbad", ("san diego", "chula vista", "carlsbad")),
        ("Sacramento-Roseville-Folsom", ("sacramento", "roseville", "folsom")),
        ("Riverside-San Bernardino-Ontario", ("riverside", "san bernardino", "ontario", "rancho cucamonga", "corona")),
        ("Fresno", ("fresno",)),
    ],
    "IL": [
        ("Chicago-Naperville-Elgin", ("chicago", "naperville", "elgin", "aurora", "joliet", "schaumburg", "skokie", "evanston", "cicero", "des plaines")),
    ],
    "OH": [
        ("Columbus", ("columbus", "dublin", "westerville")),
        ("Cleveland-Elyria", ("cleveland", "elyria", "parma", "lakewood")),
        ("Cincinnati", ("cincinnati",)),
        ("Dayton-Kettering", ("dayton", "kettering")),
        ("Akron", ("akron",)),
        ("Toledo", ("toledo",)),
    ],
    "GA": [
        ("Atlanta-Sandy Springs-Alpharetta", ("atlanta", "sandy springs", "alpharetta", "marietta", "roswell", "duluth", "norcross", "kennesaw", "decatur", "lawrenceville")),
        ("Savannah", ("savannah",)),
        ("Augusta-Richmond County", ("augusta",)),
    ],
    "NC": [
        ("Charlotte-Concord-Gastonia", ("charlotte", "concord", "gastonia")),
        ("Raleigh-Cary", ("raleigh", "cary")),
        ("Durham-Chapel Hill", ("durham", "chapel hill")),
        ("Greensboro-High Point", ("greensboro", "high point")),
    ],
    "MI": [
        ("Detroit-Warren-Dearborn", ("detroit", "warren", "dearborn", "troy", "livonia", "sterling heights", "southfield", "pontiac")),
        ("Grand Rapids-Kentwood", ("grand rapids", "kentwood")),
    ],
    "VA": [
        ("Washington-Arlington-Alexandria", ("arlington", "alexandria", "fairfax", "reston", "ashburn", "manassas", "sterling", "chantilly", "springfield", "woodbridge")),
        ("Virginia Beach-Norfolk-Newport News", ("virginia beach", "norfolk", "newport news", "chesapeake", "hampton", "suffolk", "portsmouth")),
        ("Richmond", ("richmond", "glen allen", "midlothian")),
    ],
    "WA": [
        ("Seattle-Tacoma-Bellevue", ("seattle", "tacoma", "bellevue", "everett", "kent", "renton", "redmond", "kirkland", "auburn")),
        ("Spokane-Spokane Valley", ("spokane",)),
    ],
    "AZ": [
        ("Phoenix-Mesa-Chandler", ("phoenix", "mesa", "chandler", "scottsdale", "tempe", "glendale", "gilbert", "peoria")),
        ("Tucson", ("tucson",)),
    ],
    "CO": [
        ("Denver-Aurora-Lakewood", ("denver", "aurora", "lakewood", "englewood", "littleton", "arvada", "westminster", "centennial")),
        ("Colorado Springs", ("colorado springs",)),
    ],
    "TN": [
        ("Nashville-Davidson-Murfreesboro", ("nashville", "murfreesboro", "franklin", "brentwood")),
        ("Memphis", ("memphis",)),
        ("Knoxville", ("knoxville",)),
        ("Chattanooga", ("chattanooga",)),
    ],
    "MD": [
        ("Baltimore-Columbia-Towson", ("baltimore", "columbia", "towson", "glen burnie", "dundalk")),
        ("Washington-Arlington-Alexandria", ("bethesda", "rockville", "silver spring", "gaithersburg", "frederick", "bowie", "laurel", "waldorf")),
    ],
}


STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_ABBREVS = set(STATE_NAMES.values())


def region_to_state(text: str) -> str:
    """Best-effort state from a search region / lead source string, e.g.
    'web search: fire protection company Stamford CT' -> 'CT',
    '... New Jersey' -> 'NJ'."""
    import re as _re

    m = _re.search(r"\b([A-Z]{2})\s*$", (text or "").strip())
    if m and m.group(1) in _ABBREVS:
        return m.group(1)
    lower = (text or "").lower()
    for name, ab in STATE_NAMES.items():
        if name in lower:
            return ab
    return ""


def assign_msa(city: str, state: str) -> str:
    """Return the MSA for a city/state, or '<STATE> (Other)' when unmapped."""
    state = (state or "").strip().upper()
    if not state:
        return ""
    city_l = (city or "").strip().lower()
    if city_l:
        for msa_name, keywords in MSA_MAP.get(state, []):
            if any(kw in city_l or city_l in kw for kw in keywords):
                return msa_name
    return f"{state} (Other)"
