def test_logging_module_imports_and_configures_level():
    import logging

    from arrow.core.logging import setup_logging

    previous = logging.getLogger().level
    try:
        setup_logging('DEBUG')
        assert logging.getLogger().level == logging.DEBUG
    finally:
        logging.getLogger().setLevel(previous)
