"""Registry service — marketed-product / registration registry (REQ-111).

Tracks registrations keyed by product × country × dossier × DIN × status, with a
status state machine (Submitted → NOC-Issued → Marketed → Suspended/Cancelled)
and the post-NOC Right-to-Sell obligation (statutory Oct-1 due date; the fee
amount itself is owned by the fees service).
"""
