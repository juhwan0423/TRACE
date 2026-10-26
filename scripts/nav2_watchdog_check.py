import time, json
# No active Nav2 action: inject one received command into the real policy sink.
assert inspection.run.status != 'moving'
demo.start('nav2')
start = time.monotonic()
demo.velocity_lease.receive(.25, 0., .3, start)
trace=[]
while time.monotonic()-start < .8:
    await app_utils.update_app_async(steps=1)
    trace.append(dict(wall_elapsed=time.monotonic()-start, command=demo._base_command.tolist()))
demo.hold()
result=dict(passed=any(any(v!=0 for v in r['command']) for r in trace)
            and all(r['command']==[0.,0.,0.] for r in trace if r['wall_elapsed']>.30),
            method='single command injected at actual policy sink; ROS transport separately verified', trace=trace)
(root/'artifacts/nav2/watchdog.json').write_text(json.dumps(result,indent=2))
print('watchdog',result['passed'])
