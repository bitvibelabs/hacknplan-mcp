"""Unit tests for the pure (no-network) logic of hacknplan-mcp.

These cover the functions that don't touch the API: stage-status inference,
response normalization, output formatting, project grouping, schedule bucketing,
and the Trello checklist flattening. Run with:  python3 -m pytest tests/ -q
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from client import HacknPlanClient  # noqa: E402
import formatting  # noqa: E402
import migrate  # noqa: E402
import portfolio  # noqa: E402


# ---- client.as_list: bare array vs paged envelope vs junk ------------------
def test_as_list_bare_array():
    assert HacknPlanClient.as_list([1, 2, 3]) == [1, 2, 3]

def test_as_list_paged_envelope():
    assert HacknPlanClient.as_list({"items": [{"a": 1}], "totalCount": 1}) == [{"a": 1}]

def test_as_list_results_key():
    assert HacknPlanClient.as_list({"results": [9]}) == [9]

def test_as_list_none_and_garbage():
    assert HacknPlanClient.as_list(None) == []
    assert HacknPlanClient.as_list({"nope": 1}) == []
    assert HacknPlanClient.as_list("string") == []


# ---- migrate.infer_status: Trello list name -> HacknPlan stage status ------
def test_infer_status_done_variants():
    for n in ["✅ Done", "Done", "Completed", "Shipped", "closed items"]:
        assert migrate.infer_status(n) == migrate.ST_COMPLETED

def test_infer_status_started_variants():
    for n in ["🚧 Doing", "In Progress", "WIP", "Review", "Testing", "⏸ Blocked"]:
        assert migrate.infer_status(n) == migrate.ST_STARTED

def test_infer_status_created_default():
    for n in ["📥 Inbox", "Backlog", "To Do", "🎯 This Week", "anything else"]:
        assert migrate.infer_status(n) == migrate.ST_CREATED

def test_status_enum_values_are_lowercase():
    # HacknPlan requires lowercase; "completed" is the literal API value "closed"
    assert migrate.ST_CREATED == "created"
    assert migrate.ST_STARTED == "started"
    assert migrate.ST_COMPLETED == "closed"


# ---- migrate._flat_checkitems: Trello checklists -> [(title, done)] --------
def test_flat_checkitems_single_list():
    cls = [{"name": "CL", "checkItems": [
        {"name": "a", "state": "complete"}, {"name": "b", "state": "incomplete"}]}]
    assert migrate._flat_checkitems(cls) == [("a", True), ("b", False)]

def test_flat_checkitems_multi_list_prefixes_name():
    cls = [{"name": "Front", "checkItems": [{"name": "x", "state": "complete"}]},
           {"name": "Back", "checkItems": [{"name": "y", "state": "incomplete"}]}]
    out = migrate._flat_checkitems(cls)
    assert ("[Front] x", True) in out and ("[Back] y", False) in out

def test_flat_checkitems_empty():
    assert migrate._flat_checkitems([]) == []


# ---- formatting --------------------------------------------------------------
def test_cap_truncates():
    big = "x" * 30000
    out = formatting.cap(big, limit=100)
    assert len(out) < 30000 and "truncated" in out

def test_cap_passthrough():
    assert formatting.cap("short") == "short"

def test_format_list_empty():
    assert "No tags" in formatting.format_list([], "tags")

def test_format_list_json():
    out = formatting.format_list([{"x": 1}], "tags", fmt="json")
    assert '"x": 1' in out


# ---- portfolio grouping + schedule bucketing --------------------------------
def test_group_of_default_when_unconfigured():
    portfolio.GROUPS = {}
    assert portfolio._group_of("Anything") == portfolio.DEFAULT_GROUP

def test_group_of_configured():
    portfolio.GROUPS = {"Team A": ["Web", "API"], "Personal": ["Notes"]}
    assert portfolio._group_of("API") == "Team A"
    assert portfolio._group_of("Notes") == "Personal"
    assert portfolio._group_of("Unknown") == portfolio.DEFAULT_GROUP
    portfolio.GROUPS = {}  # reset

def test_bar_proportions():
    assert portfolio._bar(0, 10) == "░" * 10
    assert portfolio._bar(100, 10) == "█" * 10
    assert portfolio._bar(50, 10).count("█") == 5

def test_schedule_markdown_buckets():
    data = {
        "generated_at": "2026-05-31T00:00:00+00:00",
        "schedule": [
            {"title": "late", "due": "2026-05-20", "days_left": -11, "project": "P", "group": "G"},
            {"title": "soon", "due": "2026-06-03", "days_left": 3, "project": "P", "group": "G"},
            {"title": "far", "due": "2026-08-01", "days_left": 62, "project": "P", "group": "G"},
        ],
    }
    md = portfolio.to_schedule_markdown(data)
    assert "Overdue" in md and "This week" in md and "Later" in md
    assert "11d overdue" in md and "3d left" in md

def test_schedule_markdown_empty():
    assert "No upcoming deadlines" in portfolio.to_schedule_markdown({"schedule": []})
