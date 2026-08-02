"""Local food table for Northern Ghana.

The point of this file is that advice has to be followable. Telling a household
in Savannah in July to eat eggs is not nutrition guidance, it is noise. So every
food carries the months it is actually available, what it costs, and whether it
is bought, stored from harvest, or simply gathered.

Northern Ghana has a single rainy season, so the year divides cleanly:

    LEAN     May-August      pre-harvest, stocks down, prices up
    HARVEST  September-November
    DRY      December-April

During the lean months the engine stops recommending purchases and starts
recommending what is stored or growing wild. Baobab leaf and moringa are the
backbone of that: both are free, both are already in the compound, and both are
dense in exactly the micronutrients that are short.

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
REGIONS = ["Northern", "North East", "Savannah", "Upper East", "Upper West"]

LEAN_MONTHS = [5, 6, 7, 8]
HARVEST_MONTHS = [9, 10, 11]
DRY_MONTHS = [12, 1, 2, 3, 4]

# Cost tiers, cheapest first. "free" means gathered, not bought.
TIERS = ["free", "low", "medium", "high"]
AFFORDABILITY_CEILING = {"low": ["free", "low"], "medium": ["free", "low", "medium"]}

YEAR = list(range(1, 13))


def _food(key, name, months, tier, source, w_groups, c_groups, message,
          regions=ALL, iron=False, vitamin_c=False, local=None):
    return {
        "key": key, "name": name, "months": months, "tier": tier,
        "source": source, "w_groups": w_groups, "c_groups": c_groups,
        "message": message, "regions": regions, "iron_rich": iron,
        "vitamin_c": vitamin_c, "local_names": local or {},
    }


FOODS = [
    # --- gathered, free, and the backbone of lean-season advice -----------
    _food("baobab_leaf", "Baobab leaf powder", YEAR, "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Stir a handful of dried baobab leaf powder into the soup. The tree is "
          "in the compound and the powder keeps all year.",
          iron=True, local={"dagbani": "kuka", "gonja": "kuka"}),
    _food("moringa", "Moringa leaves", YEAR, "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Pick moringa leaves, dry them, and add two spoons to the porridge or "
          "soup. It costs nothing and grows through the dry season.",
          iron=True, local={"dagbani": "zangala"}),
    _food("shea_fruit", "Shea fruit", [5, 6, 7], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "Shea fruit is ripe now and free. Eat the sweet pulp — it comes exactly "
          "when the stores are lowest."),
    _food("dawadawa_fruit", "Dawadawa fruit pulp", [4, 5, 6], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "The yellow pulp inside the dawadawa pod is sweet and free. Give it to "
          "the child instead of buying fruit.", vitamin_c=True),
    _food("wild_greens", "Ayoyo and aleefu leaves", [6, 7, 8, 9], "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Ayoyo and aleefu are growing now. Cook a handful into the soup — they "
          "cost nothing during the rains.", iron=True),
    _food("kenaf", "Bito (kenaf) leaves", [6, 7, 8, 9], "free", "gathered",
          ["dark_leafy"], ["vita_fruit_veg"],
          "Bito leaves are in season. Add them to the soup."),

    # --- stored from harvest, cheap all year ------------------------------
    _food("groundnut", "Groundnut paste", YEAR, "low", "stored",
          ["nuts_seeds"], ["pulses_nuts_seeds"],
          "Add a spoon of groundnut paste to the porridge. It stores from harvest "
          "and adds energy the child needs to grow.",
          local={"dagbani": "sinkaafa"}),
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
          "Pound dried small fish into powder and stir a spoon into the porridge. "
          "It is cheap, and the whole fish gives both iron and calcium.",
          iron=True, local={"dagbani": "amane"}),
    _food("okra_dried", "Dried okra", YEAR, "low", "stored",
          ["other_veg"], ["other_fruit_veg"],
          "Dried okra keeps all year. Add it to the soup."),
    _food("maize", "Maize", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Maize from the harvest store. Use it as the base of the porridge."),
    _food("millet", "Millet", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Millet koko is fine as a base, but enrich it — plain koko alone is "
          "mostly water."),
    _food("sorghum", "Sorghum", YEAR, "low", "stored",
          ["grains"], ["grains"], "Sorghum from the store, as the porridge base."),
    _food("tom_brown", "Enriched Tom Brown", YEAR, "low", "stored",
          ["grains"], ["grains"],
          "Make Tom Brown with roasted maize, soybean and groundnut together — "
          "not maize alone. Same porridge, far more in it.",
          local={"dagbani": "tombrown"}),
    _food("shea_butter", "Shea butter", YEAR, "low", "stored",
          ["other_veg"], ["other_fruit_veg"],
          "A little shea butter in the food helps the body take up vitamin A."),

    # --- seasonal, grown --------------------------------------------------
    _food("yam", "Yam", [7, 8, 9, 10, 11, 12], "low", "grown",
          ["grains"], ["grains"], "New yam is in. Use it as the meal base."),
    _food("cassava", "Cassava", YEAR, "low", "grown",
          ["grains"], ["grains"], "Cassava is available. Use it as the base, but "
          "add groundnut or fish so it is not starch alone.",
          regions=["Northern", "Savannah", "North East"]),
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
          "Mangoes are ripe. Give the child one every day while they last — they "
          "carry vitamin A right into the lean months.", vitamin_c=True),
    _food("baobab_fruit", "Baobab fruit", [12, 1, 2, 3, 4], "free", "gathered",
          ["other_fruit"], ["other_fruit_veg"],
          "Mix baobab fruit powder into water or porridge. It is very high in "
          "vitamin C, which helps the body take up iron.", vitamin_c=True),
    _food("pawpaw", "Pawpaw", YEAR, "low", "grown",
          ["vita_fruit_veg"], ["vita_fruit_veg"],
          "Pawpaw is available. Half a pawpaw covers the child's vitamin A.",
          vitamin_c=True),
    _food("tomato", "Tomato", [11, 12, 1, 2, 3], "medium", "purchased",
          ["other_veg"], ["other_fruit_veg"],
          "Tomatoes are in season and cheap now. Cook them with iron-rich food — "
          "they help the body absorb it.", vitamin_c=True),
    _food("onion", "Onion", YEAR, "low", "purchased",
          ["other_veg"], ["other_fruit_veg"], "Onion in the stew."),
    _food("orange", "Orange", [11, 12, 1, 2], "low", "purchased",
          ["other_fruit"], ["other_fruit_veg"],
          "Oranges are cheap now. Eat one with the beans — the vitamin C helps "
          "the iron get in.", vitamin_c=True),

    # --- animal source, costlier -----------------------------------------
    _food("eggs", "Eggs", YEAR, "medium", "purchased",
          ["eggs"], ["eggs"],
          "One egg for the child, most days, if you can manage it."),
    _food("fresh_fish", "Fresh fish", [6, 7, 8, 9, 10], "medium", "purchased",
          ["flesh"], ["flesh"], "Fresh fish is available in the rains."),
    _food("guinea_fowl", "Guinea fowl", YEAR, "high", "purchased",
          ["flesh"], ["flesh"], "Guinea fowl when the household can afford it."),
    _food("goat", "Goat meat", YEAR, "high", "purchased",
          ["flesh"], ["flesh"], "Goat meat when there is money for it."),
    _food("milk_fermented", "Fermented milk (burkina)", [6, 7, 8, 9, 10], "medium", "purchased",
          ["dairy"], ["dairy"],
          "Fermented milk is around during the rains — good for the child."),
    _food("milk_fresh", "Fresh cow milk", [6, 7, 8, 9, 10], "medium", "purchased",
          ["dairy"], ["dairy"], "Fresh milk while the cattle are producing."),
]

FOODS_BY_KEY = {f["key"]: f for f in FOODS}


# Foods whose price genuinely moves. The file's own opening paragraph says the
# lean season means "stocks down, prices up", and the first version then priced
# everything identically in all twelve months. Stored staples are what a
# household sells or eats first, so they are the ones that stop being cheap.
LEAN_PRICE_SHIFT = {
    "maize": "medium", "millet": "medium", "sorghum": "medium",
    "cowpea": "medium", "bambara": "medium", "groundnut": "medium",
    "soybean": "medium", "yam": "medium",
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


def season_for(month: int) -> str:
    if month in LEAN_MONTHS:
        return "lean"
    if month in HARVEST_MONTHS:
        return "harvest"
    return "dry"


def group_labels(instrument: str):
    return dict(MDDW_GROUPS if instrument == "mdd_w" else CHILD_GROUPS)


def groups_for(instrument: str):
    return [k for k, _ in (MDDW_GROUPS if instrument == "mdd_w" else CHILD_GROUPS)]
