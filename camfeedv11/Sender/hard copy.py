import subprocess
import gi
import threading
from flask_cors import CORS
from flask import Flask, render_template, request, redirect, url_for
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import logging
import sys
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
            
            logger.info(f"Pipeline thread exiting for {camera_device}")
            
        except Exception as e:
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
            
            thread = threading.Thread(
                target=self.start_pipeline_thread,
                args=(camera_device, resolution, fps, port, bitrate)
            )
            self.streams[camera_device].thread = thread
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
            self.stop_stream(camera_device, from_thread=True)


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
            self._cleanup_pipeline(stream)
            
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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_active_video_devices() -> list:
    devices = []
    try:
        for i in range(11):
            device = f"/dev/video{i}"
            try:
                output = subprocess.check_output(
                    ['v4l2-ctl', '--device=' + device, '--all'],
                    stderr=subprocess.STDOUT
                ).decode('utf-8')
                if "Video Capture" in output:
                    devices.append(device)
            except subprocess.CalledProcessError:
                continue
    except Exception as e:
        logger.error(f"Error detecting video devices: {str(e)}")
    
    logger.info(f"Found active video devices: {devices}")
    return devices


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_stream', methods=['POST'])
def start_stream():
    resolution = request.form['resolution']
    fps = request.form.get('fps', 10, type=int)
    bitrate = request.form.get('bitrate', 500, type=int)

    resolution_map = {
        '720p': (1280, 720),
        '480p': (640, 480),
        '360p': (480, 360),
        '240p': (320, 240),
        '144p': (256, 144),
    }

    selected_resolution = resolution_map.get(resolution)
    if not selected_resolution:
        return "Invalid resolution", 400

    active_devices = get_active_video_devices()
    if not active_devices:
        return "No active video devices found", 400

    success_count = 0
    for i, device in enumerate(active_devices):
        port = BASE_PORT + i
        if stream_manager.start_stream(device, selected_resolution, fps, port, bitrate):
            success_count += 1

    print(f"Started {success_count} streams successfully")
    return redirect(url_for('index'))


@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    stream_manager.stop_all_streams()
    return redirect(url_for('index'))

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
        import signal
        signal.signal(signal.SIGINT, cleanup_and_exit)
        signal.signal(signal.SIGTERM, cleanup_and_exit)
        app.run(host='0.0.0.0', port=51000)
    except KeyboardInterrupt:
        cleanup_and_exit()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        cleanup_and_exit()