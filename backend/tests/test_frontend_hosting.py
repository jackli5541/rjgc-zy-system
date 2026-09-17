from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings


def test_frontend_dist_spa_cache_and_gzip(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>coursework app</main>", encoding="utf-8")
    script = "const payload = 'coursework';\n" * 200
    (assets / "app-123.js").write_text(script, encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist", dist)

    client = TestClient(app)
    index = client.get("/")
    assert index.status_code == 200
    assert index.text == "<main>coursework app</main>"
    assert index.headers["cache-control"] == "no-cache"

    spa_route = client.get("/assignments/current")
    assert spa_route.status_code == 200
    assert spa_route.text == index.text
    assert spa_route.headers["cache-control"] == "no-cache"

    asset = client.get("/assets/app-123.js", headers={"Accept-Encoding": "gzip"})
    assert asset.status_code == 200
    assert asset.text == script
    assert asset.headers["content-encoding"] == "gzip"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "Accept-Encoding" in asset.headers["vary"]

    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/v1/missing").status_code == 404
    assert client.post("/api/v1/missing").status_code == 404


def test_frontend_returns_404_when_dist_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frontend_dist", tmp_path / "missing")
    response = TestClient(app).get("/")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
