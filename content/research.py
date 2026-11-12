"""Fixed texts on the Research page. The page lists published papers only: it never says an
ingredient works, is safe, or is good for anything. Never use the words safe, best for, treats,
cures, proven or effective here (tests check this file and the page)."""

TITLE = "Research"
INTRO = "Look up published papers about a skincare ingredient."

# The one note above the results, word for word
NOTE = ("Listing of published papers. A study existing does not mean a product works. "
        "Source: PubMed (US National Library of Medicine).")

QUICK_LINKS_LABEL = "Common ingredients:"
QUICK_LINKS = ["niacinamide", "retinol", "vitamin C", "hyaluronic acid", "salicylic acid", "ceramides"]

SEARCH_PLACEHOLDER = "For example niacinamide"
REVIEWS_ONLY_LABEL = "Reviews only"

QUERY_LINE = "PubMed search: {query}"
REVIEWS_ONLY_NOTE = "reviews only"

EMPTY = "No papers found for “{term}”."
UNAVAILABLE = "Research search is unavailable right now."
STALE = "PubMed could not be reached, so these are saved results from {date}."
INVALID = ("Please enter an ingredient name using letters, numbers, spaces, hyphens, apostrophes, "
           "commas or full stops (2 to 60 characters).")

NCBI_POLICIES_URL = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
NCBI_POLICIES_LABEL = "NCBI Disclaimer and Copyright"
