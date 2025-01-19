import subprocess
import gi
import threading
from flask_cors import CORS
from flask import Flask, render_template, request, redirect, url_for
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import logging
import sys
import requests  # Add this import statement
import os
import time

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
Gst.init(None)
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "http://192.168.1.11:5002"}})
IP_RECEIVER = "192.168.1.11"
BASE_PORT = 9000

@dataclass
class StreamContext:
    pipeline: Optional[Gst.Pipeline]
    loop: Optional[GLib.MainLoop]
    thread: Optional[threading.Thread]
    bus_watch_id: Optional[int]
    active: bool
    device: str
    port: int
    cleanup_event: threading.Event

class StreamManager:
    def __init__(self):
        self.streams: Dict[str, StreamContext] = {}
        self.lock = threading.Lock()
        self.main_context = GLib.MainContext.default()
        self.stoprequest = threading.Event()
        self.active_pipelines = set()
        self.device_to_port = {}  # Mapping to store device -> port

        
    def create_pipeline(self, camera_device: str, resolution: Tuple[int, int], 
                       fps: int, port: int, bitrate: int) -> str:
        width, height = resolution
        return (
            f"v4l2src device={camera_device} do-timestamp=true ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "queue max-size-buffers=2 ! "
            "jpegdec ! "
            
            "nvvidconv interpolation-method=1 ! "
            "video/x-raw(memory:NVMM),format=NV12 ! "
            
            "nvv4l2h264enc "
            f"bitrate={bitrate}000 "
            "control-rate=1 "  
            "preset-level=1 "  
            "iframeinterval=30 "  
            "idrinterval=60 " 
            "insert-sps-pps=true "
            "profile=4 "  
            "maxperf-enable=true "  
            "ratecontrol-enable=true "  
            f"vbv-size={bitrate*2}000 "  
            "num-Ref-Frames=2 " 
            "poc-type=0 ! "  
            
            "h264parse ! "
            "rtph264pay config-interval=1 pt=96 ! "
            f"udpsink host={IP_RECEIVER} port={port} "
            "sync=false async=false "
            "buffer-size=2097152 "
            "qos=true"
        )

    def _bus_callback(self, bus, message, camera_device):
        if self.stoprequest.is_set():
            return False
            
        t = message.type
        if t == Gst.MessageType.EOS:
            logger.info(f"End of stream for {camera_device}")
            self.stop_stream(camera_device)
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"Error from {camera_device}: {err.message}")
            logger.debug(f"Debug info: {debug}")
            logger.error(f"GStreamer Error Code: {err.code}") 
            self.stop_stream(camera_device)
        elif t == Gst.MessageType.WARNING:
            wrn, debug = message.parse_warning()
            logger.warning(f"Warning from {camera_device}: {wrn.message}")
            logger.debug(f"Debug info: {debug}")
        
        return True

    def start_pipeline_thread(self, camera_device: str, resolution: Tuple[int, int], 
                            fps: int, port: int, bitrate: int) -> None:
        try:
            pipeline_str = self.create_pipeline(camera_device, resolution, fps, port, bitrate)
            pipeline = Gst.parse_launch(pipeline_str)
            
            if not pipeline:
                raise RuntimeError("Failed to create pipeline")
            
            bus = pipeline.get_bus()
            bus.add_signal_watch()
            loop = GLib.MainLoop(context=None)
            bus_watch_id = bus.connect('message', self._bus_callback, camera_device)

            with self.lock:
                stream = self.streams[camera_device]
                stream.pipeline = pipeline
                stream.loop = loop
                stream.bus_watch_id = bus_watch_id

            ret = pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError(f"Failed to start pipeline for {camera_device}")
            
            logger.info(f"Started streaming from {camera_device} at {resolution} "
                       f"({fps} FPS) to UDP port {port}")
            
            with self.lock:
                stream.active = True

            while not stream.cleanup_event.is_set() and not self.stoprequest.is_set():
                try:
                    if loop.is_running():
                        loop.iteration(False)  # Non-blocking iteration
                    else:
                        break
                except Exception as e:
                    logger.error(f"Error in loop iteration: {str(e)}")
                    break
            # self.active_pipelines.remove(camera_device)
            logger.info(f"Pipeline thread exiting for {camera_device}")
            
        except Exception as e:
            self.active_pipelines.remove(camera_device)
            logger.error(f"Error in pipeline thread for {camera_device}: {str(e)}")
        # finally:
        #     # Call stop_stream with from_thread=True to avoid thread joining
        #     self.stop_stream(camera_device, from_thread=True)

    def start_stream(self, camera_device: str, resolution: Tuple[int, int], 
                    fps: int, port: int, bitrate: int) -> bool:
        with self.lock:
            if camera_device in self.streams and self.streams[camera_device].active:
                logger.warning(f"Stream already active for {camera_device}")
                return False
            

            cleanup_event = threading.Event()
            self.streams[camera_device] = StreamContext(
                pipeline=None,
                loop=None,
                thread=None,
                bus_watch_id=None,
                active=False,
                device=camera_device,
                port=port,
                cleanup_event=cleanup_event
            )
            self.device_to_port[camera_device] = port

            thread = threading.Thread(
                target=self.start_pipeline_thread,
                args=(camera_device, resolution, fps, port, bitrate)
            )
            self.streams[camera_device].thread = thread
            self.active_pipelines.add(camera_device)
            print("starting camera ", camera_device)
            thread.daemon = True
            thread.start()
            
            return True

    def _cleanup_pipeline(self, stream: StreamContext):
        try:
            stream.cleanup_event.set()
            
            if stream.pipeline:
                if stream.bus_watch_id is not None:
                    bus = stream.pipeline.get_bus()
                    if bus:
                        bus.remove_signal_watch()
                        bus.disconnect(stream.bus_watch_id)

                # Send EOS event
                stream.pipeline.send_event(Gst.Event.new_eos())
                
                # Wait for EOS to be processed
                timeout = Gst.SECOND * 2
                bus = stream.pipeline.get_bus()
                bus.timed_pop_filtered(timeout, Gst.MessageType.EOS)
                
                # Now set to NULL state
                stream.pipeline.set_state(Gst.State.NULL)
                state_change = stream.pipeline.get_state(timeout)
                if state_change[0] != Gst.StateChangeReturn.SUCCESS:
                    logger.warning(f"Pipeline state change failed for {stream.device}")
                
                stream.pipeline = None

            if stream.loop and stream.loop.is_running():
                GLib.idle_add(stream.loop.quit)
                
        except Exception as e:
            logger.error(f"Error cleaning up pipeline for {stream.device}: {str(e)}")

    def stop_stream(self, camera_device: str, from_thread: bool = False) -> bool:
        """
        Stop a stream and cleanup resources.
        
        Args:
            camera_device: The device to stop
            from_thread: True if called from within the stream thread
        """
        with self.lock:
            if camera_device not in self.streams:
                return False
            
            stream = self.streams[camera_device]
            if not stream.active:
                return False
            
            stream.active = False
            
            # Clean up the pipeline
            self._cleanup_pipeline(stream)
            
            # Remove the associated port from the mapping
            if camera_device in self.device_to_port:
                del self.device_to_port[camera_device]

            if camera_device in self.active_pipelines:
                self.active_pipelines.remove(camera_device)
            # Only attempt to join the thread if we're not in the thread itself
            if not from_thread and stream.thread and stream.thread.is_alive():
                try:
                    stream.thread.join(timeout=5.0)
                    if stream.thread.is_alive():
                        logger.warning(f"Thread for {camera_device} did not terminate properly")
                except RuntimeError as e:
                    logger.warning(f"Could not join thread for {camera_device}: {str(e)}")
            
            logger.info(f"Stopped stream for {camera_device}")
            return True

    def stop_all_streams(self) -> None:
        """Stop all streams and cleanup resources."""
        self.stoprequest.set()
        with self.lock:
            devices = list(self.streams.keys())
        
        current_thread_id = threading.get_ident()
        for device in devices:
            # Check if we're in the thread we're trying to stop
            stream = self.streams.get(device)
            if stream and stream.thread:
                is_current_thread = (
                    stream.thread.is_alive() and 
                    stream.thread.ident == current_thread_id
                )
                self.stop_stream(device, from_thread=is_current_thread)
            
        with self.lock:
            self.streams.clear()
            self.active_pipelines.clear()  # Clear the active pipeline list
    
    def get_active_pipeline_devices(self) -> list:
        """Return the list of devices currently being used in the pipeline."""
        print(list(self.streams.keys()))
        return list(self.active_pipelines )

    def monitor_and_cleanup_disconnected_cameras(self):
        while True:
            time.sleep(1)  # Check every second for disconnected cameras
            active_devices = get_active_video_devices()  # Get active video devices from the external function
            
            with self.lock:
                devices = list(self.streams.keys())
            
            for device in devices:
                if device not in active_devices:
                    logger.info(f"Camera {device} disconnected. Stopping stream...")
                    self.stop_stream(device)      
    def get_device_ports(self) -> Dict[str, int]:
        """Return a dictionary of devices and their associated ports."""
        with self.lock:
            return self.device_to_port



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_active_video_devices() -> list:
    devices = []
    try:
        for i in range(21):
            device = f"/dev/video{i}"
            try:
                # Check if device supports video capture
                output = subprocess.check_output(
                    ['v4l2-ctl', '--device=' + device, '--list-formats'],
                    stderr=subprocess.STDOUT
                ).decode('utf-8')

                # If the device lists formats, it's considered an active video device
                if "[0]" in output:
                    # Ensure unique cameras by checking formats
                    if device not in devices:
                        devices.append(device)
            
            except subprocess.CalledProcessError:
                continue
    except Exception as e:
        logger.error(f"Error detecting video devices: {str(e)}")
    
    # logger.info(f"Found active video devices: {devices}")
    return devices


@app.route('/')
def index():
    active_devices = get_active_video_devices()
    return render_template('index.html', active_devices=active_devices)
    
resolution_map = {
    '720p': (1280, 720),
    '480p': (640, 480),
    '360p': (480, 360),
    '240p': (426, 240),
    '144p': (256, 144)
}

@app.route('/start_stream', methods=['POST'])
def start_stream():
    resolution = request.form['resolution']
    fps = request.form.get('fps', 10, type=int)
    bitrate = request.form.get('bitrate', 500, type=int)
    
    selected_resolution = resolution_map.get(resolution)
    if not selected_resolution:
        return "Invalid resolution", 400

    active_devices = get_active_video_devices()
    if not active_devices:
        return "No active video devices found", 400

    selected_devices = request.form.getlist('devices')
    if not selected_devices:
        return redirect(url_for('index'))
    
    success_count = 0
    for device in selected_devices:
        if device in active_devices:
            port = BASE_PORT + active_devices.index(device)
            if stream_manager.start_stream(device, selected_resolution, fps, port, bitrate):
                success_count += 1

    print(f"Started {success_count} streams successfully")
    return redirect(url_for('index'))


@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    # Get the selected camera devices from the form data (could be multiple)
    selected_devices = request.form.getlist('device')
    print(selected_devices,"this is log")
    
    if selected_devices:
        for camera_device in selected_devices:
            # Stop each selected stream
            success = stream_manager.stop_stream(camera_device)
            if success:
                logger.info(f"Stream for {camera_device} stopped successfully.")
            else:
                logger.warning(f"Failed to stop stream for {camera_device}.")
    else:
        # If no specific device is selected, stop all streams
        stream_manager.stop_all_streams()
    
    return redirect(url_for('index'))

