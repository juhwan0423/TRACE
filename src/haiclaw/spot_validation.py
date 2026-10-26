"""Evaluate frozen Spot acceptance limits against measured physics telemetry."""
import math


def evaluate(records, config, failure=None):
    phases = {p: [r for r in records if r['phase']==p] for p in config['phases_seconds']}
    if failure or any(not phases[p] for p in phases):
        return {'passed': False, 'failure': failure or 'missing phase telemetry'}
    valid = [r for r in records if r['t'] >= config['phases_seconds']['settle']]
    hold, forward, turn, stop = (phases[p] for p in ('hold','forward','turn','stop'))
    def distance(a, b):
        return math.hypot(b['position'][0]-a['position'][0], b['position'][1]-a['position'][1])
    def speed(r):
        return math.hypot(*r['velocity'][:2])
    residual = [r for r in stop if r['t'] >= stop[0]['t']+config['stop_grace_seconds']]
    if not residual:
        return {'passed':False, 'failure':'missing stop residual window'}
    yaw_change = sum((b['yaw']-a['yaw']+math.pi)%(2*math.pi)-math.pi for a,b in zip(turn,turn[1:]))
    mean_forward = sum(r['velocity'][0]*math.cos(r['yaw'])+r['velocity'][1]*math.sin(r['yaw']) for r in forward)/len(forward)
    mean_turn = sum(r['angular_velocity'][2] for r in turn)/len(turn)
    metrics = dict(height_min=min(r['position'][2] for r in valid), height_max=max(r['position'][2] for r in valid),
                   tilt_max=max(r['tilt_deg'] for r in valid), hold_drift=distance(hold[0],hold[-1]),
                   forward_distance=distance(forward[0],forward[-1]), forward_mean_speed=mean_forward,
                   turn_yaw=yaw_change, turn_mean_rate=mean_turn,
                   stop_residual=max(distance(residual[0],r) for r in residual),
                   stop_final_speed=sum(speed(r) for r in stop[-25:])/len(stop[-25:]))
    tests = dict(height=config['height_range_m'][0]<=metrics['height_min'] and metrics['height_max']<=config['height_range_m'][1],
                 tilt=metrics['tilt_max']<=config['max_tilt_degrees'],
                 hold=metrics['hold_drift']<=config['hold_drift_max_m'],
                 forward_distance=metrics['forward_distance']>=config['forward_distance_min_m'],
                 forward_speed=config['forward_mean_speed_range_mps'][0]<=mean_forward<=config['forward_mean_speed_range_mps'][1],
                 turn_yaw=yaw_change>=config['turn_yaw_min_rad'],
                 turn_rate=config['turn_mean_rate_range_radps'][0]<=mean_turn<=config['turn_mean_rate_range_radps'][1],
                 stop_residual=metrics['stop_residual']<=config['stop_residual_max_m'],
                 stop_speed=metrics['stop_final_speed']<=config['stop_final_speed_max_mps'])
    return dict(passed=all(tests.values()), checks=tests, metrics=metrics, failure=None)
