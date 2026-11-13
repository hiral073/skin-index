"""The "At a glance" cards of the Ingredient Science page: two short lines per ingredient, each with a
named source and a link, in plain words of our own (nothing is copied from a source).

- "What it is": a neutral fact, such as the vitamin or chemical family or where it occurs naturally.
- "Often discussed in relation to": 1 to 3 topics, taken only from the named source. The line is not
  an effect, a use or advice: it only names what the source talks about.

A line without a reliable source is left out (set it to None). Never use the words safe, best for,
treats, cures, proven, effective, helps or "is for", and never name a skin type. Tests check every
text here. One narrow exception, by decision of the project owner: the topic words (acne, eczema ...)
may appear here because they are the source's topics, always shown with the source and CARD_NOTE.

`checked` is the date the sources were last read. Match by name: `names` are the lower-case search
texts (as cleaned by clean_search_text) that show this card.
"""

CARD_TITLE = "At a glance"
CARD_WHAT_LABEL = "What it is"
CARD_DISCUSSED_LABEL = "Often discussed in relation to"
CARD_SOURCE_LABEL = "Source"
CARD_NOTE = "General information from the sources named. Not medical advice."

CHEBI = "ChEBI (EMBL-EBI)"
MEDLINEPLUS_VITAMIN_A = {"name": "MedlinePlus: Vitamin A", "url": "https://medlineplus.gov/ency/article/002400.htm"}
MEDLINEPLUS_VITAMIN_C = {"name": "MedlinePlus: Vitamin C", "url": "https://medlineplus.gov/ency/article/002404.htm"}
MEDLINEPLUS_NIACIN = {"name": "MedlinePlus: Niacin", "url": "https://medlineplus.gov/ency/article/002409.htm"}
MEDLINEPLUS_SALICYLIC = {"name": "MedlinePlus: Salicylic Acid Topical",
                         "url": "https://medlineplus.gov/druginfo/meds/a607072.html"}
MESH_RETINALDEHYDE = {"name": "NLM MeSH: Retinaldehyde", "url": "https://meshb.nlm.nih.gov/record/ui?ui=D012172"}
AAD_RETINOID_RETINOL = {"name": "American Academy of Dermatology: Retinoid or retinol?",
                        "url": "https://www.aad.org/public/everyday-care/skin-care-secrets/anti-aging/retinoid-retinol"}
AAD_SKINCARE_GUIDE = {"name": "American Academy of Dermatology: A dermatologist's guide to skincare",
                      "url": "https://www.aad.org/news/dermatologist-guide-skincare"}
CLEVELAND_CERAMIDES = {"name": "Cleveland Clinic: What Do Ceramides Do for Your Skin?",
                       "url": "https://health.clevelandclinic.org/ceramides"}


def chebi(chebi_id):
    return {"name": CHEBI, "url": f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:{chebi_id}"}


CARDS = [
    {
        "key": "niacinamide", "names": ["niacinamide", "nicotinamide"], "checked": "2026-11-13",
        "what": {"text": "A form of vitamin B3.", "source": chebi(17154)},
        # MedlinePlus writes about niacin (vitamin B3) as a whole, not about skin care use
        "discussed": {"topics": ["the digestive system", "skin", "nerves"],
                      "context": "as described for niacin (vitamin B3)", "source": MEDLINEPLUS_NIACIN},
    },
    {
        "key": "retinol", "names": ["retinol"], "checked": "2026-11-13",
        "what": {"text": "A form of vitamin A, found in animal liver and whole milk.",
                 "source": MEDLINEPLUS_VITAMIN_A},
        "discussed": {"topics": ["uneven skin tone", "pigmentation", "texture"], "context": None,
                      "source": AAD_RETINOID_RETINOL},
    },
    {
        "key": "retinal", "names": ["retinal", "retinaldehyde"], "checked": "2026-11-13",
        "what": {"text": "A vitamin A derivative that is the active component of the visual cycle.",
                 "source": MESH_RETINALDEHYDE},
        # the only readable source ties retinal to vision
        "discussed": {"topics": ["the visual cycle (vision)"], "context": None, "source": MESH_RETINALDEHYDE},
    },
    {
        "key": "vitamin c", "names": ["vitamin c", "ascorbic acid"], "checked": "2026-11-13",
        "what": {"text": "A water-soluble vitamin found in fruits and vegetables.", "source": MEDLINEPLUS_VITAMIN_C},
        "discussed": {"topics": ["collagen formation", "wound healing", "antioxidants"], "context": None,
                      "source": MEDLINEPLUS_VITAMIN_C},
    },
    {
        "key": "hyaluronic acid", "names": ["hyaluronic acid", "hyaluronan"], "checked": "2026-11-13",
        "what": {"text": "A sugar-based molecule found in the connective tissues of vertebrates.",
                 "source": chebi(16336)},
        "discussed": {"topics": ["hydration", "skin texture", "fine lines"], "context": None,
                      "source": AAD_SKINCARE_GUIDE},
    },
    {
        "key": "salicylic acid", "names": ["salicylic acid"], "checked": "2026-11-13",
        "what": {"text": "Obtained from the bark of the white willow and wintergreen leaves.",
                 "source": chebi(16914)},
        "discussed": {"topics": ["acne", "scaling skin conditions", "warts and calluses"], "context": None,
                      "source": MEDLINEPLUS_SALICYLIC},
    },
    {
        "key": "ceramides", "names": ["ceramides", "ceramide"], "checked": "2026-11-13",
        "what": {"text": "Fats (lipids) that make up about half of the epidermis, the outer layer of skin.",
                 "source": CLEVELAND_CERAMIDES},
        "discussed": {"topics": ["the skin barrier", "moisture", "eczema"], "context": None,
                      "source": CLEVELAND_CERAMIDES},
    },
]
