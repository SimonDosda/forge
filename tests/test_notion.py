from datetime import date
from types import SimpleNamespace

from memory.notion import NotionMemory
from models import ActionType, GardenAction


class _FakePages:
    def __init__(self):
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "fake"}


class _FakeDatabases:
    def __init__(self, query_result=None, retrieve_result=None):
        self._query_result = query_result or {"results": []}
        self._retrieve_result = retrieve_result or {
            "properties": {"Plants": {"multi_select": {"options": []}}}
        }
        self.last_query: dict | None = None

    def query(self, **kwargs):
        self.last_query = kwargs
        return self._query_result

    def retrieve(self, **kwargs):
        return self._retrieve_result


def _client(query_result=None, retrieve_result=None):
    pages = _FakePages()
    databases = _FakeDatabases(query_result, retrieve_result)
    return SimpleNamespace(pages=pages, databases=databases), pages, databases


def test_log_action_builds_correct_properties_payload():
    client, pages, _ = _client()
    memory = NotionMemory("tok", "db-id", client=client)

    memory.log_action(
        GardenAction(
            name="Watered tomatoes",
            type=ActionType.WATERING,
            plants=("tomatoes", "basil"),
            notes="Heat wave",
            when=date(2026, 5, 6),
        )
    )

    assert len(pages.created) == 1
    payload = pages.created[0]
    assert payload["parent"] == {"database_id": "db-id"}
    props = payload["properties"]
    assert props["Name"]["title"][0]["text"]["content"] == "Watered tomatoes"
    assert props["Date"]["date"]["start"] == "2026-05-06"
    assert props["Type"]["select"]["name"] == "watering"
    assert [p["name"] for p in props["Plants"]["multi_select"]] == ["tomatoes", "basil"]
    assert props["Notes"]["rich_text"][0]["text"]["content"] == "Heat wave"


def test_recent_actions_parses_pages_into_domain():
    page = {
        "properties": {
            "Name": {"title": [{"plain_text": "Pruned roses"}]},
            "Date": {"date": {"start": "2026-05-05"}},
            "Type": {"select": {"name": "pruning"}},
            "Plants": {"multi_select": [{"name": "roses"}]},
            "Notes": {"rich_text": [{"plain_text": "spring trim"}]},
        }
    }
    client, _, databases = _client(query_result={"results": [page]})
    memory = NotionMemory("tok", "db-id", client=client)

    actions = memory.recent_actions(limit=5)

    assert databases.last_query["page_size"] == 5
    assert databases.last_query["database_id"] == "db-id"
    assert len(actions) == 1
    a = actions[0]
    assert a.name == "Pruned roses"
    assert a.type == ActionType.PRUNING
    assert a.plants == ("roses",)
    assert a.notes == "spring trim"
    assert a.when == date(2026, 5, 5)


def test_unknown_action_type_falls_back_to_other():
    page = {
        "properties": {
            "Name": {"title": [{"plain_text": "X"}]},
            "Date": {"date": {"start": "2026-05-05"}},
            "Type": {"select": {"name": "weeding"}},
            "Plants": {"multi_select": []},
            "Notes": {"rich_text": []},
        }
    }
    client, _, _ = _client(query_result={"results": [page]})
    memory = NotionMemory("tok", "db-id", client=client)

    assert memory.recent_actions()[0].type == ActionType.OTHER


def test_plants_reads_database_schema_options():
    schema = {
        "properties": {
            "Plants": {
                "multi_select": {
                    "options": [{"name": "tomatoes"}, {"name": "roses"}]
                }
            }
        }
    }
    client, _, _ = _client(retrieve_result=schema)
    memory = NotionMemory("tok", "db-id", client=client)

    assert memory.plants() == ["tomatoes", "roses"]