@app.route('/get_device_ports', methods=['GET'])
def get_device_ports():
    device_ports = stream_manager.get_device_ports()
    return {"device_ports": device_ports}

@app.route('/get_cameras', methods=['GET'])
def get_cameras():
    active_devices = get_active_video_devices()
    print("niceeeee " , active_devices)
    return active_devices

@app.route('/get_cameras2', methods=['GET'])
def get_cameras2():
    active_pipeline_devices = stream_manager.get_active_pipeline_devices()
    print("Active pipeline devices: ", active_pipeline_devices)
    return {"devices": active_pipeline_devices}


CAMERA_LIST_URL = "http://192.168.1.11:5002/get_cameras"  # Endpoint to send camera list
CAMERA_LIST_URL2 = "http://192.168.1.11:5002/get_active_cameras"  # Endpoint to send camera list


def send_camera_list_to_ip(devices: list):
    try:
        response = requests.post(CAMERA_LIST_URL, json={'devices': devices})
        if response.status_code == 200:
            logger.info("Camera list sent successfully to IP")
        else:
            logger.error(f"Failed to send camera list. Status Code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending camera list: {e}")

# Background thread that monitors the camera list for changes
def monitor_camera_list():
    previous_list = []
    while True:
        current_list = get_active_video_devices()
        if current_list != previous_list:
            send_camera_list_to_ip(current_list)
            previous_list = current_list
        time.sleep(5)  # Check every 5 seconds

def send_active_camera_list_to_ip(devices: list):
    try:
        response = requests.post(CAMERA_LIST_URL2, json={'devices': devices})
        if response.status_code == 200:
            logger.info("Camera active list sent successfully to IP")
        else:
            logger.error(f"Failed to send active camera list. Status Code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending active  camera list: {e}")
        
def monitor_active_camera_list():
    previous_list = []
    while True:
        current_list = stream_manager.get_active_pipeline_devices()
        if current_list != previous_list:
            send_active_camera_list_to_ip(current_list)
            previous_list = current_list
        time.sleep(5)  
        
stream_manager = StreamManager()

def cleanup_and_exit(signum=None, frame=None):
    logger.info("Cleaning up and exiting...")
    stream_manager.stop_all_streams()
    # Give some time for cleanup to complete
    timeout = 5
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not any(stream.thread and stream.thread.is_alive() 
                  for stream in stream_manager.streams.values()):
            break
        time.sleep(0.1)
    sys.exit(0)

if __name__ == "__main__":
    try:
        disconnect_monitor_thread = threading.Thread(target=stream_manager.monitor_and_cleanup_disconnected_cameras, daemon=True)
        disconnect_monitor_thread.start()

        monitor_thread = threading.Thread(target=monitor_camera_list, daemon=True)
        monitor_thread.start()
        
        monitor_active_thread = threading.Thread(target=monitor_active_camera_list, daemon=True)
        monitor_active_thread.start()
        
        import signal
        signal.signal(signal.SIGINT, cleanup_and_exit)
        signal.signal(signal.SIGTERM, cleanup_and_exit)
        app.run(host='0.0.0.0', port=51000)
    except KeyboardInterrupt:
        cleanup_and_exit()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        cleanup_and_exit()