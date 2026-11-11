def test_landing_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Skin Index" in response.data


def test_placeholder_routes_respond(client):
    for path in ["/products/1", "/compare", "/insights"]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_static_files_are_served(client):
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/main.js").status_code == 200
