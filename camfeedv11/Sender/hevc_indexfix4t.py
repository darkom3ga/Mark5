import subprocess
import gi
import threading
from flask_cors import CORS
from flask import Flask, render_template, request, redirect, url_for
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import logging
import sys

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

class StreamManager:
    def __init__(self):
        self.streams: Dict[str, StreamContext] = {}
        self.lock = threading.Lock()
        self.main_context = GLib.MainContext.default()
        self.stoprequest = False
        
    def create_pipeline(self, camera_device: str, resolution: Tuple[int, int], 
                       fps: int, port: int, bitrate: int) -> str:
        width, height = resolution

        return (
    f"v4l2src device={camera_device} do-timestamp=true ! "
    f"image/jpeg,width=320,height=240,framerate=15/1 ! "
    "queue max-size-buffers=2 ! "
    "rtpjpegpay ! "
    f"udpsink host={IP_RECEIVER} port={port} "
    "sync=false async=false "
    "buffer-size=2097152 "
    "qos=true"
    # f"v4l2src device={camera_device} do-timestamp=true ! "
    # f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
    # "queue max-size-buffers=2 ! "
    # "nvv4l2decoder ! "  # Use NVIDIA's V4L2 decoder
    # "nvv4l2h264enc "  # This will now receive NVMM format directly
    # f"bitrate={bitrate}000 "
    # "control-rate=1 "
    # "preset-level=1 "
    # "iframeinterval=30 "
    # "idrinterval=60 "
    # "insert-sps-pps=true "
    # "profile=4 "
    # "maxperf-enable=true "
    # "ratecontrol-enable=true "
    # f"vbv-size={bitrate*2}000 "
    # "num-Ref-Frames=2 "
    # "poc-type=0 ! "
    # "h264parse ! "
    # "rtph264pay config-interval=1 pt=96 ! "
    # f"udpsink host={IP_RECEIVER} port={port} "
    # "sync=false async=false "
    # "buffer-size=2097152 "
    # "qos=true"
)
        # return (
        #     f"v4l2src device={camera_device} do-timestamp=true ! "
        #     f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
        #     "queue max-size-buffers=2 ! "      
        #     "nvvidconv interpolation-method=1 ! "
        #     "video/x-raw(memory:NVMM),format=NV12 ! "
        #     "nvv4l2h264enc "
        #     f"bitrate={bitrate}000 "
        #     "control-rate=1 "  
        #     "preset-level=1 "  
        #     "iframeinterval=30 "  
        #     "idrinterval=60 " 
        #     "insert-sps-pps=true "
        #     "profile=4 "  
        #     "maxperf-enable=true "  
        #     "ratecontrol-enable=true "  
        #     f"vbv-size={bitrate*2}000 "  
        #     "num-Ref-Frames=2 " 
        #     "poc-type=0 ! "  
        #     "h264parse ! "
        #     "rtph264pay config-interval=1 pt=96 ! "
        #     f"udpsink host={IP_RECEIVER} port={port} "
        #     "sync=false async=false "
        #     "buffer-size=2097152 "
        #     "qos=true"
        # )

    def _bus_callback(self, bus, message, camera_device):
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
                self.streams[camera_device].pipeline = pipeline
                self.streams[camera_device].loop = loop
                self.streams[camera_device].bus_watch_id = bus_watch_id

            ret = pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError(f"Failed to start pipeline for {camera_device}")
            
            logger.info(f"Started streaming from {camera_device} at {resolution} "
                       f"({fps} FPS) to UDP port {port}")
            
            with self.lock:
                self.streams[camera_device].active = True
            # while not self.stop_requested:  
                loop.run()
            
        except Exception as e:
            logger.error(f"Error in pipeline thread for {camera_device}: {str(e)}")
            self.stop_stream(camera_device)

    def start_stream(self, camera_device: str, resolution: Tuple[int, int], 
                    fps: int, port: int, bitrate: int) -> bool:
        with self.lock:
            if camera_device in self.streams and self.streams[camera_device].active:
                logger.warning(f"Stream already active for {camera_device}")
                return False
            self.streams[camera_device] = StreamContext(
                pipeline=None,
                loop=None,
                thread=None,
                bus_watch_id=None,
                active=False,
                device=camera_device,
                port=port
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
            if stream.pipeline:
                if stream.bus_watch_id is not None:
                    bus = stream.pipeline.get_bus()
                    if bus:
                        bus.remove_signal_watch()
                        bus.disconnect(stream.bus_watch_id)

                stream.pipeline.set_state(Gst.State.NULL)
                
                timeout = 5  
                state_change = stream.pipeline.get_state(timeout * Gst.SECOND)
                if state_change[0] != Gst.StateChangeReturn.SUCCESS:
                    logger.warning(f"Pipeline state change failed for {stream.device}")
                stream.pipeline = None
        
        except Exception as e:
            logger.error(f"Error cleaning up pipeline for {stream.device}: {str(e)}")

    def stop_stream(self, camera_device: str) -> bool:
        with self.lock:
            if camera_device not in self.streams:
                return False
            
            stream = self.streams[camera_device]
            if not stream.active:
                return False
            
            stream.active = False
            
            if stream.loop and stream.loop.is_running():
                stream.loop.quit()
            self._cleanup_pipeline(stream)
            if stream.thread and stream.thread.is_alive():
                stream.thread.join(timeout=2.0)
            
            logger.info(f"Stopped stream for {camera_device}")
            return True

    def stop_all_streams(self) -> None:
        self.stoprequest = True
        with self.lock:
            devices = list(self.streams.keys())
            
        for device in devices:
            self.stop_stream(device)
            
        with self.lock:
            self.streams.clear()


def get_active_video_devices() -> list:
    devices = []
    try:
        for i in range(10):
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

    print (f"Started {success_count} streams successfully")
    return redirect(url_for('index'))


@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    stream_manager.stop_all_streams()
    return redirect(url_for('index'))

stream_manager = StreamManager()

def cleanup_and_exit(signum=None, frame=None):
    logger.info("Cleaning up and exiting...")
    stream_manager.stop_all_streams()
    sys.exit(0)

    
# import time
# import psutil
# def monitor_bandwidth():
#     previous_stats = psutil.net_io_counters()
#     while True:
#         try:
#             time.sleep(1)
#             current_stats = psutil.net_io_counters()
            
#             bytes_sent = current_stats.bytes_sent - previous_stats.bytes_sent
#             bytes_recv = current_stats.bytes_recv - previous_stats.bytes_recv
#             mb_sent = bytes_sent * 8 / (1024 * 1024)
#             mb_recv = bytes_recv * 8 / (1024 * 1024)
            
#             logger.info(f"Bandwidth - Sent: {mb_sent:.2f} Mbps, Received: {mb_recv:.2f} Mbps")
#             previous_stats = current_stats
            
#         except Exception as e:
#             logger.error(f"Error monitoring bandwidth: {str(e)}")

if __name__ == "__main__":
    try:
        import signal
        signal.signal(signal.SIGINT, cleanup_and_exit)
        signal.signal(signal.SIGTERM, cleanup_and_exit)
        # threading.Thread(target=monitor_bandwidth, daemon=True).start()
        app.run(host='0.0.0.0', port=51000)
    except KeyboardInterrupt:
        cleanup_and_exit()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        cleanup_and_exit()
