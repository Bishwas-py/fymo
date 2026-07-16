"""Broadcast providers and the owned-schema-objects declaration.

The postgres broadcast provider is pure LISTEN/NOTIFY, it creates no
tables, functions, or types, so it must declare exactly nothing (issue
#51 named it as a suspect; the honest answer is an empty list).
"""
from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.providers.postgres import PostgresBroadcastProvider


def test_base_broadcast_provider_owns_no_schema_objects():
    assert BaseBroadcastProvider().owned_schema_objects() == ()


def test_postgres_broadcast_provider_owns_no_schema_objects():
    assert PostgresBroadcastProvider().owned_schema_objects() == ()
