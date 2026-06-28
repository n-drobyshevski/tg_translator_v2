"""SQLite event-store package (replaces the events.json file).

Public surface lives in :mod:`translator.db.events_dao`. Connection handling is
in :mod:`translator.db.connection`. Run ``python -m translator.db.migrate`` once
to import an existing ``events.json`` into the database.
"""
