# -*- coding: utf-8 -*-
"""Keyed project base classes.

A keyed project stores a list of records (default field ``items``) and merges
incoming snapshots by primary key instead of replacing the whole list. This is
the shared template for schedule / bottle / wishpool.
"""
from __future__ import annotations

from ..project import JsonDocProject, merge_items_by_key, find_item_by_key
from .coin import CoinProject


class KeyedJsonDocProject(JsonDocProject):
    base = "keyed"
    merge_field = "items"

    def item_key(self, item):
        if isinstance(item, dict):
            return str(item.get("id") or item.get("key") or "")
        return ""

    def merge(self, old, incoming, payload):
        merged = dict(incoming)
        merged[self.merge_field] = merge_items_by_key(
            old.get(self.merge_field), incoming.get(self.merge_field), self.item_key
        )
        return merged

    def find_item(self, data, item_id):
        return find_item_by_key(data, item_id, self.merge_field, self.item_key)


class KeyedCoinProject(CoinProject):
    base = "keyed-coin"
    merge_field = "items"

    def item_key(self, item):
        if isinstance(item, dict):
            return str(item.get("id") or item.get("key") or "")
        return ""

    def merge(self, old, incoming, payload):
        merged = dict(incoming)
        merged[self.merge_field] = merge_items_by_key(
            old.get(self.merge_field), incoming.get(self.merge_field), self.item_key
        )
        return merged

    def find_item(self, data, item_id):
        return find_item_by_key(data, item_id, self.merge_field, self.item_key)
