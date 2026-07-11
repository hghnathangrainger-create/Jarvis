"""
notice package

Phase 22: the minimal, honest CLI startup notice for new scheduled
Inbox activity - a single durable last-seen marker (see
scheduled_inbox_notice_store.py) and a pure notice-building function
(see scheduled_inbox_notice.py). Not a general notification system: no
per-entry record, no read/unread/dismiss state, no delivery channel.
"""
