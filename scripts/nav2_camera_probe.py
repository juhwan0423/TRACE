import omni.replicator.core as rep
print('render product', demo.camera.render_product)
frame_time = rep.AnnotatorRegistry.get_annotator('IsaacReadSimulationTime')
frame_time.attach([demo.camera.render_product])
await app_utils.update_app_async(steps=5)
print('time', frame_time.get_data())
print('bridge', ros_bridge.failure, ros_bridge.commands)
