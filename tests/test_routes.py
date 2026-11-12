def test_landing_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Skin Index" in response.data


def test_every_page_loads_on_an_empty_database(client):
    # no placeholder routes are left; each page must work with nothing loaded
    for path in ["/", "/products", "/compare", "/insights"]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_static_files_are_served(client):
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/main.js").status_code == 200
