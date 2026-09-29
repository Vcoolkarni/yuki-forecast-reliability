from forecast_bust.acquisition import download_gfs_grib_message


def test_gfs_downloader_requires_unique_inventory_match(monkeypatch, tmp_path):
    class Response:
        text = "1:0:d=2026092500:APCP:surface:x\n2:10:d=2026092500:APCP:surface:y"
        def raise_for_status(self): pass
    monkeypatch.setattr("forecast_bust.acquisition.requests.get", lambda *a, **k: Response())
    try:
        download_gfs_grib_message("https://example.invalid/file", tmp_path / "x.grb2")
        assert False
    except ValueError as error:
        assert "exactly one" in str(error)
