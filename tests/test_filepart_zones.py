import pytest
from clm import fileparts


def test_zone_configuration_requires_names(monkeypatch):
    monkeypatch.delenv('CLM_ZONES', raising=False)
    with pytest.raises(ValueError, match='CLM_ZONES'):
        fileparts.configured_zones()
    monkeypatch.setenv('CLM_ZONES', ' Zona Sur , Zona Norte ')
    assert fileparts.configured_zones() == ['Zona Sur', 'Zona Norte']


def test_process_visits_zones_in_order_with_shared_history(monkeypatch):
    monkeypatch.setenv('CLM_ZONES', 'Zona Sur,Zona Norte')
    calls = []
    monkeypatch.setattr(fileparts, 'processed_ids', lambda: {'already-done'})
    def run_zone(page, report, snapshot, zone, known):
        calls.append((zone, set(known)))
        known.add(zone)
        return 1
    monkeypatch.setattr(fileparts, 'process_zone', run_zone)
    class Page:
        url = 'https://example.test/start'
        def goto(self, url, **kwargs):
            calls.append(('navigate', url))
    assert fileparts.process_one(Page(), lambda _: None, lambda _: None) == 2
    assert calls == [('Zona Sur', {'already-done'}), ('navigate', 'https://example.test/start'),
                     ('Zona Norte', {'already-done', 'Zona Sur'})]
