print('odom pub', str(ros_bridge.get_publishers_info_by_topic('/odom')[0]))
for endpoint in ros_bridge.get_subscriptions_info_by_topic('/odom'):
    print('odom sub',str(endpoint))
