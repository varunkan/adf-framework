# Synthetic usability panel for ANDS Studio.
#
# Adapts "LLMs Reproduce Human Purchase Intent via Semantic Similarity
# Elicitation of Likert Ratings" (Maier et al., arXiv:2510.08338) from
# consumer purchase-intent research to software usability / user-preference
# testing:
#
#   synthetic respondent = LLM conditioned on a professional persona
#   stimulus             = faithful text walkthrough of a real app flow
#   elicitation          = free text (never direct numeric ratings)
#   rating               = semantic-similarity mapping of the text onto a
#                          5-point Likert scale via anchor statements (SSR)
#
# Per the paper: direct Likert elicitation collapses to narrow "3/4"
# distributions; free-text + SSR reaches ~90% of the human test-retest
# ceiling while keeping realistic distributions AND qualitative rationales.
