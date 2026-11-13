# Run in the owned Spot Python Server context after Spot scene setup.
import importlib
importlib.invalidate_caches()
import omni.kit.app
import omni.usd
import carb.settings
if (carb.settings.get_settings().get('/haiclaw/workspace') != str(root)
        or omni.usd.get_context().get_stage().GetRootLayer().identifier != spot_stage_id):
    raise RuntimeError('Refusing ROS attachment to a replaced or unowned stage')
import tracebot.navigation
importlib.reload(tracebot.navigation)
from pxr import Usd, UsdGeom
bounds = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default', 'render']).ComputeWorldBound(
    omni.usd.get_context().get_stage().GetPrimAtPath('/World/Equipment')).ComputeAlignedRange()
expected = (-1.2, -.6, 0., 1.2, .6, 2.4)
actual = (*bounds.GetMin(), *bounds.GetMax())
if any(abs(a-b) > 1e-5 for a,b in zip(actual,expected)):
    raise RuntimeError('Equipment geometry differs from the navigation map; regenerate the map first')
if 'inspection' in globals():
    inspection.close()
if 'ros_bridge' in globals():
    ros_bridge.close()
if not hasattr(demo, 'velocity_lease'):
    raise RuntimeError('Reload the owned Spot demo from current source first')
import spot_ros_bridge
importlib.reload(spot_ros_bridge)
ros_bridge = spot_ros_bridge.SpotROS(demo)
ros_bridge.update_subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(ros_bridge.update, name='HAICLAW ROS transport')
print('ROS bridge attached; navigation remains disabled until explicit start')
