"""Local food table for Ghana.

The point of this file is that advice has to be followable. Telling a household
in Savannah in July to eat eggs is not nutrition guidance, it is noise. So every
food carries the months it is actually available, what it costs, and whether it
is bought, stored from harvest, or simply gathered -- and the calendar those
months sit on depends on where the household lives.

Ghana has two rainfall regimes, and the year does not divide the same way in
both:

  savanna     one rainy season (the five northern regions)
                LEAN     May-August      pre-harvest, stocks down, prices up
                HARVEST  September-November
                DRY      December-April

  bimodal     two rainy seasons (everywhere south of the savanna belt)
                LEAN     April-June      before the major-season harvest
                HARVEST  July-August and November-December (major and minor)
                DRY      January-March and September-October

"DRY" here means *neither lean nor harvest* -- stocks are adequate and nothing
new is coming in -- not literally dry weather. September and October are rainy
in the south and still fall under it, because for food supply they behave like
the dry months do in the north.

These calendars are PROVISIONAL. The savanna one was built for the original
five-region pilot. The bimodal one is a first approximation from national
rainfall and harvest patterns and has not been reviewed by anyone who works the
land or the nutrition programme in those regions. It needs that review before
it is trusted in a pilot, and so does every region-to-zone assignment below.

During the lean months the engine stops recommending purchases and starts
recommending what is stored or growing wild. In the north baobab leaf and
moringa are the backbone of that: both are free, both are already in the
compound, and both are dense in exactly the micronutrients that are short.

Food groups follow the two WHO instruments, which are NOT the same and are never
conflated:

  MDD-W (women 15-49)      10 groups, minimum 5
  Child MDD (6-23 months)   8 groups, minimum 5   (includes breast milk)
"""

# ------------------------------------------------------------------ groups

MDDW_GROUPS = [
    ("grains", "Grains, white roots, tubers and plantains"),
    ("pulses", "Pulses — beans, peas and lentils"),
    ("nuts_seeds", "Nuts and seeds"),
    ("dairy", "Milk and milk products"),
    ("flesh", "Meat, poultry and fish"),
    ("eggs", "Eggs"),
    ("dark_leafy", "Dark green leafy vegetables"),
    ("vita_fruit_veg", "Other vitamin A-rich fruits and vegetables"),
    ("other_veg", "Other vegetables"),
    ("other_fruit", "Other fruits"),
]

CHILD_GROUPS = [
    ("breastmilk", "Breast milk"),
    ("grains", "Grains, roots, tubers and plantains"),
    ("pulses_nuts_seeds", "Pulses, nuts and seeds"),
    ("dairy", "Dairy products"),
    ("flesh", "Flesh foods — meat, fish, poultry, organ meats"),
    ("eggs", "Eggs"),
    ("vita_fruit_veg", "Vitamin A-rich fruits and vegetables"),
    ("other_fruit_veg", "Other fruits and vegetables"),
]

MDDW_MINIMUM = 5
CHILD_MINIMUM = 5

ALL = "all"

SAVANNA = "savanna"
BIMODAL = "bimodal"

# All sixteen regions and the rainfall regime each one is calendared under.
# frontend/src/lib/regions.js carries the same names for the offline forms, and
# a test keeps the two from drifting apart.
#
# Oti and Bono East straddle the boundary between the two regimes; both are
# calendared as bimodal because that is where most of their households are, and
# both want checking. So does Savannah Region's southern fringe, which is
# calendared with the rest of the savanna belt.
REGION_ZONES = {
    "Ahafo": BIMODAL,
    "Ashanti": BIMODAL,
    "Bono": BIMODAL,
    "Bono East": BIMODAL,
    "Central": BIMODAL,
    "Eastern": BIMODAL,
    "Greater Accra": BIMODAL,
    "North East": SAVANNA,
    "Northern": SAVANNA,
    "Oti": BIMODAL,
    "Savannah": SAVANNA,
    "Upper East": SAVANNA,
    "Upper West": SAVANNA,
    "Volta": BIMODAL,
    "Western": BIMODAL,
    "Western North": BIMODAL,
}
REGIONS = list(REGION_ZONES)

