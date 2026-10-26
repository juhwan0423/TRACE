print('inspection', vars(inspection.run) if inspection.run else None)
print('goal handle', inspection.handle)
print('mode', demo.mode, 'failure', demo.failure, 'bridge', ros_bridge.failure, 'commands', ros_bridge.commands)
print('pose', demo.state()[0], demo.state()[4])
