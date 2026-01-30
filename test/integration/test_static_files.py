"""Integration tests for static file serving."""
import re
import pytest


@pytest.mark.integration
class TestStaticFiles:
    def test_serve_exercise_html(self, client):
        """Exercise path should serve index.html."""
        response = client.get("/exercise")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_index_has_cache_busting(self, client):
        """Index should have cache-busting query params injected."""
        response = client.get("/exercise")
        content = response.text
        assert "?v=" in content

    def test_index_contains_expected_elements(self, client):
        """Index should contain stylesheet and script references."""
        response = client.get("/exercise")
        content = response.text
        assert "styles.css" in content
        assert "app.js" in content

    def test_serve_css(self, client):
        """Should serve styles.css with correct content type."""
        response = client.get("/styles.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_css_has_no_cache_header(self, client):
        """CSS should have no-cache header."""
        response = client.get("/styles.css")
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control

    def test_serve_js(self, client):
        """Should serve JavaScript files."""
        response = client.get("/js/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_js_has_no_cache_header(self, client):
        """JS files should have no-cache header."""
        response = client.get("/js/app.js")
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control

    def test_missing_js_file_returns_404(self, client):
        """Missing JS files should return 404."""
        response = client.get("/js/nonexistent.js")
        assert response.status_code == 404

    def test_missing_css_file_returns_404(self, client, test_app, tmp_path, monkeypatch):
        """Missing CSS file should return 404."""
        import server
        # Create public dir without styles.css
        public_dir = tmp_path / "public_no_css"
        public_dir.mkdir()
        (public_dir / "index.html").write_text("<html></html>")
        monkeypatch.setattr(server, "PUBLIC_DIR", public_dir)

        response = client.get("/styles.css")
        assert response.status_code == 404

    def test_cache_busting_version_format(self, client):
        """Cache busting version should be 8 hex characters."""
        response = client.get("/exercise")
        content = response.text

        # Should have version query param
        assert "?v=" in content

        # Version should be 8 hex characters
        match = re.search(r'\?v=([a-f0-9]{8})', content)
        assert match is not None

    def test_html_has_no_cache_header(self, client):
        """HTML page should have no-cache header."""
        response = client.get("/exercise")
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control


@pytest.mark.integration
class TestCORS:
    def test_cors_headers_on_api_response(self, client):
        """API responses should include CORS headers when Origin is present."""
        response = client.get(
            "/api/workout/status",
            headers={"Origin": "http://example.com"}
        )
        assert response.headers.get("access-control-allow-origin") == "*"

    def test_cors_preflight_request(self, client):
        """OPTIONS preflight requests should return CORS headers."""
        response = client.options(
            "/api/workout/sync",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            }
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers
