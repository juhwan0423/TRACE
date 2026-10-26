# Abort this owned capture workflow at its next scene boundary; preserve its finally cleanup.
def build_case(*args, **kwargs):
    raise RuntimeError('Capture workflow superseded by matched-view batch capture')
inspection.cancel()
print('owned capture cancellation requested')
