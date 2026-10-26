import os, rclpy
from rclpy.utilities import get_rmw_implementation_identifier
print('xml', os.environ.get('FASTRTPS_DEFAULT_PROFILES_FILE'))
print('rmw', get_rmw_implementation_identifier())
print('endpoints', ros_bridge.get_subscriptions_info_by_topic('/odom'))
print('clock', ros_bridge.clock.get_subscription_count(), ros_bridge.last_scan)
print('query', ros_bridge.failure)
