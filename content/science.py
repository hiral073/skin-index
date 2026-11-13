"""Fixed texts on the Ingredient Science page. The page lists published papers only: it never says an
ingredient works, is safe, or is good for anything. Never use the words safe, best for, treats,
cures, proven or effective here (tests check this file and the page).

One narrow exception, by decision of the project owner: the "At a glance" box shows counts of papers,
including the number of papers that mention an ingredient together with a topic (acne, rosacea ...).
It states no conclusion and carries GLANCE_NOTE. The topic words are allowed only in this file."""

TITLE = "Ingredient Science"
INTRO = "Look up published papers about a skincare ingredient."

# The one note above the results, word for word
NOTE = ("Listing of published papers. A study existing does not mean a product works. "
        "Source: PubMed (US National Library of Medicine).")

# One line above the results about the groups; they name the kind of paper, taken from PubMed's
# own record, and are not our summary of what a paper found
LABELS_LINE = ("Papers are grouped by kind, using the type PubMed records for each one: overview papers, "
               "studies combined into one analysis, trials with people and other research papers. "
               "The groups are not our summary of what a paper found.")

# (label, PubMed publication types that give it). A paper gets the first label in this list that
# one of its types fits, so a combined analysis is not also listed as an overview; any paper that
# fits none is an "Other research paper". The groups on the page come in the order of GROUP_ORDER.
PAPER_LABELS = [
    ("Studies combined into one analysis", ["Systematic Review", "Meta-Analysis"]),
    ("Start here: overview papers", ["Review"]),
    ("Trials with people", ["Randomized Controlled Trial", "Clinical Trial"]),
]
OTHER_LABEL = "Other research papers"
# Order of the groups on the page: overview papers first
GROUP_ORDER = ["Start here: overview papers", "Studies combined into one analysis", "Trials with people", OTHER_LABEL]

# The "At a glance" box: counts of papers only, no conclusions. Each topic is searched as
# "<ingredient> AND <topic>"; the box lists the topics that have at least one paper, most papers first,
# and is left out when none has.
GLANCE_TITLE = "At a glance"
GLANCE_TOPICS_HEADING = "Often mentioned together with"
GLANCE_TOPICS = ["acne", "hyperpigmentation", "skin aging", "skin barrier", "irritation", "rosacea", "eczema"]
GLANCE_NOTE = ("These numbers show how often topics appear in published papers. They do not show that an "
               "ingredient works or is suitable for anyone. Source: PubMed (US National Library of Medicine).")

TITLE_MAX_LENGTH = 120
READ_LINK_LABEL = "Read on PubMed"

QUICK_LINKS_LABEL = "Common ingredients:"
QUICK_LINKS = ["niacinamide", "retinol", "vitamin C", "hyaluronic acid", "salicylic acid", "ceramides"]

SEARCH_PLACEHOLDER = "For example niacinamide"
REVIEWS_ONLY_LABEL = "Overview papers and combined analyses only"

QUERY_LINE = "PubMed search: {query}"
REVIEWS_ONLY_NOTE = "overview papers and combined analyses only"

EMPTY = "No papers found for “{term}”."
UNAVAILABLE = "Research search is unavailable right now."
STALE = "PubMed could not be reached, so these are saved results from {date}."
INVALID = ("Please enter an ingredient name using letters, numbers, spaces, hyphens, apostrophes, "
           "commas or full stops (2 to 60 characters).")

NCBI_POLICIES_URL = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
NCBI_POLICIES_LABEL = "NCBI Disclaimer and Copyright"
