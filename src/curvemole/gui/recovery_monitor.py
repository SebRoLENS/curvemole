"""Persistent 50-copy warning bands; counting does not decode large archives."""


def warning_band(count):
    return count // 50 if count >= 50 else 0


def should_warn(settings, count, *, announce=False):
    settings.sync()
    band = warning_band(count)
    if band == 0:
        settings.setValue("recovery/warning_band", 0)
        settings.sync()
        return False
    previous = settings.value("recovery/warning_band", 0, type=int)
    if announce and band > previous:
        settings.setValue("recovery/warning_band", band)
        settings.sync()
        return True
    return False