# What the engine stores when nobody said which region a household is in. It is
# deliberately NOT a region: an unrecognised region gets no seasonal shift and
# only the foods that are sold and grown everywhere, instead of quietly being
# given another region's calendar and another region's foods.
UNKNOWN_REGION = "Unknown"

# The five regions of the original pilot, for foods that only make sense there.
NORTH = [r for r, z in REGION_ZONES.items() if z == SAVANNA]

SEASON_CALENDARS = {
    SAVANNA: {"lean": [5, 6, 7, 8],
              "harvest": [9, 10, 11],
              "dry": [12, 1, 2, 3, 4]},
    BIMODAL: {"lean": [4, 5, 6],
              "harvest": [7, 8, 11, 12],
              "dry": [1, 2, 3, 9, 10]},
}

# Returned when the region is not one we know. No calendar is guessed, so no
# lean-season price shift or gathered-food weighting is applied either.
UNSPECIFIED_SEASON = "unspecified"

# Cost tiers, cheapest first. "free" means gathered, not bought.
TIERS = ["free", "low", "medium", "high"]
# Every tier a household at this level can reach. "high" must be listed
# explicitly: while _affordable() failed open, an unrecognised value quietly
# meant "everything", so the missing key was invisible -- and the moment the
# filter was made to fail closed, a well-off household could suddenly afford
# nothing but free food. A lookup table with a hole in it is only ever one
# default away from being wrong in either direction.
AFFORDABILITY_CEILING = {
    "low": ["free", "low"],
    "medium": ["free", "low", "medium"],
    "high": ["free", "low", "medium", "high"],
}

YEAR = list(range(1, 13))


def _food(key, name, months, tier, source, w_groups, c_groups, message,
          regions=ALL, iron=False, vitamin_c=False, local=None,
          mother_message=None):
    """One food.

    `message` is what a caregiver hears about a child. `mother_message` is the
    same advice addressed to the woman herself, and is only given where the two
    genuinely differ -- six of these foods were worded for a caregiver, so a
    gap measured in HER intake came back as "give the child one every day",
    which points the advice away from the deficit that was measured.

    The original wording is kept as `message` on purpose. Rewriting it in place
    would have marked its Dagbani translation stale, and with the quota
    exhausted a translation cannot be regenerated for weeks -- so a correctness
    fix would have cost five recorded lines. The mother wording is a new line
    to translate instead of a lost one.
    """
    return {
        "key": key, "name": name, "months": months, "tier": tier,
        "mother_message": mother_message or message,
        "source": source, "w_groups": w_groups, "c_groups": c_groups,
        "message": message, "regions": regions, "iron_rich": iron,
        "vitamin_c": vitamin_c, "local_names": local or {},
    }


