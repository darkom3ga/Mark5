import cv2
from flask import Flask, render_template, Response, redirect, url_for ,request ,jsonify

import gi
import threading
import numpy as np
import paramiko
import time
import os

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

app = Flask(__name__)

Gst.init(None)

class GStreamerVideo:
    def __init__(self, pipeline_str):
        self.pipeline_str = pipeline_str
        self.pipeline = None
        self.video_sink = None
        self.running = False
        self.latest_frame = None
        self.frame_condition = threading.Condition()
        self.frame_queue = []
        self.max_queue_size = 20  # Increase queue size to buffer a few frames for smoother playback

    def start(self):
        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.video_sink = self.pipeline.get_by_name('appsink0')

        self.video_sink.set_property('emit-signals', True)
        self.video_sink.set_property('max-buffers', 50)  # Larger buffer size to reduce lag
        self.video_sink.set_property('drop', False)  # Prevent dropping frames
        self.video_sink.set_property('sync', False)
        self.video_sink.connect('new-sample', self.on_new_sample)

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise Exception("Unable to set the pipeline to the playing state")
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
                try:
                    frame = np.ndarray(
                        shape=(height, width, 3),
                        dtype=np.uint8,
                        buffer=map_info.data
                    ).copy()

                    with self.frame_condition:
                        self.frame_queue.append(frame)
                        if len(self.frame_queue) > self.max_queue_size:
                            self.frame_queue.pop(0)  # Remove oldest frame
                        self.frame_condition.notify_all()
                finally:
                    buf.unmap(map_info)

        return Gst.FlowReturn.OK

    def get_frame(self):
        with self.frame_condition:
            if self.frame_queue:
                return self.frame_queue.pop(0)  # Fetch the earliest frame in the queue
            return None

    def stop(self):
        self.running = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.loop:
            self.loop.quit()
        if self.thread:
            self.thread.join()

pipeline_template = """
    udpsrc port={} buffer-size=921600 ! 
    application/x-rtp,payload=96 ! 
    rtph264depay ! 
    h264parse ! 
    avdec_h264 max-threads=4 ! 
    videoconvert ! 
    video/x-raw,format=BGR ! 
    appsink name=appsink0 max-buffers=20 drop=false sync=false
"""




camera_ports = {
    '9000': pipeline_template.format(9000),
    '9001': pipeline_template.format(9001),
    '9002': pipeline_template.format(9002),
    '9003': pipeline_template.format(9003),
    '9004': pipeline_template.format(9004),
    '9005': pipeline_template.format(9005),
    '9006': pipeline_template.format(9006),
    '9007': pipeline_template.format(9007),
    '9008': pipeline_template.format(9008)
}

camera_instances = {}

# SSH Configuration
kratos_ip = "192.168.1.10"
kratos_username = "kratos"
kratos_password = "kratos123"
ssh = paramiko.SSHClient()
start_command = "cd ~/h264final_fixed/Sender ; python3 hard.py "

class SSHManager:
    def __init__(self):
        self.ssh = paramiko.SSHClient()
        self.is_ssh_connected = False
        self.stop_thread = False
        self.ssh_thread = None

    def check_ping(self, ip):
        response = os.system("ping -c 1 " + ip)
        return response == 0

    def connect(self, ip_sender, username, password, start_command):
        attempt = 1
        total_attempt = 3

        while attempt <= total_attempt and not self.stop_thread:
            if self.check_ping(ip_sender):
                print("Ping Success")
                try:
                    print(f"Attempting to connect to {ip_sender} (Attempt {attempt})")
                    self.ssh.load_system_host_keys()
                    self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    self.ssh.connect(
                        ip_sender,
                        username=username,
                        password=password,
                        look_for_keys=False
                    )
                    self.is_ssh_connected = True
                    print("SSH Connection successful")
                    
                    if self.is_ssh_connected:
                        try:
                            ssh_stdin, ssh_stdout, ssh_stderr = self.ssh.exec_command(start_command)
                            output = ssh_stdout.readlines()
                            print(output)
                            while not self.stop_thread:
                                time.sleep(1)
                                
                        except Exception as e:
                            print(f"Error executing start command via SSH: {e}")
                        finally:
                            if self.stop_thread:
                                break
                    return

                except Exception as error_message:
                    print("Unable to connect, retrying...")
                    print(error_message)
                    time.sleep(2)
                    attempt += 1
            else:
                print(f"Ping Issue : Connection Not established : No of attempt {attempt}/{total_attempt}")
                attempt += 1

