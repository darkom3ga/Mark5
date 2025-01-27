import cv2
from flask import Flask, render_template, Response
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import threading
import numpy as np
# import paramiko
# import time
# import os 
# import subprocess
app = Flask(__name__)

# kratos_ip = "192.168.1.10"
# kratos_username = "kratos"
# kratos_password = "kratos123"
# ssh = paramiko.SSHClient()
# start_command="cd ~/Desktop/ipcam ; python3 hevc_indexfix4.py "
# stop_command = "ps -ef | grep '[p]ython.*hevc_indexfix4.py' | awk '{print $2}' | xargs sudo kill"
# is_ssh_connected = False


# def check_ping():
#     hostname = "192.168.1.10"
#     response = os.system("ping -c 1 " + hostname)
#     if response == 0:
#         pingstatus = True
#     else:
#         pingstatus = False
#     return pingstatus

# def sshconnectkratos(ip_sender, username, password):
#     global is_ssh_connected  
#     attempt = 1
#     total_attempt=3
#     while (attempt<=total_attempt):
#         if check_ping():
#             print("Ping Success")
#             try:
#                 print(f"Attempting to connect to {ip_sender} (Attempt {attempt})")
#                 ssh.load_system_host_keys()
#                 ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#                 ssh.connect(ip_sender, 
#                             username=username, 
#                             password=password,
#                             look_for_keys=False)
#                 is_ssh_connected = True
#                 print("SSH Connection successful")

#             except Exception as error_message:
                
#                 print("Unable to connect, retrying...")
#                 print(error_message)
#                 time.sleep(2) 
#                 attempt +=1
#         else :
#             print(f"Ping Issue : Connection Not established : No of attempt {attempt}/{total_attempt} \n")
#             attempt +=1

# def run_command_startup(start_command):
#     if is_ssh_connected:
#         try:
#             ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(start_command)
#             output = ssh_stdout.readlines()
#             print(output)
#         except Exception as e:
#             print(f"Error executing start command via SSH: {e}")


# def run_stop():
#     try:
#         subprocess.run(stop_command, shell=True, check=True)
#         print("Stopped hevc_indexfix4.py successfully.")
#     except subprocess.CalledProcessError as e:
#         print(f"Error stopping process: {e}")

# def keep_ssh_alive():
#     global is_ssh_connected
#     while True:
#         if is_ssh_connected:
#             try:
#                 ssh.exec_command("echo keepalive")
#                 time.sleep(60) 
#             except Exception as e:
#                 print("SSH connection lost, attempting to reconnect...")
#                 is_ssh_connected = False
#                 sshconnectkratos(kratos_ip, kratos_username, kratos_password)
#         else:
#             time.sleep(5)  
            
# def run_ssh_connection():
#     sshconnectkratos(kratos_ip, kratos_username, kratos_password)

Gst.init(None)

class GStreamerVideo:
    def __init__(self, pipeline_str):
        self.pipeline_str = pipeline_str
        self.pipeline = None
        self.video_sink = None
        self.running = False
        self.latest_frame = None
        self.frame_condition = threading.Condition()

    def start(self):
        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.video_sink = self.pipeline.get_by_name('appsink0')
        
        self.video_sink.set_property('emit-signals', True)
        self.video_sink.connect('new-sample', self.on_new_sample)
        
        self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True
        
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run)
        self.thread.daemon = True
        self.thread.start()

    def on_new_sample(self, sink):
        sample = sink.emit('pull-sample')
        if sample:
            buf = sample.get_buffer()
            caps = sample.get_caps()
            
            caps_struct = caps.get_structure(0)
            width = caps_struct.get_value('width')
            height = caps_struct.get_value('height')
            
            success, map_info = buf.map(Gst.MapFlags.READ)
            if success:
                frame = np.ndarray(
                    shape=(height, width, 3),
                    dtype=np.uint8,
                    buffer=map_info.data
                )
                
                with self.frame_condition:
                    self.latest_frame = frame.copy()
                    self.frame_condition.notify_all()
                
                buf.unmap(map_info)
        
        return Gst.FlowReturn.OK

    def get_frame(self):
        with self.frame_condition:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None

    def stop(self):
        self.running = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.loop:
            self.loop.quit()
        if self.thread:
            self.thread.join()


camera_ports = {
    'Camera 1': 'udpsrc port=9000 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0',
    'Camera 2': 'udpsrc port=9001 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0',
    'Camera 3': 'udpsrc port=9002 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0',
    'Camera 4': 'udpsrc port=9003 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0',
    'Camera 5': 'udpsrc port=9004 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0',
    'Camera 6': 'udpsrc port=9005 ! application/x-rtp,payload=96 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink name=appsink0'
}

camera_instances = {}

@app.route("/")
def index():
    return render_template('index.html', camera_ports=camera_ports)

def generate_frames(camera_instance):
    while camera_instance.running:
        frame = camera_instance.get_frame()
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route("/video_feed/<camera_name>")
def video_feed(camera_name):
    if camera_name not in camera_instances:
        pipeline_str = camera_ports.get(camera_name)
        if pipeline_str:
            camera_instances[camera_name] = GStreamerVideo(pipeline_str)
            camera_instances[camera_name].start()
        else:
            return "Camera not found", 404

    return Response(
        generate_frames(camera_instances[camera_name]),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
# @app.route("/refresh" )
# def refresh():
#     if is_ssh_connected:
#         run_stop()
#     run_command_startup(start_command)


if __name__ == "__main__":
    try:
        # ssh_thread = threading.Thread(target=run_ssh_connection)
        # ssh_thread.start()
        # keep_alive_thread = threading.Thread(target=keep_ssh_alive)
        # keep_alive_thread.daemon = True
        # keep_alive_thread.start()
        app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
        
    finally:
        for camera in camera_instances.values():
            camera.stop()