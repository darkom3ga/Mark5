#!/usr/bin/env python3
import time
import rospy
from geometry_msgs.msg import Point
from std_msgs.msg import Int16MultiArray

if __name__=='__main__':
    rospy.init_node("Test_drive")
    rospy.logwarn("ENTERING TESTING SCRIPT")
    rospy.loginfo("CHECKING DRIVE")
    point=Point()
    pub=rospy.Publisher("/rover",Point,queue_size=10)
    point.x=15
    point.z=15
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.z=0
    pub.publish(point)
    time.sleep(1)
    point.x=-15
    point.z=-15
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.z=0
    pub.publish(point)
    time.sleep(1)
    point.x=15
    point.z=-15
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.z=0
    pub.publish(point)
    time.sleep(1)
    point.x=-15
    point.z=15
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    rospy.loginfo("FINISHED CHECKING DRIVE")
    
    rospy.loginfo("CHECKING GIMBAL")
    pub=rospy.Publisher("/cam_gimble",Point,queue_size=10)
    point.x=1
    point.y=0
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=-1
    point.y=0
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=1
    point.y=0
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.y=1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.y=-1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=0
    point.y=1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=1
    point.y=1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=-1
    point.y=-1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=1
    point.y=1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=1
    point.y=-1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=-1
    point.y=1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    point.x=1
    point.y=-1
    for i in range(1,3):
        pub.publish(point)
        time.sleep(1)
    rospy.loginfo("FINISHED CHECKING GIMBAL")
    
    rospy.loginfo("CHECKING ARM : BASE AND BEVEL")
    msg=Int16MultiArray()
    pub = rospy.Publisher("/control2", Int16MultiArray, queue_size=1)
    msg.data=[1,125,0,0,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[2,125,0,0,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[1,125,0,0,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,0,1,125,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,0,2,125,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,0,3,125,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,0,4,125,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    rospy.loginfo("FINISHED CHECKING ARM : BASE AND BEVEL")

    rospy.loginfo("CHECKING ARM : LINEAR ACTUATORS 1 AND 2")
    pub = rospy.Publisher("/control1", Int16MultiArray, queue_size=1)
    msg.data=[255,0,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[-255,0,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,255,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    msg.data=[0,-255,0]
    for i in range(1,3):
        pub.publish(msg)
        time.sleep(1)
    rospy.loginfo("FINISHED CHECKING ARM : LINEAR ACTUATORS 1 AND 2")

    rospy.loginfo("CHECKING GRIPPER")
    msg2=Int16MultiArray()
    pub2=rospy.Publisher("/control2", Int16MultiArray, queue_size=1)
    msg.data=[0,0,2]
    msg2.data=[0,0,0,0,1]
    for i in range(1,3):
        pub.publish(msg)
        pub2.publish(msg2)
        time.sleep(1)
    msg2.data=[0,0,0,0,2]
    for i in range(1,3):
        pub.publish(msg)
        pub2.publish(msg2)
        time.sleep(1)
    msg.data=[0,0,0]
    msg2.data=[0,0,0,0,0]
    for i in range(1,3):
        pub.publish(msg)
        pub2.publish(msg2)
        time.sleep(1)
    rospy.loginfo("FINISHED CHECKING GRIPPER")
    rospy.logwarn("EXITING TESTING SCRIPT")
