"""Run via official Python Server client before any Spot spawn."""
import json
from dataclasses import asdict
from pathlib import Path
import omni.client
import omni.usd
from isaacsim.robot.policy.examples import get_spot_spec, PolicyEnvConfig
root = Path(workspace)
spec = get_spot_spec()
artifact = spec.engines['physx']
paths = {'usd': spec.usd_path, 'model': artifact.model_path,
         'env': artifact.env_config_path, 'descriptor': artifact.descriptor_path}
report = {'engine': 'physx', 'paths': paths, 'expected_model_sha256': artifact.model_sha256,
          'stage_before': omni.usd.get_context().get_stage_url(), 'files': {}}
for name, path in paths.items():
    result, entry = await omni.client.stat_async(path)
    report['files'][name] = {'result': str(result), 'size': entry.size if entry else None}
(root/'artifacts/spot/preflight.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if any('OK' not in x['result'] for x in report['files'].values()):
    raise RuntimeError('Spot artifact unavailable; see exact paths in preflight.json')
if report['files']['model']['size'] > 10_000_000:
    raise RuntimeError('Policy exceeds 10 MB local task limit; do not download automatically')
env = PolicyEnvConfig.from_file(artifact.env_config_path)
report['timing'] = asdict(env.timing)
report['descriptor'] = artifact.load_descriptor()
assert abs(env.timing.physics_dt-.002) < 1e-9, 'Export differs from official Spot 500Hz example'
(root/'artifacts/spot/preflight.json').write_text(json.dumps(report, indent=2, default=str))
print('TIMING', report['timing'])
