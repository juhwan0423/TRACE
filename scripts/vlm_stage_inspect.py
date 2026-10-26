import omni.usd, omni.timeline
print('stage',omni.usd.get_context().get_stage().GetRootLayer().identifier)
print('owned stage',globals().get('spot_stage_id'))
print('playing',omni.timeline.get_timeline_interface().is_playing())
print('navigation',inspection.run.status if inspection.run else None)
print('human root exists',bool(omni.usd.get_context().get_stage().GetPrimAtPath('/World/HAIVLM')))
