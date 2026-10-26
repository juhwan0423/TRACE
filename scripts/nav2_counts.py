from isaacsim.core.simulation_manager import SimulationManager
print('sub counts', ros_bridge.odom.get_subscription_count(), ros_bridge.tf.get_subscription_count(),ros_bridge.clock.get_subscription_count())
print('last scan', ros_bridge.last_scan, 'time', SimulationManager.get_simulation_time())
print('tf type', type(ros_bridge.tf))
print('nodes', ros_bridge.get_node_names_and_namespaces())
print('sim ready',demo._physics_ready, demo.failure, ros_bridge.failure)
print('frame time', frame_time.get_data())
