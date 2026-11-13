"""Control an authored worker scenario in the existing Real2Sim session.

No USD source files are saved or reloaded. Diagnostic segmentation is evaluator
data only and is never sent to the planner or the loss monitor.
"""
import argparse
import json
from pathlib import Path
import time

from real2sim_control import request

ROOT = Path(__file__).resolve().parents[1]

CAPTURE = '''
import numpy as np
from PIL import Image
from isaacsim.core.simulation_manager import SimulationManager
import omni.kit.app
import omni.replicator.core as rep
if measure and not globals().get('trace_diagnostic_segments'):
    trace_diagnostic_segments = {}
    for key, (product, rgb, clock) in real2sim_monitor_sensors.items():
        annotator = rep.AnnotatorRegistry.get_annotator('instance_id_segmentation')
        annotator.attach([product])
        trace_diagnostic_segments[key] = annotator
after = SimulationManager.get_simulation_time()
for _ in range(120):
    await omni.kit.app.get_app().next_update_async()
    if all(float(clock.get_data().get('simulationTime', -1)) > after
           for _, rgb, clock in real2sim_monitor_sensors.values()):
        break
else:
    raise RuntimeError('No fresh camera frame; is the simulation playing?')
directory = Path(output_dir)
directory.mkdir(parents=True, exist_ok=True)
result = dict(snapshot=real2sim_navigation.snapshot(), frames={})
for key, (_, rgb, clock) in real2sim_monitor_sensors.items():
    pixels = np.asarray(rgb.get_data())[:, :, :3].copy()
    stamp = float(clock.get_data().get('simulationTime', -1))
    path = directory / (key + '.png')
    Image.fromarray(pixels).save(path)
    row = dict(path=str(path), capture_time=stamp, width=pixels.shape[1],
               height=pixels.shape[0], mean_rgb=float(pixels.mean()),
               pixel_variance=float(pixels.var()))
    if measure:
        data = trace_diagnostic_segments[key].get_data()
        ids = [int(i) for i, label in data['info']['idToLabels'].items()
               if '/World/Human/' in str(label)]
        mask = np.isin(data['data'], ids)
        row['evaluator_human_pixels'] = int(mask.sum())
        Image.fromarray(mask.astype(np.uint8) * 255).save(directory / (key + '-human-mask.png'))
    result['frames'][key] = row
if globals().get('real2sim_worker_scenario'):
    result['evaluator_scenario'] = real2sim_worker_scenario.state()
(directory / 'capture.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'restore', 'state', 'capture'])
    parser.add_argument('--position', type=float, nargs=3, metavar=('X', 'Y', 'Z'),
                        help='World bounding-box center X/Y and minimum Z in meters')
    parser.add_argument('--rotation', type=float, nargs=3, default=[0, 0, 0],
                        metavar=('RX', 'RY', 'RZ'), help='World Euler delta, degrees')
    parser.add_argument('--frame', type=float, default=0)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'artifacts/worker_scenario' / str(time.time_ns()))
    parser.add_argument('--measure', action='store_true', help='Save evaluator-only segmentation counts')
    args = parser.parse_args()
    if args.action == 'apply' and args.position is None:
        parser.error('apply requires --position X Y Z')
    if args.action == 'capture':
        result = request(CAPTURE, dict(output_dir=str(args.output.resolve()), measure=args.measure), timeout=40)
    else:
        source = (ROOT / 'scripts/real2sim_worker_scene.py').read_text()
        request("exec(worker_source); print(json.dumps(real2sim_worker_scenario.state()))",
                dict(worker_source=source), timeout=40)
        if args.action == 'apply':
            code = 'real2sim_worker_scenario.apply(position, rotation, frame)'
        else:
            code = 'real2sim_worker_scenario.' + args.action + '()'
        result = request('print(json.dumps(' + code + '))',
                         dict(position=args.position, rotation=args.rotation, frame=args.frame), timeout=40)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
