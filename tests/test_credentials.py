from forecast_bust.acquisition import load_cds_credentials


def test_loads_cds_yaml_credentials(tmp_path):
    path = tmp_path / "credentials.txt"
    path.write_text("url: https://example.invalid/api\nkey: not-a-real-secret\n")
    url, key = load_cds_credentials(path)
    assert url == "https://example.invalid/api"
    assert key == "not-a-real-secret"
