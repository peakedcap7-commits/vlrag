"""浏览器图片边界与公开状态契约，不连接模型或存储。"""

import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from src.api.app import create_app
from src.assets import MAX_BYTES, AssetService
from src.auth import LocalJWTAuthenticator
from src.memory import NullMemoryService

SECRET = "frontend-test-secret-" * 3


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, bucket, key, stream, length, content_type, metadata):
        self.objects[key] = (stream.read(), SimpleNamespace(metadata=metadata, content_type=content_type))

    def stat_object(self, bucket, key):
        return self.objects[key][1]

    def get_object(self, bucket, key):
        data = self.objects[key][0]
        return SimpleNamespace(stream=lambda _: iter([data]), close=lambda: None, release_conn=lambda: None)


class FakeMemory(NullMemoryService):
    enabled = True

    def __init__(self):
        self.state = None

    def record_run(self, identity, thread_id, payload, state):
        self.state = state
        return uuid4()

    def list_memory_events(self, identity, **kwargs):
        return {"cursor": None, "events": []}

    def decide_memory_event(self, identity, event_id, action):
        return {"event_id": str(event_id), "status": "confirmed"}

    def list_admin_episodes(self, identity, **kwargs):
        return {"cursor": None, "items": []}

    list_admin_runs = list_admin_episodes


class FakeService:
    def recommend(self, query, *_):
        return {"query": query, "anchor": None, "outfit_candidates": []}


def setup_client():
    auth = LocalJWTAuthenticator(SECRET)
    tenant, user, thread = uuid4(), uuid4(), uuid4()
    jwt_token = auth.issue(tenant, user)
    identity = auth.decode(jwt_token)
    storage = FakeStorage()
    assets = AssetService(storage, "test", SECRET)
    memory = FakeMemory()
    client = TestClient(create_app(service=FakeService(), authenticator=auth,
                                   memory_service=memory, asset_service=assets))
    client.headers["Authorization"] = f"Bearer {jwt_token}"
    return client, assets, storage, auth, identity, thread, memory


def image_bytes(fmt="PNG", size=(20, 20)):
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, format=fmt)
    return stream.getvalue()


def test_image_upload_blob_token_identity_and_thread_boundaries():
    client, assets, storage, auth, who, thread, _ = setup_client()
    result = client.post("/assets/images", data={"thread_id": str(thread)},
                         files={"file": ("pretend.txt", image_bytes(), "text/plain")})
    assert result.status_code == 200
    body = result.json()
    key = body["image_key"]
    assert storage.objects[key][0].startswith(b"\xff\xd8")
    url = body["content_url"].removeprefix("/api")
    content = client.get(url)
    assert content.status_code == 200 and content.headers["cache-control"] == "no-store"
    assert client.get("/auth/me").json()["user_id"] == str(who.user_id)
    expired = jwt.encode({"tenant": str(who.tenant_id), "sub": str(who.user_id), "key": key,
                          "aud": "asset-content-v1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                         assets.secret, algorithm="HS256")
    assert client.get(f"/assets/content/{expired}").status_code == 404
    assert client.get("/assets/content/invalid").status_code == 404
    for foreign in (auth.issue(who.tenant_id, uuid4()), auth.issue(uuid4(), who.user_id)):
        assert client.get(url, headers={"Authorization": f"Bearer {foreign}"}).status_code == 404
        assert client.post("/assets/urls", json={"keys": [key]}, headers={"Authorization": f"Bearer {foreign}"}).status_code == 404
    assert client.post("/assistant/message", json={"thread_id": str(uuid4()), "image_keys": [key]}).status_code == 404
    metadata = storage.objects[key][1].metadata
    metadata["expires-at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "data,status",
    [(b"not an image", 415), (image_bytes("GIF"), 415), (b"a" * (MAX_BYTES + 1), 413)],
    ids=("invalid", "gif", "too-large"),
)
def test_upload_rejects_invalid_format_and_size(data, status):
    client, _, _, _, _, thread, _ = setup_client()
    assert client.post("/assets/images", data={"thread_id": str(thread)},
                       files={"file": ("x.jpg", data, "image/jpeg")}).status_code == status


def test_decode_pixel_limit_and_key_prefix_denial():
    _, assets, _, _, who, thread, _ = setup_client()
    with pytest.raises(HTTPException) as error:
        assets.upload(who, thread, image_bytes(size=(5000, 4001)))
    assert error.value.status_code == 413
    for key in ("private/secret", "demo/items/../secret", "uploads//test", "demo/items/a\\b"):
        with pytest.raises(HTTPException) as error:
            assets.authorize(who, key)
        assert error.value.status_code == 404


def test_memory_and_admin_route_authorization_and_schema():
    client, _, _, auth, who, _, _ = setup_client()
    assert client.get("/assistant/memory-events").json() == {"cursor": None, "events": []}
    assert client.get("/assistant/memory-events?limit=101").status_code == 422
    assert client.post(f"/assistant/memory-events/{uuid4()}/decision", json={"action": "erase"}).status_code == 422
    for route in ("/admin/episodes", "/admin/runs"):
        assert client.get(route).status_code == 403
        admin = auth.issue(who.tenant_id, who.user_id, ["tenant_admin"])
        assert client.get(route, headers={"Authorization": f"Bearer {admin}"}).status_code == 200
    client.headers.pop("Authorization")
    assert client.get("/auth/me").status_code == 401


def test_server_generated_state_persisted_and_returned():
    client, _, _, _, _, thread, memory = setup_client()
    result = client.post("/assistant/message", json={"thread_id": str(thread), "message": "蓝色衬衫"})
    assert result.status_code == 200
    assert result.json()["conversation_state"] == memory.state["conversation_state"]
    assert result.json()["conversation_state"]["last_intent"] == "single_item_recommend"


def test_analyze_then_revise_uses_retrieval_facts_and_keeps_locked_item():
    from src.assistant_graph import build_assistant_graph
    from src.outfit_revise_service import OutfitReviseService

    catalog = {key: {"item_id": key, "object_key": f"demo/items/{key}.jpg", "category": category,
                     "sub_category": sub, "colors": [], "style": []}
               for key, category, sub in (("shirt", "上装", "衬衫"), ("skirt", "下装", "裙子"), ("pants", "下装", "裤子"))}
    service = SimpleNamespace(resolver=lambda key: catalog[key])
    analyzer = SimpleNamespace(analyze=lambda _: {"items": [{"matches": [catalog[key]]} for key in ("shirt", "skirt")]})
    advice = SimpleNamespace(generate=lambda _: {"verdict": "推荐", "summary": "可用", "strengths": [], "issues": [], "suggestions": []})
    candidates = SimpleNamespace(find_replacements=lambda *_: {"replacement_candidates": [catalog["pants"]], "message": "已替换"})
    graph = build_assistant_graph(service, analyzer, advice, OutfitReviseService(), candidates)
    first = graph.invoke({"message": "看看搭配", "image_keys": ["a", "b"], "top_k": 5, "retrieval_limit": 5})
    assert first["conversation_state"]["selected_item_ids"] == ["shirt", "skirt"]
    prior = {**first["conversation_state"], "locked_item_ids": ["shirt"]}
    revised = graph.invoke({"message": "不要裙子，换成裤子", "conversation_state": prior,
                            "top_k": 5, "retrieval_limit": 5})
    assert revised["conversation_state"]["selected_item_ids"] == ["shirt", "pants"]
    assert revised["conversation_state"]["locked_item_ids"] == ["shirt"]
    assert [item["object_key"] for item in revised["display_items"]] == ["demo/items/shirt.jpg", "demo/items/pants.jpg"]
    full = graph.invoke({"message": "重新搭一套", "conversation_state": prior, "top_k": 5, "retrieval_limit": 5})
    assert full["status"] == "not_ready"
    assert full["conversation_state"] == prior
