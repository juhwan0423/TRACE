from isaacsim.core.simulation_manager import SimulationManager
print('scan', ros_bridge.scan_messages, ros_bridge.last_scan, 'simulation', SimulationManager.get_simulation_time(), 'failure', ros_bridge.failure)
print('goal', inspection.run.status, 'commands', ros_bridge.commands)