ssh_manager = SSHManager()


@app.route("/")
def index():
    return render_template('index2.html', camera_ports=camera_ports)

def generate_frames(camera_instance):
    while camera_instance.running:
        frame = camera_instance.get_frame()
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])  # Lower JPEG quality for faster encoding
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.1)  # Avoid busy-wait and reduce CPU usage

import logging
from flask_socketio import SocketIO, emit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
stored_camera_list = []
stored_active_camera_list =[]
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)


@app.route('/get_cameras', methods=['GET'])
def get_camera_list():
    # Return the stored list of cameras
    return jsonify(stored_camera_list)

@app.route('/get_cameras', methods=['POST'])
def receive_camera_list():
    try:
        # Get the camera list from the request
        data = request.get_json()
        devices = data.get('devices', [])
        
        if devices:
            logger.info(f"Received camera list: {devices}")
            # Store the received list
            global stored_camera_list
            print(devices)
            stored_camera_list = devices
            
            # Emit an event to notify the frontend of the update
            print("aaaaaa")
            socketio.emit('camera_list_updated', {'devices': devices})
            
            return jsonify({"message": "Camera list received successfully"}), 200
        else:
            logger.error("No devices found in the request")
            return jsonify({"error": "No devices in the list"}), 400
    except Exception as e:
        logger.error(f"Error receiving camera list: {e}")
        return jsonify({"error": "Failed to receive camera list"}), 500
    
@app.route('/get_active_cameras', methods=['POST'])
def receive_active_camera_list():
    try:
        # Get the camera list from the request
        data = request.get_json()
        devices = data.get('devices', [])
        print(devices , "active camera ka list")
        
        if devices:
            logger.info(f"Received active camera list: {devices}")
            # Store the received list
            global stored_active_camera_list
            stored_active_camera_list = devices
            
            
            # Emit an event to notify the frontend of the update
            socketio.emit('active_camera_list_updated', {'devices': devices})
            
            return jsonify({"message": "Active Camera list received successfully"}), 200
        else:
            logger.error("No  active devices found in the request")
            return jsonify({"error": "No active devices in the list"}), 400
    except Exception as e:
        logger.error(f"Error receiving active camera list: {e}")
        return jsonify({"error": "Failed to receive active camera list"}), 500
    
@app.route("/video_feed/<camera_name>")
def video_feed(camera_name):
    print(f"Requesting feed for camera: {camera_name}")
    print ( "sasssssssssss" , camera_instances)

    if camera_name not in camera_instances:
        pipeline_str = camera_ports.get(camera_name)
        if pipeline_str:
            print(f"Starting pipeline for camera {camera_name} with pipeline: {pipeline_str}")

            camera_instances[camera_name] = GStreamerVideo(pipeline_str)
            camera_instances[camera_name].start()
            print(f"Active camera instances: {list(camera_instances.keys())}")

        else:
            return "Camera not found", 404

    return Response(

        generate_frames(camera_instances[camera_name]),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route("/start_stream", methods=['POST'])
def start_stream():
    camera_name = request.form.get("camera_name")  # Get camera name from the frontend
    if not ssh_manager.is_ssh_connected:
        threading.Thread(
            target=ssh_manager.connect,
            args=(kratos_ip, kratos_username, kratos_password, start_command),
        ).start()
        return f"Starting SSH and stream for {camera_name}", 200
    return "SSH connection already active", 400

# @app.route("/stop_stream", methods=['POST'])
# def stop_stream_new():
#     # Stop SSH connection and cleanup
#     return redirect(url_for('index'))

if __name__ == "__main__":
    try:
        app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
    finally:
        for camera in camera_instances.values():
            camera.stop()