# NOT YET WRITTEN: the southern food table.
#
# Every food below was built for the five northern regions. Where a food is a
# northern one it is tagged `regions=NORTH` and is never offered elsewhere; the
# rest are sold and grown nationally and are offered everywhere. What is missing
# is the other direction -- the foods a household in Ashanti, Volta or Greater
# Accra would actually reach for (plantain, cocoyam and kontomire leaves, palm
# nut and red palm oil, year-round fresh and smoked fish, and so on), with the
# months, prices and gathered/grown/purchased split that go with them.
#
# That is nutrition content, not engineering, and it should be written by the
# person who owns the food model and checked against what is really sold in
# those regions. It was left unwritten rather than guessed. Until it exists a
# southern household's dark-leafy and flesh gaps have far fewer foods to draw
# on, and the engine falls back to "this needs a home visit". uncovered_groups()
# above says exactly which groups that affects, and /api/nutrition/foods
# reports it per region.
FOODS = [
    # --- gathered, free, and the backbone of lean-season advice -----------
    _food("baobab_leaf", "Baobab leaf powder", YEAR, "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Stir a handful of dried baobab leaf powder into the soup. The tree is "
          "in the compound and the powder keeps all year.",
          iron=True, local={"hausa": "kuka"}, regions=NORTH),
    _food("moringa", "Moringa leaves", YEAR, "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Pick moringa leaves, dry them, and add two spoons to the porridge or "
          "soup. It costs nothing and grows through the dry season.",
          iron=True, local={"dagbani": "zangala"}),
    _food("shea_fruit", "Shea fruit", [5, 6, 7], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "Shea fruit is ripe and free. Eat the sweet pulp.", regions=NORTH),
    _food("dawadawa_fruit", "Dawadawa fruit pulp", [4, 5, 6], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "The pulp inside a dawadawa pod is sweet and free. Give it to the child.",
          mother_message="The pulp inside a dawadawa pod is sweet and free. "
                         "Eat it as it is.", vitamin_c=True, regions=NORTH),
    _food("wild_greens", "Ayoyo and aleefu leaves", [6, 7, 8, 9], "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Ayoyo and aleefu are growing now. Cook a handful into the soup — they "
          "cost nothing during the rains.", iron=True, regions=NORTH),
    _food("kenaf", "Bito (kenaf) leaves", [6, 7, 8, 9], "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Bito leaves are in season. Add them to the soup.", regions=NORTH),

    # --- stored from harvest, cheap all year ------------------------------
    _food("groundnut", "Groundnut paste", YEAR, "low", "stored",
          ["nuts_seeds"], ["pulses_nuts_seeds"],
          "Add a spoon of groundnut paste to the porridge. It stores from harvest "
          "and adds energy the child needs to grow.",
          local={"dagbani": "sinkpam"}),
    _food("dawadawa", "Dawadawa", YEAR, "low", "stored",
          ["nuts_seeds"], ["pulses_nuts_seeds"],
          "Cook with dawadawa. It is rich in iron and it is already in most "
          "kitchens.", iron=True, local={"dagbani": "kpalgu"}),
    _food("cowpea", "Cowpea (beans)", YEAR, "low", "stored",
          ["pulses"], ["pulses_nuts_seeds"],
          "Cook beans twice this week. They store well and build the blood.",
          iron=True, local={"dagbani": "tuya"}),
    _food("bambara", "Bambara beans", YEAR, "low", "stored",
          ["pulses"], ["pulses_nuts_seeds"],
          "Bambara beans keep from harvest and are filling. Cook them for the "
          "family this week.", iron=True),
    _food("soybean", "Soybean", YEAR, "low", "stored",
          ["pulses"], ["pulses_nuts_seeds"],
          "Roast and grind soybean into the Tom Brown. It makes the same porridge "
          "far stronger."),
    _food("dried_fish", "Dried small fish", YEAR, "low", "purchased",
          ["flesh"], ["flesh"],
          "Pound dried small fish and stir a spoon into the porridge. It is cheap "
          "and builds the blood.",
          iron=True, local={"dagbani": "zahim kuɣili"}),
    _food("okra_dried", "Dried okra", YEAR, "low", "stored",
          ["other_veg"], ["other_fruit_veg"],
          "Dried okra keeps all year. Add it to the soup."),
    _food("maize", "Maize", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Maize from the harvest store. Use it as the base of the porridge."),
    _food("millet", "Millet", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Millet koko is fine as a base, but enrich it — plain koko alone is "
          "mostly water.", regions=NORTH),
    _food("sorghum", "Sorghum", YEAR, "low", "stored",
          ["grains"], ["grains"], "Sorghum from the store, as the porridge base.",
          regions=NORTH),
    _food("tom_brown", "Enriched Tom Brown", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Make Tom Brown with roasted maize, soybean and groundnut together — "
          "not maize alone. Same porridge, far more in it."),
    # Shea butter is a fat. Fats and oils are not a group in either instrument,
    # so it carries no group and can never inflate a diversity score. It is kept
    # because the advice is sound: fat is what makes vitamin A absorbable.
    _food("shea_butter", "Shea butter", YEAR, "low", "stored",
          [], [],
          "A little shea butter in the food helps the body take up vitamin A."),

    # --- seasonal, grown --------------------------------------------------
    _food("yam", "Yam", [7, 8, 9, 10, 11, 12], "low", "grown",
          ["grains"], ["grains"], "New yam is in. Use it as the meal base."),
    _food("cassava", "Cassava", YEAR, "low", "grown",
          ["grains"], ["grains"], "Use cassava as the base, with groundnut or fish so it is not starch "
          "alone.",
          # Everywhere except the two driest regions, which is where it was
          # already withheld from.
          regions=[r for r in REGIONS if r not in ("Upper East", "Upper West")]),
    _food("sweet_potato", "Orange-fleshed sweet potato", [9, 10, 11, 12], "low", "grown",
          ["vita_fruit_veg"], ["vita_fruit_veg"],
          "Orange sweet potato is in season and is one of the best sources of "
          "vitamin A you can grow."),
    _food("okra_fresh", "Fresh okra", [6, 7, 8, 9, 10], "low", "grown",
          ["other_veg"], ["other_fruit_veg"], "Fresh okra is in the market now."),
    _food("garden_egg", "Garden egg", [6, 7, 8, 9, 10, 11], "low", "grown",
          ["other_veg"], ["other_fruit_veg"], "Garden eggs are cheap this season."),
    _food("mango", "Mango", [3, 4, 5, 6], "free", "gathered",
          ["vita_fruit_veg"], ["vita_fruit_veg"],
          "Mangoes are ripe. Give the child one every day while they last.",
          mother_message="Mangoes are ripe. Have one every day while they "
                         "last.", vitamin_c=True),
    _food("baobab_fruit", "Baobab fruit", [12, 1, 2, 3, 4], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "Mix baobab fruit powder into water or porridge. It is very high in "
          "vitamin C, which helps the body take up iron.", vitamin_c=True,
          regions=NORTH),
    _food("pawpaw", "Pawpaw", YEAR, "low", "grown",
          ["vita_fruit_veg"], ["vita_fruit_veg"],
          "Pawpaw is available. Half a pawpaw covers the child's vitamin A.",
          mother_message="Pawpaw is available. Half a pawpaw covers your "
                         "vitamin A for the day.",
          vitamin_c=True),
    _food("tomato", "Tomato", [11, 12, 1, 2, 3], "medium", "purchased",
          ["other_veg"], ["other_fruit_veg"],
          "Tomatoes are cheap now. Cook them with beans to help the iron get in.", vitamin_c=True),
    _food("onion", "Onion", YEAR, "low", "purchased",
          ["other_veg"], ["other_fruit_veg"], "Onion in the stew."),
    _food("orange", "Orange", [11, 12, 1, 2], "low", "purchased",
          ["other_fruit"], ["other_fruit_veg"],
          "Oranges are cheap now. Eat one with the beans — the vitamin C helps "
          "the iron get in.", vitamin_c=True),

    # --- animal source, costlier -----------------------------------------
    _food("eggs", "Eggs", YEAR, "medium", "purchased",
          ["eggs"], ["eggs"],
          "One egg for the child, most days, if you can manage it.",
          mother_message="One egg most days, if you can manage it."),
    _food("fresh_fish", "Fresh fish", [6, 7, 8, 9, 10], "medium", "purchased",
          ["flesh"], ["flesh"], "Fresh fish is available in the rains.",
          # Inland fish that comes with the rains. The south has fish all year,
          # and that belongs in the southern table, not stretched onto this row.
          regions=NORTH),
    _food("guinea_fowl", "Guinea fowl", YEAR, "high", "purchased",
          ["flesh"], ["flesh"], "Guinea fowl when the household can afford it.",
          regions=NORTH),
    _food("goat", "Goat meat", YEAR, "high", "purchased",
          ["flesh"], ["flesh"], "Goat meat when there is money for it."),
    _food("milk_fermented", "Fermented milk (burkina)", [6, 7, 8, 9, 10], "medium", "purchased",
          ["dairy"], ["dairy"],
          "Fermented milk is around during the rains — good for the child.",
          mother_message="Fermented milk is around during the rains — good "
                         "for you and the baby.", regions=NORTH),
    _food("milk_fresh", "Fresh cow milk", [6, 7, 8, 9, 10], "medium", "purchased",
          ["dairy"], ["dairy"], "Fresh milk while the cattle are producing.",
          regions=NORTH),
]

FOODS_BY_KEY = {f["key"]: f for f in FOODS}


# Foods whose price genuinely moves. The file's own opening paragraph says the
# lean season means "stocks down, prices up", and the first version then priced
# everything identically in all twelve months. Stored staples are what a
# household sells or eats first, so they are the ones that stop being cheap.
LEAN_PRICE_SHIFT = {
    "maize": "medium", "millet": "medium", "sorghum": "medium",
    "cowpea": "medium", "bambara": "medium",
    "soybean": "medium", "yam": "medium",
    # Groundnut deliberately absent: it is the staple households hold back
    # rather than sell, and it is the lean-season fallback this whole engine is
    # built around. Pricing it out in July contradicted the one worked example
    # the documentation leads with.
    "eggs": "high", "fresh_fish": "high", "milk_fresh": "high",
    "milk_fermented": "high", "tomato": "high",
}


def tier_for(food, season: str) -> str:
    """What this food costs *this* season, not on average."""
    if season == "lean":
        return LEAN_PRICE_SHIFT.get(food["key"], food["tier"])
    return food["tier"]


# Why each gap matters, in words a caregiver would use. Deliberately plain and
# deliberately modest: these describe what a food group is for, not what will
# happen to her if she misses it. Nutrition advice that implies a diagnosis is
# both wrong and frightening, and a CHO has to be able to say it out loud
# without over-promising.
GROUP_WHY = {
    "flesh": "Fish, meat and eggs build the blood. Women short of them tire "
             "easily and are more likely to be anaemic.",
    "dark_leafy": "Green leaves carry iron and folate, which the body needs "
                  "more of during pregnancy.",
    "vita_fruit_veg": "Orange and yellow foods carry vitamin A, which protects "
                      "a child's eyes and helps them fight infection.",
    "pulses": "Beans and groundnuts are the cheapest way to add protein when "
              "meat is out of reach.",
    "pulses_nuts_seeds": "Beans and groundnuts add the protein a growing child "
                         "needs when meat is too costly.",
    "nuts_seeds": "Groundnut and dawadawa add energy and iron to food that is "
                  "otherwise mostly starch.",
    "dairy": "Milk adds calcium and protein, useful but not essential if other "
             "protein is there.",
    "eggs": "One egg is a complete protein and among the easiest to add.",
    "grains": "The base of the meal. On its own it fills the stomach without "
              "feeding growth, so it needs something added to it.",
    "other_veg": "Vegetables add the vitamins that keep the rest of the diet "
                 "working.",
    "other_fruit": "Fruit adds vitamin C, which helps the body take up iron "
                   "from the same meal.",
    "other_fruit_veg": "Fruit and vegetables add vitamins and help iron get in.",
    "breastmilk": "Breast milk remains the single most important food up to "
                  "two years, alongside other foods after six months.",
}

# Attached alongside the food message. Water is not a food group and is not
# scored, but it is the cheapest advice there is and it is routinely missed.
HYDRATION_NOTE = ("Drink clean water through the day, more when it is hot or "
                  "you are working in the field.")


def zone_for(region):
    """The rainfall regime a region is calendared under, or None if unknown."""
    return REGION_ZONES.get(region)


def season_for(month: int, region=None) -> str:
    """Lean, harvest or dry -- on the calendar of the household's own region.

    No region, or one we do not recognise, returns "unspecified" rather than
    borrowing the savanna calendar. The old single-argument form silently gave
    every household the northern one, which is exactly wrong in the south.
    """
    zone = zone_for(region)
    if zone is None:
        return UNSPECIFIED_SEASON
    calendar = SEASON_CALENDARS[zone]
    for season in ("lean", "harvest"):
        if month in calendar[season]:
            return season
    return "dry"


def serves_region(food, region) -> bool:
    """Is this food sold or grown where the household lives?

    A food tagged for particular regions is never offered to a household whose
    region is unknown -- only the foods that are tagged for everywhere are.
    """
    return food["regions"] == ALL or region in food["regions"]


def uncovered_groups(instrument: str, region) -> list:
    """Food groups that no food in the table can fill, in any month, there.

    The southern food table has not been written yet (see FOODS below). Until
    it is, a gap in one of these groups can only end in "this needs a home
    visit". Naming them is how that stays visible instead of being discovered
    by a household.
    """
    groups = groups_for(instrument)
    covered = set()
    for food in FOODS:
        if serves_region(food, region):
            covered.update(food["w_groups"] if instrument == "mdd_w"
                           else food["c_groups"])
    return [g for g in groups if g not in covered]


def group_labels(instrument: str):
    return dict(MDDW_GROUPS if instrument == "mdd_w" else CHILD_GROUPS)


def groups_for(instrument: str):
    return [k for k, _ in (MDDW_GROUPS if instrument == "mdd_w" else CHILD_GROUPS)]
