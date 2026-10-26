import time
await reset_and_navigate()
while inspection.run.status == 'moving':
    await app_utils.update_app_async(steps=5)
end = time.monotonic()+30
while inspection.run.status=='arrived' and inspection.run.evidence is None and time.monotonic()<end:
    await app_utils.update_app_async(steps=5)
inspection.save()
print(inspection.output, inspection.run.status, inspection.run.evidence)
