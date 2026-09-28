"""Feature domains.

Each subpackage owns its own entities, persistence and business rules and does
not import from its sibling. Where the domains need to refer to each other they
do so by primary-key value only, which is the seam a later assignment would cut
along to split them into separate services.
"""
