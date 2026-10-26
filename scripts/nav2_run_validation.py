import time
await replay('hold')
while demo.elapsed < 3.:
    await app_utils.update_app_async(steps=5)
inspection.start()
print('run', inspection.output)
while inspection.run.status == 'moving':
    await app_utils.update_app_async(steps=5)
end = time.monotonic()+30
while inspection.run.status == 'arrived' and inspection.run.evidence is None and time.monotonic()<end:
    await app_utils.update_app_async(steps=5)
inspection.save()
demo.save()
print('result', vars(inspection.run), 'capture failure', inspection.capture_failure)
