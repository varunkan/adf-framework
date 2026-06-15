#!/usr/bin/env python3
"""The fixed benchmark suite — the ~10 prompts ADF and Lovable are scored on.
Chosen to span the common app shapes (lists, boards, records, content, forms,
realtime) so the scorecard reflects breadth, not a single happy path."""

SUITE = [
    {"id": "todo",
     "prompt": "A todo list app: add, complete, and delete tasks; persist them."},
    {"id": "kanban",
     "prompt": "A kanban board with three columns and drag-and-drop cards, "
               "persisted to the database."},
    {"id": "expense-tracker",
     "prompt": "An expense tracker: add expenses with amount/category/date, "
               "list them, and show a running total per category."},
    {"id": "crm",
     "prompt": "A simple CRM: create contacts with name/email/company, search "
               "them, and log notes against each contact."},
    {"id": "blog",
     "prompt": "A minimal blog: create/edit/publish posts in markdown and list "
               "them newest-first."},
    {"id": "booking",
     "prompt": "A booking app: list available time slots, book one, and prevent "
               "double-booking."},
    {"id": "dashboard",
     "prompt": "A metrics dashboard: ingest sample records and render summary "
               "cards plus a simple chart."},
    {"id": "chat",
     "prompt": "A single-room chat: post messages, persist them, and show the "
               "latest at the bottom."},
    {"id": "inventory",
     "prompt": "An inventory manager: products with stock counts, adjust stock, "
               "and flag low-stock items."},
    {"id": "form-builder",
     "prompt": "A form builder: define fields, render the form, and store "
               "submissions."},
]


def ids():
    return [item["id"] for item in SUITE]
