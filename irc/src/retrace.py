#!/usr/bin/env python3

import subprocess
import rospy
from std_msgs.msg import String


class RemoteConnectionManager:
    def __init__(self):
        rospy.init_node('remote_connection_manager', anonymous=True)
        self.remote_device_ip = "192.168.1.10"  # Replace with your remote device IP
        self.gps_positions = []  # Store past GPS positions, format: [(latitude, longitude), ...]

        # Set up ROS publisher for retracing path
        self.path_retrace_pub = rospy.Publisher('/rover', String, queue_size=10)

    def ping_remote_device(self):
        try:
            subprocess.check_output(["ping", "-c", "1", self.remote_device_ip])
            return True
        except subprocess.CalledProcessError:
            return False

    def start_monitoring(self):
        rate = rospy.Rate(1)  # Adjust the rate as needed
        while not rospy.is_shutdown():
            if not self.ping_remote_device():
                rospy.logwarn("Connection lost! Retracing path to reestablish connection.")
                self.retrace_path()
            rate.sleep()

    def retrace_path(self):
        # Use the stored GPS positions to retrace the path
        for position in reversed(self.gps_positions):
            self.path_retrace_pub.publish(f"Retracing to: {position}")
            
            
            # Add logic here to attempt to reestablish connection using the retraced GPS position
        

    def gps_callback(self, data):
        # Assuming GPS data is published on topic '/gps'
        latitude, longitude = data.data.split(',')
        self.gps_positions.append((float(latitude), float(longitude)))

    def current_gps(self, data):
        # Assuming GPS data is published on topic '/gps'
        latitude, longitude = data.data.split(',')
        return (latitude,longitude)                            t
        

if __name__ == '__main__':
    remote_connection_manager = RemoteConnectionManager()

    # Subscribe to GPS data
    rospy.Subscriber('/mavros/gpsstatus/gps1/raw', String, remote_connection_manager.gps_callback)
    rospy.Subscriber('/mavros/gpsstatus/gps1/raw', String, remote_connection_manager.current_gps)

    # Start monitoring the remote connection
    remote_connection_manager.start_monitoring()

    rospy.spin()
