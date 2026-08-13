"""Entity definitions for the USDA PSD explorer.

PSD uses FIPS 10-4 country codes, and mixes present-day countries with
supranational aggregates (European Union) and historic entities (USSR,
Czechoslovakia, Yugoslavia). Aggregates and their members can both appear in
the file, so any World/continent total has to suppress members whenever their
parent is reported, or production gets counted twice.
"""

# --- Aggregates and the members they subsume -------------------------------
EU15 = ["AU", "BE", "S8", "LU", "DA", "FI", "FR", "GM", "GR", "EI", "IT",
        "NL", "PO", "SP", "SW", "UK"]
EU25_ADD = ["CY", "EZ", "EN", "HU", "LG", "LH", "MT", "PL", "LO", "SI"]
EU28_ADD = ["BU", "RO", "HR"]

USSR_REPUBLICS = ["RS", "UP", "BO", "MD", "EN", "LG", "LH", "GG", "AM", "AJ",
                  "KZ", "KG", "TI", "TX", "UZ"]

# parent code -> codes it contains (must be dropped when the parent is present)
AGGREGATE_MEMBERS = {
    "E4": EU15 + EU25_ADD + EU28_ADD + ["E2", "E3"],   # European Union
    "E3": EU15 + EU25_ADD + ["E2"],                     # EU-25
    "E2": EU15,                                         # EU-15
    "UR": USSR_REPUBLICS,                               # USSR
    "CZ": ["EZ", "LO"],                                 # Czechoslovakia
    "YO": ["BK", "HR", "MJ", "MK", "RB", "SI", "KV", "SR", "YU"],
    "YU": ["RB", "MJ", "KV"],                           # Yugoslavia (>05/92)
    "SR": ["RB", "MJ"],                                 # Serbia and Montenegro
    "BE": ["S8", "LU"],                                 # Belgium-Luxembourg
    "YM": ["YE", "YS"],                                 # Yemen
    "GM": ["GC", "GE"],                                 # Germany / GDR + FRG
}

# --- Entities country_converter cannot resolve -----------------------------
# code -> (display name, iso3 or None, continent or None)
MANUAL = {
    "E2": ("EU-15", None, "Europe"),
    "E3": ("EU-25", None, "Europe"),
    "E4": ("European Union", None, "Europe"),
    "UR": ("USSR", None, "Europe"),
    "CZ": ("Czechoslovakia", None, "Europe"),
    "YO": ("Yugoslavia", None, "Europe"),
    "YU": ("Yugoslavia (>05/92)", None, "Europe"),
    "SR": ("Serbia and Montenegro", None, "Europe"),
    "GC": ("East Germany", None, "Europe"),
    "GE": ("West Germany", None, "Europe"),
    "BE": ("Belgium-Luxembourg", None, "Europe"),
    "S8": ("Belgium", "BEL", "Europe"),
    "YE": ("North Yemen", None, "Asia"),
    "YS": ("South Yemen", None, "Asia"),
    "FT": ("French Territory of the Afars and Issas", None, "Africa"),
    "GN": ("Gilbert and Ellice Islands", None, "Oceania"),
    "NA": ("Netherlands Antilles", None, "North America"),
    "Y2": ("French West Indies", None, "North America"),
    "ZZ": ("Other", None, None),   # residual: World only, no continent
}

# Entities that are aggregates or defunct states. They still carry real
# production and belong in World/continent totals, but they are not offered
# as map polygons and are listed separately in the entity picker.
HISTORIC = {"UR", "CZ", "YO", "YU", "SR", "GC", "GE", "BE", "YE", "YS",
            "FT", "GN", "NA", "Y2", "E2", "E3", "ZZ"}

# Shown in the picker as a region rather than a country.
SUPRANATIONAL = {"E4"}

CONTINENTS = ["Africa", "Asia", "Europe", "North America", "Oceania",
              "South America"]
