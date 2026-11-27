def test_hardcoded_config_overrides_environment(monkeypatch):
    import os
    import config
    for name in ('CLM_URL', 'CLM_USERNAME', 'CLM_PASSWORD', 'CLM_Zone', 'CLM_DATA_DIR'):
        monkeypatch.setenv(name, 'old value')
    monkeypatch.setenv('CLM_Zone', 'old zone')
    monkeypatch.setenv('CLM_HISTORY_PATH', '/old/path')
    monkeypatch.setattr(config, 'CLM_Zone', 'new zone')
    monkeypatch.setattr(config, 'CLM_URL', 'https://example.test')
    config.apply_config()
    assert os.environ['CLM_Zone'] == 'new zone'
    assert os.environ['CLM_URL'] == 'https://example.test'
    assert 'CLM_HISTORY_PATH' not in os.environ
