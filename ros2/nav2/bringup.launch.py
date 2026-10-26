from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import TimerAction


def generate_launch_description():
    names = ['map_server', 'planner_server', 'controller_server', 'bt_navigator']
    packages = ['nav2_map_server', 'nav2_planner', 'nav2_controller', 'nav2_bt_navigator']
    nodes = [Node(package=p, executable=n, name=n, output='screen', parameters=[
        '/workspace/ros2/nav2/params.yaml', {'use_sim_time': True}]) for p, n in zip(packages, names)]
    nodes.append(TimerAction(period=5.0, actions=[Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_navigation',
                      output='screen', parameters=[{'use_sim_time': True, 'autostart': True, 'node_names': names}])]))
    return LaunchDescription(nodes)
