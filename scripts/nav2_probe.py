import rclpy
import omni.physx
import omni.replicator.core as rep
print('rclpy', rclpy.__file__)
print('query', omni.physx.get_physx_scene_query_interface().raycast_all.__doc__)
print('camera properties', [x for x in dir(demo.camera) if 'render' in x or 'product' in x])
print('time annotator', rep.AnnotatorRegistry.get_annotator('IsaacReadSimulationTime'))
print('state', demo.state())
