
### REDUCED DELAY ( Based on SSH IMPROVEMENT  code , can be used in the without ssh improvement code )

import cv2
from flask import Flask, render_template, Response ,redirect, url_for
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import threading
import numpy as np
import paramiko, time, os 
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
        self.max_queue_size = 2  

    def start(self):
        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.video_sink = self.pipeline.get_by_name('appsink0')
        
        self.video_sink.set_property('emit-signals', True)
        self.video_sink.set_property('max-buffers', 2)
        self.video_sink.set_property('drop', True)
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
                return self.frame_queue.pop() 
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
    udpsrc port={} buffer-size=65536 ! 
    application/x-rtp,payload=96 ! 
    rtph264depay ! 
    h264parse ! 
    avdec_h264 max-threads=4 ! 
    videoconvert ! 
    video/x-raw,format=BGR ! 
    appsink name=appsink0 max-buffers=2 drop=true sync=false
"""

camera_ports = {
    'Camera 1': pipeline_template.format(9000),
    'Camera 2': pipeline_template.format(9001),
    'Camera 3': pipeline_template.format(9002),
    'Camera 4': pipeline_template.format(9003),
    'Camera 5': pipeline_template.format(9004),
    'Camera 6': pipeline_template.format(9005)
}

camera_instances = {}
kratos_ip = "127.0.0.1"
kratos_username = "om3ga"
kratos_password = "om3ga"
# kratos_ip = "192.168.1.10"
# kratos_username = "kratos"
# kratos_password = "kratos123"
ssh = paramiko.SSHClient()
# start_command="cd ~/Desktop/ipcam ; python3 hevc_indexfix4.py "
start_command="cd ~/ ; python3 timeee.py "

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
                                self.disconnect()
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
                
    def disconnect(self):
        if self.is_ssh_connected:
            try:
                # ssh_stdin, ssh_stdout, ssh_stderr = self.ssh.exec_command("ps aux | grep '[p]ython3 timeee.py'")
                # output = ssh_stdout.readlines()
                # print(output)
                self.ssh.exec_command("pkill -f 'python3 timeee.py'")  
                self.ssh.close()
                print("SSH Connection closed successfully")
            except Exception as e:
                print(f"Error during SSH disconnection: {e}")
            finally:
                self.is_ssh_connected = False

ssh_manager = SSHManager()

@app.route("/")
def index():
    return render_template('index2.html', camera_ports=camera_ports)

def generate_frames(camera_instance):
    while camera_instance.running:
        frame = camera_instance.get_frame()
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            def generate_frames(camera_instance):
    # while camera_instance.running:
    #     frame = camera_instance.get_frame()
    #     if frame is not None:
    #         # Use lower JPEG quality for faster encoding
    #         encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
    #         _, buffer = cv2.imencode('.jpg', frame, encode_params)
    #         frame_bytes = buffer.tobytes()
    #         yield (b'--frame\r\n'
    #                b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    #     else:
    #         time.sleep(0.001)  # Short sleep to prevent CPU overload

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

@app.route("/start_stream", methods=['POST'])
def start_stream_new():
    ssh_manager.stop_thread = False
    ssh_manager.ssh_thread = threading.Thread(
        target=ssh_manager.connect,
        args=(kratos_ip, kratos_username, kratos_password, start_command)
    )
    ssh_manager.ssh_thread.start()
    return redirect(url_for('index'))

@app.route("/stop_stream", methods=['POST'])
def stop_stream_new():
    ssh_manager.stop_thread = True
    if ssh_manager.ssh_thread and ssh_manager.ssh_thread.is_alive():
        ssh_manager.disconnect()  
        ssh_manager.ssh_thread.join(timeout=5)
        if ssh_manager.ssh_thread.is_alive():
            print("Warning: SSH thread did not terminate properly")
    print("SSH thread stopped and resources freed")
    return redirect(url_for('index'))


if __name__ == "__main__":
    try:
        app.run(host='0.0.0.0', port=5002, debug=True, threaded=True)
        
    finally:
        ssh_manager.stop_thread = True
        if ssh_manager.ssh_thread:
            ssh_manager.ssh_thread.join()
        for camera in camera_instances.values():
            camera.stop()