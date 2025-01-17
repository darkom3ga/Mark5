#!/usr/bin/env python3
import rospy
from std_msgs.msg import Float32MultiArray
from sensor_msgs.msg import Joy
a=[]
b=[]
c=[0,0,0,0,0,0,0]
global n

def callback(data):
    global b

    b=data.axes

    global a
    a=data.buttons
    global c
    if data.axes[6]==1:
        c[0]=1
    elif b[7]==1:
        c[0]=2
    elif b[6]==-1:
        c[0]=3
    elif a[3]==1:
        c[2]=1
    elif a[2]==1:
        c[2]=2
    elif a[1]==1:
        c[2]=3



    elif a[4]==1:    
        c[4]=1
    elif a[5]==1:
        c[4]=0
    elif b[7]==-1:
        c[5]=1
    elif a[0]==1:
        c[5]=-1

   

    if b[6]==0 and b[7]==0:
        c[0]=0
    if a[1]==0 and a[2]==0 and a[3]==0:
        c[2]=0
    if b[7]==0 and a[0]==0:
        c[5]=0
    c[6]=-1*b[0]
    c[1]=b[4]
    c[3]=b[1]




def talker():
    rospy.init_node('sum'),
    pub2=rospy.Publisher("publish",Float32MultiArray,queue_size=10)
    rate = rospy.Rate(10)

    while not rospy.is_shutdown():

        
        rospy.Subscriber('/joy', Joy, callback)
        arg1=Float32MultiArray()
        
        arg1.data=c
        
        pub2.publish(arg1)
        rate.sleep()
    rospy.spin()

if __name__ == '__main__':
    try:
        talker()
    except rospy.ROSInterruptException:
        pass