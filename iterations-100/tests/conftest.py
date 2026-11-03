"""Configuration pytest : marqueur « lent » (exécution réelle de la réduction)."""


def pytest_configure(config):
    config.addinivalue_line("markers", "lent: exécution réelle de nexus-core (quelques secondes)")
